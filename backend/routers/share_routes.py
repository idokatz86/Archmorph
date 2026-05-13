from error_envelope import ArchmorphException
"""
Stakeholder share routes — role-based shareable report links.

Extends the basic sharing in routers/sharing.py with role-filtered views
(executive, technical, financial) and share link management.
"""

from fastapi import APIRouter, Depends, Request, Query
from typing import Optional, Literal
import logging

from routers.shared import limiter, verify_api_key
from routers.samples import get_or_recreate_session
from auth import get_user_from_request_headers
import shareable_reports

logger = logging.getLogger(__name__)

router = APIRouter()


# ─────────────────────────────────────────────────────────────
# Shareable Stakeholder Reports
# ─────────────────────────────────────────────────────────────

@router.post("/api/diagrams/{diagram_id}/share")
@limiter.limit("10/minute")
async def create_stakeholder_share(
    request: Request,
    diagram_id: str,
    expiry_days: int = Query(30, ge=1, le=365),
    _auth=Depends(verify_api_key),
):
    """Generate a shareable stakeholder link with role-based views."""
    analysis = get_or_recreate_session(diagram_id)
    if not analysis:
        raise ArchmorphException(404, "Analysis not found")

    # Extract creator identity when the request also carries an end-user session.
    creator_id = None
    try:
        user = get_user_from_request_headers(dict(request.headers))
        if user and user.id:
            creator_id = user.id
    except Exception:
        pass

    result = shareable_reports.create_share(
        analysis_snapshot=analysis,
        creator_id=creator_id,
        expiry_days=expiry_days,
    )
    return result


@router.get("/api/shared/{share_id}")
@limiter.limit("60/minute")
async def get_shared_report(
    request: Request,
    share_id: str,
    view: Optional[Literal["executive", "technical", "financial"]] = None,
):
    """Get shared report (public, no auth). Optionally filter by view type."""
    record = shareable_reports.get_share(share_id)
    if not record:
        raise ArchmorphException(404, "Share link expired or invalid")

    snapshot = record["analysis_snapshot"]
    rendered = shareable_reports.render_view(snapshot, view_type=view)

    return {
        "share_id": share_id,
        "shared_at": record["created_at"],
        "expires_at": record["expires_at"],
        "read_only": True,
        **rendered,
    }


@router.get("/api/shared/{share_id}/stats")
@limiter.limit("30/minute")
async def get_share_stats(request: Request, share_id: str, _auth=Depends(verify_api_key)):
    """View count and metadata (creator only)."""
    stats = shareable_reports.get_share_stats(share_id)
    if not stats:
        raise ArchmorphException(404, "Share link not found")

    creator_id = stats.get("creator_id")
    if not creator_id:
        return stats

    try:
        user = get_user_from_request_headers(dict(request.headers))
        if not user or not user.id or user.id != creator_id:
            raise ArchmorphException(403, "Only the creator can view share stats")
    except ArchmorphException:
        raise
    except Exception:
        raise ArchmorphException(403, "Only the creator can view share stats")

    return stats


@router.delete("/api/shared/{share_id}")
@limiter.limit("10/minute")
async def revoke_share(request: Request, share_id: str, _auth=Depends(verify_api_key)):
    """Revoke a share link."""
    deleted = shareable_reports.delete_share(share_id)
    if not deleted:
        raise ArchmorphException(404, "Share link not found")
    return {"status": "revoked", "share_id": share_id}
