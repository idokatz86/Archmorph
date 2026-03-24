"""
Collaboration routes — real-time collaborative workspace sessions.

Allows multiple users to join a shared analysis session with role-based
participation (architect, devops, manager, security) and submit changes
(annotations, comments, approvals, answer updates).
"""

import logging
import secrets
import time
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from error_envelope import ArchmorphException
from log_sanitizer import safe
from routers.shared import limiter, verify_api_key
from session_store import get_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/collab", tags=["Collaboration"])

# ── Stores ───────────────────────────────────────────────────
_session_store = get_store("collab_sessions", maxsize=500, ttl=86400)
_change_store = get_store("collab_changes", maxsize=5000, ttl=86400)

# ── Models ───────────────────────────────────────────────────

Role = Literal["architect", "devops", "manager", "security"]
ChangeType = Literal["answer_update", "annotation", "comment", "approval"]


class CreateSessionRequest(BaseModel):
    analysis_id: str = Field(..., min_length=1, max_length=128)
    owner: str = Field(..., min_length=1, max_length=128)


class CreateSessionResponse(BaseModel):
    session_id: str
    share_code: str
    analysis_id: str
    owner: str


class JoinSessionRequest(BaseModel):
    share_code: str = Field(..., min_length=1, max_length=16)
    user_id: str = Field(..., min_length=1, max_length=128)
    role: Role


class SubmitChangeRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=128)
    change_type: ChangeType
    payload: dict = Field(default_factory=dict)


# ── Endpoints ────────────────────────────────────────────────


@router.post("/sessions", response_model=CreateSessionResponse)
@limiter.limit("10/minute")
async def create_session(
    request: Request, body: CreateSessionRequest, _auth=Depends(verify_api_key)
):
    """Create a collaborative session with a shareable join code."""
    session_id = str(uuid.uuid4())
    share_code = secrets.token_urlsafe(4)[:6]  # 6-char code

    session = {
        "session_id": session_id,
        "share_code": share_code,
        "analysis_id": body.analysis_id,
        "owner": body.owner,
        "participants": [{"user_id": body.owner, "role": "architect", "joined_at": time.time()}],
        "created_at": time.time(),
    }
    _session_store[session_id] = session
    _change_store[session_id] = []

    logger.info("Collab session created: %s for analysis %s", session_id, safe(body.analysis_id))
    return CreateSessionResponse(
        session_id=session_id,
        share_code=share_code,
        analysis_id=body.analysis_id,
        owner=body.owner,
    )


@router.get("/sessions/{session_id}")
@limiter.limit("30/minute")
async def get_session(
    request: Request, session_id: str, _auth=Depends(verify_api_key)
):
    """Get session info including participants."""
    session = _session_store.get(session_id)
    if not session:
        raise ArchmorphException(404, "Collaboration session not found")
    return session


@router.post("/sessions/{session_id}/join")
@limiter.limit("10/minute")
async def join_session(
    request: Request,
    session_id: str,
    body: JoinSessionRequest,
    _auth=Depends(verify_api_key),
):
    """Join a session using the share code."""
    session = _session_store.get(session_id)
    if not session:
        raise ArchmorphException(404, "Collaboration session not found")

    if not secrets.compare_digest(session["share_code"], body.share_code):
        raise ArchmorphException(403, "Invalid share code")

    # Prevent duplicate joins
    existing_ids = {p["user_id"] for p in session["participants"]}
    if body.user_id in existing_ids:
        return {"status": "already_joined", "session_id": session_id}

    session["participants"].append({
        "user_id": body.user_id,
        "role": body.role,
        "joined_at": time.time(),
    })
    _session_store[session_id] = session

    logger.info("User %s joined session %s as %s", safe(body.user_id), safe(session_id), safe(body.role))
    return {"status": "joined", "session_id": session_id, "role": body.role}


@router.post("/sessions/{session_id}/changes")
@limiter.limit("30/minute")
async def submit_change(
    request: Request,
    session_id: str,
    body: SubmitChangeRequest,
    _auth=Depends(verify_api_key),
):
    """Submit a change to the collaborative session."""
    session = _session_store.get(session_id)
    if not session:
        raise ArchmorphException(404, "Collaboration session not found")

    participant_ids = {p["user_id"] for p in session["participants"]}
    if body.user_id not in participant_ids:
        raise ArchmorphException(403, "Not a participant in this session")

    changes: list = _change_store.get(session_id, [])
    change = {
        "change_id": str(uuid.uuid4()),
        "user_id": body.user_id,
        "change_type": body.change_type,
        "payload": body.payload,
        "timestamp": time.time(),
    }
    changes.append(change)
    _change_store[session_id] = changes

    return {"status": "recorded", "change_id": change["change_id"]}


@router.get("/sessions/{session_id}/changes")
@limiter.limit("30/minute")
async def get_changes(
    request: Request, session_id: str, _auth=Depends(verify_api_key)
):
    """Get change history for a session."""
    if not _session_store.get(session_id):
        raise ArchmorphException(404, "Collaboration session not found")

    changes = _change_store.get(session_id, [])
    return {"session_id": session_id, "changes": changes, "total": len(changes)}
