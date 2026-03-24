"""
Gallery routes — public migration gallery.

Showcases anonymized migration stories submitted by users.  Entries are
filtered by source/target cloud, support likes, and provide aggregate
statistics.  All submissions are automatically anonymized to strip
PII (IPs, account IDs, company names).
"""

import logging
import re
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from error_envelope import ArchmorphException
from routers.shared import limiter, verify_api_key
from session_store import get_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gallery", tags=["Gallery"])

# ── Store ────────────────────────────────────────────────────
_gallery_store = get_store("gallery_entries", maxsize=1000, ttl=86400 * 90)

# ── Anonymization ────────────────────────────────────────────

_IP_RE = re.compile(
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
    r"|"
    r"\b[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4}){7}\b"
)
_ACCOUNT_ID_RE = re.compile(
    r"\b\d{12}\b"                                     # AWS account IDs
    r"|"
    r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b"  # Azure subscription GUIDs
)
_COMPANY_INDICATORS_RE = re.compile(
    r"\b(?:Inc\.|Corp\.|LLC|Ltd\.|GmbH|S\.A\.|Pty|PLC)\b",
    re.IGNORECASE,
)


def _anonymize(text: str) -> str:
    """Strip IPs, cloud account IDs, and company name indicators."""
    text = _IP_RE.sub("[REDACTED_IP]", text)
    text = _ACCOUNT_ID_RE.sub("[REDACTED_ID]", text)
    text = _COMPANY_INDICATORS_RE.sub("[REDACTED]", text)
    return text


def _anonymize_dict(data: dict) -> dict:
    """Recursively anonymize string values in a dict."""
    result = {}
    for key, value in data.items():
        if isinstance(value, str):
            result[key] = _anonymize(value)
        elif isinstance(value, dict):
            result[key] = _anonymize_dict(value)
        elif isinstance(value, list):
            result[key] = [
                _anonymize(v) if isinstance(v, str) else v for v in value
            ]
        else:
            result[key] = value
    return result


# ── Models ───────────────────────────────────────────────────


class SubmitEntryRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)
    description: str = Field(..., min_length=1, max_length=4096)
    source_cloud: str = Field(..., min_length=1, max_length=64)
    target_cloud: str = Field("Azure", max_length=64)
    services_migrated: List[str] = Field(default_factory=list)
    details: dict = Field(default_factory=dict)


# ── Endpoints ────────────────────────────────────────────────


@router.post("/submit")
@limiter.limit("5/minute")
async def submit_entry(
    request: Request, body: SubmitEntryRequest, _auth=Depends(verify_api_key)
):
    """Submit an anonymized migration story to the gallery."""
    entry_id = str(uuid.uuid4())

    entry = {
        "entry_id": entry_id,
        "title": _anonymize(body.title),
        "description": _anonymize(body.description),
        "source_cloud": body.source_cloud,
        "target_cloud": body.target_cloud,
        "services_migrated": body.services_migrated,
        "details": _anonymize_dict(body.details),
        "likes": 0,
        "liked_by": [],
        "created_at": time.time(),
    }
    _gallery_store[entry_id] = entry

    logger.info("Gallery entry submitted: %s (%s → %s)", entry_id, str(body.source_cloud).replace('\n', '').replace('\r', ''), str(body.target_cloud).replace('\n', '').replace('\r', ''))
    return {"entry_id": entry_id, "status": "submitted"}


@router.get("")
@limiter.limit("30/minute")
async def list_entries(
    request: Request,
    source_cloud: Optional[str] = Query(None, max_length=64),
    target_cloud: Optional[str] = Query(None, max_length=64),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
    _auth=Depends(verify_api_key),
):
    """List gallery entries with optional cloud filters."""
    entries = list(_gallery_store.values())

    if source_cloud:
        entries = [e for e in entries if e["source_cloud"].lower() == source_cloud.lower()]
    if target_cloud:
        entries = [e for e in entries if e["target_cloud"].lower() == target_cloud.lower()]

    entries.sort(key=lambda e: e.get("created_at", 0), reverse=True)

    start = (page - 1) * limit
    page_items = entries[start : start + limit]

    # Omit liked_by from list view
    summaries = [
        {k: v for k, v in e.items() if k != "liked_by"}
        for e in page_items
    ]

    return {"entries": summaries, "total": len(entries), "page": page, "limit": limit}


@router.get("/stats")
@limiter.limit("20/minute")
async def gallery_stats(request: Request, _auth=Depends(verify_api_key)):
    """Aggregate gallery statistics."""
    entries = list(_gallery_store.values())
    source_counts: dict[str, int] = {}
    target_counts: dict[str, int] = {}
    total_likes = 0

    for e in entries:
        src = e.get("source_cloud", "unknown")
        tgt = e.get("target_cloud", "unknown")
        source_counts[src] = source_counts.get(src, 0) + 1
        target_counts[tgt] = target_counts.get(tgt, 0) + 1
        total_likes += e.get("likes", 0)

    return {
        "total_entries": len(entries),
        "total_likes": total_likes,
        "by_source_cloud": source_counts,
        "by_target_cloud": target_counts,
    }


@router.get("/{entry_id}")
@limiter.limit("30/minute")
async def get_entry(
    request: Request, entry_id: str, _auth=Depends(verify_api_key)
):
    """Get full gallery entry details."""
    entry = _gallery_store.get(entry_id)
    if not entry:
        raise ArchmorphException(404, "Gallery entry not found")
    # Return without liked_by list
    return {k: v for k, v in entry.items() if k != "liked_by"}


@router.post("/{entry_id}/like")
@limiter.limit("10/minute")
async def like_entry(
    request: Request, entry_id: str, _auth=Depends(verify_api_key)
):
    """Like a gallery entry (1 per session, keyed by client IP)."""
    entry = _gallery_store.get(entry_id)
    if not entry:
        raise ArchmorphException(404, "Gallery entry not found")

    # Use client IP hash as session key to enforce 1-like-per-session
    client_ip = request.client.host if request.client else "unknown"
    session_key = str(uuid.uuid5(uuid.NAMESPACE_URL, client_ip))

    if session_key in entry.get("liked_by", []):
        return {"entry_id": entry_id, "likes": entry["likes"], "status": "already_liked"}

    entry["likes"] = entry.get("likes", 0) + 1
    entry.setdefault("liked_by", []).append(session_key)
    _gallery_store[entry_id] = entry

    return {"entry_id": entry_id, "likes": entry["likes"], "status": "liked"}
