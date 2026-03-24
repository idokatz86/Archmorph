"""
Analytics event ingestion endpoint (#492).

Receives frontend funnel events and stores them for analysis.
Lightweight — no external dependencies, persists to session store.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from session_store import get_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])

# Event store — Redis-backed in production, in-memory for dev
_event_store = get_store("analytics_events", maxsize=10000, ttl=86400 * 7)  # 7 days
_funnel_store = get_store("analytics_funnel", maxsize=5000, ttl=86400 * 30)  # 30 days


class AnalyticsEvent(BaseModel):
    event: str = Field(..., max_length=100)
    session_id: str = Field(..., max_length=100)
    timestamp: str = ""
    properties: Dict[str, Any] = {}


class FunnelMetrics(BaseModel):
    step: str
    count: int
    conversion_rate: float


@router.post("/events", status_code=202)
async def ingest_event(payload: AnalyticsEvent, request: Request):
    """Ingest a single analytics event (fire-and-forget)."""
    event_data = {
        "event": payload.event,
        "session_id": payload.session_id,
        "timestamp": payload.timestamp or datetime.now(timezone.utc).isoformat(),
        "properties": payload.properties,
        "ip": request.client.host if request.client else None,
    }

    # Store by session for aggregation
    key = f"events:{payload.session_id}"
    existing = _event_store.get(key)
    if existing and isinstance(existing, list):
        existing.append(event_data)
        # Cap at 200 events per session
        if len(existing) > 200:
            existing = existing[-200:]
        _event_store.set(key, existing)
    else:
        _event_store.set(key, [event_data])

    # Track funnel steps separately for fast aggregation
    if payload.event.startswith("funnel:"):
        step = payload.event.replace("funnel:", "")
        funnel_key = f"funnel:{step}"
        count = _funnel_store.get(funnel_key)
        _funnel_store.set(funnel_key, (count or 0) + 1)

    return {"status": "accepted"}


@router.get("/funnel")
async def get_funnel():
    """Get funnel conversion metrics."""
    steps = [
        "page_view", "sign_up", "first_upload", "analysis_complete",
        "questions_answered", "iac_generated", "iac_downloaded",
        "hld_exported", "cost_viewed", "upgrade_to_pro",
    ]

    results = []
    prev_count = None
    for step in steps:
        count = _funnel_store.get(f"funnel:{step}") or 0
        rate = (count / prev_count * 100) if prev_count and prev_count > 0 else 100.0 if count > 0 else 0.0
        results.append({"step": step, "count": count, "conversion_rate": round(rate, 1)})
        if count > 0:
            prev_count = count

    return {"funnel": results}


@router.get("/overview")
async def get_overview():
    """Get analytics overview metrics."""
    total_sessions = len([k for k in _event_store.keys() if k.startswith("events:")])  # type: ignore
    total_page_views = _funnel_store.get("funnel:page_view") or 0
    total_uploads = _funnel_store.get("funnel:first_upload") or 0
    total_analyses = _funnel_store.get("funnel:analysis_complete") or 0
    total_iac = _funnel_store.get("funnel:iac_generated") or 0

    return {
        "sessions": total_sessions,
        "page_views": total_page_views,
        "uploads": total_uploads,
        "analyses": total_analyses,
        "iac_generations": total_iac,
        "upload_conversion": round(total_uploads / max(total_page_views, 1) * 100, 1),
        "analysis_conversion": round(total_analyses / max(total_uploads, 1) * 100, 1),
        "iac_conversion": round(total_iac / max(total_analyses, 1) * 100, 1),
    }
