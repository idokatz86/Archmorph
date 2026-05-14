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
from strict_models import StrictBaseModel
from typing import Dict, Any, Optional
import asyncio
import base64
import logging

from routers.shared import (
    SESSION_STORE, IMAGE_STORE, SHARE_STORE, EXPORT_CAPABILITY_STORE,
    limiter, verify_api_key, MAX_UPLOAD_SIZE, generate_session_id,
    require_authenticated_user, get_api_key_service_principal,
    require_diagram_access,
)
import ci_smoke
from job_queue import job_manager
from usage_metrics import record_event, record_funnel_step
from export_capabilities import attach_export_capability
from image_classifier import classify_image
from vision_analyzer import analyze_image
from openai_client import OpenAIServiceError, handle_openai_error
from hld_generator import generate_hld, generate_hld_markdown  # noqa: F401 — re-exported for test monkeypatching
from auth import get_user_from_request_headers
from analysis_history import maybe_save_from_session
from error_envelope import ArchmorphException
from upload_validator import validate_upload, UploadValidationError
from sku_translator import get_sku_translator
from confidence_provenance import build_provenance
from architecture_rules import evaluate as evaluate_architecture_rules
from architecture_review import build_audit_pipeline_issue, classify_regulated_workload
from source_provider import normalize_source_provider
from project_store import (
    mark_diagram_analyzed,
    register_diagram,
    remove_diagram,
    get_project_id_for_diagram,
)
import shareable_reports
from analysis_payload_bounds import (
    AnalysisPayloadTooLarge,
    validate_analysis_payload_bounds,
)

logger = logging.getLogger(__name__)

router = APIRouter()

UPLOAD_CHUNK_SIZE_BYTES = 1024 * 1024
VISIO_EXTENSION = ".vsdx"


def _enrich_with_sku(result: dict) -> dict:
    """Enrich analysis mappings with SKU-level instance type translations.

    For each mapping whose source category is Compute, Database, or Storage,
    attempt to detect instance types from the service names/roles and attach
    SKU translation details with parity scores.
    """
    engine = get_sku_translator()
    provider = normalize_source_provider(result.get("source_provider"))

    for m in result.get("mappings", []):
        source_name = m.get("source_service", "")
        if isinstance(source_name, dict):
            source_name = source_name.get("name", "")
        role = m.get("role", m.get("description", ""))
        search_text = f"{source_name} {role}"

        category = m.get("category", "").lower()
        if category in ("compute", ""):
            translation = engine.best_fit(search_text, provider)
            if translation is not None:
                m["sku_translation"] = {
                    "source_sku": translation.source.sku,
                    "azure_sku": translation.target.sku,
                    "parity_score": translation.parity.overall,
                    "parity_details": translation.parity.details,
                    "vcpus": translation.target.vcpus,
                    "ram_gb": translation.target.ram_gb,
                }

    return result


def _enrich_with_provenance(result: dict) -> dict:
    """Attach structured confidence provenance to each mapping."""
    for m in result.get("mappings", []):
        try:
            m["confidence_provenance"] = build_provenance(m)
        except Exception:
            logger.debug("Provenance enrichment skipped for mapping: %s", m.get("source_service"))
    return result


def _enrich_with_architecture_issues(result: dict) -> dict:
    """Run the architecture-limitations engine against the analysis (Issue #610).

    Adds two top-level keys to the result:
      - architecture_issues: list of issue dicts (rule_id, severity, message, ...)
      - architecture_issues_summary: { blocker, warning, info, total }

    Failures are swallowed and logged: a broken rule must never break analysis.
    """
    try:
        issues = evaluate_architecture_rules(result)
        classification = classify_regulated_workload(result)
        result["regulated_workload"] = classification.to_dict()
        audit_issue = build_audit_pipeline_issue(result, classification)
        if audit_issue is not None:
            issues.append(audit_issue)
        issue_dicts = [i.to_dict() for i in issues]
        summary = {"blocker": 0, "warning": 0, "info": 0, "total": len(issue_dicts)}
        for d in issue_dicts:
            sev = d.get("severity")
            if sev in summary:
                summary[sev] += 1
        result["architecture_issues"] = issue_dicts
        result["architecture_issues_summary"] = summary
    except Exception as exc:
        logger.warning(
            "architecture_rules evaluation failed: %s",
            str(exc).replace("\n", " ").replace("\r", " "),
        )
        result.setdefault("architecture_issues", [])
        result.setdefault(
            "architecture_issues_summary",
            {"blocker": 0, "warning": 0, "info": 0, "total": 0, "engine_error": True},
        )
    return result


def _normalize_analysis(result: dict) -> dict:
    """Normalize GPT vision output so downstream code always sees consistent fields.

    - source_service: always a string (GPT-4.1 sometimes returns a dict)
    - azure_service: always present (GPT-4.1 sometimes uses target_service instead)
    - sku_translation: enriched when instance types are detected in service text
    """
    for m in result.get("mappings", []):
        if isinstance(m.get("source_service"), dict):
            m["source_service"] = m["source_service"].get("name", str(m["source_service"]))
        if "azure_service" not in m and "target_service" in m:
            m["azure_service"] = m.pop("target_service")

    result = _enrich_with_sku(result)
    result = _enrich_with_provenance(result)
    result = _enrich_with_architecture_issues(result)
    return result


# ─────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────
class RestoreSessionRequest(StrictBaseModel):
    """Request body for restoring a cached analysis session."""
    analysis: Dict[str, Any]
    hld: Optional[Dict[str, Any]] = None
    hld_markdown: Optional[str] = None
    iac_code: Optional[str] = None
    iac_format: Optional[str] = None
    image_base64: Optional[str] = None
    image_content_type: Optional[str] = None


def _purge_store_records_for_diagram(store, diagram_id: str) -> int:
    purged = 0
    for key in list(store.keys("*")):
        value = store.get(key)
        if isinstance(value, dict) and value.get("diagram_id") == diagram_id:
            store.delete(key)
            purged += 1
    return purged


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

    diagram_id = generate_session_id("diag")
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

    # Content-level validation (magic bytes, active PDF/SVG/ZIP content, etc.)
    try:
        validate_upload(image_bytes, file.content_type or "", file.filename)
    except UploadValidationError as exc:
        raise ArchmorphException(exc.status_code, exc.message)

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

    register_diagram(project_id, diagram_id, file.filename, len(image_bytes))

    record_event("diagrams_uploaded", {"filename": file.filename})
    record_funnel_step(diagram_id, "upload")
    return attach_export_capability({
        "diagram_id": diagram_id,
        "project_id": project_id,
        "filename": file.filename,
        "size": len(image_bytes),
        "status": "uploaded"
    }, diagram_id)


# ─────────────────────────────────────────────────────────────
# Session Restore
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/restore-session")
@limiter.limit("10/minute")
async def restore_session(
    request: Request,
    diagram_id: str,
    body: RestoreSessionRequest,
    user=Depends(require_authenticated_user),
):
    """Re-inject a cached analysis result into the session store.

    The frontend caches analysis data in sessionStorage.  When the backend
    restarts and the in-memory store is wiped, the frontend can push its
    cached copy here to transparently restore the session.
    """
    analysis = body.analysis
    if not analysis or not isinstance(analysis, dict):
        raise ArchmorphException(400, "Invalid analysis payload")
    try:
        validate_analysis_payload_bounds(analysis)
    except AnalysisPayloadTooLarge as exc:
        raise ArchmorphException(
            413,
            detail={
                "error": "analysis_payload_too_large",
                "message": str(exc),
                **exc.details,
            },
        )

    existing = SESSION_STORE.get(diagram_id)
    if isinstance(existing, dict):
        existing_owner = existing.get("_owner_user_id")
        existing_tenant = existing.get("_tenant_id")
        if existing_owner and existing_owner != user.id:
            raise ArchmorphException(403, "Forbidden: session owner mismatch")
        if existing_tenant and existing_tenant != user.tenant_id:
            raise ArchmorphException(403, "Forbidden: tenant mismatch")

    analysis["diagram_id"] = diagram_id
    analysis["_owner_user_id"] = user.id
    analysis["_tenant_id"] = user.tenant_id

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
        try:
            decoded = base64.b64decode(body.image_base64, validate=True)
        except Exception as exc:
            raise ArchmorphException(400, f"Invalid image_base64 payload: {str(exc)}")
        if len(decoded) > MAX_UPLOAD_SIZE:
            raise ArchmorphException(
                413,
                f"image_base64 too large. Maximum allowed: {MAX_UPLOAD_SIZE // (1024*1024)} MB.",
            )
        restored_content_type = body.image_content_type or "image/png"
        try:
            validate_upload(decoded, restored_content_type, None)
        except UploadValidationError as exc:
            raise ArchmorphException(exc.status_code, exc.message)
        IMAGE_STORE[diagram_id] = (
            body.image_base64,
            restored_content_type,
        )
        restored_parts.append("image")
    logger.info("Session restored for %s via client cache (%s)", str(diagram_id).replace('\n', '').replace('\r', ''), str(", ".join(restored_parts)).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom
    record_event("sessions_restored", {"diagram_id": diagram_id, "parts": restored_parts})
    return attach_export_capability(
        {"status": "restored", "diagram_id": diagram_id, "restored": restored_parts},
        diagram_id,
    )


@router.delete("/api/diagrams/{diagram_id}/purge", dependencies=[Depends(require_diagram_access)])
@limiter.limit("20/minute")
async def purge_diagram_session(
    request: Request,
    diagram_id: str,
    _auth=Depends(verify_api_key),
):
    """Purge uploaded content and derived artifacts for a diagram.

    Retention baseline: upload/session/project/export capability stores use a
    2-hour TTL by default. Browser sessionStorage cache may also hold analysis
    state until tab/session close unless the client clears it.

    This endpoint provides immediate deletion of server-side data for API/UI
    callers, including uploaded bytes, analysis session payloads, project
    indexes, share links, export capabilities, and queued async jobs/events.
    Uploaded data is processed by model services for analysis and is not used
    by Archmorph for model training.
    """
    image_record = IMAGE_STORE.get(diagram_id)
    session_record = SESSION_STORE.get(diagram_id)
    image_deleted = image_record is not None
    session_deleted = session_record is not None
    if image_record is not None:
        IMAGE_STORE.delete(diagram_id)
    if session_record is not None:
        SESSION_STORE.delete(diagram_id)

    project_id = get_project_id_for_diagram(diagram_id)
    remove_diagram(diagram_id)

    export_capabilities_deleted = _purge_store_records_for_diagram(EXPORT_CAPABILITY_STORE, diagram_id)
    share_store_deleted = _purge_store_records_for_diagram(SHARE_STORE, diagram_id)
    share_links_deleted = shareable_reports.purge_diagram_shares(diagram_id)
    jobs_deleted = job_manager.purge_diagram(diagram_id)

    record_event("diagram_data_purged", {
        "diagram_id": diagram_id,
        "project_id": project_id,
        "image_deleted": image_deleted,
        "session_deleted": session_deleted,
        "export_capabilities_deleted": export_capabilities_deleted,
        "share_store_deleted": share_store_deleted,
        "share_links_deleted": share_links_deleted,
        "jobs_deleted": jobs_deleted,
    })
    return {
        "status": "purged",
        "diagram_id": diagram_id,
        "project_id": project_id,
        "purged": {
            "image": image_deleted,
            "session": session_deleted,
            "export_capabilities": export_capabilities_deleted,
            "share_store": share_store_deleted,
            "share_links": share_links_deleted,
            "jobs": jobs_deleted,
        },
    }


# ─────────────────────────────────────────────────────────────
# Diagrams — Analyze (sync)
# ─────────────────────────────────────────────────────────────

def _retry_after_seconds(exc: Exception, default: int = 30) -> int:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", {}) or {}
    value = headers.get("Retry-After") or headers.get("retry-after")
    try:
        retry_after = int(value) if value is not None else default
    except (TypeError, ValueError):
        retry_after = default
    return max(1, min(retry_after, 300))


def _raise_analysis_service_failure(exc: Exception) -> None:
    service_error = exc if isinstance(exc, OpenAIServiceError) else handle_openai_error(exc, "Vision analysis")
    if service_error.status_code == 429:
        retry_after = _retry_after_seconds(exc)
        raise ArchmorphException(
            429,
            "Analysis service is busy. Please wait a moment and try again.",
            details={"error": "analysis_retryable", "retry_after_seconds": retry_after},
            headers={"Retry-After": str(retry_after)},
        )
    if service_error.retryable:
        raise ArchmorphException(
            503,
            service_error.args[0] if service_error.args else "Analysis service is temporarily unavailable.",
            details={"error": "analysis_retryable", "retry_after_seconds": 30},
            headers={"Retry-After": "30"},
        )
    raise ArchmorphException(service_error.status_code, service_error.args[0] if service_error.args else "Vision analysis failed.")


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

    headers = dict(request.headers)
    user = get_user_from_request_headers(headers)
    api_key_principal_id = get_api_key_service_principal(headers)

    if ci_smoke.enabled():
        result = ci_smoke.clone_analysis(diagram_id)
        if user:
            result["_owner_user_id"] = user.id
            result["_tenant_id"] = user.tenant_id
        elif api_key_principal_id:
            result["_owner_api_key_id"] = api_key_principal_id
        SESSION_STORE[diagram_id] = result
        mark_diagram_analyzed(diagram_id, result)
        record_event("analyses_run", {"diagram_id": diagram_id, "services": result["services_detected"]})
        record_funnel_step(diagram_id, "analyze")
        if user:
            maybe_save_from_session(user.id, result, diagram_id)
        return attach_export_capability(result, diagram_id)

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
        _raise_analysis_service_failure(analysis_result_or_exc)

    result = await asyncio.to_thread(_normalize_analysis, analysis_result_or_exc)
    result["diagram_id"] = diagram_id
    result["image_classification"] = classification

    # Save to user history if authenticated (#245)
    if user:
        result["_owner_user_id"] = user.id
        result["_tenant_id"] = user.tenant_id
    elif api_key_principal_id:
        result["_owner_api_key_id"] = api_key_principal_id

    if len(SESSION_STORE) >= SESSION_STORE.maxsize:
        logger.warning("Session store at capacity (%d/%d) — oldest sessions will be evicted",
                       str(len(SESSION_STORE)).replace('\n', '').replace('\r', ''), str(SESSION_STORE.maxsize).replace('\n', '').replace('\r', ''))
    SESSION_STORE[diagram_id] = result
    mark_diagram_analyzed(diagram_id, result)
    record_event("analyses_run", {"diagram_id": diagram_id, "services": result["services_detected"]})
    record_funnel_step(diagram_id, "analyze")

    if user:
        maybe_save_from_session(user.id, result, diagram_id)

    return attach_export_capability(result, diagram_id)


# ─────────────────────────────────────────────────────────────
# Async Analysis (Issue #172)
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/analyze-async")
@limiter.limit("5/minute")
async def analyze_diagram_async(
    request: Request,
    diagram_id: str,
    _auth=Depends(verify_api_key),
):
    """Start an async analysis of an uploaded diagram.

    Returns ``202 Accepted`` with a ``job_id``. Use the SSE stream
    endpoint ``GET /api/jobs/{job_id}/stream`` to receive real-time
    progress events, or poll ``GET /api/jobs/{job_id}`` for status.
    """
    if diagram_id not in IMAGE_STORE:
        raise ArchmorphException(404, f"No uploaded image found for diagram {diagram_id}. Upload first.")

    headers = dict(request.headers)
    user = get_user_from_request_headers(headers)
    api_key_principal_id = get_api_key_service_principal(headers)
    job = job_manager.submit(
        "analyze",
        diagram_id=diagram_id,
        owner_user_id=user.id if user else None,
        tenant_id=user.tenant_id if user else None,
        owner_api_key_id=api_key_principal_id if not user else None,
    )
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

        result = _normalize_analysis(result)
        result["diagram_id"] = diagram_id
        result["image_classification"] = classification

        job_record = job_manager.get(job_id)
        job_user_id = getattr(job_record, "owner_user_id", None)
        job_tenant_id = getattr(job_record, "tenant_id", None)
        job_api_principal_id = getattr(job_record, "owner_api_key_id", None)
        if job_user_id and job_tenant_id:
            result["_owner_user_id"] = job_user_id
            result["_tenant_id"] = job_tenant_id
        elif job_api_principal_id:
            result["_owner_api_key_id"] = job_api_principal_id

        job_manager.update_progress(job_id, 80, "Storing analysis results...")
        SESSION_STORE[diagram_id] = result
        mark_diagram_analyzed(diagram_id, result)

        job_manager.update_progress(job_id, 90, "Generating guided questions...")

        record_event("analyses_run", {"diagram_id": diagram_id, "services": result.get("services_detected", 0)})
        record_funnel_step(diagram_id, "analyze")

        # Save to user history if job carries an authenticated owner.
        if job_user_id:
            maybe_save_from_session(job_user_id, result, diagram_id)
        elif job_api_principal_id:
            logger.debug(
                "Skipping user history persistence for API principal-owned async analysis %s",
                str(diagram_id).replace('\n', '').replace('\r', ''),
            )

        job_manager.update_progress(job_id, 95, "Finalizing...")
        job_manager.complete(job_id, result=attach_export_capability(result, diagram_id))

    except Exception as exc:
        logger.error("Async analysis failed for %s: %s", str(diagram_id).replace('\n', '').replace('\r', ''), str(exc).replace('\n', '').replace('\r', ''), exc_info=True)  # codeql[py/log-injection] Handled by custom
        job_manager.fail(job_id, str(exc))
