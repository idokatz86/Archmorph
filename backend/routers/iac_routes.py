from error_envelope import ArchmorphException
"""
IaC (Infrastructure as Code) routes — generation, chat, async generation.

Split from diagrams.py for maintainability (#284).
"""

from fastapi import APIRouter, Request, Depends
from pydantic import Field
from starlette.responses import JSONResponse
from strict_models import StrictBaseModel
import asyncio
import hashlib
import logging
import re
import secrets
from typing import Literal, Optional

from routers.shared import (
    SESSION_STORE,
    authorize_diagram_access,
    get_api_key_service_principal,
    limiter,
    require_diagram_access,
    verify_api_key,
)
from job_queue import job_manager
from usage_metrics import record_event, record_funnel_step
from iac_chat import process_iac_chat, get_iac_chat_history, clear_iac_chat
from iac_generator import generate_iac_code
from iac_scaffold import generate_scaffold

logger = logging.getLogger(__name__)

router = APIRouter()


# ─────────────────────────────────────────────────────────────
# IaC version (ETag) helpers — optimistic concurrency (#858 / F-BUG-8)
# ─────────────────────────────────────────────────────────────
_IAC_ETAG_KEY = "_iac_etag"


def _compute_iac_etag(code: str) -> str:
    """Return a short, deterministic ETag for the given IaC code string."""
    return hashlib.sha256(code.encode()).hexdigest()[:16]


def _get_stored_etag(session: dict) -> str | None:
    """Return the stored IaC ETag (None if no code has been generated yet)."""
    return session.get(_IAC_ETAG_KEY)


def _store_iac_etag(diagram_id: str, session: dict, code: str) -> str:
    """Compute and persist the new ETag; return it."""
    etag = _compute_iac_etag(code)
    session[_IAC_ETAG_KEY] = etag
    SESSION_STORE[diagram_id] = session
    return etag


# ─────────────────────────────────────────────────────────────
# Architecture-blocker gate (Issue #610)
# ─────────────────────────────────────────────────────────────
def _check_architecture_blockers(diagram_id: str, session: dict, force: bool) -> None:
    """Refuse IaC generation when unresolved architecture blockers exist.

    Reads ``session["architecture_issues"]`` (set by the analysis enrichment
    pipeline). If any issue has severity=blocker:

    - ``force=False`` → raise 409 with the blocker list and an override hint.
    - ``force=True`` → log a warning and proceed (admin/expert override).
    - No issues / no blockers → return silently.

    Failures while inspecting the session are swallowed so the gate can never
    break IaC generation for sessions that pre-date the engine.
    """
    try:
        issues = session.get("architecture_issues") or []
    except Exception:
        return

    blockers = [i for i in issues if isinstance(i, dict) and i.get("severity") == "blocker"]
    if not blockers:
        return

    if force:
        logger.warning(
            "iac_blockers_overridden blocker_count=%d",
            len(blockers),
        )
        record_event(
            "iac_blockers_overridden",
            {
                "diagram_id": diagram_id,
                "blocker_count": len(blockers),
                "rule_ids": [b.get("rule_id") for b in blockers],
            },
        )
        return

    raise ArchmorphException(
        409,
        detail={
            "error": "architecture_blocker_unresolved",
            "message": (
                "IaC generation is blocked because the architecture has "
                f"{len(blockers)} unresolved blocker issue(s). "
                "Resolve the issues, or pass ?force=true to override."
            ),
            "blockers": [
                {
                    "rule_id": b.get("rule_id"),
                    "title": b.get("title"),
                    "message": b.get("message"),
                    "remediation": b.get("remediation"),
                    "docs_url": b.get("docs_url"),
                    "affected_services": b.get("affected_services", []),
                }
                for b in blockers
            ],
            "override_hint": "Append ?force=true to the request URL to generate anyway.",
        },
    )


def _iac_code_hash(code: str) -> str:
    """Return a SHA-256 hex digest of the IaC code string (used for tamper detection)."""
    return hashlib.sha256(code.encode()).hexdigest()


class IaCChatMessage(StrictBaseModel):
    """Request body for IaC chat messages.

    ``code_hash`` is the SHA-256 hex digest (lowercase) of the client's local copy
    of the IaC code. When supplied, it must match the server-side hash. A mismatch
    returns HTTP 409 so the client knows to re-fetch the authoritative code before
    retrying (#842). Missing hashes remain accepted for older clients; the server
    still ignores client-supplied code whenever canonical state exists.
    """
    message: str = Field(..., min_length=1, max_length=5000)
    code: str = Field(default="", max_length=100000)
    format: Literal["terraform", "bicep"] = "terraform"
    code_hash: Optional[str] = Field(
        None,
        min_length=64,
        max_length=64,
        description="Optional SHA-256 hex digest of the client's current IaC code for stale-copy detection",
    )


# ─────────────────────────────────────────────────────────────
# IaC Generation
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/generate", dependencies=[Depends(require_diagram_access)])
@limiter.limit("5/minute")
async def generate_iac(
    request: Request,
    diagram_id: str,
    format: Literal["terraform", "bicep"] = "terraform",
    force: bool = False,
    _auth=Depends(verify_api_key),
):
    """Generate Infrastructure as Code from the architecture analysis.

    ``force=true`` overrides the architecture-blocker gate (Issue #610).

    Optimistic concurrency (#858 / F-BUG-8): if an ``If-Match`` request header
    is supplied and a previous generation exists for this diagram, the stored
    ETag must match.  A mismatch returns HTTP 409 so that concurrent clients
    can detect and resolve conflicts instead of silently overwriting each other.
    """
    session = authorize_diagram_access(request, diagram_id, purpose="generate IaC")
    iac_params = session.get("iac_parameters", {})

    # Optimistic concurrency guard: honour If-Match when code was previously
    # generated for this diagram.  Only enforced when the caller supplies the
    # header — omitting it freely regenerates (first-time or intentional).
    if_match = request.headers.get("If-Match")
    stored_etag = _get_stored_etag(session)
    if if_match is not None and stored_etag is not None and if_match != stored_etag:
        raise ArchmorphException(
            409,
            detail={
                "error": "iac_version_conflict",
                "message": (
                    "The IaC code has been updated since you last fetched it. "
                    "Re-fetch the current version and retry."
                ),
                "current_etag": stored_etag,
            },
        )

    _check_architecture_blockers(diagram_id, session, force)

    try:
        code = await asyncio.to_thread(
            generate_iac_code,
            analysis=session if session else None,
            iac_format=format,
            params=iac_params,
        )
    except Exception as exc:
        logger.error("IaC generation failed for %s: %s", str(diagram_id).replace('\n', '').replace('\r', ''), str(exc).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom
        raise ArchmorphException(500, "IaC generation failed. Please try again.")

    record_event(f"iac_generated_{format}", {"diagram_id": diagram_id})
    record_funnel_step(diagram_id, "iac_generate")

    # Persist the canonical IaC code server-side so chat turns can validate
    # the client is working against the same version (#842), and update the
    # short ETag used by If-Match optimistic concurrency checks (#858).
    session["iac_code"] = code
    session["iac_code_hash"] = _iac_code_hash(code)
    session["iac_format"] = format
    new_etag = _store_iac_etag(diagram_id, session, code)
    return JSONResponse(
        content={
            "diagram_id": diagram_id,
            "format": format,
            "code": code,
            "code_hash": session["iac_code_hash"],
            "etag": new_etag,
        },
        headers={"ETag": new_etag},
    )


# ─────────────────────────────────────────────────────────────
# IaC Chat — GPT-4o powered Terraform/Bicep assistant
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/iac-chat", dependencies=[Depends(require_diagram_access)])
@limiter.limit("10/minute")
async def iac_chat_endpoint(request: Request, diagram_id: str, msg: IaCChatMessage, _auth=Depends(verify_api_key)):
    """Chat with AI to modify generated Terraform/Bicep code.

    The server always uses its own canonical IaC code (stored after ``/generate``)
    rather than the client-supplied ``code`` field to prevent state overwrite from
    tampered request bodies (#842). When the client supplies ``code_hash`` it must
    match the server's SHA-256 digest; a mismatch returns 409 so the client knows
    to refresh.
    """
    record_event("iac_chat_messages", {"diagram_id": diagram_id})

    session = authorize_diagram_access(request, diagram_id, purpose="chat about IaC")
    analysis_context = session.get("analysis") if session else None

    # ── Server-side canonical code validation (#842) ──────────────────────
    server_code = session.get("iac_code") if session else None
    if server_code is not None:
        server_hash = session.get("iac_code_hash") or _iac_code_hash(server_code)
        if msg.code_hash is not None:
            # Constant-time comparison prevents timing-based oracle attacks
            if not secrets.compare_digest(msg.code_hash.lower(), server_hash):
                raise ArchmorphException(
                    409,
                    "IaC code version mismatch — your local copy is stale. "
                    "Re-fetch the current IaC code before continuing.",
                )
        # Always use server-side code; ignore client-supplied code
        code_to_use = server_code
    else:
        # No server-side canonical state yet (pre-generate flow) — use client code
        code_to_use = msg.code

    result = await asyncio.to_thread(
        process_iac_chat,
        diagram_id=diagram_id,
        message=msg.message,
        current_code=code_to_use,
        iac_format=msg.format,
        analysis_context=analysis_context,
    )

    # ── Persist updated code as new canonical state (#842) ───────────────
    if not result.get("error"):
        new_code = result.get("code")
        if new_code:
            session = SESSION_STORE.get(diagram_id) or session
            session["iac_code"] = new_code
            session["iac_code_hash"] = _iac_code_hash(new_code)
            new_etag = _store_iac_etag(diagram_id, session, new_code)
            # Surface the new hash so clients can synchronise without re-fetching
            result["code_hash"] = session["iac_code_hash"]
            result["etag"] = new_etag

    if result.get("services_added"):
        record_event("iac_services_added", {
            "diagram_id": diagram_id,
            "services": result["services_added"],
        })

    return result


@router.get("/api/diagrams/{diagram_id}/iac-chat/history", dependencies=[Depends(require_diagram_access)])
@limiter.limit("30/minute")
async def iac_chat_history(
    request: Request,
    diagram_id: str,
    _auth=Depends(verify_api_key),
    _session=Depends(require_diagram_access),
):
    """Get IaC chat history for a diagram."""
    return {
        "diagram_id": diagram_id,
        "messages": get_iac_chat_history(diagram_id),
    }


@router.delete("/api/diagrams/{diagram_id}/iac-chat", dependencies=[Depends(require_diagram_access)])
@limiter.limit("10/minute")
async def iac_chat_clear(
    request: Request,
    diagram_id: str,
    _auth=Depends(verify_api_key),
    _session=Depends(require_diagram_access),
):
    """Clear IaC chat session for a diagram."""
    cleared = clear_iac_chat(diagram_id)
    return {"cleared": cleared}


# ─────────────────────────────────────────────────────────────
# Async IaC Generation (Issue #172)
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/generate-async", dependencies=[Depends(require_diagram_access)])
@limiter.limit("5/minute")
async def generate_iac_async(
    request: Request,
    diagram_id: str,
    format: Literal["terraform", "bicep"] = "terraform",
    force: bool = False,
    _auth=Depends(verify_api_key),
):
    """Start async IaC code generation. Returns 202 with job_id.

    ``force=true`` overrides the architecture-blocker gate (Issue #610).
    """
    from auth import get_user_from_request_headers

    headers = dict(request.headers)
    user = get_user_from_request_headers(headers)
    api_key_principal_id = get_api_key_service_principal(headers)
    session = authorize_diagram_access(request, diagram_id, purpose="queue IaC generation")
    _check_architecture_blockers(diagram_id, session, force)
    queued_etag = _get_stored_etag(session)
    queued_code_hash = session.get("iac_code_hash")

    job = job_manager.submit(
        "generate_iac",
        diagram_id=diagram_id,
        owner_user_id=user.id if user else None,
        tenant_id=user.tenant_id if user else None,
        owner_api_key_id=api_key_principal_id if not user else None,
    )
    asyncio.create_task(_run_iac_job(job.job_id, diagram_id, format, queued_etag, queued_code_hash))

    from starlette.responses import JSONResponse
    return JSONResponse(
        status_code=202,
        content={
            "job_id": job.job_id,
            "diagram_id": diagram_id,
            "format": format,
            "status": "queued",
            "stream_url": f"/api/jobs/{job.job_id}/stream",
        },
    )


async def _run_iac_job(
    job_id: str,
    diagram_id: str,
    iac_format: str,
    queued_etag: Optional[str] = None,
    queued_code_hash: Optional[str] = None,
) -> None:
    """Background worker for IaC generation."""
    try:
        job_manager.start(job_id)
        job_manager.update_progress(job_id, 10, f"Generating {iac_format.title()} code...")

        session = SESSION_STORE.get(diagram_id, {})
        iac_params = session.get("iac_parameters", {})

        if job_manager.is_cancelled(job_id):
            return

        job_manager.update_progress(job_id, 30, "Calling GPT-4o for code generation...")

        code = await asyncio.to_thread(
            generate_iac_code,
            analysis=session if session else None,
            iac_format=iac_format,
            params=iac_params,
        )

        if job_manager.is_cancelled(job_id):
            return

        job_manager.update_progress(job_id, 90, "Finalizing code...")

        record_event(f"iac_generated_{iac_format}", {"diagram_id": diagram_id})
        record_funnel_step(diagram_id, "iac_generate")

        # Keep async generation canonical state aligned with sync /generate,
        # unless the canonical code changed while this job was running.
        latest_session = SESSION_STORE.get(diagram_id)
        if latest_session is None:
            latest_session = session
        session = latest_session
        current_etag = _get_stored_etag(session)
        current_code_hash = session.get("iac_code_hash")
        code_hash = _iac_code_hash(code)
        new_etag = _compute_iac_etag(code)
        canonical_state_changed = current_etag != queued_etag or current_code_hash != queued_code_hash
        if not canonical_state_changed:
            session["iac_code"] = code
            session["iac_code_hash"] = code_hash
            session["iac_format"] = iac_format
            new_etag = _store_iac_etag(diagram_id, session, code)

        job_manager.complete(
            job_id,
            result={
                "diagram_id": diagram_id,
                "format": iac_format,
                "code": code,
                "code_hash": code_hash,
                "etag": new_etag,
                "canonical_state_persisted": not canonical_state_changed,
                "canonical_state_conflict": canonical_state_changed,
                "current_etag": current_etag if canonical_state_changed else new_etag,
            },
        )

    except Exception as exc:
        logger.error("Async IaC generation failed: %s", str(exc).replace('\n', '').replace('\r', ''), exc_info=True)  # codeql[py/log-injection] Handled by custom
        job_manager.fail(job_id, str(exc))


# ─────────────────────────────────────────────────────────────
# Email Notification — send session link when generation completes
# ─────────────────────────────────────────────────────────────
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


class NotifyEmailRequest(StrictBaseModel):
    """Request body for email notification."""
    email: str = Field(..., min_length=5, max_length=254)
    diagram_name: str = Field(default="", max_length=200)


@router.post("/api/diagrams/{diagram_id}/notify-email", dependencies=[Depends(require_diagram_access)])
@limiter.limit("3/minute")
async def notify_email(
    request: Request,
    diagram_id: str,
    body: NotifyEmailRequest,
    _auth=Depends(verify_api_key),
    _session=Depends(require_diagram_access),
):
    """Send a session-ready notification email to the user."""
    if not _EMAIL_RE.match(body.email):
        raise ArchmorphException(400, "Invalid email address format.")

    from services.email_service import send_session_ready_email, is_email_configured

    if not is_email_configured():
        raise ArchmorphException(503, "Email service is not configured.")

    success = await asyncio.to_thread(
        send_session_ready_email,
        recipient_email=body.email,
        diagram_id=diagram_id,
        diagram_name=body.diagram_name or None,
    )

    if not success:
        raise ArchmorphException(502, "Failed to send email. Please try again.")

    record_event("email_notification_sent", {"diagram_id": diagram_id})
    return {"sent": True, "email": body.email}


# ─────────────────────────────────────────────────────────────
# IaC Scaffold — Full Terraform project structure
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/iac-scaffold", dependencies=[Depends(require_diagram_access)])
@limiter.limit("5/minute")
async def generate_iac_scaffold(
    request: Request,
    diagram_id: str,
    format: str = "terraform",
    _auth=Depends(verify_api_key),
):
    """Generate a production-grade IaC project scaffold.

    Returns a JSON object with ``files`` mapping relative paths to content.
    Currently supports ``format=terraform`` only.
    """
    if format != "terraform":
        raise ArchmorphException(400, "Scaffold generation currently supports 'terraform' only")

    session = authorize_diagram_access(request, diagram_id, purpose="generate IaC scaffold")
    iac_params = session.get("iac_parameters", {})

    try:
        files = await asyncio.to_thread(
            generate_scaffold,
            analysis=session if session else None,
            params=iac_params,
        )
    except Exception as exc:
        logger.error(
            "IaC scaffold generation failed for %s: %s",
            str(diagram_id).replace('\n', '').replace('\r', ''),
            str(exc).replace('\n', '').replace('\r', ''),
        )
        raise ArchmorphException(500, "IaC scaffold generation failed. Please try again.")

    record_event("iac_scaffold_generated", {"diagram_id": diagram_id, "file_count": len(files)})
    record_funnel_step(diagram_id, "iac_scaffold")

    return {
        "diagram_id": diagram_id,
        "format": format,
        "file_count": len(files),
        "files": files,
    }
