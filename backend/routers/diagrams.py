from error_envelope import ArchmorphException
"""
Core diagram routes — upload, analyze, session restore, async analysis.

Other diagram-related routes have been split into focused modules (#284):
  - routers/analysis.py     — questions, answers, add-services, export-diagram
  - routers/iac_routes.py   — IaC generation, IaC chat
  - routers/hld_routes.py   — HLD generation, export
  - routers/insights.py     — best practices, cost, risk, compliance
  - routers/sharing.py      — share links
  - routers/infra.py        — infrastructure import
  - routers/suggestions.py  — AI mapping suggestions
"""

from fastapi import APIRouter, UploadFile, File, Request, Depends
from pydantic import BaseModel
from typing import Dict, Any, Optional
import asyncio
import base64
import uuid
import logging

from routers.shared import (
    SESSION_STORE, IMAGE_STORE,
    limiter, verify_api_key, MAX_UPLOAD_SIZE,
)
from job_queue import job_manager
from usage_metrics import record_event, record_funnel_step
from image_classifier import classify_image
from vision_analyzer import analyze_image
from hld_generator import generate_hld, generate_hld_markdown  # noqa: F401 — re-exported for test monkeypatching

logger = logging.getLogger(__name__)

router = APIRouter()

UPLOAD_CHUNK_SIZE_BYTES = 1024 * 1024
VISIO_EXTENSION = ".vsdx"


# ─────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────
class RestoreSessionRequest(BaseModel):
    """Request body for restoring a cached analysis session."""
    analysis: Dict[str, Any]
    hld: Optional[Dict[str, Any]] = None
    hld_markdown: Optional[str] = None
    iac_code: Optional[str] = None
    iac_format: Optional[str] = None
    image_base64: Optional[str] = None
    image_content_type: Optional[str] = None


# ─────────────────────────────────────────────────────────────
# Diagrams — Upload
# ─────────────────────────────────────────────────────────────
@router.post("/api/projects/{project_id}/diagrams")
@limiter.limit("10/minute")
async def upload_diagram(request: Request, project_id: str, file: UploadFile = File(...), _auth=Depends(verify_api_key)):
    """Upload an architecture diagram image for analysis.

    Accepts PNG, JPEG, SVG, PDF, and Visio (.vsdx) files up to the
    configured MAX_UPLOAD_SIZE limit.
    """
    # Validate file type
    allowed_types = [
        "image/png", "image/jpeg", "image/svg+xml", "application/pdf",
        "application/vnd.ms-visio.drawing.main+xml",  # .vsdx
        "application/vnd.visio",  # legacy alias
        "application/xml", "text/xml",  # .drawio files
        "application/octet-stream",  # browsers may send .vsdx/.drawio as octet-stream
    ]
    is_visio = file.filename and file.filename.lower().endswith(VISIO_EXTENSION)
    is_drawio = file.filename and file.filename.lower().endswith(".drawio")
    if file.content_type not in allowed_types and not is_visio and not is_drawio:
        raise ArchmorphException(400, f"File type {file.content_type} not supported. Accepted: PNG, JPG, JPEG, SVG, PDF, Draw.io, Visio.")

    diagram_id = f"diag-{uuid.uuid4().hex[:8]}"
    # Read file in chunks with early size limit enforcement
    chunks = []
    total_size = 0
    while True:
        chunk = await file.read(UPLOAD_CHUNK_SIZE_BYTES)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > MAX_UPLOAD_SIZE:
            raise ArchmorphException(
                413,
                f"File too large. Maximum allowed: {MAX_UPLOAD_SIZE // (1024*1024)} MB."
            )
        chunks.append(chunk)
    image_bytes = b"".join(chunks)

    # Base64-encode for Redis/FileStore compatibility
    IMAGE_STORE[diagram_id] = (base64.b64encode(image_bytes).decode("ascii"), file.content_type)
    logger.info("Stored image for %s (%s bytes, %s)", str(diagram_id).replace('\n', '').replace('\r', ''), str(len(image_bytes)).replace('\n', '').replace('\r', ''), str(file.content_type).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom

    # Proactive capacity warning (#177)
    img_usage = len(IMAGE_STORE) / IMAGE_STORE.maxsize
    if img_usage >= 0.8:
        logger.warning(
            "IMAGE_STORE at %.0f%% capacity (%d/%d) — oldest entries will be evicted",
            str(img_usage * 100).replace('\n', '').replace('\r', ''), str(len(IMAGE_STORE)).replace('\n', '').replace('\r', ''), str(IMAGE_STORE.maxsize).replace('\n', '').replace('\r', ''),
        )

    record_event("diagrams_uploaded", {"filename": file.filename})
    record_funnel_step(diagram_id, "upload")
    return {
        "diagram_id": diagram_id,
        "filename": file.filename,
        "size": len(image_bytes),
        "status": "uploaded"
    }


# ─────────────────────────────────────────────────────────────
# Session Restore
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/restore-session")
@limiter.limit("10/minute")
async def restore_session(request: Request, diagram_id: str, body: RestoreSessionRequest):
    """Re-inject a cached analysis result into the session store.

    The frontend caches analysis data in sessionStorage.  When the backend
    restarts and the in-memory store is wiped, the frontend can push its
    cached copy here to transparently restore the session.
    """
    analysis = body.analysis
    if not analysis or not isinstance(analysis, dict):
        raise ArchmorphException(400, "Invalid analysis payload")

    analysis["diagram_id"] = diagram_id

    if body.hld:
        analysis["hld"] = body.hld
    if body.hld_markdown:
        analysis["hld_markdown"] = body.hld_markdown
    if body.iac_code:
        analysis["_cached_iac_code"] = body.iac_code
    if body.iac_format:
        analysis["_cached_iac_format"] = body.iac_format

    SESSION_STORE[diagram_id] = analysis
    restored_parts = ["analysis"]
    if body.hld:
        restored_parts.append("hld")
    if body.iac_code:
        restored_parts.append("iac")
    if body.image_base64:
        IMAGE_STORE[diagram_id] = (body.image_base64, body.image_content_type or "image/png")
        restored_parts.append("image")
    logger.info("Session restored for %s via client cache (%s)", str(diagram_id).replace('\n', '').replace('\r', ''), str(", ".join(restored_parts)).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom
    record_event("sessions_restored", {"diagram_id": diagram_id, "parts": restored_parts})
    return {"status": "restored", "diagram_id": diagram_id, "restored": restored_parts}


# ─────────────────────────────────────────────────────────────
# Diagrams — Analyze (sync)
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/analyze")
@limiter.limit("5/minute")
async def analyze_diagram(request: Request, diagram_id: str, _auth=Depends(verify_api_key)):
    """Analyze an uploaded architecture diagram using GPT-4o vision.

    Detects cloud services and maps them to Azure equivalents using the catalog.
    Includes an image classification pre-check to reject non-architecture images.
    """
    if diagram_id not in IMAGE_STORE:
        raise ArchmorphException(404, f"No uploaded image found for diagram {diagram_id}. Upload first.")

    image_b64, content_type = IMAGE_STORE[diagram_id]
    image_bytes = base64.b64decode(image_b64) if isinstance(image_b64, str) else image_b64
    logger.info("Analyzing diagram %s (%s bytes)", str(diagram_id).replace('\n', '').replace('\r', ''), str(len(image_bytes)).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom

    # No need to pre-compress, vision analyzer and classifier handle it internally
    compressed_bytes, compressed_type = image_bytes, content_type

    # Speculative parallel: classify + analyze concurrently (#299)
    async def _classify():
        try:
            return await asyncio.to_thread(classify_image, compressed_bytes, compressed_type)
        except Exception as exc:
            logger.warning("Image classification failed for %s: %s — proceeding with analysis", str(diagram_id).replace('\n', '').replace('\r', ''), str(exc).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom
            return {"is_architecture_diagram": True, "confidence": 0.5, "image_type": "unknown", "reason": "Classification unavailable"}

    async def _analyze():
        return await asyncio.to_thread(analyze_image, compressed_bytes, compressed_type)

    classification, analysis_result_or_exc = await asyncio.gather(
        _classify(),
        _analyze(),
        return_exceptions=True,
    )

    if not classification["is_architecture_diagram"]:
        logger.info("Image rejected for %s: %s (confidence: %s)", str(diagram_id).replace('\n', '').replace('\r', ''), str(classification["reason"]).replace('\n', '').replace('\r', ''), str(classification["confidence"]).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom
        record_event("images_rejected", {"diagram_id": diagram_id, "image_type": classification["image_type"], "reason": classification["reason"]})
        raise ArchmorphException(
            status_code=422,
            detail={
                "error": "not_architecture_diagram",
                "message": f"The uploaded image does not appear to be a cloud architecture diagram. Detected: {classification['image_type']}.",
                "classification": classification,
            },
        )

    logger.info("Image classified as architecture diagram for %s (confidence: %s)", str(diagram_id).replace('\n', '').replace('\r', ''), str(classification["confidence"]).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom

    if isinstance(analysis_result_or_exc, Exception):
        logger.error("Vision analysis failed for %s: %s", str(diagram_id).replace('\n', '').replace('\r', ''), str(analysis_result_or_exc).replace('\n', '').replace('\r', ''), exc_info=True)  # codeql[py/log-injection] Handled by custom
        raise ArchmorphException(500, "Vision analysis failed. Please try again with a different image.")

    result = analysis_result_or_exc
    result["diagram_id"] = diagram_id
    result["image_classification"] = classification

    if len(SESSION_STORE) >= SESSION_STORE.maxsize:
        logger.warning("Session store at capacity (%d/%d) — oldest sessions will be evicted",
                       str(len(SESSION_STORE)).replace('\n', '').replace('\r', ''), str(SESSION_STORE.maxsize).replace('\n', '').replace('\r', ''))
    SESSION_STORE[diagram_id] = result
    record_event("analyses_run", {"diagram_id": diagram_id, "services": result["services_detected"]})
    record_funnel_step(diagram_id, "analyze")
    return result


# ─────────────────────────────────────────────────────────────
# Async Analysis (Issue #172)
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/analyze-async")
@limiter.limit("5/minute")
async def analyze_diagram_async(request: Request, diagram_id: str, _auth=Depends(verify_api_key)):
    """Start an async analysis of an uploaded diagram.

    Returns ``202 Accepted`` with a ``job_id``. Use the SSE stream
    endpoint ``GET /api/jobs/{job_id}/stream`` to receive real-time
    progress events, or poll ``GET /api/jobs/{job_id}`` for status.
    """
    if diagram_id not in IMAGE_STORE:
        raise ArchmorphException(404, f"No uploaded image found for diagram {diagram_id}. Upload first.")

    job = job_manager.submit("analyze", diagram_id=diagram_id)
    asyncio.create_task(_run_analysis_job(job.job_id, diagram_id))

    from starlette.responses import JSONResponse
    return JSONResponse(
        status_code=202,
        content={
            "job_id": job.job_id,
            "diagram_id": diagram_id,
            "status": "queued",
            "stream_url": f"/api/jobs/{job.job_id}/stream",
            "status_url": f"/api/jobs/{job.job_id}",
        },
    )


async def _run_analysis_job(job_id: str, diagram_id: str) -> None:
    """Background worker for diagram analysis with real progress updates."""
    try:
        job_manager.start(job_id)

        image_b64, content_type = IMAGE_STORE[diagram_id]
        image_bytes = base64.b64decode(image_b64) if isinstance(image_b64, str) else image_b64
        job_manager.update_progress(job_id, 5, "Pre-compressing image...")

        if job_manager.is_cancelled(job_id):
            return

        # Forward raw bytes directly
        compressed_bytes, compressed_type = image_bytes, content_type

        job_manager.update_progress(job_id, 15, "Classifying image type...")

        if job_manager.is_cancelled(job_id):
            return

        # Classify
        try:
            classification = await asyncio.to_thread(classify_image, compressed_bytes, compressed_type)
        except Exception as exc:
            logger.warning("Classification failed for %s: %s", str(diagram_id).replace('\n', '').replace('\r', ''), str(exc).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom
            classification = {"is_architecture_diagram": True, "confidence": 0.5, "image_type": "unknown"}

        if not classification.get("is_architecture_diagram", True):
            job_manager.fail(
                job_id,
                f"Not an architecture diagram. Detected: {classification.get('image_type', 'unknown')}",
            )
            return

        job_manager.update_progress(job_id, 30, "Analyzing architecture with GPT-4o Vision...")

        if job_manager.is_cancelled(job_id):
            return

        job_manager.update_progress(job_id, 40, "Detecting cloud services and topology...")
        result = await asyncio.to_thread(analyze_image, compressed_bytes, compressed_type)

        if job_manager.is_cancelled(job_id):
            return

        job_manager.update_progress(job_id, 70, "Mapping services to Azure equivalents...")

        result["diagram_id"] = diagram_id
        result["image_classification"] = classification

        job_manager.update_progress(job_id, 80, "Storing analysis results...")
        SESSION_STORE[diagram_id] = result

        job_manager.update_progress(job_id, 90, "Generating guided questions...")

        record_event("analyses_run", {"diagram_id": diagram_id, "services": result.get("services_detected", 0)})
        record_funnel_step(diagram_id, "analyze")

        job_manager.update_progress(job_id, 95, "Finalizing...")
        job_manager.complete(job_id, result=result)

    except Exception as exc:
        logger.error("Async analysis failed for %s: %s", str(diagram_id).replace('\n', '').replace('\r', ''), str(exc).replace('\n', '').replace('\r', ''), exc_info=True)  # codeql[py/log-injection] Handled by custom
        job_manager.fail(job_id, str(exc))
