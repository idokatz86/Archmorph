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
from functools import partial
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Request, Security
from fastapi.security import APIKeyHeader
from pydantic import Field
from starlette.concurrency import run_in_threadpool
from strict_models import StrictBaseModel

from auth import get_user_from_request_headers
from error_envelope import ArchmorphException
from log_sanitizer import safe
from routers.shared import (
    authorize_diagram_access_async,
    get_request_durable_principal,
    limiter,
    optional_api_read_or_user_session,
    optional_api_write_or_user_session,
    require_api_write_or_user_session,
    require_authenticated_user,
)
from session_store import get_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/collab", tags=["Collaboration"])
PARTICIPANT_CAPABILITY_HEADER = APIKeyHeader(
    name="X-Participant-Capability",
    auto_error=False,
    scheme_name="ParticipantCapability",
)

# ── Stores ───────────────────────────────────────────────────
_session_store = get_store("collab_sessions", maxsize=500, ttl=86400)
_change_store = get_store("collab_changes", maxsize=5000, ttl=86400)


def purge_diagram_collaboration(diagram_id: str) -> int:
    """Delete collaboration sessions and changes linked to a diagram."""
    removed = 0
    for session_id in list(_session_store.keys("*")):
        session = _session_store.peek(session_id) or {}
        if session.get("diagram_id", session.get("analysis_id")) != diagram_id:
            continue
        if not _change_store.delete(session_id) or not _session_store.delete(
            session_id
        ):
            raise RuntimeError("Collaboration deletion could not be confirmed")
        removed += 1
    return removed


def diagram_collaboration_absent(diagram_id: str) -> bool:
    return not any(
        (_session_store.peek(session_id) or {}).get(
            "diagram_id",
            (_session_store.peek(session_id) or {}).get("analysis_id"),
        )
        == diagram_id
        for session_id in _session_store.keys("*")
    )


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


def _participant_capability_record(
    session: dict,
    participant: dict,
    *,
    intent: str,
) -> dict:
    return {
        "version": 1,
        "intent": intent,
        "session_id": session.get("session_id"),
        "analysis_id": session.get("analysis_id"),
        "project_id": session.get("project_id"),
        "owner_user_id": session.get("owner"),
        "project_owner_user_id": session.get("project_owner_user_id"),
        "tenant_id": session.get("tenant_id"),
        "participant_user_id": participant.get("user_id"),
        "role": participant.get("role"),
        "expires_at": session.get("expires_at"),
    }


def _participant_without_secret(participant: dict) -> dict:
    return {
        k: v
        for k, v in participant.items()
        if k not in {"participant_token", "participant_capability"}
    }


def _serialize_session(session: dict) -> dict:
    return {
        "session_id": session["session_id"],
        "share_code": session["share_code"],
        "analysis_id": session["analysis_id"],
        "owner": session["owner"],
        "participants": [
            _participant_without_secret(p) for p in session.get("participants", [])
        ],
        "created_at": session["created_at"],
    }


def _find_participant_by_user_id(session: dict, user_id: str) -> Optional[dict]:
    for participant in session.get("participants", []):
        if participant.get("user_id") == user_id:
            return participant
    return None


def _find_participant_by_token(
    session: dict,
    participant_token: str,
    *,
    intent: str,
) -> Optional[dict]:
    if not participant_token:
        return None
    if len(participant_token) > 256:
        return None
    for participant in session.get("participants", []):
        stored_token = participant.get("participant_token")
        binding = participant.get("participant_capability")
        if not stored_token or not secrets.compare_digest(
            stored_token, participant_token
        ):
            continue
        if not isinstance(binding, dict):
            continue
        if binding.get("revoked_at") is not None:
            continue
        try:
            if float(binding.get("expires_at", 0)) <= time.time():
                continue
        except (TypeError, ValueError):
            continue
        expected = _participant_capability_record(session, participant, intent=intent)
        if all(
            secrets.compare_digest(str(binding.get(key, "")), str(value))
            for key, value in expected.items()
        ):
            return participant
    return None


def _optional_user_from_request(request: Request):
    return get_user_from_request_headers(dict(request.headers))


def _session_access_not_found() -> ArchmorphException:
    return ArchmorphException(404, "Collaboration session not found")


def _participant_token_from_transports(
    *,
    header_token: Optional[str],
    body_token: Optional[str] = None,
) -> Optional[str]:
    if (
        header_token
        and body_token
        and not secrets.compare_digest(
            header_token,
            body_token,
        )
    ):
        raise _session_access_not_found()
    return header_token or body_token


def _reject_participant_capability_query(request: Request) -> None:
    if any(
        key in request.query_params
        for key in ("participant_token", "participant_capability")
    ):
        raise ArchmorphException(
            400, "Participant capabilities are not accepted in URLs"
        )


def _validate_session_durable_scope(session: dict) -> None:
    """Require the collaboration binding to match one active canonical graph."""
    from database import SessionLocal
    from models.workspace import Analysis, Workspace
    from project_store import PROJECT_READ_ROLES, resolve_diagram_access

    db = SessionLocal()
    try:
        row = (
            db.query(Analysis, Workspace)
            .join(
                Workspace,
                Workspace.id == Analysis.workspace_id,
            )
            .filter(
                Analysis.id == session.get("durable_analysis_id"),
                Analysis.diagram_id == session.get("analysis_id"),
                Analysis.workspace_id == session.get("project_id"),
                Analysis.owner_user_id == session.get("project_owner_user_id"),
                Analysis.tenant_id == session.get("tenant_id"),
                Workspace.id == session.get("project_id"),
                Workspace.owner_user_id == session.get("project_owner_user_id"),
                Workspace.tenant_id == session.get("tenant_id"),
                Workspace.status == "active",
            )
            .first()
        )
        if row is None:
            raise _session_access_not_found()
        resolved = resolve_diagram_access(
            db,
            session.get("analysis_id"),
            caller_user_id=session.get("owner"),
            tenant_id=session.get("tenant_id"),
            allowed_roles=PROJECT_READ_ROLES,
        )
        if (
            resolved is None
            or resolved[0].id != session.get("durable_analysis_id")
            or resolved[1].id != session.get("project_id")
        ):
            raise _session_access_not_found()
    finally:
        db.close()


def _migrate_session_principal_aliases(
    session: dict, principal: Optional[dict]
) -> bool:
    """Canonicalize only aliases proven by the currently verified B2C caller."""
    if not principal or principal.get("owner_api_key_id") is not None:
        return False
    if session.get("tenant_id") != principal.get("tenant_id"):
        return False
    legacy_ids = set(principal.get("legacy_owner_user_ids", []))
    if not legacy_ids or session.get("owner") not in legacy_ids:
        return False
    session["owner"] = principal["owner_user_id"]
    changed = True
    for participant in session.get("participants", []):
        if participant.get("user_id") in legacy_ids:
            participant["user_id"] = principal["owner_user_id"]
        participant["participant_capability"] = _participant_capability_record(
            session,
            participant,
            intent="collaboration:participant",
        )
    return changed


def _prepare_session_scope(request: Request, session: dict) -> Optional[dict]:
    principal = get_request_durable_principal(request)
    if _migrate_session_principal_aliases(session, principal):
        if not _session_store.set(session["session_id"], session):
            raise _session_access_not_found()
    _validate_session_durable_scope(session)
    return principal


def _resolve_collaboration_scope(
    diagram_id: str,
    *,
    caller_user_id: str,
    tenant_id: str,
) -> tuple[str, str, str, int]:
    from database import SessionLocal
    from project_store import PROJECT_READ_ROLES, resolve_diagram_access

    db = SessionLocal()
    try:
        resolved = resolve_diagram_access(
            db,
            diagram_id,
            caller_user_id=caller_user_id,
            tenant_id=tenant_id,
            allowed_roles=PROJECT_READ_ROLES,
        )
        if resolved is None:
            raise _session_access_not_found()
        durable_analysis, project, _role = resolved
        return (
            durable_analysis.id,
            project.id,
            project.owner_user_id,
            int(durable_analysis.current_version or 0),
        )
    finally:
        db.close()


def _resolve_session_participant(
    request: Request,
    session: dict,
    *,
    participant_token: Optional[str] = None,
    intent: str,
) -> dict:
    principal = _prepare_session_scope(request, session)
    session_tenant_id = session.get("tenant_id")
    if principal and principal.get("owner_api_key_id") is None:
        if session_tenant_id and session_tenant_id != principal.get("tenant_id"):
            raise _session_access_not_found()
        accepted_ids = {
            principal["owner_user_id"],
            *principal.get("legacy_owner_user_ids", []),
        }
        participant = next(
            (
                item
                for item in session.get("participants", [])
                if item.get("user_id") in accepted_ids
            ),
            None,
        )
        if participant:
            return participant
        raise _session_access_not_found()

    if not participant_token:
        raise _session_access_not_found()

    participant = _find_participant_by_token(
        session,
        participant_token,
        intent=intent,
    )
    if not participant:
        raise _session_access_not_found()
    return participant


async def _resolve_session_participant_async(
    request: Request,
    session: dict,
    *,
    participant_token: Optional[str],
    intent: str,
) -> dict:
    return await run_in_threadpool(
        partial(
            _resolve_session_participant,
            request,
            session,
            participant_token=participant_token,
            intent=intent,
        )
    )


# ── Endpoints ────────────────────────────────────────────────


@router.post("/sessions", response_model=CreateSessionResponse)
@limiter.limit("10/minute")
async def create_session(
    request: Request,
    body: CreateSessionRequest,
    _auth=Depends(require_api_write_or_user_session),
    user=Depends(require_authenticated_user),
):
    """Create a collaborative session with a shareable join code."""
    principal = get_request_durable_principal(request)
    if principal is None or not principal.get("tenant_id"):
        raise _session_access_not_found()
    if body.owner not in {
        principal["owner_user_id"],
        user.id,
        *principal.get("legacy_owner_user_ids", []),
    }:
        raise _session_access_not_found()
    try:
        analysis = await authorize_diagram_access_async(
            request,
            body.analysis_id,
            purpose="create a collaboration session",
        )
    except ArchmorphException as exc:
        raise _session_access_not_found() from exc

    (
        durable_analysis_id,
        project_id,
        project_owner_user_id,
        analysis_version,
    ) = await run_in_threadpool(
        partial(
            _resolve_collaboration_scope,
            body.analysis_id,
            caller_user_id=principal["owner_user_id"],
            tenant_id=principal["tenant_id"],
        )
    )

    session_id = str(uuid.uuid4())
    share_code = secrets.token_urlsafe(9)
    owner_participant = _new_participant(
        user_id=principal["owner_user_id"],
        role="architect",
        tenant_id=principal["tenant_id"],
    )

    session = {
        "session_id": session_id,
        "share_code": share_code,
        "analysis_id": body.analysis_id,
        "owner": principal["owner_user_id"],
        "tenant_id": principal["tenant_id"],
        "diagram_id": body.analysis_id,
        "durable_analysis_id": durable_analysis_id,
        "project_id": project_id,
        "project_owner_user_id": project_owner_user_id,
        "analysis_version": analysis_version
        or int(analysis.get("_analysis_version") or 0),
        "participants": [owner_participant],
        "created_at": time.time(),
        "expires_at": time.time() + 86400,
    }
    owner_participant["participant_capability"] = _participant_capability_record(
        session,
        owner_participant,
        intent="collaboration:participant",
    )
    _session_store[session_id] = session
    _change_store[session_id] = []

    logger.info(
        "Collab session created: %s for analysis %s", session_id, safe(body.analysis_id)
    )
    return CreateSessionResponse(
        session_id=session_id,
        share_code=share_code,
        analysis_id=body.analysis_id,
        owner=principal["owner_user_id"],
        participant_token=owner_participant["participant_token"],
    )


@router.get("/sessions/{session_id}")
@limiter.limit("30/minute")
async def get_session(
    request: Request,
    session_id: str,
    x_participant_capability: Optional[str] = Security(PARTICIPANT_CAPABILITY_HEADER),
    _auth=Depends(optional_api_read_or_user_session),
):
    """Get session info including participants."""
    _reject_participant_capability_query(request)
    session = _session_store.get(session_id)
    if not session:
        raise _session_access_not_found()
    await _resolve_session_participant_async(
        request,
        session,
        participant_token=x_participant_capability,
        intent="collaboration:participant",
    )
    return _serialize_session(session)


@router.post("/sessions/{session_id}/join")
@limiter.limit("10/minute")
async def join_session(
    request: Request,
    session_id: str,
    body: JoinSessionRequest,
    _auth=Depends(require_api_write_or_user_session),
    user=Depends(require_authenticated_user),
):
    """Join a session using the share code."""
    session = _session_store.get(session_id)
    if not session:
        raise _session_access_not_found()

    principal = await run_in_threadpool(
        partial(_prepare_session_scope, request, session)
    )
    if principal is None or session.get("tenant_id") != principal.get("tenant_id"):
        raise _session_access_not_found()
    accepted_ids = {
        principal["owner_user_id"],
        user.id,
        *principal.get("legacy_owner_user_ids", []),
    }
    if body.user_id not in accepted_ids:
        raise _session_access_not_found()

    if not secrets.compare_digest(session["share_code"], body.share_code):
        raise _session_access_not_found()

    # Prevent duplicate joins
    canonical_user_id = principal["owner_user_id"]
    existing_participant = next(
        (
            item
            for item in session.get("participants", [])
            if item.get("user_id") in accepted_ids
        ),
        None,
    )
    if existing_participant:
        if not existing_participant.get("participant_token"):
            logger.warning(
                "Participant missing collaboration token; regenerating token"
            )
            existing_participant["participant_token"] = secrets.token_urlsafe(24)
        existing_participant["user_id"] = canonical_user_id
        existing_participant["tenant_id"] = principal["tenant_id"]
        existing_participant["participant_capability"] = _participant_capability_record(
            session,
            existing_participant,
            intent="collaboration:participant",
        )
        if not _session_store.set(session_id, session):
            raise _session_access_not_found()
        return {
            "status": "already_joined",
            "session_id": session_id,
            "role": existing_participant["role"],
            "participant_token": existing_participant["participant_token"],
        }

    participant = _new_participant(
        user_id=canonical_user_id,
        role=body.role,
        tenant_id=principal["tenant_id"],
    )
    participant["participant_capability"] = _participant_capability_record(
        session,
        participant,
        intent="collaboration:participant",
    )
    session["participants"].append(participant)
    _session_store[session_id] = session

    logger.info("Collaboration participant joined session")
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
    x_participant_capability: Optional[str] = Security(PARTICIPANT_CAPABILITY_HEADER),
    _auth=Depends(optional_api_write_or_user_session),
):
    """Submit a change to the collaborative session."""
    _reject_participant_capability_query(request)
    session = _session_store.get(session_id)
    if not session:
        raise _session_access_not_found()

    participant = await _resolve_session_participant_async(
        request,
        session,
        participant_token=_participant_token_from_transports(
            header_token=x_participant_capability,
            body_token=body.participant_token,
        ),
        intent="collaboration:participant",
    )
    principal = get_request_durable_principal(request)
    accepted_body_ids = {
        participant["user_id"],
        *(
            [
                principal["owner_user_id"],
                *principal.get("legacy_owner_user_ids", []),
            ]
            if principal and principal.get("owner_api_key_id") is None
            else []
        ),
    }
    if body.user_id not in accepted_body_ids:
        raise _session_access_not_found()

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
    x_participant_capability: Optional[str] = Security(PARTICIPANT_CAPABILITY_HEADER),
    _auth=Depends(optional_api_read_or_user_session),
):
    """Get change history for a session."""
    _reject_participant_capability_query(request)
    session = _session_store.get(session_id)
    if not session:
        raise _session_access_not_found()
    await _resolve_session_participant_async(
        request,
        session,
        participant_token=x_participant_capability,
        intent="collaboration:participant",
    )

    changes = _change_store.get(session_id, [])
    return {"session_id": session_id, "changes": changes, "total": len(changes)}
