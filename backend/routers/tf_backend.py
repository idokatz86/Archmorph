from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import logging
import threading
from typing import Generator

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from error_envelope import ArchmorphException
from models.deployment_state import DeploymentState
from models.workspace import Workspace
from project_store import PROJECT_EDIT_ROLES, PROJECT_READ_ROLES, require_project_access
from routers.shared import (
    get_request_durable_principal,
    get_store,
    require_authenticated_user,
)

LOCK_STORE = get_store("tf_locks", maxsize=500, ttl=3600)

CANONICAL_STATE_ENVIRONMENTS = frozenset({"dev", "staging", "prod"})
_STATE_ENVIRONMENT_ALIASES = {"production": "prod"}
_LOCAL_STATE_CREATION_LOCKS = tuple(threading.RLock() for _ in range(256))

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/terraform/state", tags=["Terraform State Backend"])


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_state_environment(environment: str) -> str:
    """Return the constrained canonical Terraform environment identity."""
    normalized = environment.strip().lower() if isinstance(environment, str) else ""
    normalized = _STATE_ENVIRONMENT_ALIASES.get(normalized, normalized)
    if normalized not in CANONICAL_STATE_ENVIRONMENTS:
        raise ArchmorphException(422, "Unsupported Terraform state environment")
    return normalized


def _state_scope_key(project_id: str, environment: str) -> str:
    return json.dumps([project_id, environment], separators=(",", ":"))


@contextmanager
def _state_creation_lock(
    db: Session,
    project_id: str,
    environment: str,
) -> Generator[None, None, None]:
    """Serialize first creation by canonical project/environment, never caller."""
    scope_key = _state_scope_key(project_id, environment)
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope_key, 0))"),
            {"scope_key": f"archmorph:terraform-state:{scope_key}"},
        )
        yield
        return

    # SQLite has no advisory locks. A fixed stripe pool makes local/test first
    # creation deterministic while the database uniqueness constraint remains
    # the final invariant on every backend.
    digest = hashlib.sha256(scope_key.encode("utf-8")).digest()
    local_lock = _LOCAL_STATE_CREATION_LOCKS[
        int.from_bytes(digest[:2], "big") % len(_LOCAL_STATE_CREATION_LOCKS)
    ]
    with local_lock:
        yield


def _synchronize_state_audit_metadata(
    state: DeploymentState,
    project: Workspace,
) -> None:
    state.owner_user_id = project.owner_user_id
    state.tenant_id = project.tenant_id


def _get_or_create_deployment_state(
    db: Session,
    project: Workspace,
    environment: str,
) -> DeploymentState:
    """Get/create the one state row for an already-authorized Project."""
    normalized_environment = normalize_state_environment(environment)
    with _state_creation_lock(db, project.id, normalized_environment):
        state = (
            db.query(DeploymentState)
            .filter(
                DeploymentState.project_id == project.id,
                DeploymentState.environment == normalized_environment,
            )
            .one_or_none()
        )
        if state is None:
            try:
                with db.begin_nested():
                    state = DeploymentState(
                        project_id=project.id,
                        environment=normalized_environment,
                        owner_user_id=project.owner_user_id,
                        tenant_id=project.tenant_id,
                        state_json={},
                    )
                    db.add(state)
                    db.flush()
            except IntegrityError:
                # The unique (project_id, environment) constraint is the final
                # cross-process guard even if a non-PostgreSQL backend cannot
                # participate in the canonical advisory-lock namespace.
                state = (
                    db.query(DeploymentState)
                    .filter(
                        DeploymentState.project_id == project.id,
                        DeploymentState.environment == normalized_environment,
                    )
                    .one()
                )
        else:
            _synchronize_state_audit_metadata(state, project)
            db.flush()
    return state


def _canonical_state_principal(request: Request) -> tuple[str, str]:
    principal = get_request_durable_principal(request)
    if principal is None or not principal.get("tenant_id"):
        raise ArchmorphException(401, "Authentication required")
    return principal["owner_user_id"], principal["tenant_id"]


@contextmanager
def authorized_deployment_state(
    db: Session,
    *,
    project_id: str,
    environment: str,
    caller_user_id: str,
    tenant_id: str,
    allowed_roles: frozenset[str],
) -> Generator[tuple[DeploymentState, Workspace, str], None, None]:
    """Hold canonical authorization and state identity through one commit."""
    try:
        resolved = require_project_access(
            db,
            project_id=project_id,
            caller_user_id=caller_user_id,
            tenant_id=tenant_id,
            allowed_roles=allowed_roles,
            lock_authorization=True,
        )
        if resolved is None:
            raise ArchmorphException(404, "Terraform state not found")
        project, _role = resolved
        normalized_environment = normalize_state_environment(environment)
        with _state_creation_lock(db, project.id, normalized_environment):
            state = _get_or_create_deployment_state(db, project, normalized_environment)
            yield state, project, normalized_environment
            db.commit()
    except Exception:
        db.rollback()
        raise


def _state_for_update(db: Session, state: DeploymentState) -> DeploymentState:
    return (
        db.query(DeploymentState)
        .filter(
            DeploymentState.id == state.id,
            DeploymentState.project_id == state.project_id,
            DeploymentState.environment == state.environment,
        )
        .with_for_update()
        .one()
    )


def _state_has_active_lock(state: DeploymentState) -> bool:
    return state.lock_id is not None or state.lock_info not in (None, {})


def _canonical_lock_info(state: DeploymentState) -> dict:
    lock_info = state.lock_info if isinstance(state.lock_info, dict) else {}
    if state.lock_id is not None and lock_info.get("ID") != state.lock_id:
        lock_info = {**lock_info, "ID": state.lock_id}
    return lock_info


def _sync_lock_projection(state: DeploymentState) -> None:
    """Best-effort cache projection; SQL remains the lock authority."""
    lock_key = _state_scope_key(state.project_id, state.environment)
    try:
        if _state_has_active_lock(state):
            LOCK_STORE.set(lock_key, _canonical_lock_info(state))
        else:
            LOCK_STORE.delete(lock_key)
    except Exception as exc:
        logger.warning(
            "Terraform lock cache projection failed error_type=%s",
            type(exc).__name__,
        )


def _parse_lock_info(body: bytes) -> dict:
    try:
        lock_info = json.loads(body) if body else {}
    except (TypeError, ValueError) as exc:
        raise ArchmorphException(400, "Invalid Terraform lock payload") from exc
    if not isinstance(lock_info, dict):
        raise ArchmorphException(400, "Invalid Terraform lock payload")
    lock_id = lock_info.get("ID")
    if not isinstance(lock_id, str) or not lock_id.strip():
        raise ArchmorphException(400, "Terraform lock ID is required")
    return lock_info


def _locked_response(state: DeploymentState) -> Response:
    return Response(
        content=json.dumps(_canonical_lock_info(state)),
        status_code=status.HTTP_423_LOCKED,
        media_type="application/json",
    )


def purge_project_state(
    db: Session, project_id: str, owner_user_id: str, tenant_id: str
) -> int:
    """Delete canonical project state after resolving the expected Project."""
    project = (
        db.query(Workspace)
        .filter(
            Workspace.id == project_id,
            Workspace.owner_user_id == owner_user_id,
            Workspace.tenant_id == tenant_id,
        )
        .one_or_none()
    )
    if project is None:
        if (
            db.query(DeploymentState.id)
            .filter(DeploymentState.project_id == project_id)
            .first()
        ):
            raise RuntimeError("Terraform state exists without its canonical project")
        return 0
    states = (
        db.query(DeploymentState)
        .filter(
            DeploymentState.project_id == project_id,
        )
        .all()
    )
    for state in states:
        lock_key = _state_scope_key(project_id, state.environment)
        if not LOCK_STORE.delete(lock_key):
            raise RuntimeError("Terraform lock deletion could not be confirmed")
        db.delete(state)
    db.commit()
    return len(states)


def project_state_absent(
    db: Session,
    project_id: str,
    _owner_user_id: str | None = None,
    _tenant_id: str | None = None,
) -> bool:
    """Check canonical state absence; scope arguments are legacy compatibility."""
    return (
        db.query(DeploymentState.id)
        .filter(
            DeploymentState.project_id == project_id,
        )
        .first()
        is None
    )


@router.get("/{project_id}/{environment}")
async def get_tf_state(
    project_id: str,
    environment: str,
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_authenticated_user),
):
    caller_user_id, tenant_id = _canonical_state_principal(request)
    with authorized_deployment_state(
        db,
        project_id=project_id,
        environment=environment,
        caller_user_id=caller_user_id,
        tenant_id=tenant_id,
        allowed_roles=PROJECT_READ_ROLES,
    ) as (state, _project, _environment):
        _sync_lock_projection(state)
        state_json = state.state_json or {}
    return Response(content=json.dumps(state_json), media_type="application/json")


@router.post("/{project_id}/{environment}")
async def update_tf_state(
    project_id: str,
    environment: str,
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_authenticated_user),
):
    caller_user_id, tenant_id = _canonical_state_principal(request)
    with authorized_deployment_state(
        db,
        project_id=project_id,
        environment=environment,
        caller_user_id=caller_user_id,
        tenant_id=tenant_id,
        allowed_roles=PROJECT_EDIT_ROLES,
    ) as (state, _project, _environment):
        body = await request.body()
        state = _state_for_update(db, state)
        lock_id = request.query_params.get("ID")

        if _state_has_active_lock(state) and state.lock_id != lock_id:
            raise ArchmorphException(
                status.HTTP_423_LOCKED,
                "State is locked by another process.",
                details={"lock_info": _canonical_lock_info(state)},
            )

        try:
            payload = json.loads(body)
        except (TypeError, ValueError) as exc:
            raise ArchmorphException(400, "Invalid Terraform state payload") from exc

        state.previous_state_json = state.state_json
        state.state_json = payload
        state.updated_at = utc_now_naive()
        _sync_lock_projection(state)
    return Response(status_code=200)


@router.api_route("/{project_id}/{environment}", methods=["LOCK"])
async def lock_tf_state(
    project_id: str,
    environment: str,
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_authenticated_user),
):
    caller_user_id, tenant_id = _canonical_state_principal(request)
    with authorized_deployment_state(
        db,
        project_id=project_id,
        environment=environment,
        caller_user_id=caller_user_id,
        tenant_id=tenant_id,
        allowed_roles=PROJECT_EDIT_ROLES,
    ) as (state, _project, _environment):
        body = await request.body()
        state = _state_for_update(db, state)

        lock_info = _parse_lock_info(body)
        req_lock_id = lock_info.get("ID")

        if _state_has_active_lock(state):
            if state.lock_id != req_lock_id:
                return _locked_response(state)
            _sync_lock_projection(state)
            return Response(status_code=200)

        state.lock_id = req_lock_id
        state.lock_info = lock_info
        state.locked_at = utc_now_naive()
        _sync_lock_projection(state)
    return Response(status_code=200)


@router.api_route(
    "/{project_id}/{environment}",
    methods=["UNLOCR"],
    operation_id="unlock_tf_state_legacy_unlocr_api_terraform_state",
)
@router.api_route(
    "/{project_id}/{environment}",
    methods=["UNLOCK"],
    operation_id="unlock_tf_state_api_terraform_state",
)
async def unlock_tf_state(
    project_id: str,
    environment: str,
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_authenticated_user),
):
    caller_user_id, tenant_id = _canonical_state_principal(request)
    with authorized_deployment_state(
        db,
        project_id=project_id,
        environment=environment,
        caller_user_id=caller_user_id,
        tenant_id=tenant_id,
        allowed_roles=PROJECT_EDIT_ROLES,
    ) as (state, _project, _environment):
        body = await request.body()
        state = _state_for_update(db, state)

        lock_info = _parse_lock_info(body)
        req_lock_id = lock_info.get("ID")

        if _state_has_active_lock(state) and state.lock_id != req_lock_id:
            return _locked_response(state)

        state.lock_id = None
        state.lock_info = None
        state.locked_at = None
        _sync_lock_projection(state)
    return Response(status_code=200)


@router.post("/{project_id}/{environment}/rollback")
async def rollback_state(
    project_id: str,
    environment: str,
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_authenticated_user),
):
    caller_user_id, tenant_id = _canonical_state_principal(request)
    with authorized_deployment_state(
        db,
        project_id=project_id,
        environment=environment,
        caller_user_id=caller_user_id,
        tenant_id=tenant_id,
        allowed_roles=PROJECT_EDIT_ROLES,
    ) as (state, _project, normalized_environment):
        state = _state_for_update(db, state)
        if not state.previous_state_json:
            raise ArchmorphException(
                400,
                "No previous state available to rollback.",
            )

        current_state = state.state_json
        state.state_json = state.previous_state_json
        state.previous_state_json = current_state

    return {"status": "rolled_back", "environment": normalized_environment}
