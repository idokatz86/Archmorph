import json
import logging
from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone

from database import get_db
from models.deployment_state import DeploymentState
from error_envelope import ArchmorphException
from routers.shared import get_request_durable_principal, get_store, require_authenticated_user

LOCK_STORE = get_store("tf_locks", maxsize=500, ttl=3600)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/terraform/state", tags=["Terraform State Backend"])


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

def get_deployment_state(
    db: Session,
    project_id: str,
    environment: str,
    *,
    owner_user_id: str,
    tenant_id: str,
    legacy_owner_user_ids: tuple[str, ...] = (),
):
    accepted_owner_ids = {owner_user_id, *legacy_owner_user_ids}
    foreign_material_scope = db.query(DeploymentState).filter(
        DeploymentState.project_id == project_id,
        DeploymentState.environment == environment,
        ~(
            (DeploymentState.owner_user_id.in_(accepted_owner_ids))
            & (DeploymentState.tenant_id == tenant_id)
        ),
    ).all()
    if any(_state_has_material_data(row) for row in foreign_material_scope):
        raise ArchmorphException(404, "Terraform state not found")
    state = db.query(DeploymentState).filter(
        DeploymentState.project_id == project_id,
        DeploymentState.environment == environment,
        DeploymentState.owner_user_id == owner_user_id,
        DeploymentState.tenant_id == tenant_id,
    ).first()
    if state is None and legacy_owner_user_ids:
        legacy_rows = db.query(DeploymentState).filter(
            DeploymentState.project_id == project_id,
            DeploymentState.environment == environment,
            DeploymentState.owner_user_id.in_(legacy_owner_user_ids),
            DeploymentState.tenant_id == tenant_id,
        ).all()
        if len(legacy_rows) == 1:
            state = legacy_rows[0]
            state.owner_user_id = owner_user_id
            db.flush()
        elif len(legacy_rows) > 1:
            raise ArchmorphException(404, "Terraform state not found")
    if not state:
        foreign_scope_exists = db.query(DeploymentState.id).filter(
            DeploymentState.project_id == project_id,
            DeploymentState.environment == environment,
        ).first()
        if foreign_scope_exists is not None:
            raise ArchmorphException(404, "Terraform state not found")
        state = DeploymentState(
            project_id=project_id,
            environment=environment,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            state_json={},
        )
        try:
            db.add(state)
            db.commit()
            db.refresh(state)
        except IntegrityError:
            db.rollback()
            state = db.query(DeploymentState).filter(
                DeploymentState.project_id == project_id,
                DeploymentState.environment == environment,
                DeploymentState.owner_user_id == owner_user_id,
                DeploymentState.tenant_id == tenant_id,
            ).one()
    return state


def _canonical_state_principal(request: Request) -> tuple[str, str, tuple[str, ...]]:
    principal = get_request_durable_principal(request)
    if principal is None or not principal.get("tenant_id"):
        raise ArchmorphException(401, "Authentication required")
    return (
        principal["owner_user_id"],
        principal["tenant_id"],
        tuple(principal.get("legacy_owner_user_ids", [])),
    )


def _state_owner_key(project_id: str, environment: str) -> str:
    return json.dumps([project_id, environment], separators=(",", ":"))


def _state_has_material_data(state: DeploymentState) -> bool:
    return bool(state.state_json or state.previous_state_json or state.lock_id or state.lock_info)


def purge_project_state(db: Session, project_id: str, owner_user_id: str, tenant_id: str) -> int:
    """Delete all owner/tenant-scoped Terraform state and locks for a project."""
    states = db.query(DeploymentState).filter(
        DeploymentState.project_id == project_id,
        DeploymentState.owner_user_id == owner_user_id,
        DeploymentState.tenant_id == tenant_id,
    ).all()
    for state in states:
        lock_key = _state_owner_key(project_id, state.environment)
        if not LOCK_STORE.delete(lock_key):
            raise RuntimeError("Terraform lock deletion could not be confirmed")
        db.delete(state)
    db.commit()
    return len(states)


def project_state_absent(db: Session, project_id: str, owner_user_id: str, tenant_id: str) -> bool:
    return db.query(DeploymentState.id).filter(
        DeploymentState.project_id == project_id,
        DeploymentState.owner_user_id == owner_user_id,
        DeploymentState.tenant_id == tenant_id,
    ).first() is None


def _enforce_state_owner(state: DeploymentState, owner_user_id: str, tenant_id: str) -> None:
    if not state.owner_user_id and not state.tenant_id:
        if _state_has_material_data(state):
            raise ArchmorphException(403, "Forbidden: state ownership missing")
        state.owner_user_id = owner_user_id
        state.tenant_id = tenant_id
        return
    if state.owner_user_id != owner_user_id or state.tenant_id != tenant_id:
        raise ArchmorphException(404, "Terraform state not found")

@router.get("/{project_id}/{environment}")
async def get_tf_state(
    project_id: str,
    environment: str,
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_authenticated_user),
):
    owner_user_id, tenant_id, legacy_owners = _canonical_state_principal(request)
    state = get_deployment_state(
        db, project_id, environment,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        legacy_owner_user_ids=legacy_owners,
    )
    _enforce_state_owner(state, owner_user_id, tenant_id)
    db.commit()
    if not state.state_json:
        return Response(content="{}", media_type="application/json")
    return Response(content=json.dumps(state.state_json), media_type="application/json")

@router.post("/{project_id}/{environment}")
async def update_tf_state(
    project_id: str,
    environment: str,
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_authenticated_user),
):
    owner_user_id, tenant_id, legacy_owners = _canonical_state_principal(request)
    state = get_deployment_state(
        db, project_id, environment,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        legacy_owner_user_ids=legacy_owners,
    )
    _enforce_state_owner(state, owner_user_id, tenant_id)
    
    lock_id = request.query_params.get("ID")
    
    lock_key = _state_owner_key(project_id, environment)
    existing_lock = LOCK_STORE.get(lock_key)
    
    if existing_lock and existing_lock.get("ID") != lock_id:
        raise ArchmorphException(
            status_code=status.HTTP_423_LOCKED,
            message="State is locked by another process.",
            context={"lock_info": existing_lock}
        )
    
    payload = await request.json()
    
    state.previous_state_json = state.state_json
    state.state_json = payload
    state.updated_at = utc_now_naive()
    
    db.commit()
    return Response(status_code=200)

@router.api_route("/{project_id}/{environment}", methods=["LOCK"])
async def lock_tf_state(
    project_id: str,
    environment: str,
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_authenticated_user),
):
    owner_user_id, tenant_id, legacy_owners = _canonical_state_principal(request)
    state = get_deployment_state(
        db, project_id, environment,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        legacy_owner_user_ids=legacy_owners,
    )
    _enforce_state_owner(state, owner_user_id, tenant_id)
    
    body = await request.body()
    lock_info = json.loads(body) if body else {}
    req_lock_id = lock_info.get("ID")
    
    lock_key = _state_owner_key(project_id, environment)
    existing_lock = LOCK_STORE.get(lock_key)
    
    if existing_lock:
        if existing_lock.get("ID") != req_lock_id:
            return Response(
                content=json.dumps(existing_lock),
                status_code=status.HTTP_423_LOCKED,
                media_type="application/json"
            )
        else:
            return Response(status_code=200)
            
    LOCK_STORE.set(lock_key, lock_info)
    
    state.lock_id = req_lock_id
    state.lock_info = lock_info
    state.locked_at = utc_now_naive()
    db.commit()
    
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
    owner_user_id, tenant_id, legacy_owners = _canonical_state_principal(request)
    state = get_deployment_state(
        db, project_id, environment,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        legacy_owner_user_ids=legacy_owners,
    )
    _enforce_state_owner(state, owner_user_id, tenant_id)
    
    body = await request.body()
    lock_info = json.loads(body) if body else {}
    req_lock_id = lock_info.get("ID")
    
    lock_key = _state_owner_key(project_id, environment)
    existing_lock = LOCK_STORE.get(lock_key)
    
    if existing_lock and existing_lock.get("ID") != req_lock_id:
        return Response(
            content=json.dumps(existing_lock),
            status_code=status.HTTP_423_LOCKED,
            media_type="application/json"
        )
        
    LOCK_STORE.delete(lock_key)
    
    state.lock_id = None
    state.lock_info = None
    state.locked_at = None
    db.commit()
    
    return Response(status_code=200)

@router.post("/{project_id}/{environment}/rollback")
async def rollback_state(
    project_id: str,
    environment: str,
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_authenticated_user),
):
    owner_user_id, tenant_id, legacy_owners = _canonical_state_principal(request)
    state = get_deployment_state(
        db, project_id, environment,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        legacy_owner_user_ids=legacy_owners,
    )
    _enforce_state_owner(state, owner_user_id, tenant_id)
    if not state.previous_state_json:
        raise ArchmorphException(
            status_code=400,
            message="No previous state available to rollback."
        )
    
    current_state = state.state_json
    state.state_json = state.previous_state_json
    state.previous_state_json = current_state
    db.commit()
    
    return {"status": "rolled_back", "environment": environment}
