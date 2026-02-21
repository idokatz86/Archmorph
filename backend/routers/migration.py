"""
Migration Runbook, Assessment & Cost Comparison routes (v2.9.0).
"""

from fastapi import APIRouter, HTTPException, Request, Response, Depends
from typing import Optional
import logging

from routers.shared import SESSION_STORE, limiter, verify_api_key
from migration_runbook import generate_migration_runbook, MigrationRunbook, render_runbook_markdown
from migration_assessment import assess_migration_complexity
from cost_comparison import generate_cost_comparison
from usage_metrics import record_event

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/diagrams/{diagram_id}/runbook")
@limiter.limit("3/minute")
async def generate_runbook_endpoint(
    request: Request,
    diagram_id: str,
    project_name: Optional[str] = None,
    _auth=Depends(verify_api_key),
):
    """Generate a migration runbook based on architecture analysis."""
    analysis = SESSION_STORE.get(diagram_id)
    if not analysis:
        raise HTTPException(404, "Analysis not found")
    
    runbook = generate_migration_runbook(diagram_id, analysis, project_name)
    
    # Store runbook in session
    analysis["runbook"] = runbook.to_dict()
    SESSION_STORE[diagram_id] = analysis
    
    record_event("runbook_generated", {"diagram_id": diagram_id, "tasks": len(runbook.tasks)})
    
    return runbook.to_dict()


@router.get("/api/diagrams/{diagram_id}/runbook")
async def get_runbook_endpoint(diagram_id: str):
    """Get generated runbook for a diagram."""
    analysis = SESSION_STORE.get(diagram_id)
    if not analysis or "runbook" not in analysis:
        raise HTTPException(404, "Runbook not found. Generate one first.")
    
    return analysis["runbook"]


@router.get("/api/diagrams/{diagram_id}/runbook/markdown")
async def get_runbook_markdown_endpoint(diagram_id: str):
    """Get runbook as downloadable Markdown."""
    analysis = SESSION_STORE.get(diagram_id)
    if not analysis or "runbook" not in analysis:
        raise HTTPException(404, "Runbook not found")
    
    # Reconstruct runbook object
    runbook_data = analysis["runbook"]
    runbook = MigrationRunbook(
        id=runbook_data["id"],
        diagram_id=runbook_data["diagram_id"],
        title=runbook_data["title"],
        source_cloud=runbook_data["source_cloud"],
        risk_level=runbook_data["risk_level"],
        estimated_duration_days=runbook_data["estimated_duration_days"],
    )
    
    markdown = render_runbook_markdown(runbook)
    
    return Response(
        content=markdown,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename=runbook-{diagram_id}.md"}
    )


# ─────────────────────────────────────────────────────────────
# Migration Complexity Assessment (Issue #65)
# ─────────────────────────────────────────────────────────────
@router.get("/api/diagrams/{diagram_id}/migration-assessment")
async def migration_assessment_endpoint(diagram_id: str):
    """Assess migration complexity for all services in a diagram analysis."""
    analysis = SESSION_STORE.get(diagram_id)
    if not analysis:
        raise HTTPException(404, "Analysis not found")

    assessment = assess_migration_complexity(analysis)

    # Cache in session
    analysis["migration_assessment"] = assessment
    SESSION_STORE[diagram_id] = analysis

    record_event("migration_assessment", {
        "diagram_id": diagram_id,
        "overall_score": assessment["overall_score"],
        "risk_level": assessment["risk_level"],
        "total_services": assessment["total_services"],
    })

    return assessment


# ─────────────────────────────────────────────────────────────
# Multi-Cloud Cost Comparison (Issue #66)
# ─────────────────────────────────────────────────────────────
@router.get("/api/diagrams/{diagram_id}/cost-comparison")
async def cost_comparison_endpoint(diagram_id: str):
    """Get multi-cloud cost comparison for services in a diagram analysis."""
    analysis = SESSION_STORE.get(diagram_id)
    if not analysis:
        raise HTTPException(404, "Analysis not found")

    comparison = generate_cost_comparison(analysis)

    analysis["cost_comparison"] = comparison
    SESSION_STORE[diagram_id] = analysis

    record_event("cost_comparison", {
        "diagram_id": diagram_id,
        "providers_compared": len(comparison.get("providers", {})),
    })

    return comparison
