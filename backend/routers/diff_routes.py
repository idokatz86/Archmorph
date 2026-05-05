from error_envelope import ArchmorphException
"""
Architecture Diff & Version Comparison routes.

Version snapshots and diffing for analysis results.
"""

from fastapi import APIRouter, Request, Query
from pydantic import Field
from strict_models import StrictBaseModel
from typing import Optional
import logging

from routers.shared import limiter
from routers.samples import get_or_recreate_session
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

@router.get("/api/diagrams/{diagram_id}/versions")
@limiter.limit("30/minute")
async def list_versions(request: Request, diagram_id: str):
    """List all saved versions for a diagram."""
    versions = architecture_diff.list_versions(diagram_id)
    return {"diagram_id": diagram_id, "versions": versions, "total": len(versions)}


@router.get("/api/diagrams/{diagram_id}/versions/{version}")
@limiter.limit("30/minute")
async def get_version(request: Request, diagram_id: str, version: int):
    """Get a specific version snapshot."""
    record = architecture_diff.get_version(diagram_id, version)
    if record is None:
        raise ArchmorphException(404, f"Version {version} not found for diagram {diagram_id}")
    return record


@router.post("/api/diagrams/{diagram_id}/versions/save")
@limiter.limit("10/minute")
async def save_version(
    request: Request,
    diagram_id: str,
    body: Optional[SaveVersionRequest] = None,
):
    """Save current analysis state as a new version snapshot."""
    analysis = get_or_recreate_session(diagram_id)
    if not analysis:
        raise ArchmorphException(404, "Analysis not found")

    label = body.label if body else None
    result = architecture_diff.save_version(diagram_id, analysis, label=label)
    return result


# ─────────────────────────────────────────────────────────────
# Diff
# ─────────────────────────────────────────────────────────────

@router.get("/api/diagrams/{diagram_id}/diff")
@limiter.limit("20/minute")
async def diff_versions(
    request: Request,
    diagram_id: str,
    v1: int = Query(..., ge=1),
    v2: int = Query(..., ge=1),
):
    """Compare two version snapshots and return a structured diff."""
    if v1 == v2:
        raise ArchmorphException(400, "Cannot diff a version with itself")

    diff = architecture_diff.compute_diff(diagram_id, v1, v2)
    if diff is None:
        raise ArchmorphException(404, "One or both versions not found")
    return diff


# ─────────────────────────────────────────────────────────────
# What-If Branching
# ─────────────────────────────────────────────────────────────

@router.post("/api/diagrams/{diagram_id}/versions/{version}/branch")
@limiter.limit("10/minute")
async def branch_version(
    request: Request,
    diagram_id: str,
    version: int,
    body: Optional[BranchRequest] = None,
):
    """Fork a version for what-if analysis."""
    label = body.label if body else None
    result = architecture_diff.branch_version(diagram_id, version, label=label)
    if result is None:
        raise ArchmorphException(404, f"Version {version} not found for diagram {diagram_id}")
    return result
