from error_envelope import ArchmorphException
"""
Architecture Versioning routes (v2.9.0).
"""

from fastapi import APIRouter, Depends, Query, Request
from typing import Optional

from database import SessionLocal
from routers.shared import SESSION_STORE, limiter, persist_diagram_mutation, require_diagram_access, verify_api_key
from versioning import (
    create_version, get_version_history, get_version,
    restore_version, compare_versions,
)

router = APIRouter()


def _durable_analysis(request: Request, diagram_id: str):
    from routers.shared import get_request_durable_principal

    principal = get_request_durable_principal(request)
    if principal is None or not principal["tenant_id"]:
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


@router.post("/api/diagrams/{diagram_id}/versions", dependencies=[Depends(require_diagram_access)])
@limiter.limit("10/minute")
async def create_version_endpoint(
    request: Request,
    diagram_id: str,
    message: Optional[str] = None,
    _auth=Depends(verify_api_key),
    analysis=Depends(require_diagram_access),
):
    """Create a new version of an architecture analysis."""
    from routers.shared import get_request_durable_principal

    principal = get_request_durable_principal(request)
    if principal is not None:
        result = persist_diagram_mutation(
            request,
            diagram_id,
            analysis,
            label=message or "manual-version",
        )
        return result.version.to_dict()
    version = create_version(diagram_id=diagram_id, snapshot=analysis, message=message)
    return {**version.to_dict(), "compatibility": "transient-anonymous-or-sample-version-store"}


@router.get("/api/diagrams/{diagram_id}/versions", dependencies=[Depends(require_diagram_access)])
@limiter.limit("30/minute")
async def get_version_history_endpoint(
    request: Request,
    diagram_id: str,
    _auth=Depends(verify_api_key),
    _session=Depends(require_diagram_access),
):
    """Get version history for a diagram."""
    db, user, analysis = _durable_analysis(request, diagram_id)
    if db is None:
        return {**get_version_history(diagram_id), "compatibility": "transient-anonymous-or-sample-version-store"}
    try:
        if analysis is None:
            raise ArchmorphException(404, "Diagram not found")
        from workspace_store import list_analysis_versions

        versions = list_analysis_versions(
            db,
            analysis_id=analysis.id,
            owner_user_id=user["owner_user_id"],
            tenant_id=user["tenant_id"],
        )
        return {
            "diagram_id": diagram_id,
            "current_version": analysis.current_version,
            "total_versions": len(versions),
            "versions": versions,
            "timeline": [
                {
                    "version": item["version_number"],
                    "timestamp": item["created_at"],
                    "message": item["label"],
                    "changes_count": 0,
                }
                for item in versions
            ],
        }
    finally:
        db.close()


@router.get("/api/diagrams/{diagram_id}/versions/{version_number}", dependencies=[Depends(require_diagram_access)])
@limiter.limit("30/minute")
async def get_version_endpoint(
    request: Request,
    diagram_id: str,
    version_number: int,
    _auth=Depends(verify_api_key),
    _session=Depends(require_diagram_access),
):
    """Get a specific version of an architecture."""
    db, user, analysis = _durable_analysis(request, diagram_id)
    if db is None:
        version = get_version(diagram_id, version_number)
        if not version:
            raise ArchmorphException(404, f"Version {version_number} not found")
        return {**version.to_dict(), "compatibility": "transient-anonymous-or-sample-version-store"}
    try:
        if analysis is None:
            raise ArchmorphException(404, "Diagram not found")
        from workspace_store import get_analysis_version

        version = get_analysis_version(
            db,
            analysis_id=analysis.id,
            version_number=version_number,
            owner_user_id=user["owner_user_id"],
            tenant_id=user["tenant_id"],
        )
        if version is None:
            raise ArchmorphException(404, f"Version {version_number} not found")
        return version.to_dict(include_snapshot=True)
    finally:
        db.close()


@router.post("/api/diagrams/{diagram_id}/versions/{version_number}/restore", dependencies=[Depends(require_diagram_access)])
@limiter.limit("10/minute")
async def restore_version_endpoint(
    request: Request,
    diagram_id: str,
    version_number: int,
    _auth=Depends(verify_api_key),
    _session=Depends(require_diagram_access),
):
    """Restore a previous version, creating a new version from it."""
    db, user, analysis = _durable_analysis(request, diagram_id)
    if db is None:
        snapshot = restore_version(diagram_id, version_number)
        if not snapshot:
            raise ArchmorphException(404, f"Version {version_number} not found")
        SESSION_STORE[diagram_id] = snapshot
        return {
            "success": True,
            "restored_from": version_number,
            "compatibility": "transient-anonymous-or-sample-version-store",
        }
    try:
        if analysis is None:
            raise ArchmorphException(404, "Diagram not found")
        from workspace_store import restore_analysis_version

        restored = restore_analysis_version(
            db,
            analysis_id=analysis.id,
            version_number=version_number,
            owner_user_id=user["owner_user_id"],
            tenant_id=user["tenant_id"],
            session_store=SESSION_STORE,
            cache_owner_api_key_id=user["owner_api_key_id"],
        )
        if restored is None:
            raise ArchmorphException(404, f"Version {version_number} not found")
        return {
            "success": True,
            "restored_from": version_number,
            "new_version": restored.to_dict(),
        }
    finally:
        db.close()


@router.get("/api/diagrams/{diagram_id}/versions/compare", dependencies=[Depends(require_diagram_access)])
@limiter.limit("30/minute")
async def compare_versions_endpoint(
    request: Request,
    diagram_id: str,
    v1: int = Query(..., description="First version number"),
    v2: int = Query(..., description="Second version number"),
    _auth=Depends(verify_api_key),
    _session=Depends(require_diagram_access),
):
    """Compare two versions of an architecture."""
    db, user, analysis = _durable_analysis(request, diagram_id)
    if db is None:
        return {
            **compare_versions(diagram_id, v1, v2),
            "compatibility": "transient-anonymous-or-sample-version-store",
        }
    try:
        if analysis is None:
            raise ArchmorphException(404, "Diagram not found")
        from workspace_store import compare_analysis_versions

        return compare_analysis_versions(
            db,
            analysis_id=analysis.id,
            owner_user_id=user["owner_user_id"],
            tenant_id=user["tenant_id"],
            version_a=v1,
            version_b=v2,
        )
    finally:
        db.close()
