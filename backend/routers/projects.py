"""Project-level routes for multi-diagram architecture analysis (#241)."""

from typing import Literal
import asyncio

from fastapi import APIRouter, Depends, Request

from error_envelope import ArchmorphException
from iac_generator import generate_iac_code
from project_merge import merge_project_analyses
from project_store import get_project, list_analyzed_diagrams, set_combined_analysis
from routers.iac_routes import _check_architecture_blockers
from routers.shared import SESSION_STORE, limiter, verify_api_key
from usage_metrics import record_event, record_funnel_step

router = APIRouter()


def _combined_analysis_for_project(project_id: str) -> dict:
    project = get_project(project_id)
    if not project:
        raise ArchmorphException(404, f"No project found for {project_id}. Upload a diagram first.")

    analyzed_ids = list_analyzed_diagrams(project)
    analyses = [SESSION_STORE.get(diagram_id) for diagram_id in analyzed_ids]
    analyses = [analysis for analysis in analyses if isinstance(analysis, dict)]
    if not analyses:
        raise ArchmorphException(404, f"No analyzed diagrams found for project {project_id}. Run /analyze first.")

    if project.get("combined_status") == "ready" and project.get("combined_analysis"):
        return project["combined_analysis"]

    combined = merge_project_analyses(project_id, analyses)
    set_combined_analysis(project_id, combined)
    return combined


@router.get("/api/projects/{project_id}")
@limiter.limit("30/minute")
async def get_project_status(request: Request, project_id: str, _auth=Depends(verify_api_key)):
    """Return project metadata and per-diagram analysis status."""
    project = get_project(project_id)
    if not project:
        raise ArchmorphException(404, f"No project found for {project_id}. Upload a diagram first.")
    return project


@router.get("/api/projects/{project_id}/analysis")
@limiter.limit("15/minute")
async def get_project_analysis(request: Request, project_id: str, _auth=Depends(verify_api_key)):
    """Return a deterministic combined analysis for all analyzed project diagrams."""
    combined = _combined_analysis_for_project(project_id)
    record_event("project_analysis_merged", {
        "project_id": project_id,
        "diagrams": len(combined.get("source_diagram_ids", [])),
        "services": combined.get("services_detected", 0),
    })
    return combined


@router.post("/api/projects/{project_id}/generate")
@limiter.limit("5/minute")
async def generate_project_iac(
    request: Request,
    project_id: str,
    format: Literal["terraform", "bicep"] = "terraform",
    force: bool = False,
    _auth=Depends(verify_api_key),
):
    """Generate unified Infrastructure as Code from combined project analysis."""
    combined = _combined_analysis_for_project(project_id)
    _check_architecture_blockers(f"project-{project_id}", combined, force)

    try:
        code = await asyncio.to_thread(
            generate_iac_code,
            analysis=combined,
            iac_format=format,
            params=combined.get("iac_parameters", {}),
        )
    except Exception:
        raise ArchmorphException(500, "Project IaC generation failed. Please try again.")

    record_event(f"project_iac_generated_{format}", {"project_id": project_id})
    record_funnel_step(f"project-{project_id}", "iac_generate")
    return {"project_id": project_id, "format": format, "code": code, "analysis": combined}