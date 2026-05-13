from error_envelope import ArchmorphException
"""
Timeline routes — phased migration timeline with dependency ordering (Issue #231).

POST /api/diagrams/{diagram_id}/migration-timeline   — Generate timeline
GET  /api/diagrams/{diagram_id}/migration-timeline    — Retrieve existing
GET  /api/diagrams/{diagram_id}/migration-timeline/export?format=json|md|csv
"""

from fastapi import APIRouter, Query, Request, Response, Depends
from typing import Optional
import asyncio
import logging

from routers.shared import limiter, require_diagram_access, verify_api_key
from usage_metrics import record_event
from migration_timeline import (
    generate_timeline,
    render_timeline_markdown,
    render_timeline_csv,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/diagrams/{diagram_id}/migration-timeline", dependencies=[Depends(require_diagram_access)])
@limiter.limit("5/minute")
async def create_migration_timeline(
    request: Request,
    diagram_id: str,
    project_name: Optional[str] = None,
    _auth=Depends(verify_api_key),
):
    """Generate a phased migration timeline from analysis results.

    The timeline includes 7 phases, dependency-ordered services,
    parallel workstreams, and estimated durations per service.
    """
    session = require_diagram_access(request, diagram_id, purpose="create a migration timeline")

    timeline = await asyncio.to_thread(generate_timeline, session, project_name)

    # Store alongside analysis
    session["migration_timeline"] = timeline
    from routers.shared import SESSION_STORE
    SESSION_STORE[diagram_id] = session

    record_event("migration_timeline_generated", {
        "diagram_id": diagram_id,
        "total_services": timeline["total_services"],
        "risk_level": timeline["risk_level"],
    })

    return timeline


@router.get("/api/diagrams/{diagram_id}/migration-timeline", dependencies=[Depends(require_diagram_access)])
@limiter.limit("30/minute")
async def get_migration_timeline(
    request: Request,
    diagram_id: str,
    _auth=Depends(verify_api_key),
):
    """Retrieve the previously generated migration timeline."""
    session = require_diagram_access(request, diagram_id, purpose="view a migration timeline")
    if not session or "migration_timeline" not in session:
        raise ArchmorphException(404, "Timeline not found. Generate one first via POST.")

    return session["migration_timeline"]


@router.get("/api/diagrams/{diagram_id}/migration-timeline/export", dependencies=[Depends(require_diagram_access)])
@limiter.limit("15/minute")
async def export_migration_timeline(
    request: Request,
    diagram_id: str,
    format: str = Query("json", pattern="^(json|md|csv)$"),
    _auth=Depends(verify_api_key),
):
    """Export the migration timeline in JSON, Markdown, or CSV format."""
    session = require_diagram_access(request, diagram_id, purpose="export a migration timeline")
    if not session or "migration_timeline" not in session:
        raise ArchmorphException(404, "Timeline not found. Generate one first via POST.")

    timeline = session["migration_timeline"]

    if format == "md":
        content = render_timeline_markdown(timeline)
        return Response(
            content=content,
            media_type="text/markdown",
            headers={"Content-Disposition": f"attachment; filename=timeline-{diagram_id}.md"},
        )

    if format == "csv":
        content = render_timeline_csv(timeline)
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=timeline-{diagram_id}.csv"},
        )

    # Default: JSON
    return timeline
