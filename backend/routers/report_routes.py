"""
Analysis Report Export routes (Issue #236).

Generates a comprehensive PDF report from a completed analysis session.
"""

import hashlib
import io
import logging
from functools import partial

from fastapi import APIRouter, Request, Depends
from fastapi.responses import StreamingResponse

from error_envelope import ArchmorphException
from routers.shared import (
    authorize_diagram_access_async,
    limiter,
    require_api_write_or_user_session,
    require_diagram_access,
)
from report_generator import generate_analysis_report_pdf
from usage_metrics import record_event
from export_capabilities import (
    consume_export_capability,
    issue_export_capability_for_request,
    verify_export_capability,
)
from export_artifacts import persist_generated_export_async
from route_effects import write_route_effects
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

router = APIRouter()


def _analysis_version_created_at(*, diagram_id: str, principal: dict):
    from database import SessionLocal
    from workspace_store import get_current_analysis_version

    db = SessionLocal()
    try:
        try:
            _analysis, version = get_current_analysis_version(
                db,
                diagram_id=diagram_id,
                owner_user_id=principal["owner_user_id"],
                tenant_id=principal["tenant_id"],
            )
        except ValueError:
            return None
        return version.created_at if version is not None else None
    finally:
        db.close()


@router.get(
    "/api/diagrams/{diagram_id}/report",
    dependencies=[Depends(require_diagram_access)],
    openapi_extra=write_route_effects("artifact", "capability", "telemetry"),
)
@limiter.limit("10/minute")
async def download_analysis_report(
    request: Request,
    diagram_id: str,
    _auth=Depends(require_api_write_or_user_session),
    capability=Depends(verify_export_capability),
):
    """Download a full analysis report as PDF.

    Query params:
      - format: pdf (only PDF is currently supported)
    """
    fmt = request.query_params.get("format", "pdf").lower()
    if fmt != "pdf":
        raise ArchmorphException(400, "Only PDF format is currently supported for analysis reports")

    session = await authorize_diagram_access_async(request, diagram_id, purpose="download a report")

    if not session.get("mappings"):
        raise ArchmorphException(404, "No analysis data found. Complete an analysis first.")

    record_event("report_downloaded", {"diagram_id": diagram_id, "format": fmt})

    from routers.shared import get_request_durable_principal

    principal = get_request_durable_principal(request)
    generated_at = None
    if principal and principal.get("tenant_id"):
        generated_at = await run_in_threadpool(partial(
            _analysis_version_created_at,
            diagram_id=diagram_id,
            principal=principal,
        ))
    pdf_bytes = generate_analysis_report_pdf(session, generated_at=generated_at)
    artifact = await persist_generated_export_async(
        request,
        diagram_id=diagram_id,
        artifact_type="analysis_report",
        format="pdf",
        content=pdf_bytes,
        force_blob=True,
    )
    consume_export_capability(capability)

    filename = f"archmorph-report-{diagram_id[:8]}.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
            "X-Artifact-SHA256": hashlib.sha256(pdf_bytes).hexdigest(),
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
