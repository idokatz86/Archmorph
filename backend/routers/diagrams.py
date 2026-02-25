"""
Diagram routes — upload, analyze, questions, services, export, IaC, HLD,
best-practices, cost-optimization, share, IaC-chat, terraform-preview.
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Request, Depends
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import asyncio
import secrets
import uuid
import logging

from routers.shared import (
    SESSION_STORE, IMAGE_STORE, SHARE_STORE,
    limiter, verify_api_key, MAX_UPLOAD_SIZE,
)
from routers.samples import get_or_recreate_session
from job_queue import job_manager
from usage_metrics import record_event, record_funnel_step
from guided_questions import generate_questions, apply_answers, get_question_constraints
from diagram_export import generate_diagram
from iac_chat import process_iac_chat, get_iac_chat_history, clear_iac_chat
from iac_generator import generate_iac_code
from hld_generator import generate_hld, generate_hld_markdown
from image_classifier import classify_image
from vision_analyzer import analyze_image, compress_image
from service_builder import deduplicate_questions, get_smart_defaults_from_analysis, add_services_from_text
from services.azure_pricing import estimate_services_cost
from hld_export import export_hld, SUPPORTED_FORMATS
from best_practices import analyze_architecture, get_quick_wins
from cost_optimizer import analyze_cost_optimizations
from terraform_preview import preview_terraform_plan
from migration_risk import compute_risk_score
from infra_import import parse_infrastructure, detect_format, InfraFormat
from compliance_mapper import assess_compliance
from ai_suggestion import (
    suggest_mapping,
    suggest_batch,
    build_dependency_graph,
    get_review_queue,
    review_suggestion,
    get_review_stats,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ─────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────
class AddServicesRequest(BaseModel):
    text: str


class IaCChatMessage(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)
    code: str = Field(..., max_length=100000)
    format: str = Field(default="terraform", pattern="^(terraform|bicep|cloudformation)$")


class TerraformValidateRequest(BaseModel):
    code: str


# ─────────────────────────────────────────────────────────────
# Diagrams — Upload & Analyze
# ─────────────────────────────────────────────────────────────
@router.post("/api/projects/{project_id}/diagrams")
@limiter.limit("10/minute")
async def upload_diagram(request: Request, project_id: str, file: UploadFile = File(...), _auth=Depends(verify_api_key)):
    # Validate file type
    allowed_types = [
        "image/png", "image/jpeg", "image/svg+xml", "application/pdf",
        "application/vnd.ms-visio.drawing.main+xml",  # .vsdx
        "application/vnd.visio",  # legacy alias
        "application/octet-stream",  # browsers may send .vsdx as octet-stream
    ]
    # Also allow by file extension for .vsdx
    is_visio = file.filename and file.filename.lower().endswith('.vsdx')
    if file.content_type not in allowed_types and not is_visio:
        raise HTTPException(400, f"File type {file.content_type} not supported")

    # Generate unique diagram ID and store image bytes
    diagram_id = f"diag-{uuid.uuid4().hex[:8]}"
    # Read file in chunks with early size limit enforcement
    chunks = []
    total_size = 0
    while True:
        chunk = await file.read(1024 * 1024)  # 1 MB chunks
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > MAX_UPLOAD_SIZE:
            raise HTTPException(
                413,
                f"File too large. Maximum allowed: {MAX_UPLOAD_SIZE // (1024*1024)} MB."
            )
        chunks.append(chunk)
    image_bytes = b"".join(chunks)

    IMAGE_STORE[diagram_id] = (image_bytes, file.content_type)
    logger.info("Stored image for %s (%d bytes, %s)", diagram_id, len(image_bytes), file.content_type)

    # Proactive capacity warning — mirrors SESSION_STORE check (#177)
    img_usage = len(IMAGE_STORE) / IMAGE_STORE.maxsize
    if img_usage >= 0.8:
        logger.warning(
            "IMAGE_STORE at %.0f%% capacity (%d/%d) — oldest entries will be evicted",
            img_usage * 100, len(IMAGE_STORE), IMAGE_STORE.maxsize,
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
# Session Restore — re-inject cached analysis after backend restart
# ─────────────────────────────────────────────────────────────
class RestoreSessionRequest(BaseModel):
    analysis: Dict[str, Any]

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
        raise HTTPException(400, "Invalid analysis payload")

    # Ensure diagram_id matches
    analysis["diagram_id"] = diagram_id

    SESSION_STORE[diagram_id] = analysis
    logger.info("Session restored for %s via client cache", diagram_id)
    record_event("sessions_restored", {"diagram_id": diagram_id})
    return {"status": "restored", "diagram_id": diagram_id}


@router.post("/api/diagrams/{diagram_id}/analyze")
@limiter.limit("5/minute")
async def analyze_diagram(request: Request, diagram_id: str, _auth=Depends(verify_api_key)):
    """
    Analyze an uploaded architecture diagram using GPT-4o vision.
    Detects cloud services and maps them to Azure equivalents using the catalog.
    Includes an image classification pre-check to reject non-architecture images.
    """
    # Retrieve stored image
    if diagram_id not in IMAGE_STORE:
        raise HTTPException(404, f"No uploaded image found for diagram {diagram_id}. Upload first.")

    image_bytes, content_type = IMAGE_STORE[diagram_id]
    logger.info("Analyzing diagram %s (%d bytes)", diagram_id, len(image_bytes))

    # ── Pre-compress once to avoid double compression (#177) ──
    # classify_image() and analyze_image() each internally call compress_image().
    # Pre-compressing here means the internal calls operate on an already-small
    # JPEG (fast no-op) instead of re-compressing a multi-MB PNG twice.
    try:
        compressed_bytes, compressed_type, _cw, _ch = compress_image(image_bytes, content_type)
    except Exception:
        compressed_bytes, compressed_type = image_bytes, content_type

    # ── Image classification pre-check (async) ──
    try:
        classification = await asyncio.to_thread(classify_image, compressed_bytes, compressed_type)
    except Exception as exc:
        logger.warning("Image classification failed for %s: %s — proceeding with analysis", diagram_id, exc)
        classification = {"is_architecture_diagram": True, "confidence": 0.5, "image_type": "unknown", "reason": "Classification unavailable"}

    if not classification["is_architecture_diagram"]:
        logger.info("Image rejected for %s: %s (confidence: %.2f)", diagram_id, classification["reason"], classification["confidence"])
        record_event("images_rejected", {"diagram_id": diagram_id, "image_type": classification["image_type"], "reason": classification["reason"]})
        raise HTTPException(
            status_code=422,
            detail={
                "error": "not_architecture_diagram",
                "message": f"The uploaded image does not appear to be a cloud architecture diagram. Detected: {classification['image_type']}.",
                "classification": classification,
            },
        )

    logger.info("Image classified as architecture diagram for %s (confidence: %.2f)", diagram_id, classification["confidence"])

    try:
        result = await asyncio.to_thread(analyze_image, compressed_bytes, compressed_type)
    except Exception as exc:
        logger.error("Vision analysis failed for %s: %s", diagram_id, exc, exc_info=True)
        raise HTTPException(500, "Vision analysis failed. Please try again with a different image.")

    # Inject diagram_id and classification metadata into result
    result["diagram_id"] = diagram_id
    result["image_classification"] = classification

    # Store analysis result for guided questions and diagram export
    if len(SESSION_STORE) >= SESSION_STORE.maxsize:
        logger.warning("Session store at capacity (%d/%d) — oldest sessions will be evicted",
                       len(SESSION_STORE), SESSION_STORE.maxsize)
    SESSION_STORE[diagram_id] = result
    record_event("analyses_run", {"diagram_id": diagram_id, "services": result["services_detected"]})
    record_funnel_step(diagram_id, "analyze")
    return result


# ─────────────────────────────────────────────────────────────
# Guided Questions
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/questions")
@limiter.limit("15/minute")
async def get_guided_questions(request: Request, diagram_id: str, smart_dedup: bool = True, _auth=Depends(verify_api_key)):
    """Generate guided questions based on detected AWS services.
    
    If smart_dedup=True, questions that have been implicitly answered
    by user context (e.g., natural language additions) are filtered out.
    """
    analysis = get_or_recreate_session(diagram_id)
    if not analysis:
        raise HTTPException(404, f"No analysis found for diagram {diagram_id}. Run /analyze first.")

    detected = [m["source_service"] for m in analysis.get("mappings", [])]
    questions = generate_questions(detected)
    
    # Apply smart deduplication if enabled
    inferred_answers = {}
    if smart_dedup:
        user_context = analysis.get("user_context", {})
        questions, inferred_answers = deduplicate_questions(questions, analysis, user_context)
        smart_defaults = get_smart_defaults_from_analysis(analysis)
        inferred_answers = {**smart_defaults, **inferred_answers}
    
    record_event("questions_generated", {"diagram_id": diagram_id, "count": len(questions)})
    record_funnel_step(diagram_id, "questions")
    return {
        "diagram_id": diagram_id,
        "questions": questions,
        "total": len(questions),
        "inferred_answers": inferred_answers,
        "questions_skipped": len(inferred_answers),
        **get_question_constraints(),
    }


# ─────────────────────────────────────────────────────────────
# Natural Language Service Builder
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/add-services")
@limiter.limit("10/minute")
async def add_services_natural_language(
    request: Request,
    diagram_id: str,
    body: AddServicesRequest,
    _auth=Depends(verify_api_key),
):
    """Add Azure services to an architecture using natural language.
    
    Example: "Add a Redis cache and API Gateway with WAF"
    
    The services are added to the existing analysis, and users can continue
    to the guided questions or IaC generation.
    """
    analysis = get_or_recreate_session(diagram_id)
    if not analysis:
        raise HTTPException(404, f"No analysis found for diagram {diagram_id}. Run /analyze first.")
    
    try:
        updated = await asyncio.to_thread(
            add_services_from_text,
            analysis=analysis,
            user_text=body.text,
        )
    except Exception as exc:
        logger.error("Failed to add services for %s: %s", diagram_id, exc)
        raise HTTPException(500, "Failed to process request. Please try again.")
    
    # Store user context for smart question deduplication
    updated.setdefault("user_context", {})
    updated["user_context"].setdefault("natural_language_additions", [])
    updated["user_context"]["natural_language_additions"].append({
        "text": body.text,
        "services_added": updated.get("services_added", []),
    })
    
    SESSION_STORE[diagram_id] = updated
    
    record_event("services_added_nl", {
        "diagram_id": diagram_id,
        "services_count": len(updated.get("services_added", [])),
    })
    
    return {
        "diagram_id": diagram_id,
        "services_added": updated.get("services_added", []),
        "services_detected": updated.get("services_detected", 0),
        "inferred_requirements": updated.get("inferred_requirements", []),
        "message": f"Added {len(updated.get('services_added', []))} service(s) to your architecture.",
    }


@router.post("/api/diagrams/{diagram_id}/apply-answers")
@limiter.limit("15/minute")
async def apply_guided_answers(request: Request, diagram_id: str, answers: Dict[str, Any]):
    """Apply user answers to refine the Azure architecture analysis."""
    analysis = get_or_recreate_session(diagram_id)
    if not analysis:
        raise HTTPException(404, f"No analysis found for diagram {diagram_id}. Run /analyze first.")

    refined = apply_answers(analysis, answers)
    SESSION_STORE[diagram_id] = refined
    record_event("answers_applied", {"diagram_id": diagram_id})
    record_funnel_step(diagram_id, "answers")
    return refined


# ─────────────────────────────────────────────────────────────
# Diagram Export (Excalidraw / Draw.io / Visio)
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/export-diagram")
@limiter.limit("10/minute")
async def export_architecture_diagram(request: Request, diagram_id: str, format: str = "excalidraw"):
    """Generate an architecture diagram in Excalidraw, Draw.io, or Visio format."""
    if format not in ("excalidraw", "drawio", "vsdx"):
        raise HTTPException(400, "Format must be 'excalidraw', 'drawio', or 'vsdx'")

    analysis = get_or_recreate_session(diagram_id)
    if not analysis:
        raise HTTPException(404, f"No analysis found for diagram {diagram_id}. Run /analyze first.")

    try:
        result = generate_diagram(analysis, format)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    record_event(f"exports_{format}", {"diagram_id": diagram_id})
    record_funnel_step(diagram_id, "export")
    return result


# ─────────────────────────────────────────────────────────────
# IaC Generation
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/generate")
@limiter.limit("5/minute")
async def generate_iac(request: Request, diagram_id: str, format: str = "terraform", _auth=Depends(verify_api_key)):
    if format not in ["terraform", "bicep", "cloudformation"]:
        raise HTTPException(400, "Format must be 'terraform', 'bicep', or 'cloudformation'")

    # Get analysis from session (may be None for base template)
    session = SESSION_STORE.get(diagram_id, {})
    iac_params = session.get("iac_parameters", {})

    # Generate IaC dynamically using GPT-4o
    try:
        code = await asyncio.to_thread(
            generate_iac_code,
            analysis=session if session else None,
            iac_format=format,
            params=iac_params,
        )
    except Exception as exc:
        logger.error("IaC generation failed for %s: %s", diagram_id, exc)
        raise HTTPException(500, "IaC generation failed. Please try again.")

    record_event(f"iac_generated_{format}", {"diagram_id": diagram_id})
    record_funnel_step(diagram_id, "iac_generate")
    return {"diagram_id": diagram_id, "format": format, "code": code}


# ─────────────────────────────────────────────────────────────
# Cost Estimation
# ─────────────────────────────────────────────────────────────
@router.get("/api/diagrams/{diagram_id}/cost-estimate")
@limiter.limit("15/minute")
async def estimate_cost(request: Request, diagram_id: str):
    record_event("cost_estimates", {"diagram_id": diagram_id})

    session = get_or_recreate_session(diagram_id)
    if not session:
        raise HTTPException(404, "No analysis found. Analyze a diagram first.")
    # The analysis result is stored directly in SESSION_STORE (not nested under "analysis")
    mappings = session.get("mappings", [])
    iac_params = session.get("iac_parameters", {})

    # Get region from guided-question answers or iac_parameters
    region = iac_params.get("deploy_region", "westeurope")
    sku_strategy = iac_params.get("sku_strategy", "Balanced")

    # If we have real mappings, compute dynamic pricing
    if mappings:
        result = estimate_services_cost(mappings, region=region, sku_strategy=sku_strategy)
        result["diagram_id"] = diagram_id
        return result

    # Fallback: return structure-compatible empty estimate
    return {
        "diagram_id": diagram_id,
        "total_monthly_estimate": {
            "low": 0,
            "high": 0,
        },
        "currency": "USD",
        "region": "West Europe",
        "arm_region": region,
        "services": [],
        "service_count": 0,
        "pricing_source": "no analysis available",
    }


# ─────────────────────────────────────────────────────────────
# IaC Chat — GPT-4o powered Terraform/Bicep assistant
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/iac-chat")
@limiter.limit("10/minute")
async def iac_chat_endpoint(request: Request, diagram_id: str, msg: IaCChatMessage, _auth=Depends(verify_api_key)):
    """Chat with AI to modify generated Terraform/Bicep code."""
    record_event("iac_chat_messages", {"diagram_id": diagram_id})

    # Get analysis context from session
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
# HLD Generation — AI-powered High-Level Design document
# ─────────────────────────────────────────────────────────────

@router.post("/api/diagrams/{diagram_id}/generate-hld")
@limiter.limit("3/minute")
async def generate_hld_endpoint(request: Request, diagram_id: str, _auth=Depends(verify_api_key)):
    """Generate a comprehensive High-Level Design document."""
    record_event("hld_generated", {"diagram_id": diagram_id})

    session = get_or_recreate_session(diagram_id)
    if not session:
        raise HTTPException(404, "No analysis found. Analyze a diagram first.")

    analysis = session

    # Get cost estimate — use cached if available (#177)
    cost_estimate = session.get("_cached_cost_estimate")
    if cost_estimate is None:
        try:
            iac_params = session.get("iac_parameters", {})
            region = iac_params.get("region", "westeurope")
            strategy = iac_params.get("sku_strategy", "balanced")
            cost_estimate = estimate_services_cost(analysis.get("mappings", []), region=region, sku_strategy=strategy)
            session["_cached_cost_estimate"] = cost_estimate
        except Exception:  # nosec B110 — session cleanup is optional, must not break response
            logger.debug("Cost estimation unavailable, proceeding without it")

    try:
        hld = await asyncio.to_thread(
            generate_hld,
            analysis=analysis,
            cost_estimate=cost_estimate,
            iac_params=session.get("iac_parameters"),
        )
        markdown = generate_hld_markdown(hld)
    except ValueError as e:
        raise HTTPException(500, str(e))
    except Exception as e:
        logger.exception("HLD generation failed: %s", e)
        raise HTTPException(500, f"HLD generation failed: {type(e).__name__}: {e}")

    # Store in session
    session["hld"] = hld
    session["hld_markdown"] = markdown

    return {
        "diagram_id": diagram_id,
        "hld": hld,
        "markdown": markdown,
    }


@router.get("/api/diagrams/{diagram_id}/hld")
@limiter.limit("30/minute")
async def get_hld(request: Request, diagram_id: str):
    """Get previously generated HLD document."""
    session = get_or_recreate_session(diagram_id)
    if not session or "hld" not in session:
        raise HTTPException(404, "No HLD found. Generate one first.")
    return {
        "diagram_id": diagram_id,
        "hld": session["hld"],
        "markdown": session.get("hld_markdown", ""),
    }


@router.post("/api/diagrams/{diagram_id}/export-hld")
@limiter.limit("10/minute")
async def export_hld_endpoint(request: Request, diagram_id: str, _auth=Depends(verify_api_key)):
    """Export HLD document to Word, PDF, or PowerPoint format.

    Query params:
      - format: docx | pdf | pptx (required)
      - include_diagrams: true | false (default: true)

    Body (optional JSON):
      - diagram_image: base64-encoded diagram image to embed
    """
    fmt = request.query_params.get("format", "").lower()
    if fmt not in SUPPORTED_FORMATS:
        raise HTTPException(400, f"Invalid format. Use one of: {', '.join(sorted(SUPPORTED_FORMATS))}")

    include_diagrams = request.query_params.get("include_diagrams", "true").lower() == "true"

    session = get_or_recreate_session(diagram_id)
    if not session or "hld" not in session:
        raise HTTPException(404, "No HLD found. Generate one first.")

    # Optional diagram image from request body
    diagram_b64 = None
    try:
        body = await request.json()
        diagram_b64 = body.get("diagram_image") if isinstance(body, dict) else None
    except Exception:
        pass  # nosec B110 — No body or non-JSON body is fine

    record_event("hld_exported", {"diagram_id": diagram_id, "format": fmt, "include_diagrams": include_diagrams})

    try:
        result = await asyncio.to_thread(
            export_hld,
            hld=session["hld"],
            format=fmt,
            include_diagrams=include_diagrams,
            diagram_b64=diagram_b64,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error("HLD export failed: %s", e)
        raise HTTPException(500, "Export failed. Please try again or contact support.")

    return result


# ─────────────────────────────────────────────────────────────
# Best Practices & WAF Analysis
# ─────────────────────────────────────────────────────────────
@router.get("/api/diagrams/{diagram_id}/best-practices")
@limiter.limit("30/minute")
async def get_best_practices(request: Request, diagram_id: str):
    """Analyze architecture against Azure Well-Architected Framework."""
    analysis = get_or_recreate_session(diagram_id)
    if not analysis:
        raise HTTPException(404, "Analysis not found")
    
    # Get user answers if available
    answers = analysis.get("applied_answers", {})
    
    result = analyze_architecture(analysis, answers)
    result["quick_wins"] = get_quick_wins(result["recommendations"])
    
    return result


# ─────────────────────────────────────────────────────────────
# Cost Optimization
# ─────────────────────────────────────────────────────────────
@router.get("/api/diagrams/{diagram_id}/cost-optimization")
@limiter.limit("15/minute")
async def get_cost_optimization(request: Request, diagram_id: str):
    """Get cost optimization recommendations for the architecture."""
    analysis = get_or_recreate_session(diagram_id)
    if not analysis:
        raise HTTPException(404, "Analysis not found")
    
    answers = analysis.get("applied_answers", {})
    
    # Try to get cost estimate if available
    cost_estimate = analysis.get("cost_estimate")
    
    return analyze_cost_optimizations(analysis, answers, cost_estimate)


# ─────────────────────────────────────────────────────────────
# Share Links
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/share")
@limiter.limit("10/minute")
async def create_share_link(request: Request, diagram_id: str):
    """Create a shareable read-only link for analysis results."""
    analysis = get_or_recreate_session(diagram_id)
    if not analysis:
        raise HTTPException(404, "Analysis not found")
    
    share_id = f"share-{secrets.token_urlsafe(24)}"
    
    # Store a read-only snapshot
    SHARE_STORE[share_id] = {
        "analysis": analysis,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_in": "24 hours"
    }
    
    return {
        "share_id": share_id,
        "share_url": f"/shared/{share_id}",
        "expires_in": "24 hours"
    }


@router.get("/api/shared/{share_id}")
@limiter.limit("30/minute")
async def get_shared_analysis(request: Request, share_id: str):
    """Get shared analysis by share ID (public, read-only)."""
    shared = SHARE_STORE.get(share_id)
    if not shared:
        raise HTTPException(404, "Share link expired or invalid")
    
    return {
        "analysis": shared["analysis"],
        "shared_at": shared["created_at"],
        "read_only": True
    }


# ─────────────────────────────────────────────────────────────
# Terraform Plan Preview (Issue #122 / #123: auth + simulation-only)
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/terraform-preview")
@limiter.limit("10/minute")
async def preview_terraform_plan_endpoint(
    request: Request,
    diagram_id: str,
    _key=Depends(verify_api_key),
):
    """Generate a preview of what Terraform would create.
    
    Uses simulation mode only — never executes real Terraform CLI
    to prevent Remote Code Execution via user-supplied HCL.
    """
    analysis = get_or_recreate_session(diagram_id)
    if not analysis:
        raise HTTPException(404, "Analysis not found")
    
    # Get IaC code if available, or generate it
    iac_code = analysis.get("generated_iac")
    if not iac_code:
        try:
            iac_code = await asyncio.to_thread(
                generate_iac_code,
                analysis=analysis,
                iac_format="terraform",
                params=analysis.get("iac_parameters", {}),
            )
        except Exception:
            raise HTTPException(500, "Failed to generate IaC code. Please try again.")
    
    # Force simulation mode — never run actual terraform CLI (Issue #122)
    result = preview_terraform_plan(iac_code, diagram_id, use_simulation=True)
    
    return result.to_dict()


# ─────────────────────────────────────────────────────────────
# Migration Risk Score (Issue #158)
# ─────────────────────────────────────────────────────────────
@router.get("/api/diagrams/{diagram_id}/risk-score")
@limiter.limit("20/minute")
async def get_risk_score(request: Request, diagram_id: str, _auth=Depends(verify_api_key)):
    """Compute the Migration Risk Score (MRS) for a diagram analysis.

    Returns a composite score (0-100) with per-factor breakdown,
    risk tier, and actionable recommendations.
    """
    analysis = get_or_recreate_session(diagram_id)
    if not analysis:
        raise HTTPException(404, "Analysis not found — analyze a diagram first")

    result = await asyncio.to_thread(compute_risk_score, analysis)
    record_event("risk_score_computed", {
        "diagram_id": diagram_id,
        "score": result["overall_score"],
        "tier": result["risk_tier"],
    })
    return result


# ─────────────────────────────────────────────────────────────
# Infrastructure Import (Issue #155)
# ─────────────────────────────────────────────────────────────
class InfraImportRequest(BaseModel):
    content: str = Field(..., min_length=10, max_length=52_428_800)
    format: str = Field(default="auto", pattern="^(auto|terraform_state|terraform_hcl|cloudformation)$")
    filename: str = Field(default="unknown")


@router.post("/api/import/infrastructure")
@limiter.limit("10/minute")
async def import_infrastructure(request: Request, body: InfraImportRequest, _auth=Depends(verify_api_key)):
    """Import infrastructure-as-code files to create an architecture analysis.

    Supports Terraform State (.tfstate), Terraform HCL (.tf), and
    CloudFormation templates (JSON/YAML). Auto-detects format when
    format='auto'.
    """
    # Auto-detect format
    if body.format == "auto":
        fmt = detect_format(body.filename, body.content)
        if fmt is None:
            raise HTTPException(400, "Could not auto-detect file format. "
                              "Specify format as terraform_state, terraform_hcl, or cloudformation.")
    else:
        try:
            fmt = InfraFormat(body.format)
        except ValueError:
            raise HTTPException(400, f"Unsupported format: {body.format}")

    # Generate diagram ID
    diagram_id = f"import-{uuid.uuid4().hex[:8]}"

    try:
        analysis = await asyncio.to_thread(
            parse_infrastructure, body.content, fmt, diagram_id
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error("Infrastructure import failed: %s", e, exc_info=True)
        raise HTTPException(500, "Failed to parse infrastructure file")

    # Store in session
    SESSION_STORE[diagram_id] = analysis
    record_event("infra_imported", {
        "diagram_id": diagram_id,
        "format": fmt.value,
        "services": analysis["services_detected"],
    })
    record_funnel_step(diagram_id, "import")

    return {
        "diagram_id": diagram_id,
        "source_format": fmt.value,
        "services_detected": analysis["services_detected"],
        "source_provider": analysis["source_provider"],
        "mappings": analysis["mappings"],
        "zones": analysis["zones"],
        "service_connections": analysis["service_connections"],
        "confidence_summary": analysis["confidence_summary"],
        "architecture_patterns": analysis["architecture_patterns"],
        "import_metadata": analysis.get("import_metadata", {}),
    }


# ─────────────────────────────────────────────────────────────
# Compliance Assessment (Issue #160)
# ─────────────────────────────────────────────────────────────
@router.get("/api/diagrams/{diagram_id}/compliance")
@limiter.limit("20/minute")
async def get_compliance(request: Request, diagram_id: str, _auth=Depends(verify_api_key)):
    """Assess compliance posture for a diagram analysis.

    Auto-detects applicable regulatory frameworks (HIPAA, PCI-DSS,
    SOC 2, GDPR, ISO 27001, FedRAMP) and returns scores, gaps,
    and remediation guidance.
    """
    analysis = get_or_recreate_session(diagram_id)
    if not analysis:
        raise HTTPException(404, "Analysis not found — analyze a diagram first")

    result = await asyncio.to_thread(assess_compliance, analysis)
    record_event("compliance_assessed", {
        "diagram_id": diagram_id,
        "frameworks": list(result["frameworks"].keys()),
        "overall_score": result["overall_score"],
    })
    return result


# ─────────────────────────────────────────────────────────────
# Async Analysis — returns immediately with job_id (Issue #172)
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/analyze-async")
@limiter.limit("5/minute")
async def analyze_diagram_async(request: Request, diagram_id: str, _auth=Depends(verify_api_key)):
    """Start an async analysis of an uploaded diagram.

    Returns ``202 Accepted`` with a ``job_id``. Use the SSE stream
    endpoint ``GET /api/jobs/{job_id}/stream`` to receive real-time
    progress events, or poll ``GET /api/jobs/{job_id}`` for status.

    The sync ``POST /api/diagrams/{diagram_id}/analyze`` endpoint
    remains available as a backward-compatible fallback.
    """
    if diagram_id not in IMAGE_STORE:
        raise HTTPException(404, f"No uploaded image found for diagram {diagram_id}. Upload first.")

    # Submit job and return immediately
    job = job_manager.submit("analyze", diagram_id=diagram_id)

    # Launch background worker
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

        image_bytes, content_type = IMAGE_STORE[diagram_id]
        job_manager.update_progress(job_id, 5, "Pre-compressing image...")

        # Check for cancellation between steps
        if job_manager.is_cancelled(job_id):
            return

        # Pre-compress
        try:
            compressed_bytes, compressed_type, _cw, _ch = compress_image(image_bytes, content_type)
        except Exception:
            compressed_bytes, compressed_type = image_bytes, content_type

        job_manager.update_progress(job_id, 15, "Classifying image type...")

        if job_manager.is_cancelled(job_id):
            return

        # Classify
        try:
            classification = await asyncio.to_thread(classify_image, compressed_bytes, compressed_type)
        except Exception as exc:
            logger.warning("Classification failed for %s: %s", diagram_id, exc)
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

        # Vision analysis (the long step — 10-30s)
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
        logger.error("Async analysis failed for %s: %s", diagram_id, exc, exc_info=True)
        job_manager.fail(job_id, str(exc))


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
        raise HTTPException(400, "Format must be 'terraform', 'bicep', or 'cloudformation'")

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
        logger.error("Async IaC generation failed: %s", exc, exc_info=True)
        job_manager.fail(job_id, str(exc))


# ─────────────────────────────────────────────────────────────
# Async HLD Generation (Issue #172)
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/generate-hld-async")
@limiter.limit("3/minute")
async def generate_hld_async(request: Request, diagram_id: str, _auth=Depends(verify_api_key)):
    """Start async HLD document generation. Returns 202 with job_id."""
    session = get_or_recreate_session(diagram_id)
    if not session:
        raise HTTPException(404, "No analysis found. Analyze a diagram first.")

    job = job_manager.submit("generate_hld", diagram_id=diagram_id)
    asyncio.create_task(_run_hld_job(job.job_id, diagram_id))

    from starlette.responses import JSONResponse
    return JSONResponse(
        status_code=202,
        content={
            "job_id": job.job_id,
            "diagram_id": diagram_id,
            "status": "queued",
            "stream_url": f"/api/jobs/{job.job_id}/stream",
        },
    )


async def _run_hld_job(job_id: str, diagram_id: str) -> None:
    """Background worker for HLD generation."""
    try:
        job_manager.start(job_id)
        job_manager.update_progress(job_id, 10, "Preparing HLD generation...")

        session = get_or_recreate_session(diagram_id)
        if not session:
            job_manager.fail(job_id, "Analysis not found")
            return

        if job_manager.is_cancelled(job_id):
            return

        # Cost estimate
        cost_estimate = session.get("_cached_cost_estimate")
        if cost_estimate is None:
            job_manager.update_progress(job_id, 20, "Calculating cost estimates...")
            try:
                iac_params = session.get("iac_parameters", {})
                region = iac_params.get("region", "westeurope")
                strategy = iac_params.get("sku_strategy", "balanced")
                cost_estimate = estimate_services_cost(session.get("mappings", []), region=region, sku_strategy=strategy)
                session["_cached_cost_estimate"] = cost_estimate
            except Exception:
                logger.debug("Cost estimation unavailable")

        job_manager.update_progress(job_id, 40, "Generating High-Level Design with GPT-4o...")

        hld = await asyncio.to_thread(
            generate_hld,
            analysis=session,
            cost_estimate=cost_estimate,
            iac_params=session.get("iac_parameters"),
        )

        if job_manager.is_cancelled(job_id):
            return

        job_manager.update_progress(job_id, 80, "Rendering markdown...")
        markdown = generate_hld_markdown(hld)

        session["hld"] = hld
        session["hld_markdown"] = markdown

        record_event("hld_generated", {"diagram_id": diagram_id})
        job_manager.complete(job_id, result={"diagram_id": diagram_id, "hld": hld, "markdown": markdown})

    except Exception as exc:
        logger.error("Async HLD generation failed: %s", exc, exc_info=True)
        job_manager.fail(job_id, str(exc))


# ─────────────────────────────────────────────────────────────
# AI Cross-Cloud Mapping Auto-Suggestion (Issue #153)
# ─────────────────────────────────────────────────────────────
class SuggestMappingRequest(BaseModel):
    source_service: str = Field(..., min_length=1, max_length=200)
    source_provider: str = Field("aws", pattern="^(aws|gcp)$")
    context_services: Optional[list] = None


class SuggestBatchRequest(BaseModel):
    services: list = Field(..., min_length=1, max_length=50)
    source_provider: str = Field("aws", pattern="^(aws|gcp)$")


class ReviewRequest(BaseModel):
    decision: str = Field(..., pattern="^(approved|rejected)$")
    reviewer: str = Field(..., min_length=1)
    override_azure_service: Optional[str] = None
    override_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    notes: Optional[str] = None


@router.post("/api/suggest/mapping", tags=["ai-suggestion"])
@limiter.limit("20/minute")
async def api_suggest_mapping(
    request: Request, body: SuggestMappingRequest, _=Depends(verify_api_key)
):
    """AI-powered Azure mapping suggestion for a single source service."""
    result = await asyncio.to_thread(
        suggest_mapping,
        body.source_service,
        body.source_provider,
        body.context_services,
    )
    record_event("ai_suggestion", {
        "source": body.source_service,
        "provider": body.source_provider,
        "confidence": result.get("confidence", 0),
    })
    return result


@router.post("/api/suggest/batch", tags=["ai-suggestion"])
@limiter.limit("5/minute")
async def api_suggest_batch(
    request: Request, body: SuggestBatchRequest, _=Depends(verify_api_key)
):
    """AI-powered batch mapping suggestion for multiple services."""
    results = await asyncio.to_thread(
        suggest_batch, body.services, body.source_provider
    )
    record_event("ai_suggestion_batch", {"count": len(results)})
    return {"suggestions": results, "count": len(results)}


@router.get("/api/diagrams/{diagram_id}/dependency-graph", tags=["ai-suggestion"])
@limiter.limit("20/minute")
async def api_dependency_graph(
    request: Request, diagram_id: str, _=Depends(verify_api_key)
):
    """Build a dependency graph from an existing analysis."""
    session = get_or_recreate_session(diagram_id)
    if not session:
        raise HTTPException(status_code=404, detail="Analysis not found")
    mappings = session.get("mappings", [])
    graph = build_dependency_graph(mappings)
    return {"diagram_id": diagram_id, **graph}


@router.get("/api/admin/suggestions/queue", tags=["ai-suggestion"])
@limiter.limit("30/minute")
async def api_review_queue(
    request: Request, status: Optional[str] = None, _=Depends(verify_api_key)
):
    """Get the admin review queue for AI mapping suggestions."""
    items = get_review_queue(status=status)
    stats = get_review_stats()
    return {"queue": items, "stats": stats}


@router.post("/api/admin/suggestions/{suggestion_id}/review", tags=["ai-suggestion"])
@limiter.limit("20/minute")
async def api_review_suggestion(
    request: Request,
    suggestion_id: str,
    body: ReviewRequest,
    _=Depends(verify_api_key),
):
    """Approve or reject an AI mapping suggestion."""
    result = review_suggestion(
        suggestion_id=suggestion_id,
        decision=body.decision,
        reviewer=body.reviewer,
        override_azure_service=body.override_azure_service,
        override_confidence=body.override_confidence,
        notes=body.notes,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return {"status": body.decision, "suggestion": result}

