from error_envelope import ArchmorphException
"""
Architecture Versioning routes (v2.9.0).
"""

from fastapi import APIRouter, Depends, Query, Request
from typing import Optional

from routers.shared import SESSION_STORE, limiter, require_diagram_access, verify_api_key
from versioning import (
    create_version, get_version_history, get_version,
    restore_version, compare_versions,
)

router = APIRouter()


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
    version = create_version(
        diagram_id=diagram_id,
        snapshot=analysis,
        message=message,
    )
    
    return version.to_dict()


@router.get("/api/diagrams/{diagram_id}/versions", dependencies=[Depends(require_diagram_access)])
@limiter.limit("30/minute")
async def get_version_history_endpoint(
    request: Request,
    diagram_id: str,
    _auth=Depends(verify_api_key),
    _session=Depends(require_diagram_access),
):
    """Get version history for a diagram."""
    return get_version_history(diagram_id)


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
    version = get_version(diagram_id, version_number)
    if not version:
        raise ArchmorphException(404, f"Version {version_number} not found")
    
    return version.to_dict()


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
    snapshot = restore_version(diagram_id, version_number)
    if not snapshot:
        raise ArchmorphException(404, f"Version {version_number} not found")
    
    # Update session
    SESSION_STORE[diagram_id] = snapshot
    
    return {"success": True, "restored_from": version_number}


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
    return compare_versions(diagram_id, v1, v2)
