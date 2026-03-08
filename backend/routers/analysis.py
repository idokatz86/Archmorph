from error_envelope import ArchmorphException
"""
Analysis routes — guided questions, apply answers, add services, export diagram.

Split from diagrams.py for maintainability (#284).
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from typing import Dict, Any
import asyncio
import logging

from routers.shared import SESSION_STORE, limiter, verify_api_key
from routers.samples import get_or_recreate_session
from usage_metrics import record_event, record_funnel_step
from guided_questions import generate_questions, apply_answers, get_question_constraints
from diagram_export import generate_diagram
from service_builder import deduplicate_questions, get_smart_defaults_from_analysis, add_services_from_text

logger = logging.getLogger(__name__)

router = APIRouter()


class AddServicesRequest(BaseModel):
    """Request body for natural language service additions."""
    text: str


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
        raise ArchmorphException(404, f"No analysis found for diagram {diagram_id}. Run /analyze first.")

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
        raise ArchmorphException(404, f"No analysis found for diagram {diagram_id}. Run /analyze first.")

    try:
        updated = await asyncio.to_thread(
            add_services_from_text,
            analysis=analysis,
            user_text=body.text,
        )
    except Exception as exc:
        logger.error("Failed to add services for %s: %s", diagram_id, exc)
        raise ArchmorphException(500, "Failed to process request. Please try again.")

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


# ─────────────────────────────────────────────────────────────
# Apply Guided Answers
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/apply-answers")
@limiter.limit("15/minute")
async def apply_guided_answers(request: Request, diagram_id: str, answers: Dict[str, Any]):
    """Apply user answers to refine the Azure architecture analysis."""
    analysis = get_or_recreate_session(diagram_id)
    if not analysis:
        raise ArchmorphException(404, f"No analysis found for diagram {diagram_id}. Run /analyze first.")

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
        raise ArchmorphException(400, "Format must be 'excalidraw', 'drawio', or 'vsdx'")

    analysis = get_or_recreate_session(diagram_id)
    if not analysis:
        raise ArchmorphException(404, f"No analysis found for diagram {diagram_id}. Run /analyze first.")

    try:
        result = generate_diagram(analysis, format)
    except ValueError as exc:
        raise ArchmorphException(400, str(exc))

    record_event(f"exports_{format}", {"diagram_id": diagram_id})
    record_funnel_step(diagram_id, "export")
    return result
