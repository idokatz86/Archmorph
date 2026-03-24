"""
Replay routes — migration replay timeline.

Records step-by-step events during a migration analysis so users can
replay the entire flow (service detection, question answering, IaC generation)
as an interactive timeline.
"""

import logging
import time
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from error_envelope import ArchmorphException
from routers.shared import limiter, verify_api_key
from session_store import get_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/replay", tags=["Replay"])

# ── Store ────────────────────────────────────────────────────
_replay_store = get_store("replays", maxsize=200, ttl=86400 * 30)

# ── Models ───────────────────────────────────────────────────

EventType = Literal[
    "step_entered",
    "service_detected",
    "mapping_resolved",
    "question_answered",
    "iac_generated",
]


class StartRecordingRequest(BaseModel):
    analysis_id: str = Field(..., min_length=1, max_length=128)
    title: Optional[str] = Field(None, max_length=256)


class AddEventRequest(BaseModel):
    replay_id: str = Field(..., min_length=1, max_length=128)
    event_type: EventType
    data: dict = Field(default_factory=dict)


# ── Endpoints ────────────────────────────────────────────────


@router.post("/record")
@limiter.limit("10/minute")
async def start_recording(
    request: Request, body: StartRecordingRequest, _auth=Depends(verify_api_key)
):
    """Start a new replay recording linked to an analysis."""
    replay_id = str(uuid.uuid4())

    replay = {
        "replay_id": replay_id,
        "analysis_id": body.analysis_id,
        "title": body.title or f"Replay {replay_id[:8]}",
        "events": [],
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    _replay_store[replay_id] = replay

    logger.info("Replay recording started: %s for analysis %s", replay_id, body.analysis_id)
    return {"replay_id": replay_id, "analysis_id": body.analysis_id}


@router.post("/events")
@limiter.limit("60/minute")
async def add_event(
    request: Request, body: AddEventRequest, _auth=Depends(verify_api_key)
):
    """Add an event to an existing replay recording."""
    replay = _replay_store.get(body.replay_id)
    if not replay:
        raise ArchmorphException(404, "Replay not found")

    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": body.event_type,
        "data": body.data,
        "timestamp": time.time(),
        "sequence": len(replay["events"]),
    }
    replay["events"].append(event)
    replay["updated_at"] = time.time()
    _replay_store[body.replay_id] = replay

    return {"event_id": event["event_id"], "sequence": event["sequence"]}


@router.get("/{replay_id}")
@limiter.limit("30/minute")
async def get_replay(
    request: Request, replay_id: str, _auth=Depends(verify_api_key)
):
    """Get full replay with all events."""
    replay = _replay_store.get(replay_id)
    if not replay:
        raise ArchmorphException(404, "Replay not found")
    return replay


@router.get("/{replay_id}/export")
@limiter.limit("10/minute")
async def export_replay(
    request: Request, replay_id: str, _auth=Depends(verify_api_key)
):
    """Export replay as a JSON timeline."""
    replay = _replay_store.get(replay_id)
    if not replay:
        raise ArchmorphException(404, "Replay not found")

    timeline = {
        "format": "archmorph-replay-v1",
        "replay_id": replay["replay_id"],
        "analysis_id": replay["analysis_id"],
        "title": replay["title"],
        "created_at": replay["created_at"],
        "total_events": len(replay["events"]),
        "duration_seconds": (
            replay["events"][-1]["timestamp"] - replay["events"][0]["timestamp"]
            if len(replay["events"]) >= 2
            else 0
        ),
        "events": replay["events"],
    }
    return timeline


@router.get("s", summary="List recent replays")
@limiter.limit("20/minute")
async def list_replays(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=20),
    _auth=Depends(verify_api_key),
):
    """List recent replays with pagination (max 20 per page)."""
    all_replays = sorted(
        _replay_store.values(),
        key=lambda r: r.get("created_at", 0),
        reverse=True,
    )
    start = (page - 1) * limit
    page_items = all_replays[start : start + limit]

    # Return summaries without full event lists
    summaries = [
        {
            "replay_id": r["replay_id"],
            "analysis_id": r["analysis_id"],
            "title": r["title"],
            "event_count": len(r.get("events", [])),
            "created_at": r["created_at"],
        }
        for r in page_items
    ]

    return {
        "replays": summaries,
        "total": len(all_replays),
        "page": page,
        "limit": limit,
    }
