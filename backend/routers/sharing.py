from error_envelope import ArchmorphException
"""
Sharing routes — create and retrieve share links.

Split from diagrams.py for maintainability (#284).
"""

from fastapi import APIRouter, Request
from datetime import datetime, timezone
import secrets
import logging

from routers.shared import SHARE_STORE, limiter
from routers.samples import get_or_recreate_session

logger = logging.getLogger(__name__)

router = APIRouter()


# ─────────────────────────────────────────────────────────────
# Share Links
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/share")
@limiter.limit("10/minute")
async def create_share_link(request: Request, diagram_id: str):
    """Create a shareable read-only link for analysis results."""
    analysis = get_or_recreate_session(diagram_id)
    if not analysis:
        raise ArchmorphException(404, "Analysis not found")

    share_id = f"share-{secrets.token_urlsafe(24)}"

    # Store a read-only snapshot
    SHARE_STORE[share_id] = {
        "analysis": analysis,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_in": "24 hours"
    }

    return {
        "share_id": share_id,
        "share_url": f"/shared/{share_id}",
        "expires_in": "24 hours"
    }


@router.get("/api/shared/{share_id}")
@limiter.limit("30/minute")
async def get_shared_analysis(request: Request, share_id: str):
    """Get shared analysis by share ID (public, read-only)."""
    shared = SHARE_STORE.get(share_id)
    if not shared:
        raise ArchmorphException(404, "Share link expired or invalid")

    return {
        "analysis": shared["analysis"],
        "shared_at": shared["created_at"],
        "read_only": True
    }
