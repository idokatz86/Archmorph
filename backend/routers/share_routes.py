from error_envelope import ArchmorphException
"""
Stakeholder share routes — role-based shareable report links.

Extends the basic sharing in routers/sharing.py with role-filtered views
(executive, architect, devops, security, finops) and share link management.
All create/access/revoke actions are written to the audit log.
"""

from fastapi import APIRouter, Depends, Request, Query
from typing import Optional, Literal
import logging

from routers.shared import (
    authorize_diagram_access,
    get_api_key_service_principal,
    limiter,
    require_diagram_access,
    verify_api_key,
)
from auth import get_user_from_request_headers
from audit_logging import AuditEventType, AuditSeverity, log_audit_event
import shareable_reports

logger = logging.getLogger(__name__)

router = APIRouter()

# All supported view types, including legacy aliases
_ALL_VIEW_TYPES = Literal[
    "executive",
    "architect",
    "devops",
    "security",
    "finops",
    "technical",
    "financial",
]


def require_share_access(request: Request, share_id: str) -> dict:
    record = shareable_reports.get_share_stats(share_id)
    if not record:
        raise ArchmorphException(404, "Share link not found")

    headers = dict(request.headers)
    user = get_user_from_request_headers(headers)
    if user:
        creator_id = record.get("creator_id")
        creator_tenant_id = record.get("creator_tenant_id")
        if creator_id and creator_id == user.id and (
            creator_tenant_id is None or creator_tenant_id == user.tenant_id
        ):
            return record
        if not creator_id:
            raise ArchmorphException(404, "Share link not found")
        raise ArchmorphException(403, "Only the creator can access this share")

    api_key_principal_id = get_api_key_service_principal(headers)
    if not api_key_principal_id:
        raise ArchmorphException(401, "Authentication required")
    if record.get("creator_api_principal_id") != api_key_principal_id:
        raise ArchmorphException(404, "Share link not found")
    return record


# ─────────────────────────────────────────────────────────────
# Shareable Stakeholder Reports
# ─────────────────────────────────────────────────────────────

@router.post("/api/diagrams/{diagram_id}/share", dependencies=[Depends(require_diagram_access)])
@limiter.limit("10/minute")
async def create_stakeholder_share(
    request: Request,
    diagram_id: str,
    expiry_days: int = Query(30, ge=1, le=365),
    _auth=Depends(verify_api_key),
):
    """Generate a shareable stakeholder link with role-based views."""
    analysis = authorize_diagram_access(request, diagram_id, purpose="create a share link")

    # Extract creator identity when the request also carries an end-user session.
    creator_id = None
    creator_tenant_id = None
    creator_api_principal_id = None
    try:
        user = get_user_from_request_headers(dict(request.headers))
        if user and user.id:
            creator_id = user.id
            creator_tenant_id = user.tenant_id
        elif not user:
            creator_api_principal_id = get_api_key_service_principal(dict(request.headers))
    except Exception:
        pass

    # Detect whether this is a public sample (no private-tenant ownership marker)
    is_sample = not bool(analysis.get("_owner_user_id") or analysis.get("_owner_api_key_id"))

    result = shareable_reports.create_share(
        analysis_snapshot=analysis,
        creator_id=creator_id,
        creator_tenant_id=creator_tenant_id,
        creator_api_principal_id=creator_api_principal_id,
        expiry_days=expiry_days,
        is_sample=is_sample,
    )

    log_audit_event(
        event_type=AuditEventType.SHARE_CREATE,
        user_id=creator_id,
        endpoint=f"/api/diagrams/{diagram_id}/share",
        method="POST",
        status_code=200,
        details={
            "share_id": result.get("share_id"),
            "diagram_id": diagram_id,
            "expiry_days": expiry_days,
            "is_sample": is_sample,
        },
        severity=AuditSeverity.INFO,
    )

    return result


@router.get("/api/shared/{share_id}")
@limiter.limit("60/minute")
async def get_shared_report(
    request: Request,
    share_id: str,
    view: Optional[_ALL_VIEW_TYPES] = None,
):
    """Get shared report (public, no auth). Optionally filter by role view type.

    Supported views: executive, architect, devops, security, finops.
    Legacy aliases: technical (→ architect), financial (→ finops).
    """
    record = shareable_reports.get_share(share_id)
    if not record:
        log_audit_event(
            event_type=AuditEventType.SHARE_ACCESS,
            endpoint=f"/api/shared/{share_id}",
            method="GET",
            status_code=404,
            details={"share_id": share_id, "outcome": "expired_or_revoked"},
            severity=AuditSeverity.WARNING,
        )
        raise ArchmorphException(404, "Share link expired or invalid")

    snapshot = record["analysis_snapshot"]
    rendered = shareable_reports.render_view(snapshot, view_type=view)

    log_audit_event(
        event_type=AuditEventType.SHARE_ACCESS,
        endpoint=f"/api/shared/{share_id}",
        method="GET",
        status_code=200,
        details={
            "share_id": share_id,
            "view": view,
            "is_sample": record.get("is_sample", False),
            "view_count": record.get("view_count"),
        },
        severity=AuditSeverity.INFO,
    )

    return {
        "share_id": share_id,
        "shared_at": record["created_at"],
        "expires_at": record["expires_at"],
        "read_only": True,
        "is_sample": record.get("is_sample", False),
        **rendered,
    }


@router.get("/api/shared/{share_id}/stats")
@limiter.limit("30/minute")
async def get_share_stats(
    request: Request,
    share_id: str,
    _auth=Depends(verify_api_key),
    _record=Depends(require_share_access),
):
    """View count and metadata (creator only)."""
    stats = shareable_reports.get_share_stats(share_id)
    if not stats:
        raise ArchmorphException(404, "Share link not found")
    return stats


@router.delete("/api/shared/{share_id}")
@limiter.limit("10/minute")
async def revoke_share(
    request: Request,
    share_id: str,
    _auth=Depends(verify_api_key),
    _record=Depends(require_share_access),
):
    """Revoke a share link."""
    deleted = shareable_reports.delete_share(share_id)
    if not deleted:
        raise ArchmorphException(404, "Share link not found")

    # Resolve revoker identity for audit log
    revoker_id = None
    try:
        user = get_user_from_request_headers(dict(request.headers))
        if user and user.id:
            revoker_id = user.id
        else:
            revoker_id = get_api_key_service_principal(dict(request.headers))
    except Exception:
        pass

    log_audit_event(
        event_type=AuditEventType.SHARE_REVOKE,
        user_id=revoker_id,
        endpoint=f"/api/shared/{share_id}",
        method="DELETE",
        status_code=200,
        details={"share_id": share_id},
        severity=AuditSeverity.INFO,
    )

    return {"status": "revoked", "share_id": share_id}
