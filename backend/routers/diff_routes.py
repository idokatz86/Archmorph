from error_envelope import ArchmorphException
"""
Architecture Diff & Version Comparison routes.

Version snapshots and diffing for analysis results.
"""

from fastapi import APIRouter, Depends, Request, Query
from pydantic import Field
from strict_models import StrictBaseModel
from typing import Optional
import logging

from routers.shared import limiter, require_diagram_access, verify_api_key
import architecture_diff

logger = logging.getLogger(__name__)

router = APIRouter()


class SaveVersionRequest(StrictBaseModel):
    label: Optional[str] = Field(None, max_length=200)


class BranchRequest(StrictBaseModel):
    label: Optional[str] = Field(None, max_length=200)


# ─────────────────────────────────────────────────────────────
# Version Management
# ─────────────────────────────────────────────────────────────

@router.get("/api/diagrams/{diagram_id}/versions", dependencies=[Depends(require_diagram_access)])
@limiter.limit("30/minute")
async def list_versions(request: Request, diagram_id: str, _auth=Depends(verify_api_key)):
    """List all saved versions for a diagram."""
    require_diagram_access(request, diagram_id, purpose="list diff versions")
    versions = architecture_diff.list_versions(diagram_id)
    return {"diagram_id": diagram_id, "versions": versions, "total": len(versions)}


@router.get("/api/diagrams/{diagram_id}/versions/{version}", dependencies=[Depends(require_diagram_access)])
@limiter.limit("30/minute")
async def get_version(
    request: Request,
    diagram_id: str,
    version: int,
    _auth=Depends(verify_api_key),
):
    """Get a specific version snapshot."""
    require_diagram_access(request, diagram_id, purpose="view a diff version")
    record = architecture_diff.get_version(diagram_id, version)
    if record is None:
        raise ArchmorphException(404, f"Version {version} not found for diagram {diagram_id}")
    return record


@router.post("/api/diagrams/{diagram_id}/versions/save", dependencies=[Depends(require_diagram_access)])
@limiter.limit("10/minute")
async def save_version(
    request: Request,
    diagram_id: str,
    body: Optional[SaveVersionRequest] = None,
    _auth=Depends(verify_api_key),
):
    """Save current analysis state as a new version snapshot."""
    analysis = require_diagram_access(request, diagram_id, purpose="save a diff version")

    label = body.label if body else None
    result = architecture_diff.save_version(diagram_id, analysis, label=label)
    return result


# ─────────────────────────────────────────────────────────────
# Diff
# ─────────────────────────────────────────────────────────────

@router.get("/api/diagrams/{diagram_id}/diff", dependencies=[Depends(require_diagram_access)])
@limiter.limit("20/minute")
async def diff_versions(
    request: Request,
    diagram_id: str,
    v1: int = Query(..., ge=1),
    v2: int = Query(..., ge=1),
    _auth=Depends(verify_api_key),
):
    """Compare two version snapshots and return a structured diff."""
    require_diagram_access(request, diagram_id, purpose="view version diffs")
    if v1 == v2:
        raise ArchmorphException(400, "Cannot diff a version with itself")

    diff = architecture_diff.compute_diff(diagram_id, v1, v2)
    if diff is None:
        raise ArchmorphException(404, "One or both versions not found")
    return diff


# ─────────────────────────────────────────────────────────────
# What-If Branching
# ─────────────────────────────────────────────────────────────

@router.post("/api/diagrams/{diagram_id}/versions/{version}/branch", dependencies=[Depends(require_diagram_access)])
@limiter.limit("10/minute")
async def branch_version(
    request: Request,
    diagram_id: str,
    version: int,
    body: Optional[BranchRequest] = None,
    _auth=Depends(verify_api_key),
):
    """Fork a version for what-if analysis."""
    require_diagram_access(request, diagram_id, purpose="branch a diagram version")
    label = body.label if body else None
    result = architecture_diff.branch_version(diagram_id, version, label=label)
    if result is None:
        raise ArchmorphException(404, f"Version {version} not found for diagram {diagram_id}")
    return result
