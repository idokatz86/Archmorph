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
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from strict_models import StrictBaseModel

from auth import get_user_from_request_headers
from error_envelope import ArchmorphException
from log_sanitizer import safe
from routers.shared import limiter, require_authenticated_user, verify_api_key
from session_store import get_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/collab", tags=["Collaboration"])

# ── Stores ───────────────────────────────────────────────────
_session_store = get_store("collab_sessions", maxsize=500, ttl=86400)
_change_store = get_store("collab_changes", maxsize=5000, ttl=86400)

# ── Models ───────────────────────────────────────────────────

Role = Literal["architect", "devops", "manager", "security"]
ChangeType = Literal["answer_update", "annotation", "comment", "approval"]


class CreateSessionRequest(StrictBaseModel):
    analysis_id: str = Field(..., min_length=1, max_length=128)
    owner: str = Field(..., min_length=1, max_length=128)


class CreateSessionResponse(StrictBaseModel):
    session_id: str
    share_code: str
    analysis_id: str
    owner: str
    participant_token: str


class JoinSessionRequest(StrictBaseModel):
    share_code: str = Field(..., min_length=1, max_length=16)
    user_id: str = Field(..., min_length=1, max_length=128)
    role: Role


class SubmitChangeRequest(StrictBaseModel):
    user_id: str = Field(..., min_length=1, max_length=128)
    change_type: ChangeType
    payload: dict = Field(default_factory=dict)
    participant_token: Optional[str] = Field(default=None, min_length=1, max_length=256)


def _new_participant(*, user_id: str, role: Role, tenant_id: str) -> dict:
    return {
        "user_id": user_id,
        "role": role,
        "tenant_id": tenant_id,
        "joined_at": time.time(),
        "participant_token": secrets.token_urlsafe(24),
    }


def _participant_without_secret(participant: dict) -> dict:
    return {k: v for k, v in participant.items() if k != "participant_token"}


def _serialize_session(session: dict) -> dict:
    return {
        "session_id": session["session_id"],
        "share_code": session["share_code"],
        "analysis_id": session["analysis_id"],
        "owner": session["owner"],
        "participants": [_participant_without_secret(p) for p in session.get("participants", [])],
        "created_at": session["created_at"],
    }


def _find_participant_by_user_id(session: dict, user_id: str) -> Optional[dict]:
    for participant in session.get("participants", []):
        if participant.get("user_id") == user_id:
            return participant
    return None


def _find_participant_by_token(session: dict, participant_token: str) -> Optional[dict]:
    if not participant_token:
        return None
    if len(participant_token) > 256:
        return None
    for participant in session.get("participants", []):
        stored_token = participant.get("participant_token")
        if stored_token and secrets.compare_digest(stored_token, participant_token):
            return participant
    return None


def _optional_user_from_request(request: Request):
    return get_user_from_request_headers(dict(request.headers))


def _session_access_not_found() -> ArchmorphException:
    return ArchmorphException(404, "Collaboration session not found")


def _resolve_session_participant(
    request: Request,
    session: dict,
    *,
    participant_token: Optional[str] = None,
) -> dict:
    user = _optional_user_from_request(request)
    session_tenant_id = session.get("tenant_id")
    if user:
        if session_tenant_id and session_tenant_id != user.tenant_id:
            raise _session_access_not_found()
        participant = _find_participant_by_user_id(session, user.id)
        if participant:
            return participant
        raise ArchmorphException(403, "Not a participant in this session")

    if not participant_token:
        raise ArchmorphException(401, "Authentication required")

    participant = _find_participant_by_token(session, participant_token)
    if not participant:
        raise _session_access_not_found()
    return participant


# ── Endpoints ────────────────────────────────────────────────


@router.post("/sessions", response_model=CreateSessionResponse)
@limiter.limit("10/minute")
async def create_session(
    request: Request,
    body: CreateSessionRequest,
    _auth=Depends(verify_api_key),
    user=Depends(require_authenticated_user),
):
    """Create a collaborative session with a shareable join code."""
    if body.owner != user.id:
        raise ArchmorphException(403, "Forbidden: owner mismatch")

    session_id = str(uuid.uuid4())
    share_code = secrets.token_urlsafe(9)
    owner_participant = _new_participant(user_id=user.id, role="architect", tenant_id=user.tenant_id)

    session = {
        "session_id": session_id,
        "share_code": share_code,
        "analysis_id": body.analysis_id,
        "owner": user.id,
        "tenant_id": user.tenant_id,
        "participants": [owner_participant],
        "created_at": time.time(),
    }
    _session_store[session_id] = session
    _change_store[session_id] = []

    logger.info("Collab session created: %s for analysis %s", session_id, safe(body.analysis_id))
    return CreateSessionResponse(
        session_id=session_id,
        share_code=share_code,
        analysis_id=body.analysis_id,
        owner=user.id,
        participant_token=owner_participant["participant_token"],
    )


@router.get("/sessions/{session_id}")
@limiter.limit("30/minute")
async def get_session(
    request: Request,
    session_id: str,
    participant_token: Optional[str] = None,
    _auth=Depends(verify_api_key),
):
    """Get session info including participants."""
    session = _session_store.get(session_id)
    if not session:
        raise _session_access_not_found()
    _resolve_session_participant(request, session, participant_token=participant_token)
    return _serialize_session(session)


@router.post("/sessions/{session_id}/join")
@limiter.limit("10/minute")
async def join_session(
    request: Request,
    session_id: str,
    body: JoinSessionRequest,
    _auth=Depends(verify_api_key),
    user=Depends(require_authenticated_user),
):
    """Join a session using the share code."""
    session = _session_store.get(session_id)
    if not session:
        raise _session_access_not_found()

    if session.get("tenant_id") and session["tenant_id"] != user.tenant_id:
        raise _session_access_not_found()
    if body.user_id != user.id:
        raise ArchmorphException(403, "Forbidden: participant mismatch")

    if not secrets.compare_digest(session["share_code"], body.share_code):
        raise ArchmorphException(403, "Invalid share code")

    # Prevent duplicate joins
    existing_participant = _find_participant_by_user_id(session, user.id)
    if existing_participant:
        if not existing_participant.get("participant_token"):
            logger.warning("Participant %s missing collaboration token in session %s", safe(user.id), safe(session_id))
            existing_participant["participant_token"] = secrets.token_urlsafe(24)
            _session_store[session_id] = session
        return {
            "status": "already_joined",
            "session_id": session_id,
            "role": existing_participant["role"],
            "participant_token": existing_participant["participant_token"],
        }

    participant = _new_participant(user_id=user.id, role=body.role, tenant_id=user.tenant_id)
    session["participants"].append(participant)
    _session_store[session_id] = session

    logger.info("User %s joined session %s as %s", safe(user.id), safe(session_id), safe(body.role))
    return {
        "status": "joined",
        "session_id": session_id,
        "role": body.role,
        "participant_token": participant["participant_token"],
    }


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
        raise _session_access_not_found()

    participant = _resolve_session_participant(
        request,
        session,
        participant_token=body.participant_token,
    )
    if body.user_id != participant["user_id"]:
        raise ArchmorphException(403, "Forbidden: participant mismatch")

    changes: list = _change_store.get(session_id, [])
    change = {
        "change_id": str(uuid.uuid4()),
        "user_id": participant["user_id"],
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
    request: Request,
    session_id: str,
    participant_token: Optional[str] = None,
    _auth=Depends(verify_api_key),
):
    """Get change history for a session."""
    session = _session_store.get(session_id)
    if not session:
        raise _session_access_not_found()
    _resolve_session_participant(request, session, participant_token=participant_token)

    changes = _change_store.get(session_id, [])
    return {"session_id": session_id, "changes": changes, "total": len(changes)}
