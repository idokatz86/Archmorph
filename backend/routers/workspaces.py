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

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field

from database import get_db
from error_envelope import ArchmorphException
from log_sanitizer import safe
from routers.shared import SESSION_STORE, limiter, require_authenticated_user, verify_api_key
from strict_models import StrictBaseModel
from workspace_store import (
    create_analysis,
    create_decision,
    create_workspace,
    delete_workspace,
    get_analysis_record,
    get_analysis_version,
    get_artifact,
    get_workspace,
    list_analyses_in_workspace,
    list_analysis_versions,
    list_artifacts,
    list_decisions,
    list_workspaces,
    restore_analysis_version,
    update_workspace,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Workspaces"])


# ─────────────────────────────────────────────────────────────
# Request / Response schemas
# ─────────────────────────────────────────────────────────────

class CreateWorkspaceRequest(StrictBaseModel):
    name: str = Field(..., min_length=1, max_length=300)
    description: Optional[str] = Field(default=None, max_length=2000)
    source_cloud: str = Field(default="aws", max_length=20)
    target_cloud: str = Field(default="azure", max_length=20)


class UpdateWorkspaceRequest(StrictBaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=300)
    description: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[str] = Field(default=None)
    source_cloud: Optional[str] = Field(default=None, max_length=20)
    target_cloud: Optional[str] = Field(default=None, max_length=20)


class CreateAnalysisRequest(StrictBaseModel):
    diagram_id: Optional[str] = Field(default=None, max_length=100)
    source_asset_id: Optional[str] = Field(default=None, max_length=36)
    title: Optional[str] = Field(default=None, max_length=300)
    source_cloud: str = Field(default="aws", max_length=20)
    target_cloud: str = Field(default="azure", max_length=20)


class CreateDecisionRequest(StrictBaseModel):
    decision_type: str = Field(..., min_length=1, max_length=50)
    title: str = Field(..., min_length=1, max_length=300)
    description: Optional[str] = Field(default=None, max_length=5000)
    severity: Optional[str] = Field(default=None, max_length=20)
    version_id: Optional[str] = Field(default=None, max_length=36)


# ─────────────────────────────────────────────────────────────
# Workspace endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/workspaces")
@limiter.limit("20/minute")
async def create_workspace_endpoint(
    request: Request,
    body: CreateWorkspaceRequest,
    user=Depends(require_authenticated_user),
    _auth=Depends(verify_api_key),
    db=Depends(get_db),
):
    """Create a new durable workspace."""
    ws = create_workspace(
        db,
        owner_user_id=user.id,
        name=body.name,
        tenant_id=getattr(user, "tenant_id", None),
        description=body.description,
        source_cloud=body.source_cloud,
        target_cloud=body.target_cloud,
    )
    logger.info("workspace_created_via_api workspace_id=%s", safe(ws.id))
    return ws.to_dict()


@router.get("/workspaces")
@limiter.limit("60/minute")
async def list_workspaces_endpoint(
    request: Request,
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user=Depends(require_authenticated_user),
    _auth=Depends(verify_api_key),
    db=Depends(get_db),
):
    """List workspaces for the authenticated user."""
    return list_workspaces(
        db,
        owner_user_id=user.id,
        tenant_id=getattr(user, "tenant_id", None),
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/workspaces/{workspace_id}")
@limiter.limit("60/minute")
async def get_workspace_endpoint(
    request: Request,
    workspace_id: str,
    user=Depends(require_authenticated_user),
    _auth=Depends(verify_api_key),
    db=Depends(get_db),
):
    """Get a single workspace."""
    ws = get_workspace(db, workspace_id, owner_user_id=user.id)
    if ws is None:
        raise ArchmorphException(404, "Workspace not found")
    return ws.to_dict()


@router.patch("/workspaces/{workspace_id}")
@limiter.limit("30/minute")
async def update_workspace_endpoint(
    request: Request,
    workspace_id: str,
    body: UpdateWorkspaceRequest,
    user=Depends(require_authenticated_user),
    _auth=Depends(verify_api_key),
    db=Depends(get_db),
):
    """Update workspace metadata."""
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    ws = update_workspace(db, workspace_id, owner_user_id=user.id, **fields)
    if ws is None:
        raise ArchmorphException(404, "Workspace not found")
    return ws.to_dict()


@router.delete("/workspaces/{workspace_id}")
@limiter.limit("10/minute")
async def delete_workspace_endpoint(
    request: Request,
    workspace_id: str,
    user=Depends(require_authenticated_user),
    _auth=Depends(verify_api_key),
    db=Depends(get_db),
):
    """Delete a workspace and its analyses/versions/artifacts."""
    deleted = delete_workspace(db, workspace_id, owner_user_id=user.id)
    if not deleted:
        raise ArchmorphException(404, "Workspace not found")
    logger.info("workspace_deleted_via_api workspace_id=%s", safe(workspace_id))
    return {"deleted": True}


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
    _auth=Depends(verify_api_key),
    db=Depends(get_db),
):
    """Create a new analysis in a workspace."""
    # Verify workspace ownership first
    ws = get_workspace(db, workspace_id, owner_user_id=user.id)
    if ws is None:
        raise ArchmorphException(404, "Workspace not found")

    analysis = create_analysis(
        db,
        workspace_id=workspace_id,
        owner_user_id=user.id,
        tenant_id=getattr(user, "tenant_id", None),
        diagram_id=body.diagram_id,
        source_asset_id=body.source_asset_id,
        title=body.title,
        source_cloud=body.source_cloud,
        target_cloud=body.target_cloud,
    )
    return analysis.to_dict()


@router.get("/workspaces/{workspace_id}/analyses")
@limiter.limit("60/minute")
async def list_analyses_endpoint(
    request: Request,
    workspace_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user=Depends(require_authenticated_user),
    _auth=Depends(verify_api_key),
    db=Depends(get_db),
):
    """List analyses in a workspace."""
    ws = get_workspace(db, workspace_id, owner_user_id=user.id)
    if ws is None:
        raise ArchmorphException(404, "Workspace not found")
    return list_analyses_in_workspace(
        db,
        workspace_id=workspace_id,
        owner_user_id=user.id,
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
    _auth=Depends(verify_api_key),
    db=Depends(get_db),
):
    """Get a single analysis record."""
    analysis = get_analysis_record(db, analysis_id, owner_user_id=user.id)
    if analysis is None:
        raise ArchmorphException(404, "Analysis not found")
    return analysis.to_dict()


@router.get("/analyses/{analysis_id}/versions")
@limiter.limit("30/minute")
async def list_versions_endpoint(
    request: Request,
    analysis_id: str,
    user=Depends(require_authenticated_user),
    _auth=Depends(verify_api_key),
    db=Depends(get_db),
):
    """List version metadata for an analysis (snapshots excluded)."""
    analysis = get_analysis_record(db, analysis_id, owner_user_id=user.id)
    if analysis is None:
        raise ArchmorphException(404, "Analysis not found")
    return {"versions": list_analysis_versions(db, analysis_id=analysis_id, owner_user_id=user.id)}


@router.get("/analyses/{analysis_id}/versions/{version_number}")
@limiter.limit("30/minute")
async def get_version_endpoint(
    request: Request,
    analysis_id: str,
    version_number: int,
    user=Depends(require_authenticated_user),
    _auth=Depends(verify_api_key),
    db=Depends(get_db),
):
    """Get a specific analysis version including the full snapshot."""
    version = get_analysis_version(
        db,
        analysis_id=analysis_id,
        version_number=version_number,
        owner_user_id=user.id,
    )
    if version is None:
        raise ArchmorphException(404, f"Version {version_number} not found")
    return version.to_dict(include_snapshot=True)


@router.post("/analyses/{analysis_id}/versions/{version_number}/restore")
@limiter.limit("10/minute")
async def restore_version_endpoint(
    request: Request,
    analysis_id: str,
    version_number: int,
    user=Depends(require_authenticated_user),
    _auth=Depends(verify_api_key),
    db=Depends(get_db),
):
    """Restore an earlier version: creates a new version from it and updates the live session."""
    new_version = restore_analysis_version(
        db,
        analysis_id=analysis_id,
        version_number=version_number,
        owner_user_id=user.id,
        session_store=SESSION_STORE,
    )
    if new_version is None:
        raise ArchmorphException(404, f"Version {version_number} not found")
    logger.info(
        "analysis_version_restored analysis_id=%s from_version=%d new_version=%d",
        safe(analysis_id),
        version_number,
        new_version.version_number,
    )
    return {
        "restored_from": version_number,
        "new_version": new_version.to_dict(include_snapshot=False),
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
    _auth=Depends(verify_api_key),
    db=Depends(get_db),
):
    """List artifacts linked to an analysis."""
    analysis = get_analysis_record(db, analysis_id, owner_user_id=user.id)
    if analysis is None:
        raise ArchmorphException(404, "Analysis not found")
    return list_artifacts(
        db,
        analysis_id=analysis_id,
        owner_user_id=user.id,
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
    _auth=Depends(verify_api_key),
    db=Depends(get_db),
):
    """Get a single artifact, optionally including inline content."""
    analysis = get_analysis_record(db, analysis_id, owner_user_id=user.id)
    if analysis is None:
        raise ArchmorphException(404, "Analysis not found")
    artifact = get_artifact(db, artifact_id, owner_user_id=user.id)
    if artifact is None or artifact.analysis_id != analysis_id:
        raise ArchmorphException(404, "Artifact not found")
    return artifact.to_dict(include_content=include_content)


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
    _auth=Depends(verify_api_key),
    db=Depends(get_db),
):
    """List decisions/risks for an analysis."""
    analysis = get_analysis_record(db, analysis_id, owner_user_id=user.id)
    if analysis is None:
        raise ArchmorphException(404, "Analysis not found")
    return {
        "decisions": list_decisions(
            db,
            analysis_id=analysis_id,
            owner_user_id=user.id,
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
    _auth=Depends(verify_api_key),
    db=Depends(get_db),
):
    """Record a risk or architectural decision for an analysis."""
    analysis = get_analysis_record(db, analysis_id, owner_user_id=user.id)
    if analysis is None:
        raise ArchmorphException(404, "Analysis not found")
    decision = create_decision(
        db,
        analysis_id=analysis_id,
        owner_user_id=user.id,
        decision_type=body.decision_type,
        title=body.title,
        description=body.description,
        severity=body.severity,
        version_id=body.version_id,
    )
    return decision.to_dict()
