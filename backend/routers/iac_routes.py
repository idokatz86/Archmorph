from utils.logger_utils import sanitize_log
from error_envelope import ArchmorphException
"""
IaC (Infrastructure as Code) routes — generation, chat, async generation.

Split from diagrams.py for maintainability (#284).
"""

from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel, Field
import asyncio
import logging

from routers.shared import SESSION_STORE, limiter, verify_api_key
from job_queue import job_manager
from usage_metrics import record_event, record_funnel_step
from iac_chat import process_iac_chat, get_iac_chat_history, clear_iac_chat
from iac_generator import generate_iac_code

logger = logging.getLogger(__name__)

router = APIRouter()


class IaCChatMessage(BaseModel):
    """Request body for IaC chat messages."""
    message: str = Field(..., min_length=1, max_length=5000)
    code: str = Field(..., max_length=100000)
    format: str = Field(default="terraform", pattern="^(terraform|bicep|cloudformation)$")


# ─────────────────────────────────────────────────────────────
# IaC Generation
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/generate")
@limiter.limit("5/minute")
async def generate_iac(request: Request, diagram_id: str, format: str = "terraform", _auth=Depends(verify_api_key)):
    """Generate Infrastructure as Code from the architecture analysis."""
    if format not in ["terraform", "bicep", "cloudformation"]:
        raise ArchmorphException(400, "Format must be 'terraform', 'bicep', or 'cloudformation'")

    session = SESSION_STORE.get(diagram_id, {})
    iac_params = session.get("iac_parameters", {})

    try:
        code = await asyncio.to_thread(
            generate_iac_code,
            analysis=session if session else None,
            iac_format=format,
            params=iac_params,
        )
    except Exception as exc:
        logger.error("IaC generation failed for %s: %s", sanitize_log(diagram_id), sanitize_log(exc))  # codeql[py/log-injection] Handled by custom sanitize_log
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
    request: Request, diagram_id: str, format: str = "terraform", _auth=Depends(verify_api_key),
):
    """Start async IaC code generation. Returns 202 with job_id."""
    if format not in ["terraform", "bicep", "cloudformation"]:
        raise ArchmorphException(400, "Format must be 'terraform', 'bicep', or 'cloudformation'")

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
        logger.error("Async IaC generation failed: %s", sanitize_log(exc), exc_info=True)  # codeql[py/log-injection] Handled by custom sanitize_log
        job_manager.fail(job_id, str(exc))
