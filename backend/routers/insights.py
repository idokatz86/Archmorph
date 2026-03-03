"""
Insights routes — best practices, cost estimation, cost optimization,
risk score, compliance, terraform preview.

Split from diagrams.py for maintainability (#284).
"""

from fastapi import APIRouter, HTTPException, Request, Depends
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
        raise HTTPException(404, "No analysis found. Analyze a diagram first.")

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
# Best Practices & WAF Analysis
# ─────────────────────────────────────────────────────────────
@router.get("/api/diagrams/{diagram_id}/best-practices")
@limiter.limit("30/minute")
async def get_best_practices(request: Request, diagram_id: str):
    """Analyze architecture against Azure Well-Architected Framework."""
    analysis = get_or_recreate_session(diagram_id)
    if not analysis:
        raise HTTPException(404, "Analysis not found")

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
        raise HTTPException(404, "Analysis not found")

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
        raise HTTPException(404, "Analysis not found")

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
