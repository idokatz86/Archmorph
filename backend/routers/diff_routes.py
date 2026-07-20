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

from database import SessionLocal
from routers.shared import limiter, persist_diagram_mutation, require_diagram_access, verify_api_key
from versioning import compare_versions, create_version, get_version

logger = logging.getLogger(__name__)

router = APIRouter()


def _durable_analysis(request: Request, diagram_id: str):
    from routers.shared import get_request_durable_principal, has_canonical_durable_principal

    principal = get_request_durable_principal(request)
    if not has_canonical_durable_principal(request):
        return None, None, None
    from workspace_store import get_analysis_by_diagram

    db = SessionLocal()
    analysis = get_analysis_by_diagram(
        db,
        diagram_id=diagram_id,
        owner_user_id=principal["owner_user_id"],
        tenant_id=principal["tenant_id"],
    )
    return db, principal, analysis


class SaveVersionRequest(StrictBaseModel):
    label: Optional[str] = Field(None, max_length=200)


class BranchRequest(StrictBaseModel):
    label: Optional[str] = Field(None, max_length=200)


@router.post("/api/diagrams/{diagram_id}/versions/save", dependencies=[Depends(require_diagram_access)])
@limiter.limit("10/minute")
async def save_version(
    request: Request,
    diagram_id: str,
    body: Optional[SaveVersionRequest] = None,
    _auth=Depends(verify_api_key),
    analysis=Depends(require_diagram_access),
):
    """Save current analysis state as a new version snapshot."""
    label = body.label if body else None
    from routers.shared import has_canonical_durable_principal

    if has_canonical_durable_principal(request):
        result = persist_diagram_mutation(
            request,
            diagram_id,
            analysis,
            label=label or "manual-version",
        )
        version = result.version
        return {
            "version": version.version_number,
            "version_number": version.version_number,
            "diagram_id": diagram_id,
            "label": version.label,
            "created_at": version.created_at.isoformat(),
        }
    version = create_version(diagram_id, analysis, message=label)
    return {
        "version": version.version_number,
        "version_number": version.version_number,
        "diagram_id": diagram_id,
        "label": version.message,
        "created_at": version.created_at.isoformat(),
        "compatibility": "transient-anonymous-or-sample-version-store",
    }


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
    _session=Depends(require_diagram_access),
):
    """Compare two version snapshots and return a structured diff."""
    if v1 == v2:
        raise ArchmorphException(400, "Cannot diff a version with itself")

    db, user, analysis = _durable_analysis(request, diagram_id)
    if db is None:
        diff = compare_versions(diagram_id, v1, v2)
        diff["compatibility"] = "transient-anonymous-or-sample-version-store"
    else:
        try:
            if analysis is None:
                raise ArchmorphException(404, "Diagram not found")
            from workspace_store import compare_analysis_versions

            diff = compare_analysis_versions(
                db,
                analysis_id=analysis.id,
                owner_user_id=user["owner_user_id"],
                tenant_id=user["tenant_id"],
                version_a=v1,
                version_b=v2,
            )
        finally:
            db.close()
    if "error" in diff:
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
    _session=Depends(require_diagram_access),
):
    """Fork a version for what-if analysis."""
    label = body.label if body else None
    db, user, analysis = _durable_analysis(request, diagram_id)
    if db is not None:
        try:
            if analysis is None:
                raise ArchmorphException(404, "Diagram not found")
            from workspace_store import get_analysis_version, persist_analysis_mutation

            source = get_analysis_version(
                db,
                analysis_id=analysis.id,
                version_number=version,
                owner_user_id=user["owner_user_id"],
                tenant_id=user["tenant_id"],
            )
            if source is None:
                raise ArchmorphException(404, f"Version {version} not found for diagram {diagram_id}")
            import json

            result = persist_analysis_mutation(
                db,
                owner_user_id=user["owner_user_id"],
                tenant_id=user["tenant_id"],
                diagram_id=diagram_id,
                snapshot=json.loads(source.snapshot),
                label=label or f"Branch from version {version}",
                restored_from=version,
            )
            branched = result.version
            return {
                "version": branched.version_number,
                "version_number": branched.version_number,
                "diagram_id": diagram_id,
                "label": branched.label,
                "created_at": branched.created_at.isoformat(),
                "branched_from": version,
            }
        finally:
            db.close()
    source = get_version(diagram_id, version)
    if source is None:
        raise ArchmorphException(404, f"Version {version} not found for diagram {diagram_id}")
    branched = create_version(diagram_id, source.snapshot, message=label or f"Branch from version {version}")
    return {
        "version": branched.version_number,
        "version_number": branched.version_number,
        "diagram_id": diagram_id,
        "label": branched.message,
        "created_at": branched.created_at.isoformat(),
        "branched_from": version,
        "compatibility": "transient-anonymous-or-sample-version-store",
    }
