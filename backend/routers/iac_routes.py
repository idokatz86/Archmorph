from error_envelope import ArchmorphException
"""
IaC (Infrastructure as Code) routes — generation, chat, async generation.

Split from diagrams.py for maintainability (#284).
"""

from fastapi import APIRouter, Request, Depends
from pydantic import Field
from strict_models import StrictBaseModel
import asyncio
import logging
import re

from routers.shared import SESSION_STORE, limiter, verify_api_key
from job_queue import job_manager
from usage_metrics import record_event, record_funnel_step
from iac_chat import process_iac_chat, get_iac_chat_history, clear_iac_chat
from iac_generator import generate_iac_code
from iac_scaffold import generate_scaffold

logger = logging.getLogger(__name__)

router = APIRouter()


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
            "iac_blockers_overridden diagram=%s blocker_count=%d ids=%s",
            str(diagram_id).replace("\n", "").replace("\r", ""),
            len(blockers),
            ",".join(b.get("rule_id", "?") for b in blockers),
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


class IaCChatMessage(StrictBaseModel):
    """Request body for IaC chat messages."""
    message: str = Field(..., min_length=1, max_length=5000)
    code: str = Field(default="", max_length=100000)
    format: str = Field(default="terraform", pattern="^(terraform|bicep|cloudformation)$")


# ─────────────────────────────────────────────────────────────
# IaC Generation
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/generate")
@limiter.limit("5/minute")
async def generate_iac(request: Request, diagram_id: str, format: str = "terraform", force: bool = False, _auth=Depends(verify_api_key)):
    """Generate Infrastructure as Code from the architecture analysis.

    ``force=true`` overrides the architecture-blocker gate (Issue #610).
    """
    if format not in ["terraform", "bicep", "cloudformation"]:
        raise ArchmorphException(400, "Format must be 'terraform', 'bicep', or 'cloudformation'")

    session = SESSION_STORE.get(diagram_id, {})
    iac_params = session.get("iac_parameters", {})

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
    return {"diagram_id": diagram_id, "format": format, "code": code}


# ─────────────────────────────────────────────────────────────
# IaC Chat — GPT-4o powered Terraform/Bicep assistant
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/iac-chat")
@limiter.limit("10/minute")
async def iac_chat_endpoint(request: Request, diagram_id: str, msg: IaCChatMessage, _auth=Depends(verify_api_key)):
    """Chat with AI to modify generated Terraform/Bicep code."""
    record_event("iac_chat_messages", {"diagram_id": diagram_id})

    session = SESSION_STORE.get(diagram_id, {})
    analysis_context = session.get("analysis") if session else None

    result = await asyncio.to_thread(
        process_iac_chat,
        diagram_id=diagram_id,
        message=msg.message,
        current_code=msg.code,
        iac_format=msg.format,
        analysis_context=analysis_context,
    )

    if result.get("services_added"):
        record_event("iac_services_added", {
            "diagram_id": diagram_id,
            "services": result["services_added"],
        })

    return result


@router.get("/api/diagrams/{diagram_id}/iac-chat/history")
@limiter.limit("30/minute")
async def iac_chat_history(request: Request, diagram_id: str):
    """Get IaC chat history for a diagram."""
    return {
        "diagram_id": diagram_id,
        "messages": get_iac_chat_history(diagram_id),
    }


@router.delete("/api/diagrams/{diagram_id}/iac-chat")
@limiter.limit("10/minute")
async def iac_chat_clear(request: Request, diagram_id: str):
    """Clear IaC chat session for a diagram."""
    cleared = clear_iac_chat(diagram_id)
    return {"cleared": cleared}


# ─────────────────────────────────────────────────────────────
# Async IaC Generation (Issue #172)
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/generate-async")
@limiter.limit("5/minute")
async def generate_iac_async(
    request: Request, diagram_id: str, format: str = "terraform", force: bool = False, _auth=Depends(verify_api_key),
):
    """Start async IaC code generation. Returns 202 with job_id.

    ``force=true`` overrides the architecture-blocker gate (Issue #610).
    """
    if format not in ["terraform", "bicep", "cloudformation"]:
        raise ArchmorphException(400, "Format must be 'terraform', 'bicep', or 'cloudformation'")

    session = SESSION_STORE.get(diagram_id, {})
    _check_architecture_blockers(diagram_id, session, force)

    job = job_manager.submit("generate_iac", diagram_id=diagram_id)
    asyncio.create_task(_run_iac_job(job.job_id, diagram_id, format))

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


async def _run_iac_job(job_id: str, diagram_id: str, iac_format: str) -> None:
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

        job_manager.complete(job_id, result={"diagram_id": diagram_id, "format": iac_format, "code": code})

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


@router.post("/api/diagrams/{diagram_id}/notify-email")
@limiter.limit("3/minute")
async def notify_email(request: Request, diagram_id: str, body: NotifyEmailRequest, _auth=Depends(verify_api_key)):
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
@router.post("/api/diagrams/{diagram_id}/iac-scaffold")
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

    session = SESSION_STORE.get(diagram_id, {})
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
