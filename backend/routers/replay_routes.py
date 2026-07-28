"""Migration replay routes with PostgreSQL-canonical, version-bound state."""

from __future__ import annotations

import logging
import json
from functools import partial
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field

from database import SessionLocal
from error_envelope import ArchmorphException
from routers.shared import (
    authorize_diagram_access_async,
    get_request_durable_principal,
    limiter,
    verify_api_key,
)
from session_store import get_store
from strict_models import StrictBaseModel
from starlette.concurrency import run_in_threadpool
from workspace_store import (
    add_migration_replay_event,
    create_migration_replay,
    get_migration_replay,
    list_migration_replays,
    serialize_migration_replay,
    create_export_artifact,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/replay", tags=["Replay"])

# Disposable projection only. Authorization and recovery always use SQL.
_replay_store = get_store("replays", maxsize=200, ttl=86400 * 30)


def _principal(request: Request) -> tuple[str, str]:
    principal = get_request_durable_principal(request)
    if principal is None or not principal.get("tenant_id"):
        raise ArchmorphException(401, "Authenticated durable principal required")
    return principal["owner_user_id"], principal["tenant_id"]


def _project(replay: dict) -> None:
    if not _replay_store.set(replay["replay_id"], replay):
        logger.warning("replay_projection_write_failed")


async def _db_call(function, /, *args, **kwargs):
    def invoke():
        db = SessionLocal()
        try:
            return function(db, *args, **kwargs)
        finally:
            db.close()

    return await run_in_threadpool(partial(invoke))


def purge_diagram_replays(diagram_id: str) -> int:
    """Delete disposable replay projections linked to a diagram."""
    removed = 0
    for replay_id in list(_replay_store.keys("*")):
        replay = _replay_store.peek(replay_id) or {}
        if replay.get("analysis_id") != diagram_id:
            continue
        if not _replay_store.delete(replay_id):
            raise RuntimeError("Replay projection deletion could not be confirmed")
        removed += 1
    return removed


def diagram_replays_absent(diagram_id: str) -> bool:
    return not any(
        (_replay_store.peek(replay_id) or {}).get("analysis_id") == diagram_id
        for replay_id in _replay_store.keys("*")
    )


EventType = Literal[
    "step_entered",
    "service_detected",
    "mapping_resolved",
    "question_answered",
    "iac_generated",
]


class StartRecordingRequest(StrictBaseModel):
    analysis_id: str = Field(..., min_length=1, max_length=128)
    title: Optional[str] = Field(None, max_length=256)


class AddEventRequest(StrictBaseModel):
    replay_id: str = Field(..., min_length=1, max_length=128)
    event_type: EventType
    data: dict = Field(default_factory=dict)


async def require_replay_access(request: Request, replay_id: str) -> dict:
    owner_user_id, tenant_id = _principal(request)

    def load(db):
        replay = get_migration_replay(
            db,
            replay_id=replay_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        )
        if replay is None:
            raise ArchmorphException(404, "Replay not found")
        return serialize_migration_replay(db, replay)

    result = await _db_call(load)
    _project(result)
    return result


async def require_replay_body_access(request: Request, body: AddEventRequest) -> dict:
    return await require_replay_access(request, body.replay_id)


@router.post("/record")
@limiter.limit("10/minute")
async def start_recording(
    request: Request,
    body: StartRecordingRequest,
    _auth=Depends(verify_api_key),
):
    """Start a new replay recording linked to an immutable analysis version."""
    await authorize_diagram_access_async(request, body.analysis_id, purpose="start a replay recording")
    owner_user_id, tenant_id = _principal(request)
    try:
        def create_and_serialize(db):
            replay = create_migration_replay(
                db,
                diagram_id=body.analysis_id,
                owner_user_id=owner_user_id,
                tenant_id=tenant_id,
                title=body.title or "Migration replay",
            )
            return serialize_migration_replay(db, replay)

        replay_data = await _db_call(create_and_serialize)
        _project(replay_data)
        return {
            "replay_id": replay_data["replay_id"],
            "analysis_id": body.analysis_id,
            "version_id": replay_data["version_id"],
        }
    except ValueError as exc:
        raise ArchmorphException(409, str(exc)) from exc


@router.post("/events")
@limiter.limit("60/minute")
async def add_event(
    request: Request,
    body: AddEventRequest,
    _auth=Depends(verify_api_key),
    _replay=Depends(require_replay_body_access),
):
    """Append an event to a canonical replay recording."""
    owner_user_id, tenant_id = _principal(request)
    try:
        def add_and_serialize(db):
            event = add_migration_replay_event(
                db,
                replay_id=body.replay_id,
                owner_user_id=owner_user_id,
                tenant_id=tenant_id,
                event_type=body.event_type,
                data=body.data,
            )
            replay = get_migration_replay(
                db,
                replay_id=body.replay_id,
                owner_user_id=owner_user_id,
                tenant_id=tenant_id,
            )
            if replay is None:
                raise ValueError("Replay not found")
            return event.id, event.sequence, serialize_migration_replay(db, replay)

        event_id, sequence, replay_data = await _db_call(add_and_serialize)
        _project(replay_data)
        return {"event_id": event_id, "sequence": sequence}
    except ValueError as exc:
        raise ArchmorphException(404, "Replay not found") from exc


@router.get("/{replay_id}")
@limiter.limit("30/minute")
async def get_replay(
    request: Request,
    replay_id: str,
    _auth=Depends(verify_api_key),
    replay=Depends(require_replay_access),
):
    """Get the full canonical replay with all events."""
    return replay


@router.get("/{replay_id}/export")
@limiter.limit("10/minute")
async def export_replay(
    request: Request,
    replay_id: str,
    _auth=Depends(verify_api_key),
    replay=Depends(require_replay_access),
):
    """Export replay JSON bound to the version recorded at replay start."""
    events = replay["events"]
    timeline = {
        "format": "archmorph-replay-v1",
        "replay_id": replay["replay_id"],
        "analysis_id": replay["analysis_id"],
        "version_id": replay["version_id"],
        "title": replay["title"],
        "created_at": replay["created_at"],
        "total_events": len(events),
        "duration_seconds": (
            events[-1]["timestamp"] - events[0]["timestamp"]
            if len(events) >= 2
            else 0
        ),
        "events": events,
    }
    owner_user_id, tenant_id = _principal(request)
    artifact = await _db_call(
        create_export_artifact,
        diagram_id=replay["analysis_id"],
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        artifact_type="migration_replay_export",
        format="json",
        content=json.dumps(timeline, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        expected_version_id=replay["version_id"],
    )
    timeline["artifact_id"] = artifact.id
    timeline["version_id"] = artifact.version_id
    return timeline


@router.get("s", summary="List recent replays")
@limiter.limit("20/minute")
async def list_replays(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=20),
    _auth=Depends(verify_api_key),
):
    """List recent canonical replays with bounded pagination."""
    owner_user_id, tenant_id = _principal(request)
    result = await _db_call(
        list_migration_replays,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        limit=limit,
        offset=(page - 1) * limit,
    )
    result.update({"page": page, "limit": limit})
    for summary in result["replays"]:
        _replay_store.set(summary["replay_id"], summary)
    return result
