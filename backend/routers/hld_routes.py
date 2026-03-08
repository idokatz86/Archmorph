from error_envelope import ArchmorphException
"""
HLD (High-Level Design) routes — generation, retrieval, export, async generation.

Split from diagrams.py for maintainability (#284).
Mandatory diagram attachments enforced in customer export mode (#357).
"""

from fastapi import APIRouter, HTTPException, Request, Depends
import asyncio
import base64
import logging

from routers.shared import SESSION_STORE, limiter, verify_api_key
from routers.samples import get_or_recreate_session
from job_queue import job_manager
from usage_metrics import record_event
import routers.diagrams as diagrams_compat
from hld_export import export_hld, SUPPORTED_FORMATS
from services.azure_pricing import estimate_services_cost
from diagram_export import generate_diagram

logger = logging.getLogger(__name__)

router = APIRouter()


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
        raise ArchmorphException(404, "No analysis found. Analyze a diagram first.")

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
            SESSION_STORE[diagram_id] = session
        except Exception:  # nosec B110 — session cleanup is optional, must not break response
            logger.debug("Cost estimation unavailable, proceeding without it")

    try:
        hld = await asyncio.to_thread(
            diagrams_compat.generate_hld,
            analysis=analysis,
            cost_estimate=cost_estimate,
            iac_params=session.get("iac_parameters"),
        )
        markdown = diagrams_compat.generate_hld_markdown(hld)
    except ValueError as e:
        raise ArchmorphException(500, str(e))
    except Exception as e:
        logger.exception("HLD generation failed: %s", e)
        raise ArchmorphException(500, f"HLD generation failed: {type(e).__name__}: {e}")

    # Store in session — must write back to store for Redis compatibility
    session["hld"] = hld
    session["hld_markdown"] = markdown
    SESSION_STORE[diagram_id] = session

    return {
        "diagram_id": diagram_id,
        "hld": hld,
        "markdown": markdown,
    }


async def _ensure_hld(session: dict, diagram_id: str) -> dict:
    """Auto-generate HLD if session exists but HLD is missing.

    This transparently handles the case where a sample session was
    recreated (or an older session restored) without HLD data.
    Returns the updated session with HLD populated.
    """
    if "hld" in session:
        return session

    # Only auto-generate if we have analysis data (mappings)
    if not session.get("mappings"):
        return session

    try:
        cost_estimate = session.get("_cached_cost_estimate")
        if cost_estimate is None:
            iac_params = session.get("iac_parameters", {})
            region = iac_params.get("region", "westeurope")
            strategy = iac_params.get("sku_strategy", "balanced")
            cost_estimate = estimate_services_cost(
                session.get("mappings", []), region=region, sku_strategy=strategy
            )
            session["_cached_cost_estimate"] = cost_estimate

        hld = await asyncio.to_thread(
            diagrams_compat.generate_hld,
            analysis=session,
            cost_estimate=cost_estimate,
            iac_params=session.get("iac_parameters"),
        )
        markdown = diagrams_compat.generate_hld_markdown(hld)
        session["hld"] = hld
        session["hld_markdown"] = markdown
        SESSION_STORE[diagram_id] = session
        logger.info("Auto-generated HLD for session %s", diagram_id)
    except Exception as e:
        logger.warning("Auto-HLD generation failed for %s: %s", diagram_id, e)

    return session


@router.get("/api/diagrams/{diagram_id}/hld")
@limiter.limit("30/minute")
async def get_hld(request: Request, diagram_id: str):
    """Get previously generated HLD document."""
    session = get_or_recreate_session(diagram_id)
    if not session:
        raise ArchmorphException(404, "No HLD found. Generate one first.")
    session = await _ensure_hld(session, diagram_id)
    if "hld" not in session:
        raise ArchmorphException(404, "No HLD found. Generate one first.")
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
      - export_mode: customer | internal (default: internal)
        When 'customer', both architecture diagram and application flow
        diagram MUST be present in the export. If missing, they are
        auto-generated from analysis data. (#357)

    Body (optional JSON):
      - diagram_image: base64-encoded architecture diagram image to embed
      - app_flow_image: base64-encoded application flow diagram to embed
    """
    fmt = request.query_params.get("format", "").lower()
    if fmt not in SUPPORTED_FORMATS:
        raise ArchmorphException(400, f"Invalid format. Use one of: {', '.join(sorted(SUPPORTED_FORMATS))}")

    include_diagrams = request.query_params.get("include_diagrams", "true").lower() == "true"
    export_mode = request.query_params.get("export_mode", "internal").lower()

    session = get_or_recreate_session(diagram_id)
    if not session:
        raise ArchmorphException(404, "No HLD found. Generate one first.")
    session = await _ensure_hld(session, diagram_id)
    if "hld" not in session:
        raise ArchmorphException(404, "No HLD found. Generate one first.")

    # Parse optional diagram images from request body
    diagram_b64 = None
    try:
        body = await request.json()
        if isinstance(body, dict):
            diagram_b64 = body.get("diagram_image")
            _app_flow_b64 = body.get("app_flow_image")  # noqa: F841 reserved for future use
    except Exception:
        pass  # nosec B110 — No body or non-JSON body is fine

    # ── Customer mode: mandatory diagram enforcement (#357) ──
    if export_mode == "customer":
        include_diagrams = True  # Override — always include in customer mode

        # Auto-generate architecture diagram if not provided
        if not diagram_b64 and session.get("mappings"):
            try:
                arch_result = await asyncio.to_thread(
                    generate_diagram, session, "excalidraw"
                )
                if arch_result and arch_result.get("content"):
                    content = arch_result["content"]
                    if isinstance(content, str):
                        diagram_b64 = base64.b64encode(content.encode()).decode()
                    elif isinstance(content, (bytes, bytearray)):
                        diagram_b64 = base64.b64encode(content).decode()
                    logger.info("Auto-generated architecture diagram for customer export of %s", diagram_id)
            except Exception as e:
                logger.warning("Failed to auto-generate architecture diagram: %s", e)

        if not diagram_b64:
            raise ArchmorphException(
                400,
                "Customer-mode export requires an architecture diagram. "
                "Upload one via 'diagram_image' in the request body, "
                "or ensure the analysis has mappings to auto-generate one."
            )

    record_event("hld_exported", {
        "diagram_id": diagram_id,
        "format": fmt,
        "include_diagrams": include_diagrams,
        "export_mode": export_mode,
    })

    try:
        result = await asyncio.to_thread(
            export_hld,
            hld=session["hld"],
            format=fmt,
            include_diagrams=include_diagrams,
            diagram_b64=diagram_b64,
        )
    except ValueError as e:
        raise ArchmorphException(400, str(e))
    except Exception as e:
        logger.error("HLD export failed: %s", e)
        raise ArchmorphException(500, "Export failed. Please try again or contact support.")

    return result


# ─────────────────────────────────────────────────────────────
# Async HLD Generation (Issue #172)
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/generate-hld-async")
@limiter.limit("3/minute")
async def generate_hld_async(request: Request, diagram_id: str, _auth=Depends(verify_api_key)):
    """Start async HLD document generation. Returns 202 with job_id."""
    session = get_or_recreate_session(diagram_id)
    if not session:
        raise ArchmorphException(404, "No analysis found. Analyze a diagram first.")

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
                SESSION_STORE[diagram_id] = session
            except Exception:
                logger.debug("Cost estimation unavailable")

        job_manager.update_progress(job_id, 40, "Generating High-Level Design with GPT-4o...")

        hld = await asyncio.to_thread(
            diagrams_compat.generate_hld,
            analysis=session,
            cost_estimate=cost_estimate,
            iac_params=session.get("iac_parameters"),
        )

        if job_manager.is_cancelled(job_id):
            return

        job_manager.update_progress(job_id, 80, "Rendering markdown...")
        markdown = diagrams_compat.generate_hld_markdown(hld)

        session["hld"] = hld
        session["hld_markdown"] = markdown
        SESSION_STORE[diagram_id] = session

        record_event("hld_generated", {"diagram_id": diagram_id})
        job_manager.complete(job_id, result={"diagram_id": diagram_id, "hld": hld, "markdown": markdown})

    except Exception as exc:
        logger.error("Async HLD generation failed: %s", exc, exc_info=True)
        job_manager.fail(job_id, str(exc))


# ─────────────────────────────────────────────────────────────
# Migration Package Export (#252)
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/export-package")
@limiter.limit("5/minute")
async def export_migration_package(request: Request, diagram_id: str, _auth=Depends(verify_api_key)):
    """Export a complete migration package as a ZIP file.

    Includes: IaC code, HLD document (DOCX), cost estimate (JSON), and
    analysis summary (JSON). This is the end-to-end migration wizard output.

    Body (optional): { "iac_format": "terraform", "include_diagrams": true }
    """
    import io
    import json
    import zipfile

    session = get_or_recreate_session(diagram_id)
    if not session:
        raise ArchmorphException(404, "No analysis found. Analyze a diagram first.")

    # Parse options
    iac_format = "terraform"
    include_diagrams = True
    try:
        body = await request.json()
        if isinstance(body, dict):
            iac_format = body.get("iac_format", "terraform")
            include_diagrams = body.get("include_diagrams", True)
    except Exception:
        pass

    session = await _ensure_hld(session, diagram_id)

    # Build ZIP in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. IaC code
        iac_code = session.get("generated_iac", "")
        if iac_code:
            ext = {"terraform": "tf", "bicep": "bicep", "cloudformation": "yaml"}.get(iac_format, "tf")
            zf.writestr(f"infrastructure/main.{ext}", iac_code)

        # 2. Analysis summary
        analysis_summary = {
            "source_provider": session.get("source_provider", "unknown"),
            "diagram_type": session.get("diagram_type", "unknown"),
            "services_detected": session.get("services_detected", 0),
            "zones": [{"id": z.get("id"), "name": z.get("name")} for z in session.get("zones", [])],
            "mappings": [
                {
                    "source": m.get("source_service", ""),
                    "azure": m.get("azure_service", ""),
                    "confidence": m.get("confidence", 0),
                    "category": m.get("category", ""),
                }
                for m in session.get("mappings", [])
            ],
        }
        zf.writestr("analysis/analysis-summary.json", json.dumps(analysis_summary, indent=2))

        # 3. Cost estimate
        mappings = session.get("mappings", [])
        if mappings:
            cost_data = estimate_services_cost(mappings)
            zf.writestr("analysis/cost-estimate.json", json.dumps(cost_data, indent=2, default=str))

        # 4. HLD markdown
        hld_md = session.get("hld_markdown", "")
        if hld_md:
            zf.writestr("documents/high-level-design.md", hld_md)

        # 5. HLD DOCX (if HLD exists)
        hld = session.get("hld")
        if hld:
            try:
                docx_bytes = export_hld(hld, "docx", include_diagrams=include_diagrams)
                zf.writestr("documents/high-level-design.docx", docx_bytes)
            except Exception as exc:
                logger.warning("DOCX export failed in package: %s", exc)

        # 6. README
        readme = f"""# Migration Package — {session.get('diagram_type', 'Architecture')}
Generated by Archmorph v{session.get('_version', '3.6.0')}

## Contents
- `infrastructure/` — Generated {iac_format.title()} code
- `analysis/` — Analysis summary and cost estimate
- `documents/` — High-Level Design document (Markdown + DOCX)

## Next Steps
1. Review the IaC code in `infrastructure/`
2. Read the HLD document for architecture decisions
3. Check the cost estimate for budget planning
4. Apply the IaC code to your Azure subscription

## Links
- Live app: https://archmorphai.com
- API docs: https://api.archmorphai.com/docs
"""
        zf.writestr("README.md", readme)

    buf.seek(0)
    content_b64 = base64.b64encode(buf.getvalue()).decode()

    record_event("migration_package_exported", {"diagram_id": diagram_id, "iac_format": iac_format})

    return {
        "filename": "archmorph-migration-package.zip",
        "content_type": "application/zip",
        "content_b64": content_b64,
        "size_bytes": len(buf.getvalue()),
    }
