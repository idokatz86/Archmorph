"""
Durable Workspace routes (Issue #1129).

Provides CRUD for workspaces, analyses, analysis versions, artifacts,
and decisions.  All routes require an authenticated user (Bearer session
or API key).

Route map
---------
  POST   /api/workspaces                           — create workspace
  GET    /api/workspaces                           — list own workspaces
  GET    /api/workspaces/{workspace_id}            — get workspace
  PATCH  /api/workspaces/{workspace_id}            — update workspace
  DELETE /api/workspaces/{workspace_id}            — delete workspace

  POST   /api/workspaces/{workspace_id}/analyses   — create analysis
  GET    /api/workspaces/{workspace_id}/analyses   — list analyses

  GET    /api/analyses/{analysis_id}               — get analysis
  GET    /api/analyses/{analysis_id}/versions      — list versions (no snapshot)
  GET    /api/analyses/{analysis_id}/versions/{n}  — get version (with snapshot)
  POST   /api/analyses/{analysis_id}/versions/{n}/restore — restore version

  GET    /api/analyses/{analysis_id}/artifacts     — list artifacts
  GET    /api/analyses/{analysis_id}/artifacts/{artifact_id} — get artifact

  GET    /api/analyses/{analysis_id}/decisions     — list decisions
  POST   /api/analyses/{analysis_id}/decisions     — create decision
"""

from enum import Enum
from functools import partial
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from error_envelope import ArchmorphException
from routers.shared import (
    SESSION_STORE,
    get_request_durable_principal,
    limiter,
    require_api_read_or_user_session,
    require_api_write_or_user_session,
    require_authenticated_user,
)
from strict_models import StrictBaseModel
from workspace_store import (
    AnalysisVersionConflictError,
    create_analysis,
    create_decision,
    create_workspace,
    get_analysis_record,
    get_analysis_version,
    get_artifact,
    get_workspace,
    list_analyses_in_workspace,
    list_analysis_versions,
    list_artifacts,
    list_decisions,
    list_workspaces,
    link_analysis_to_workspace,
    load_analysis_state,
    owner_migration_conflict_status,
    restore_analysis_version,
    rehome_legacy_owner_scope,
    update_workspace,
)
from models.workspace import DecisionSeverity, DecisionType, WorkspaceStatus

router = APIRouter(prefix="/api", tags=["Workspaces"])


# ─────────────────────────────────────────────────────────────
# Request / Response schemas
# ─────────────────────────────────────────────────────────────

class CreateWorkspaceRequest(StrictBaseModel):
    name: str = Field(..., min_length=1, max_length=300)
    description: Optional[str] = Field(default=None, max_length=2000)
    source_cloud: str = Field(default="aws", max_length=20)
    target_cloud: str = Field(default="azure", max_length=20)


class WorkspaceStatusValue(str, Enum):
    active = WorkspaceStatus.ACTIVE.value
    archived = WorkspaceStatus.ARCHIVED.value


class UpdateWorkspaceRequest(StrictBaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=300)
    description: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[WorkspaceStatusValue] = Field(default=None)
    source_cloud: Optional[str] = Field(default=None, max_length=20)
    target_cloud: Optional[str] = Field(default=None, max_length=20)


class CreateAnalysisRequest(StrictBaseModel):
    diagram_id: Optional[str] = Field(default=None, max_length=100)
    source_asset_id: Optional[str] = Field(default=None, max_length=36)
    title: Optional[str] = Field(default=None, max_length=300)
    source_cloud: str = Field(default="aws", max_length=20)
    target_cloud: str = Field(default="azure", max_length=20)


class CreateDecisionRequest(StrictBaseModel):
    decision_type: DecisionType
    title: str = Field(..., min_length=1, max_length=300)
    description: Optional[str] = Field(default=None, max_length=5000)
    severity: Optional[DecisionSeverity] = Field(default=None)
    version_id: Optional[str] = Field(default=None, max_length=36)


def _expected_version(if_match: str) -> int:
    value = if_match.strip()
    if value.startswith('W/"') and value.endswith('"'):
        value = value[3:-1]
    elif value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    try:
        expected = int(value)
    except ValueError as exc:
        raise ArchmorphException(400, "If-Match must contain an integer analysis version") from exc
    if expected < 0:
        raise ArchmorphException(400, "If-Match must contain a non-negative analysis version")
    return expected


def _tenant_id(user) -> Optional[str]:
    tenant_id = getattr(user, "tenant_id", None)
    if not tenant_id:
        raise ArchmorphException(
            401,
            "Authenticated tenant context is required for durable workspace state.",
            details={"error": "tenant_context_required"},
        )
    return tenant_id


def _owner_id(request: Request, user) -> str:
    principal = get_request_durable_principal(request)
    return principal["owner_user_id"] if principal else user.id


async def _db_call(function, /, *args, **kwargs):
    """Run one synchronous SQLAlchemy unit of work in a thread-local session."""
    def invoke():
        from database import SessionLocal

        db = SessionLocal()
        try:
            return function(db, *args, **kwargs)
        finally:
            db.close()

    return await run_in_threadpool(partial(invoke))


def _link_analysis_payload(db, **kwargs):
    analysis, previous_workspace_id = link_analysis_to_workspace(db, **kwargs)
    return analysis.to_dict(), previous_workspace_id


async def _migrate_legacy_owner_graphs(request: Request) -> None:
    principal = get_request_durable_principal(request)
    if principal is None or not principal.get("tenant_id"):
        return
    source_owners = [
        principal["owner_user_id"],
        *principal.get("legacy_owner_user_ids", []),
    ]
    await _db_call(
        rehome_legacy_owner_scope,
        owner_user_ids=source_owners,
        source_tenant_id="default_tenant",
        target_tenant_id=principal["tenant_id"],
        target_owner_user_id=principal["owner_user_id"],
    )
    for legacy_scope in principal.get("legacy_owner_scopes", []):
        await _db_call(
            rehome_legacy_owner_scope,
            owner_user_ids=[legacy_scope["owner_user_id"]],
            source_tenant_id=legacy_scope["tenant_id"],
            target_tenant_id=principal["tenant_id"],
            target_owner_user_id=principal["owner_user_id"],
        )


# ─────────────────────────────────────────────────────────────
# Workspace endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/workspaces")
@limiter.limit("20/minute")
async def create_workspace_endpoint(
    request: Request,
    body: CreateWorkspaceRequest,
    user=Depends(require_authenticated_user),
    _auth=Depends(require_api_write_or_user_session),
):
    """Create a new durable workspace."""
    await _migrate_legacy_owner_graphs(request)
    ws = await _db_call(
        lambda db, **kwargs: create_workspace(db, **kwargs).to_dict(),
        owner_user_id=_owner_id(request, user),
        name=body.name,
        tenant_id=_tenant_id(user),
        description=body.description,
        source_cloud=body.source_cloud,
        target_cloud=body.target_cloud,
    )
    return ws


@router.get("/workspaces")
@limiter.limit("60/minute")
async def list_workspaces_endpoint(
    request: Request,
    status: Optional[WorkspaceStatusValue] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user=Depends(require_authenticated_user),
    _auth=Depends(require_api_read_or_user_session),
):
    """List workspaces for the authenticated user."""
    await _migrate_legacy_owner_graphs(request)
    owner_user_id = _owner_id(request, user)
    result = await _db_call(
        list_workspaces,
        owner_user_id=owner_user_id,
        tenant_id=_tenant_id(user),
        status=status.value if status is not None else None,
        limit=limit,
        offset=offset,
    )
    result["migration"] = await _db_call(
        owner_migration_conflict_status,
        target_owner_user_id=owner_user_id,
        target_tenant_id=_tenant_id(user),
    )
    return result


@router.get("/workspaces/{workspace_id}")
@limiter.limit("60/minute")
async def get_workspace_endpoint(
    request: Request,
    workspace_id: str,
    user=Depends(require_authenticated_user),
    _auth=Depends(require_api_read_or_user_session),
):
    """Get a single workspace."""
    await _migrate_legacy_owner_graphs(request)
    ws = await _db_call(
        lambda db, workspace_id, **kwargs: (
            workspace.to_dict()
            if (workspace := get_workspace(db, workspace_id, **kwargs)) is not None
            else None
        ),
        workspace_id,
        owner_user_id=_owner_id(request, user),
        tenant_id=_tenant_id(user),
    )
    if ws is None:
        raise ArchmorphException(404, "Workspace not found")
    return ws


@router.patch("/workspaces/{workspace_id}")
@limiter.limit("30/minute")
async def update_workspace_endpoint(
    request: Request,
    workspace_id: str,
    body: UpdateWorkspaceRequest,
    user=Depends(require_authenticated_user),
    _auth=Depends(require_api_write_or_user_session),
):
    """Update workspace metadata."""
    fields = {
        key: (value.value if isinstance(value, Enum) else value)
        for key, value in body.model_dump().items()
        if value is not None
    }
    try:
        ws = await _db_call(
            lambda db, workspace_id, **kwargs: (
                workspace.to_dict()
                if (workspace := update_workspace(db, workspace_id, **kwargs)) is not None
                else None
            ),
            workspace_id,
            owner_user_id=_owner_id(request, user),
            tenant_id=_tenant_id(user),
            **fields,
        )
    except ValueError as exc:
        raise ArchmorphException(409, str(exc)) from exc
    if ws is None:
        raise ArchmorphException(404, "Workspace not found")
    return ws


@router.delete("/workspaces/{workspace_id}")
@limiter.limit("10/minute")
async def delete_workspace_endpoint(
    request: Request,
    workspace_id: str,
    user=Depends(require_authenticated_user),
    _auth=Depends(require_api_write_or_user_session),
):
    """Converge all workspace-owned state to a confirmed deletion fixed point."""
    from purge_service import PurgeIncompleteError, purge_workspace

    owner_user_id = _owner_id(request, user)
    tenant_id = _tenant_id(user)
    try:
        result = await run_in_threadpool(
            partial(
                purge_workspace,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                tenant_id=tenant_id,
            )
        )
    except ValueError as exc:
        raise ArchmorphException(404, "Workspace not found") from exc
    except PurgeIncompleteError as exc:
        raise ArchmorphException(
            503,
            "Workspace purge is incomplete and can be retried.",
            details={
                "error": "workspace_purge_pending",
                "operation_id": exc.operation_id,
                "pending_stage": exc.stage,
            },
            headers={"Retry-After": "5"},
        ) from exc
    return {
        "deleted": True,
        "status": result.status,
        "operation_id": result.operation_id,
    }


# ─────────────────────────────────────────────────────────────
# Analysis endpoints (under workspace)
# ─────────────────────────────────────────────────────────────

@router.post("/workspaces/{workspace_id}/analyses")
@limiter.limit("20/minute")
async def create_analysis_endpoint(
    request: Request,
    workspace_id: str,
    body: CreateAnalysisRequest,
    user=Depends(require_authenticated_user),
    _auth=Depends(require_api_write_or_user_session),
):
    """Create a new analysis in a workspace."""
    # Verify workspace ownership first
    owner_user_id = _owner_id(request, user)
    ws = await _db_call(
        get_workspace,
        workspace_id,
        owner_user_id=owner_user_id,
        tenant_id=_tenant_id(user),
    )
    if ws is None:
        raise ArchmorphException(404, "Workspace not found")
    if body.diagram_id:
        try:
            result, previous_workspace_id = await _db_call(
                _link_analysis_payload,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                tenant_id=_tenant_id(user),
                diagram_id=body.diagram_id,
            )
        except ValueError as exc:
            raise ArchmorphException(404, "Analysis not found") from exc
        from routers.shared import PROJECT_STORE

        for cached_workspace_id in {workspace_id, previous_workspace_id}:
            if cached_workspace_id:
                PROJECT_STORE.delete(cached_workspace_id)
        if int(result.get("current_version") or 0) > 0:
            await _db_call(
                load_analysis_state,
                diagram_id=body.diagram_id,
                owner_user_id=owner_user_id,
                tenant_id=_tenant_id(user),
                session_store=SESSION_STORE,
                cache_owner_api_key_id=(get_request_durable_principal(request) or {}).get(
                    "owner_api_key_id"
                ),
            )
        return result

    analysis = await _db_call(
        lambda db, **kwargs: create_analysis(db, **kwargs).to_dict(),
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        tenant_id=_tenant_id(user),
        diagram_id=body.diagram_id,
        source_asset_id=body.source_asset_id,
        title=body.title,
        source_cloud=body.source_cloud,
        target_cloud=body.target_cloud,
    )
    return analysis


@router.get("/workspaces/{workspace_id}/analyses")
@limiter.limit("60/minute")
async def list_analyses_endpoint(
    request: Request,
    workspace_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user=Depends(require_authenticated_user),
    _auth=Depends(require_api_read_or_user_session),
):
    """List analyses in a workspace."""
    owner_user_id = _owner_id(request, user)
    await _migrate_legacy_owner_graphs(request)
    ws = await _db_call(
        get_workspace,
        workspace_id,
        owner_user_id=owner_user_id,
        tenant_id=_tenant_id(user),
    )
    if ws is None:
        raise ArchmorphException(404, "Workspace not found")
    return await _db_call(
        list_analyses_in_workspace,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        tenant_id=_tenant_id(user),
        limit=limit,
        offset=offset,
    )


# ─────────────────────────────────────────────────────────────
# Analysis detail + version endpoints
# ─────────────────────────────────────────────────────────────

@router.get("/analyses/{analysis_id}")
@limiter.limit("60/minute")
async def get_analysis_endpoint(
    request: Request,
    analysis_id: str,
    user=Depends(require_authenticated_user),
    _auth=Depends(require_api_read_or_user_session),
):
    """Get a single analysis record."""
    analysis = await _db_call(
        lambda db, analysis_id, **kwargs: (
            record.to_dict()
            if (record := get_analysis_record(db, analysis_id, **kwargs)) is not None
            else None
        ),
        analysis_id,
        owner_user_id=_owner_id(request, user),
        tenant_id=_tenant_id(user),
    )
    if analysis is None:
        raise ArchmorphException(404, "Analysis not found")
    return analysis


@router.get("/analyses/{analysis_id}/versions")
@limiter.limit("30/minute")
async def list_versions_endpoint(
    request: Request,
    analysis_id: str,
    user=Depends(require_authenticated_user),
    _auth=Depends(require_api_read_or_user_session),
):
    """List version metadata for an analysis (snapshots excluded)."""
    owner_user_id = _owner_id(request, user)
    analysis = await _db_call(
        get_analysis_record,
        analysis_id,
        owner_user_id=owner_user_id,
        tenant_id=_tenant_id(user),
    )
    if analysis is None:
        raise ArchmorphException(404, "Analysis not found")
    versions = await _db_call(
        list_analysis_versions,
        analysis_id=analysis_id,
        owner_user_id=owner_user_id,
        tenant_id=_tenant_id(user),
    )
    return {"versions": versions}


@router.get("/analyses/{analysis_id}/versions/{version_number}")
@limiter.limit("30/minute")
async def get_version_endpoint(
    request: Request,
    analysis_id: str,
    version_number: int,
    user=Depends(require_authenticated_user),
    _auth=Depends(require_api_read_or_user_session),
):
    """Get a specific analysis version including the full snapshot."""
    version = await _db_call(
        lambda db, **kwargs: (
            record.to_dict(include_snapshot=True)
            if (record := get_analysis_version(db, **kwargs)) is not None
            else None
        ),
        analysis_id=analysis_id,
        version_number=version_number,
        owner_user_id=_owner_id(request, user),
        tenant_id=_tenant_id(user),
    )
    if version is None:
        raise ArchmorphException(404, f"Version {version_number} not found")
    return version


@router.post("/analyses/{analysis_id}/versions/{version_number}/restore")
@limiter.limit("10/minute")
async def restore_version_endpoint(
    request: Request,
    analysis_id: str,
    version_number: int,
    if_match: str = Header(..., alias="If-Match"),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=200),
    user=Depends(require_authenticated_user),
    _auth=Depends(require_api_write_or_user_session),
):
    """Restore an earlier version: creates a new version from it and updates the live session."""
    principal = get_request_durable_principal(request) or {}
    try:
        new_version = await _db_call(
            lambda db, **kwargs: (
                record.to_dict(include_snapshot=False)
                if (record := restore_analysis_version(db, **kwargs)) is not None
                else None
            ),
            analysis_id=analysis_id,
            version_number=version_number,
            owner_user_id=_owner_id(request, user),
            tenant_id=_tenant_id(user),
            session_store=SESSION_STORE,
            cache_owner_api_key_id=principal.get("owner_api_key_id"),
            expected_version=_expected_version(if_match),
            idempotency_key=idempotency_key,
        )
    except AnalysisVersionConflictError as exc:
        raise ArchmorphException(409, str(exc)) from exc
    except ValueError as exc:
        raise ArchmorphException(400, str(exc)) from exc
    if new_version is None:
        raise ArchmorphException(404, f"Version {version_number} not found")
    return {
        "restored_from": version_number,
        "new_version": new_version,
    }


# ─────────────────────────────────────────────────────────────
# Artifact endpoints
# ─────────────────────────────────────────────────────────────

@router.get("/analyses/{analysis_id}/artifacts")
@limiter.limit("60/minute")
async def list_artifacts_endpoint(
    request: Request,
    analysis_id: str,
    artifact_type: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user=Depends(require_authenticated_user),
    _auth=Depends(require_api_read_or_user_session),
):
    """List artifacts linked to an analysis."""
    owner_user_id = _owner_id(request, user)
    analysis = await _db_call(
        get_analysis_record,
        analysis_id,
        owner_user_id=owner_user_id,
        tenant_id=_tenant_id(user),
    )
    if analysis is None:
        raise ArchmorphException(404, "Analysis not found")
    return await _db_call(
        list_artifacts,
        analysis_id=analysis_id,
        owner_user_id=owner_user_id,
        tenant_id=_tenant_id(user),
        artifact_type=artifact_type,
        limit=limit,
        offset=offset,
    )


@router.get("/analyses/{analysis_id}/artifacts/{artifact_id}")
@limiter.limit("30/minute")
async def get_artifact_endpoint(
    request: Request,
    analysis_id: str,
    artifact_id: str,
    include_content: bool = Query(default=False),
    user=Depends(require_authenticated_user),
    _auth=Depends(require_api_read_or_user_session),
):
    """Get a single artifact, optionally including inline content."""
    owner_user_id = _owner_id(request, user)
    analysis = await _db_call(
        get_analysis_record,
        analysis_id,
        owner_user_id=owner_user_id,
        tenant_id=_tenant_id(user),
    )
    if analysis is None:
        raise ArchmorphException(404, "Analysis not found")
    artifact = await _db_call(
        lambda db, artifact_id, **kwargs: (
            record.to_dict(include_content=include_content)
            if (record := get_artifact(db, artifact_id, **kwargs)) is not None
            else None
        ),
        artifact_id,
        owner_user_id=owner_user_id,
        tenant_id=_tenant_id(user),
    )
    if artifact is None or artifact["analysis_id"] != analysis_id:
        raise ArchmorphException(404, "Artifact not found")
    return artifact


# ─────────────────────────────────────────────────────────────
# Decision endpoints
# ─────────────────────────────────────────────────────────────

@router.get("/analyses/{analysis_id}/decisions")
@limiter.limit("30/minute")
async def list_decisions_endpoint(
    request: Request,
    analysis_id: str,
    decision_type: Optional[str] = Query(default=None),
    user=Depends(require_authenticated_user),
    _auth=Depends(require_api_read_or_user_session),
):
    """List decisions/risks for an analysis."""
    owner_user_id = _owner_id(request, user)
    analysis = await _db_call(
        get_analysis_record,
        analysis_id,
        owner_user_id=owner_user_id,
        tenant_id=_tenant_id(user),
    )
    if analysis is None:
        raise ArchmorphException(404, "Analysis not found")
    return {
        "decisions": await _db_call(
            list_decisions,
            analysis_id=analysis_id,
            owner_user_id=owner_user_id,
            tenant_id=_tenant_id(user),
            decision_type=decision_type,
        )
    }


@router.post("/analyses/{analysis_id}/decisions")
@limiter.limit("20/minute")
async def create_decision_endpoint(
    request: Request,
    analysis_id: str,
    body: CreateDecisionRequest,
    user=Depends(require_authenticated_user),
    _auth=Depends(require_api_write_or_user_session),
):
    """Record a risk or architectural decision for an analysis."""
    owner_user_id = _owner_id(request, user)
    analysis = await _db_call(
        get_analysis_record,
        analysis_id,
        owner_user_id=owner_user_id,
        tenant_id=_tenant_id(user),
    )
    if analysis is None:
        raise ArchmorphException(404, "Analysis not found")
    try:
        decision = await _db_call(
            lambda db, **kwargs: create_decision(db, **kwargs).to_dict(),
            analysis_id=analysis_id,
            owner_user_id=owner_user_id,
            tenant_id=_tenant_id(user),
            decision_type=body.decision_type.value,
            title=body.title,
            description=body.description,
            severity=body.severity.value if body.severity is not None else None,
            version_id=body.version_id,
        )
    except ValueError as exc:
        raise ArchmorphException(422, str(exc)) from exc
    return decision
