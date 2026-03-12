from utils.logger_utils import sanitize_log
from error_envelope import ArchmorphException
"""
Insights routes — best practices, cost estimation, cost optimization,
risk score, compliance, terraform preview.

Split from diagrams.py for maintainability (#284).
"""

from fastapi import APIRouter, Request, Depends
import asyncio
import logging

from routers.shared import limiter, verify_api_key
from routers.samples import get_or_recreate_session
from usage_metrics import record_event
from best_practices import analyze_architecture, get_quick_wins
from cost_optimizer import analyze_cost_optimizations
from services.azure_pricing import estimate_services_cost
from terraform_preview import preview_terraform_plan
from migration_risk import compute_risk_score
from compliance_mapper import assess_compliance
from iac_generator import generate_iac_code

logger = logging.getLogger(__name__)

router = APIRouter()


# ─────────────────────────────────────────────────────────────
# Cost Estimation
# ─────────────────────────────────────────────────────────────
@router.get("/api/diagrams/{diagram_id}/cost-estimate")
@limiter.limit("15/minute")
async def estimate_cost(request: Request, diagram_id: str):
    """Estimate monthly Azure costs for the analysed architecture."""
    record_event("cost_estimates", {"diagram_id": diagram_id})

    session = get_or_recreate_session(diagram_id)
    if not session:
        raise ArchmorphException(404, "No analysis found. Analyze a diagram first.")

    mappings = session.get("mappings", [])
    iac_params = session.get("iac_parameters", {})

    # Get region from guided-question answers or iac_parameters
    region = iac_params.get("deploy_region", "westeurope")
    sku_strategy = iac_params.get("sku_strategy", "Balanced")

    if mappings:
        result = estimate_services_cost(mappings, region=region, sku_strategy=sku_strategy)
        result["diagram_id"] = diagram_id
        return result

    # Fallback: return structure-compatible empty estimate
    return {
        "diagram_id": diagram_id,
        "total_monthly_estimate": {"low": 0, "high": 0},
        "currency": "USD",
        "region": "West Europe",
        "arm_region": region,
        "services": [],
        "service_count": 0,
        "pricing_source": "no analysis available",
    }


# ─────────────────────────────────────────────────────────────
# Enriched Cost Breakdown (#403)
# ─────────────────────────────────────────────────────────────
@router.get("/api/diagrams/{diagram_id}/cost-breakdown")
@limiter.limit("15/minute")
async def cost_breakdown(request: Request, diagram_id: str):
    """Return enriched cost data for the Pricing tab.

    Includes per-service formula, assumptions, alternative SKUs,
    optimization recommendations, cost-by-category, and source vs
    target comparison.
    """
    record_event("cost_breakdown", {"diagram_id": diagram_id})

    session = get_or_recreate_session(diagram_id)
    if not session:
        raise ArchmorphException(404, "No analysis found. Analyze a diagram first.")

    mappings = session.get("mappings", [])
    iac_params = session.get("iac_parameters", {})
    answers = session.get("applied_answers", {})
    region = iac_params.get("deploy_region", "westeurope")
    sku_strategy = iac_params.get("sku_strategy", "Balanced")

    # Base cost estimate
    if mappings:
        cost_data = estimate_services_cost(mappings, region=region, sku_strategy=sku_strategy)
    else:
        cost_data = {"services": [], "total_monthly_estimate": {"low": 0, "high": 0}}

    services = cost_data.get("services", [])

    # Enrich each service with formula, assumptions, and alternatives
    enriched_services = []
    category_costs = {}
    total_low = 0
    total_high = 0

    for svc in services:
        low = svc.get("monthly_low", 0) or 0
        high = svc.get("monthly_high", 0) or 0
        mid = (low + high) / 2
        total_low += low
        total_high += high

        category = svc.get("category", "Other")
        category_costs[category] = category_costs.get(category, 0) + mid

        # Price source and formula
        price_source = svc.get("price_source", "Azure Retail Prices API")
        formula = svc.get("formula", "")
        assumptions = svc.get("assumptions", [])
        if not formula and high > 0:
            formula = f"Estimated ${low:,.0f}–${high:,.0f}/month based on {price_source}"
        if not assumptions:
            assumptions = [
                f"Region: {region}",
                f"SKU strategy: {sku_strategy}",
                "Pay-as-you-go pricing (no reservations)",
                "730 hours/month",
            ]

        # Alternative SKU suggestions
        alternatives = []
        if high > 100:
            alternatives.append({
                "sku": "Reserved 1-year",
                "monthly": round(mid * 0.65, 2),
                "savings": "35%",
                "tradeoff": "Requires 1-year commitment",
            })
            alternatives.append({
                "sku": "Reserved 3-year",
                "monthly": round(mid * 0.50, 2),
                "savings": "50%",
                "tradeoff": "Requires 3-year commitment",
            })
        if "compute" in category.lower() or "virtual" in svc.get("service", "").lower():
            alternatives.append({
                "sku": "Spot Instance",
                "monthly": round(mid * 0.15, 2),
                "savings": "up to 85%",
                "tradeoff": "Can be evicted with 30s notice; for fault-tolerant workloads only",
            })

        enriched_services.append({
            **svc,
            "monthly_mid": round(mid, 2),
            "price_source": price_source,
            "formula": formula,
            "assumptions": assumptions,
            "alternatives": alternatives,
        })

    # Sort by cost (highest first)
    enriched_services.sort(key=lambda s: s.get("monthly_mid", 0), reverse=True)

    # Cost drivers — top 3 most expensive
    cost_drivers = []
    for svc in enriched_services[:3]:
        if svc.get("monthly_mid", 0) > 0:
            pct = (svc["monthly_mid"] / ((total_low + total_high) / 2) * 100) if (total_low + total_high) > 0 else 0
            cost_drivers.append({
                "service": svc.get("service", ""),
                "monthly_mid": svc["monthly_mid"],
                "percentage": round(pct, 1),
                "reason": f"Highest cost contributor at ~${svc['monthly_mid']:,.0f}/mo ({pct:.0f}% of total)",
            })

    # Optimization recommendations from cost_optimizer
    optimizations = []
    try:
        opt_result = await asyncio.to_thread(analyze_cost_optimizations, session, answers, cost_data)
        for opt in opt_result.get("optimizations", []):
            optimizations.append({
                "title": opt.get("title", ""),
                "description": opt.get("description", ""),
                "savings": opt.get("estimated_savings", ""),
                "effort": opt.get("effort", "medium"),
                "services_affected": opt.get("services_affected", []),
                "action_steps": opt.get("action_steps", []),
                "azure_doc_link": opt.get("azure_doc_link", ""),
            })
    except Exception:
        logger.warning("Cost optimization analysis failed for %s", sanitize_log(diagram_id))  # lgtm[py/log-injection]

    # Source vs target comparison (rough estimate: source typically 10-20% more)
    total_mid = (total_low + total_high) / 2
    source_estimate = round(total_mid * 1.12, 2)  # Conservative: Azure ~12% cheaper than AWS/GCP on average
    savings_pct = round((1 - total_mid / source_estimate) * 100, 1) if source_estimate > 0 else 0

    # Region impact — show cheapest region vs current
    region_impact = None
    cheapest_regions = ["eastus", "eastus2", "centralus", "westus2"]
    if region not in cheapest_regions:
        region_impact = {
            "current_region": region,
            "current_monthly": round(total_mid, 2),
            "cheapest_region": "eastus",
            "cheapest_monthly": round(total_mid * 0.92, 2),
            "potential_savings": f"{round((1 - 0.92) * 100)}%",
            "note": "US East regions are typically 5-10% cheaper than European regions.",
        }

    return {
        "diagram_id": diagram_id,
        "summary": {
            "total_monthly": {
                "low": round(total_low, 2),
                "mid": round(total_mid, 2),
                "high": round(total_high, 2),
            },
            "currency": "USD",
            "region": cost_data.get("region", "West Europe"),
            "arm_region": region,
            "service_count": len(enriched_services),
        },
        "services": enriched_services,
        "cost_drivers": cost_drivers,
        "optimizations": optimizations,
        "cost_by_category": category_costs,
        "source_comparison": {
            "source_provider": session.get("source_provider", "aws"),
            "source_monthly_estimate": source_estimate,
            "target_monthly_estimate": round(total_mid, 2),
            "savings_percentage": savings_pct,
            "note": "Source cost is an approximation based on equivalent service pricing.",
        },
        "region_impact": region_impact,
        "pricing_assumptions": [
            "Prices from Azure Retail Prices API (cached 24h)",
            "Pay-as-you-go pricing unless otherwise noted",
            "730 hours/month for always-on resources",
            f"Region: {region}",
            f"SKU strategy: {sku_strategy}",
            "Does not include data transfer, support plans, or tax",
            "Reserved Instance and Spot prices shown as alternatives",
        ],
    }


# ─────────────────────────────────────────────────────────────
# Best Practices & WAF Analysis
# ─────────────────────────────────────────────────────────────
@router.get("/api/diagrams/{diagram_id}/best-practices")
@limiter.limit("30/minute")
async def get_best_practices(request: Request, diagram_id: str):
    """Analyze architecture against Azure Well-Architected Framework."""
    analysis = get_or_recreate_session(diagram_id)
    if not analysis:
        raise ArchmorphException(404, "Analysis not found")

    answers = analysis.get("applied_answers", {})

    result = await asyncio.to_thread(analyze_architecture, analysis, answers)
    result["quick_wins"] = await asyncio.to_thread(get_quick_wins, result["recommendations"])

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
        raise ArchmorphException(404, "Analysis not found")

    answers = analysis.get("applied_answers", {})
    cost_estimate = analysis.get("cost_estimate")

    return await asyncio.to_thread(analyze_cost_optimizations, analysis, answers, cost_estimate)


# ─────────────────────────────────────────────────────────────
# Terraform Plan Preview (Issue #122 / #123)
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
        raise ArchmorphException(404, "Analysis not found")

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
            raise ArchmorphException(500, "Failed to generate IaC code. Please try again.")

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
        raise ArchmorphException(404, "Analysis not found — analyze a diagram first")

    result = await asyncio.to_thread(compute_risk_score, analysis)
    record_event("risk_score_computed", {
        "diagram_id": diagram_id,
        "score": result["overall_score"],
        "tier": result["risk_tier"],
    })
    return result


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
        raise ArchmorphException(404, "Analysis not found — analyze a diagram first")

    result = await asyncio.to_thread(assess_compliance, analysis)
    record_event("compliance_assessed", {
        "diagram_id": diagram_id,
        "frameworks": list(result["frameworks"].keys()),
        "overall_score": result["overall_score"],
    })
    return result


# ─────────────────────────────────────────────────────────────
# Migration Q&A Chat (#258)
# ─────────────────────────────────────────────────────────────
_MIGRATION_QA_SYSTEM = """You are an expert Azure migration architect embedded in the Archmorph platform.
The user has uploaded a cloud architecture diagram and received an analysis with service mappings.
Answer their questions about the migration using the analysis context provided.

Guidelines:
- Be specific about the Azure services in THEIR architecture (reference by name)
- Cite specific SKUs, tiers, and configurations when relevant
- Address limitations and risks honestly
- Suggest Azure Well-Architected Framework best practices
- Keep answers concise (2-4 paragraphs max)
- If asked about cost, reference the pricing data in the context
- If unsure, say so — don't hallucinate Azure features

Return a JSON object:
{"reply": "your answer", "related_services": ["Azure Service 1", "Azure Service 2"]}
"""


@router.post("/api/diagrams/{diagram_id}/migration-chat")
@limiter.limit("20/minute")
async def migration_chat(request: Request, diagram_id: str):
    """Contextual Q&A about the migration analysis results (#258).

    Body: { "message": "user question" }
    Returns: { "reply": "...", "related_services": [...] }
    """
    analysis = get_or_recreate_session(diagram_id)
    if not analysis:
        raise ArchmorphException(404, "No analysis found. Analyze a diagram first.")

    try:
        body = await request.json()
        message = body.get("message", "").strip()
    except Exception:
        raise ArchmorphException(400, "Request body must be JSON with a 'message' field")

    if not message:
        raise ArchmorphException(400, "Message cannot be empty")
    if len(message) > 2000:
        raise ArchmorphException(400, "Message too long (max 2000 chars)")

    # Build context from analysis
    mappings = analysis.get("mappings", [])
    services_ctx = ", ".join(
        f"{m.get('source_service', '?')} -> {m.get('azure_service', '?')} ({m.get('confidence', 0):.0%})"
        for m in mappings[:20]
    )
    zones_ctx = ", ".join(z.get("name", "") for z in analysis.get("zones", [])[:10])
    source = analysis.get("source_provider", "unknown").upper()

    context = f"""Architecture: {source} to Azure
Services mapped: {services_ctx}
Zones: {zones_ctx}
Total services: {len(mappings)}
Diagram type: {analysis.get('diagram_type', 'unknown')}"""

    try:
        from openai_client import get_openai_client, AZURE_OPENAI_DEPLOYMENT
        import json as _json
        client = get_openai_client()

        response = await asyncio.to_thread(
            lambda: client.chat.completions.create(
                model=AZURE_OPENAI_DEPLOYMENT,
                messages=[
                    {"role": "system", "content": _MIGRATION_QA_SYSTEM},
                    {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {message}"},
                ],
                temperature=0.3,
                max_tokens=800,
                response_format={"type": "json_object"},
            )
        )
        raw = response.choices[0].message.content or "{}"
        result = _json.loads(raw)
        return {
            "reply": result.get("reply", "I couldn't generate a response. Please try rephrasing."),
            "related_services": result.get("related_services", []),
        }
    except Exception as exc:
        logger.error("Migration chat failed: %s", sanitize_log(exc))
        return {
            "reply": "Sorry, I couldn't process your question right now. Please try again.",
            "related_services": [],
        }
