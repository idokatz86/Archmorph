from error_envelope import ArchmorphException
"""
Analysis routes — guided questions, apply answers, add services, export diagram.

Split from diagrams.py for maintainability (#284).
"""

from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel
from typing import Dict, Any
import asyncio
import logging

from routers.shared import SESSION_STORE, limiter, verify_api_key
from routers.samples import get_or_recreate_session
from usage_metrics import record_event, record_funnel_step
from guided_questions import generate_questions, apply_answers, get_question_constraints
from mcp_diagram_generator import mcp_client
from service_builder import deduplicate_questions, get_smart_defaults_from_analysis, add_services_from_text
from architecture_package import generate_architecture_package

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

    detected = [
        m["source_service"]["name"] if isinstance(m["source_service"], dict) else m["source_service"]
        for m in analysis.get("mappings", [])
    ]
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
        logger.error("Failed to add services for %s: %s", str(diagram_id).replace("\n", "").replace("\r", ""), str(exc).replace("\n", "").replace("\r", ""))  # lgtm[py/log-injection]
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
async def export_architecture_diagram(
    request: Request,
    diagram_id: str,
    format: str = "excalidraw",
    multi_page: bool = False,
    dr_variant: str = "primary",
):
    """Generate an architecture diagram in Excalidraw, Draw.io, Visio, or
    Landing-Zone-SVG format.

    Set multi_page=true for presentation-ready 4-page exports (Draw.io only, #479).
    Set format=landing-zone-svg + dr_variant=primary|dr for the region-aware
    landing-zone diagram (#571).

    Note (#576): the source provider for the landing-zone diagram is read
    implicitly from ``analysis["source_provider"]`` (allowed: "aws"|"gcp",
    default "aws"). It is intentionally NOT exposed as a query param so the
    frontend stays untouched and the analyzer pipeline remains the single
    source of truth. Unknown values raise ``ValueError`` → HTTP 400.
    """
    if format not in ("excalidraw", "drawio", "vsdx", "landing-zone-svg"):
        raise ArchmorphException(
            400,
            "Format must be 'excalidraw', 'drawio', 'vsdx', or 'landing-zone-svg'",
        )

    # dr_variant only applies to the landing-zone-svg format.
    if format != "landing-zone-svg" and dr_variant != "primary":
        raise ArchmorphException(
            400,
            "dr_variant is only valid when format='landing-zone-svg'",
        )
    if format == "landing-zone-svg" and dr_variant not in ("primary", "dr"):
        raise ArchmorphException(
            400,
            "dr_variant must be 'primary' or 'dr'",
        )

    analysis = get_or_recreate_session(diagram_id)
    if not analysis:
        raise ArchmorphException(404, f"No analysis found for diagram {diagram_id}. Run /analyze first.")

    if multi_page:
        analysis["multi_page"] = True

    # Landing-Zone-SVG path: synchronous, in-process, no MCP gateway round-trip.
    if format == "landing-zone-svg":
        try:
            from azure_landing_zone import generate_landing_zone_svg

            result = generate_landing_zone_svg(analysis, dr_variant=dr_variant)  # type: ignore[arg-type]
        except ValueError as exc:
            raise ArchmorphException(400, str(exc))
        record_event("exports_landing_zone_svg", {
            "diagram_id": diagram_id,
            "dr_variant": dr_variant,
        })
        record_funnel_step(diagram_id, "export")
        return result

    try:
        content = await mcp_client.generate_diagram(format, analysis)
        if not content or not isinstance(content, str) or not content.strip():
            # MCP gateway returned empty payload and the local fallback also
            # produced nothing usable. Fail loudly instead of writing an empty
            # file the user cannot open.
            raise ArchmorphException(502, "Diagram generation produced empty content")
        zones = analysis.get("zones", [])
        zone_name = zones[0].get("name", "diagram") if zones else "diagram"
        # Visio export uses the legacy VDX 2003 XML format (single XML file).
        # The on-disk extension must be ``.vdx`` — modern ``.vsdx`` is an
        # OOXML zip container, which Visio refuses if the bytes are raw XML.
        # The API ``format`` value remains ``"vsdx"`` for frontend stability.
        format_ext = "vdx" if format == "vsdx" else format
        result = {
            "format": format,
            "filename": f"archmorph-{zone_name}.{format_ext}",
            "content": content,
        }
    except ValueError as exc:
        raise ArchmorphException(400, str(exc))

    record_event(f"exports_{format}", {"diagram_id": diagram_id})
    record_funnel_step(diagram_id, "export")
    return result


# ─────────────────────────────────────────────────────────────
# Architecture Package Export (HTML / SVG)
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/export-architecture-package")
@limiter.limit("10/minute")
async def export_architecture_package(
    request: Request,
    diagram_id: str,
    format: str = "html",
    diagram: str = "primary",
):
    """Generate the customer-facing Architecture Package.

    format=html returns the full tabbed package. format=svg returns a single
    selected topology SVG where diagram=primary|dr.
    """
    if format not in ("html", "svg"):
        raise ArchmorphException(400, "Format must be 'html' or 'svg'")
    if diagram not in ("primary", "dr"):
        raise ArchmorphException(400, "diagram must be 'primary' or 'dr'")

    analysis = get_or_recreate_session(diagram_id)
    if not analysis:
        raise ArchmorphException(404, f"No analysis found for diagram {diagram_id}. Run /analyze first.")

    try:
        result = generate_architecture_package(
            analysis,
            format=format,  # type: ignore[arg-type]
            diagram=diagram,  # type: ignore[arg-type]
        )
    except ValueError as exc:
        raise ArchmorphException(400, str(exc))

    record_event("exports_architecture_package", {
        "diagram_id": diagram_id,
        "format": format,
        "diagram": diagram,
    })
    record_funnel_step(diagram_id, "export")
    return result
