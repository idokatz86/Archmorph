"""
Diagram routes — upload, analyze, questions, services, export, IaC, HLD,
best-practices, cost-optimization, share, IaC-chat, terraform-preview.
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Query, Response, Request, Depends
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import asyncio
import uuid
import logging

from routers.shared import (
    SESSION_STORE, IMAGE_STORE, SHARE_STORE,
    limiter, verify_api_key, MAX_UPLOAD_SIZE,
)
from usage_metrics import record_event, record_funnel_step
from guided_questions import generate_questions, apply_answers
from diagram_export import generate_diagram
from iac_chat import process_iac_chat, get_iac_chat_history, clear_iac_chat
from iac_generator import generate_iac_code
from hld_generator import generate_hld, generate_hld_markdown
from image_classifier import classify_image
from vision_analyzer import analyze_image
from service_builder import deduplicate_questions, get_smart_defaults_from_analysis, add_services_from_text
from services.azure_pricing import estimate_services_cost
from hld_export import export_hld, SUPPORTED_FORMATS
from best_practices import analyze_architecture, get_quick_wins
from cost_optimizer import analyze_cost_optimizations
from terraform_preview import preview_terraform_plan

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
    format: str = Field(default="terraform", pattern="^(terraform|bicep)$")


class TerraformValidateRequest(BaseModel):
    code: str


# ─────────────────────────────────────────────────────────────
# Diagrams — Upload & Analyze
# ─────────────────────────────────────────────────────────────
@router.post("/api/projects/{project_id}/diagrams")
@limiter.limit("10/minute")
async def upload_diagram(request: Request, project_id: str, file: UploadFile = File(...), _auth=Depends(verify_api_key)):
    # Validate file type
    allowed_types = ["image/png", "image/jpeg", "image/svg+xml", "application/pdf"]
    if file.content_type not in allowed_types:
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

    record_event("diagrams_uploaded", {"filename": file.filename})
    record_funnel_step(diagram_id, "upload")
    return {
        "diagram_id": diagram_id,
        "filename": file.filename,
        "size": len(image_bytes),
        "status": "uploaded"
    }


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

    # ── Image classification pre-check (async) ──
    try:
        classification = await asyncio.to_thread(classify_image, image_bytes, content_type)
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
        result = await asyncio.to_thread(analyze_image, image_bytes, content_type)
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
async def get_guided_questions(diagram_id: str, smart_dedup: bool = True):
    """Generate guided questions based on detected AWS services.
    
    If smart_dedup=True, questions that have been implicitly answered
    by user context (e.g., natural language additions) are filtered out.
    """
    analysis = SESSION_STORE.get(diagram_id)
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
    analysis = SESSION_STORE.get(diagram_id)
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
async def apply_guided_answers(diagram_id: str, answers: Dict[str, Any]):
    """Apply user answers to refine the Azure architecture analysis."""
    analysis = SESSION_STORE.get(diagram_id)
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
async def export_architecture_diagram(diagram_id: str, format: str = "excalidraw"):
    """Generate an architecture diagram in Excalidraw, Draw.io, or Visio format."""
    if format not in ("excalidraw", "drawio", "vsdx"):
        raise HTTPException(400, "Format must be 'excalidraw', 'drawio', or 'vsdx'")

    analysis = SESSION_STORE.get(diagram_id)
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
    if format not in ["terraform", "bicep"]:
        raise HTTPException(400, "Format must be 'terraform' or 'bicep'")

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
async def estimate_cost(diagram_id: str):
    record_event("cost_estimates", {"diagram_id": diagram_id})

    session = SESSION_STORE.get(diagram_id, {})
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
async def iac_chat_history(diagram_id: str):
    """Get IaC chat history for a diagram."""
    return {
        "diagram_id": diagram_id,
        "messages": get_iac_chat_history(diagram_id),
    }


@router.delete("/api/diagrams/{diagram_id}/iac-chat")
async def iac_chat_clear(diagram_id: str):
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

    session = SESSION_STORE.get(diagram_id)
    if not session:
        raise HTTPException(404, "No analysis found. Analyze a diagram first.")

    analysis = session

    # Get cost estimate if available
    cost_estimate = None
    try:
        iac_params = session.get("iac_parameters", {})
        region = iac_params.get("region", "westeurope")
        strategy = iac_params.get("sku_strategy", "balanced")
        cost_estimate = estimate_services_cost(analysis.get("mappings", []), region=region, sku_strategy=strategy)
    except Exception:  # nosec B110
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

    # Store in session
    session["hld"] = hld
    session["hld_markdown"] = markdown

    return {
        "diagram_id": diagram_id,
        "hld": hld,
        "markdown": markdown,
    }


@router.get("/api/diagrams/{diagram_id}/hld")
async def get_hld(diagram_id: str):
    """Get previously generated HLD document."""
    session = SESSION_STORE.get(diagram_id)
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

    session = SESSION_STORE.get(diagram_id)
    if not session or "hld" not in session:
        raise HTTPException(404, "No HLD found. Generate one first.")

    # Optional diagram image from request body
    diagram_b64 = None
    try:
        body = await request.json()
        diagram_b64 = body.get("diagram_image") if isinstance(body, dict) else None
    except Exception:
        pass  # No body or non-JSON body is fine

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
async def get_best_practices(diagram_id: str):
    """Analyze architecture against Azure Well-Architected Framework."""
    analysis = SESSION_STORE.get(diagram_id)
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
async def get_cost_optimization(diagram_id: str):
    """Get cost optimization recommendations for the architecture."""
    analysis = SESSION_STORE.get(diagram_id)
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
async def create_share_link(diagram_id: str):
    """Create a shareable read-only link for analysis results."""
    analysis = SESSION_STORE.get(diagram_id)
    if not analysis:
        raise HTTPException(404, "Analysis not found")
    
    share_id = f"share-{uuid.uuid4().hex[:10]}"
    
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
async def get_shared_analysis(share_id: str):
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
# Terraform Plan Preview
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/terraform-preview")
async def preview_terraform_plan_endpoint(diagram_id: str):
    """Generate a preview of what Terraform would create."""
    analysis = SESSION_STORE.get(diagram_id)
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
    
    result = preview_terraform_plan(iac_code, diagram_id)
    
    return result.to_dict()
