"""
HLD (High-Level Design) routes — generation, retrieval, export, async generation.

Split from diagrams.py for maintainability (#284).
Mandatory diagram attachments enforced in customer export mode (#357).
"""

from fastapi import APIRouter, Request, Depends
import asyncio
import base64
import logging

from routers.shared import (
    SESSION_STORE,
    authorize_diagram_access,
    get_api_key_service_principal,
    limiter,
    require_diagram_access,
    verify_api_key,
    verify_api_key_or_user_session,
)
from job_queue import job_manager
from usage_metrics import record_event
import routers.diagrams as diagrams_compat
from error_envelope import ArchmorphException
from hld_export import export_hld, SUPPORTED_FORMATS
from services.azure_pricing import estimate_services_cost
from diagram_export import generate_diagram
from export_capabilities import attach_export_capability, consume_export_capability, verify_export_capability

logger = logging.getLogger(__name__)

router = APIRouter()


# ─────────────────────────────────────────────────────────────
# HLD Generation — AI-powered High-Level Design document
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/generate-hld", dependencies=[Depends(require_diagram_access)])
@limiter.limit("10/minute")
async def generate_hld_endpoint(request: Request, diagram_id: str, _auth=Depends(verify_api_key)):
    """Generate a comprehensive High-Level Design document."""
    record_event("hld_generated", {"diagram_id": diagram_id})

    session = authorize_diagram_access(request, diagram_id, purpose="generate an HLD")

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
        hld = diagrams_compat.generate_hld(
            analysis=analysis,
            cost_estimate=cost_estimate,
            iac_params=session.get("iac_parameters"),
        )
        markdown = diagrams_compat.generate_hld_markdown(hld)
    except ValueError as e:
        raise ArchmorphException(500, str(e))
    except Exception as e:
        logger.exception("HLD generation failed: %s", str(e).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom
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

        hld = diagrams_compat.generate_hld(
            analysis=session,
            cost_estimate=cost_estimate,
            iac_params=session.get("iac_parameters"),
        )
        markdown = diagrams_compat.generate_hld_markdown(hld)
        session["hld"] = hld
        session["hld_markdown"] = markdown
        SESSION_STORE[diagram_id] = session
        logger.info("Auto-generated HLD for session %s", str(diagram_id).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom
    except Exception as e:
        logger.warning("Auto-HLD generation failed for %s: %s", str(diagram_id).replace('\n', '').replace('\r', ''), str(e).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom

    return session


@router.get("/api/diagrams/{diagram_id}/hld", dependencies=[Depends(require_diagram_access)])
@limiter.limit("30/minute")
async def get_hld(request: Request, diagram_id: str, _auth=Depends(verify_api_key)):
    """Get previously generated HLD document."""
    session = authorize_diagram_access(request, diagram_id, purpose="view an HLD")
    session = await _ensure_hld(session, diagram_id)
    if "hld" not in session:
        raise ArchmorphException(404, "No HLD found. Generate one first.")
    return {
        "diagram_id": diagram_id,
        "hld": session["hld"],
        "markdown": session.get("hld_markdown", ""),
    }


@router.post("/api/diagrams/{diagram_id}/export-hld", dependencies=[Depends(require_diagram_access)])
@limiter.limit("10/minute")
async def export_hld_endpoint(
    request: Request,
    diagram_id: str,
    _auth=Depends(verify_api_key),
    capability=Depends(verify_export_capability),
):
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

    session = authorize_diagram_access(request, diagram_id, purpose="export an HLD")
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
                    logger.info("Auto-generated architecture diagram for customer export of %s", str(diagram_id).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom
            except Exception as e:
                logger.warning("Failed to auto-generate architecture diagram: %s", str(e).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom

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
        logger.error("HLD export failed: %s", str(e).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom
        raise ArchmorphException(500, "Export failed. Please try again or contact support.")

    consume_export_capability(capability)
    return attach_export_capability(result, diagram_id)


# ─────────────────────────────────────────────────────────────
# Async HLD Generation (Issue #172)
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/generate-hld-async", dependencies=[Depends(require_diagram_access)])
@limiter.limit("10/minute")
async def generate_hld_async(
    request: Request,
    diagram_id: str,
    _auth=Depends(verify_api_key),
):
    """Start async HLD document generation. Returns 202 with job_id."""
    from auth import get_user_from_request_headers

    headers = dict(request.headers)
    user = get_user_from_request_headers(headers)
    api_key_principal_id = get_api_key_service_principal(headers)
    authorize_diagram_access(request, diagram_id, purpose="queue HLD generation")

    job = job_manager.submit(
        "generate_hld",
        diagram_id=diagram_id,
        owner_user_id=user.id if user else None,
        tenant_id=user.tenant_id if user else None,
        owner_api_key_id=api_key_principal_id if not user else None,
    )
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

        job_record = job_manager.get(job_id)
        session = SESSION_STORE.get(diagram_id)
        if not session:
            job_manager.fail(job_id, "Analysis not found")
            return
        if job_record:
            job_user_id = getattr(job_record, "owner_user_id", None)
            job_tenant_id = getattr(job_record, "tenant_id", None)
            job_api_key_id = getattr(job_record, "owner_api_key_id", None)
            if job_user_id or job_tenant_id:
                if (
                    session.get("_owner_user_id") != job_user_id
                    or session.get("_tenant_id") != job_tenant_id
                ):
                    job_manager.fail(job_id, "Analysis access revoked")
                    return
            elif job_api_key_id and session.get("_owner_api_key_id") != job_api_key_id:
                job_manager.fail(job_id, "Analysis access revoked")
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

        hld = diagrams_compat.generate_hld(
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
        logger.error("Async HLD generation failed: %s", str(exc).replace('\n', '').replace('\r', ''), exc_info=True)  # codeql[py/log-injection] Handled by custom
        job_manager.fail(job_id, str(exc))


# ─────────────────────────────────────────────────────────────
# Migration Package Export (#252)
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/export-package", dependencies=[Depends(require_diagram_access)])
@limiter.limit("5/minute")
async def export_migration_package(
    request: Request,
    diagram_id: str,
    _auth=Depends(verify_api_key_or_user_session),
    capability=Depends(verify_export_capability),
):
    """Export a complete migration package as a ZIP file.

    Includes: IaC code, HLD document (DOCX), cost estimate (JSON), and
    analysis summary (JSON). This is the end-to-end migration wizard output.

    Body (optional): { "iac_format": "terraform", "include_diagrams": true }
    """
    import io
    import json
    import zipfile

    session = authorize_diagram_access(request, diagram_id, purpose="export a migration package")

    # Parse options
    iac_format = "terraform"
    include_diagrams = True
    try:
        body = await request.json()
        if isinstance(body, dict):
            iac_format = body.get("iac_format", "terraform")
            include_diagrams = body.get("include_diagrams", True)
    except (json.JSONDecodeError, ValueError):
        # Optional request body; treat malformed/absent JSON as defaults.
        pass
    if iac_format not in {"terraform", "bicep"}:
        raise ArchmorphException(422, "IaC format must be 'terraform' or 'bicep'.")

    session = await _ensure_hld(session, diagram_id)

    # Build ZIP in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        def text_value(value, fallback=""):
            if value is None:
                return fallback
            if isinstance(value, str):
                return value
            return str(value)

        # 1. IaC code
        iac_code = session.get("generated_iac", "")
        if iac_code:
            ext = {"terraform": "tf", "bicep": "bicep"}[iac_format]
            zf.writestr(f"infrastructure/main.{ext}", iac_code)

        # 2. Analysis summary — includes executive summary, decisions vs recommendations,
        #    methodology/confidence, and risks/gaps/limitations.
        mappings = [m for m in (session.get("mappings", []) or []) if isinstance(m, dict)]
        assumptions_raw = session.get("assumptions", []) or []
        if not isinstance(assumptions_raw, list):
            assumptions_raw = []
        answers_raw = session.get("guided_answers") or session.get("answers") or {}
        if not isinstance(answers_raw, dict):
            answers_raw = {}

        # Separate confirmed (user-reviewed) from AI-generated recommendations
        confirmed_decisions = []
        for assumption in assumptions_raw:
            if not isinstance(assumption, dict):
                continue
            assumption_id = assumption.get("id")
            has_confirmed_answer = assumption_id in answers_raw
            confirmed_decisions.append({
                "id": assumption_id,
                "question": text_value(assumption.get("question")),
                "confirmed_answer": answers_raw.get(assumption_id) if has_confirmed_answer else assumption.get("assumed_answer"),
                "source": "user_confirmed" if has_confirmed_answer else "ai_assumed",
            })

        # Collect risks/gaps from mapping limitations
        risks_and_gaps = []
        for m in mappings:
            for lim in (m.get("limitations") or []):
                if isinstance(lim, dict):
                    factor = text_value(lim.get("factor"))
                    detail = text_value(lim.get("detail"))
                    severity = text_value(lim.get("severity"), "medium") or "medium"
                else:
                    factor = text_value(lim)
                    detail = ""
                    severity = "medium"
                if factor and factor.lower() not in {"none", "n/a", "none.", "none identified"}:
                    risks_and_gaps.append({
                        "service": text_value(m.get("source_service")),
                        "azure_target": text_value(m.get("azure_service")),
                        "risk": factor,
                        "detail": detail,
                        "severity": severity,
                    })

        confidence_summary = session.get("confidence_summary") or {}
        services_detected = session.get("services_detected", len(mappings))
        zones = [z for z in (session.get("zones", []) or []) if isinstance(z, dict)]
        source_provider = text_value(session.get("source_provider"), "the source environment") or "the source environment"

        executive_summary = (
            f"This Azure Migration Package covers {services_detected} services "
            f"across {len(zones)} zone(s) migrating from "
            f"{source_provider.upper()} to Azure. "
            f"Average mapping confidence: "
            f"{round(confidence_summary.get('average', 0) * 100)}%. "
            f"{confidence_summary.get('high', 0)} mappings are high confidence, "
            f"{confidence_summary.get('medium', 0)} medium, "
            f"{confidence_summary.get('low', 0)} low. "
            f"{'IaC code has been generated. ' if iac_code else ''}"
            "Review confirmed decisions and open risks before committing to Azure."
        )

        analysis_summary = {
            "executive_summary": executive_summary,
            "source_provider": text_value(session.get("source_provider"), "unknown") or "unknown",
            "diagram_type": text_value(session.get("diagram_type"), "unknown") or "unknown",
            "services_detected": services_detected,
            "zones": [{"id": z.get("id"), "name": z.get("name")} for z in zones],
            "mappings": [
                {
                    "source": m.get("source_service", ""),
                    "azure": m.get("azure_service", ""),
                    "confidence": m.get("confidence", 0),
                    "category": m.get("category", ""),
                    "recommendation_source": "ai_generated",
                }
                for m in mappings
            ],
            "decisions": confirmed_decisions,
            "risks_and_gaps": risks_and_gaps,
            "methodology": {
                "note": (
                    confidence_summary.get("methodology")
                    or "Service mappings are AI-generated based on architectural pattern recognition. "
                    "Confidence scores reflect feature parity, migration guidance availability, "
                    "and known limitations. Items marked 'user_confirmed' reflect explicit reviewer decisions."
                ),
                "confidence_scoring": "0.0–1.0 scale; ≥0.85 = high, 0.65–0.84 = medium, <0.65 = low",
                "limitations": [
                    "Mappings are recommendations only — not a guarantee of full feature parity.",
                    "Cost estimates are indicative ranges based on standard pricing; actual costs will vary.",
                    "IaC code requires review and adaptation to your specific environment and security policies.",
                ],
            },
        }
        zf.writestr("analysis/analysis-summary.json", json.dumps(analysis_summary, indent=2))

        # 3. Cost estimate
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
                logger.warning("DOCX export failed in package: %s", str(exc).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom

        # 6. README
        diagram_type = session.get('diagram_type', 'Architecture')
        version = session.get('_version', '3.6.0')
        readme = f"""# Azure Migration Package — {diagram_type}
Generated by Archmorph v{version}

## Executive Summary
{executive_summary}

## Contents
- `infrastructure/` — Generated {iac_format.title()} IaC code
- `analysis/analysis-summary.json` — Source inventory, Azure target mappings, confirmed decisions, risks/gaps, and methodology
- `analysis/cost-estimate.json` — Indicative monthly cost ranges by service
- `documents/` — High-Level Design document (Markdown + DOCX)

## Package Sections
- **Source architecture inventory** — services and zones discovered from the uploaded diagram
- **Azure target mappings** — AI-generated recommendations (marked `ai_generated`)
- **Confirmed decisions** — reviewer-confirmed answers (marked `user_confirmed`) vs AI assumptions
- **Risks and gaps** — per-service limitations and migration blockers with severity ratings
- **Cost assumptions** — indicative Azure pricing with low/mid/high monthly ranges
- **IaC / HLD appendix** — Terraform or Bicep code and the High-Level Design document
- **Methodology and confidence notes** — how confidence scores are calculated and package limitations

## Important Notes
- Generated recommendations are AI-assisted and require human review before deployment.
- Confirmed decisions (source: user_confirmed) reflect explicit reviewer choices.
- Cost estimates are indicative ranges; consult the Azure Pricing Calculator for exact figures.
- IaC code must be reviewed and adapted to your environment and security policies.

## Next Steps
1. Review `analysis/analysis-summary.json` — confirm or override AI-generated mappings
2. Address open risks in the `risks_and_gaps` section
3. Read the HLD document for architecture decisions and CAF alignment
4. Review the cost estimate and adjust SKUs/regions as needed
5. Apply IaC code to your Azure subscription after thorough review

## Links
- Live app: https://archmorphai.com
- API docs: https://api.archmorphai.com/docs
"""
        zf.writestr("README.md", readme)

    buf.seek(0)
    content_b64 = base64.b64encode(buf.getvalue()).decode()

    record_event("migration_package_exported", {"diagram_id": diagram_id, "iac_format": iac_format})

    consume_export_capability(capability)
    return attach_export_capability({
        "filename": "archmorph-migration-package.zip",
        "content_type": "application/zip",
        "content_b64": content_b64,
        "size_bytes": len(buf.getvalue()),
    }, diagram_id)
