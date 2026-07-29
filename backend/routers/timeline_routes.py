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
import hashlib
import json
import logging

from export_capabilities import (
    consume_export_capability,
    issue_export_capability_for_request,
    verify_export_capability,
)
from export_artifacts import persist_generated_export_async
from routers.shared import (
    authorize_diagram_access_async,
    limiter,
    persist_diagram_mutation_async,
    require_api_read_or_user_session,
    require_api_write_or_user_session,
    require_diagram_access,
)
from usage_metrics import record_event
from migration_timeline import (
    generate_timeline,
    render_timeline_markdown,
    render_timeline_csv,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/api/diagrams/{diagram_id}/migration-timeline",
    dependencies=[Depends(require_diagram_access)],
)
@limiter.limit("5/minute")
async def create_migration_timeline(
    request: Request,
    diagram_id: str,
    project_name: Optional[str] = None,
    _auth=Depends(require_api_write_or_user_session),
):
    """Generate a phased migration timeline from analysis results.

    The timeline includes 7 phases, dependency-ordered services,
    parallel workstreams, and estimated durations per service.
    """
    session = await authorize_diagram_access_async(
        request, diagram_id, purpose="create a migration timeline"
    )

    timeline = await asyncio.to_thread(generate_timeline, session, project_name)

    updated_session = dict(session)
    updated_session["migration_timeline"] = timeline
    await persist_diagram_mutation_async(
        request,
        diagram_id,
        updated_session,
        artifact_type="migration_timeline",
        artifact_format="json",
        artifact_content=json.dumps(
            timeline, ensure_ascii=False, sort_keys=True, default=str
        ),
        label="migration-timeline-generated",
    )

    record_event(
        "migration_timeline_generated",
        {
            "diagram_id": diagram_id,
            "total_services": timeline["total_services"],
            "risk_level": timeline["risk_level"],
        },
    )

    return timeline


@router.get(
    "/api/diagrams/{diagram_id}/migration-timeline",
    dependencies=[Depends(require_diagram_access)],
)
@limiter.limit("30/minute")
async def get_migration_timeline(
    request: Request,
    diagram_id: str,
    _auth=Depends(require_api_read_or_user_session),
):
    """Retrieve the previously generated migration timeline."""
    session = await authorize_diagram_access_async(
        request, diagram_id, purpose="view a migration timeline"
    )
    if not session or "migration_timeline" not in session:
        raise ArchmorphException(
            404, "Timeline not found. Generate one first via POST."
        )

    return session["migration_timeline"]


@router.get(
    "/api/diagrams/{diagram_id}/migration-timeline/export",
    dependencies=[Depends(require_diagram_access)],
)
@limiter.limit("15/minute")
async def export_migration_timeline(
    request: Request,
    diagram_id: str,
    format: str = Query("json", pattern="^(json|md|csv)$"),
    _auth=Depends(require_api_write_or_user_session),
    capability=Depends(verify_export_capability),
):
    """Export the migration timeline in JSON, Markdown, or CSV format."""
    session = await authorize_diagram_access_async(
        request, diagram_id, purpose="export a migration timeline"
    )
    if not session or "migration_timeline" not in session:
        raise ArchmorphException(
            404, "Timeline not found. Generate one first via POST."
        )

    timeline = session["migration_timeline"]

    if format == "md":
        content = render_timeline_markdown(timeline)
        media_type = "text/markdown"
        extension = "md"
    elif format == "csv":
        content = render_timeline_csv(timeline)
        media_type = "text/csv"
        extension = "csv"
    else:
        content = json.dumps(timeline, ensure_ascii=False, default=str)
        media_type = "application/json"
        extension = "json"

    artifact = await persist_generated_export_async(
        request,
        diagram_id=diagram_id,
        artifact_type=f"migration_timeline_export_{format}",
        format=format,
        content=content,
    )
    consume_export_capability(capability)
    record_event(
        "migration_timeline_exported",
        {
            "diagram_id": diagram_id,
            "format": format,
        },
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="timeline-{diagram_id}.{extension}"',
            "X-Artifact-SHA256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            **(
                {
                    "X-Artifact-ID": artifact.id,
                    "X-Analysis-Version-ID": artifact.version_id,
                }
                if artifact is not None
                else {}
            ),
            "X-Export-Capability-Next": await issue_export_capability_for_request(
                request,
                diagram_id,
            ),
        },
    )
