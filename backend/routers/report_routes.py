"""
Analysis Report Export routes (Issue #236).

Generates a comprehensive PDF report from a completed analysis session.
"""

import io
import logging

from fastapi import APIRouter, Request, Depends
from fastapi.responses import StreamingResponse

from error_envelope import ArchmorphException
from routers.shared import limiter, verify_api_key
from routers.samples import get_or_recreate_session
from report_generator import generate_analysis_report_pdf
from usage_metrics import record_event
from export_capabilities import issue_export_capability, verify_export_capability

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/diagrams/{diagram_id}/report")
@limiter.limit("10/minute")
async def download_analysis_report(
    request: Request,
    diagram_id: str,
    _auth=Depends(verify_api_key),
    _capability=Depends(verify_export_capability),
):
    """Download a full analysis report as PDF.

    Query params:
      - format: pdf (only PDF is currently supported)
    """
    fmt = request.query_params.get("format", "pdf").lower()
    if fmt != "pdf":
        raise ArchmorphException(400, "Only PDF format is currently supported for analysis reports")

    session = get_or_recreate_session(diagram_id)
    if not session:
        raise ArchmorphException(404, "Analysis session not found. Please re-analyze the diagram.")

    if not session.get("mappings"):
        raise ArchmorphException(404, "No analysis data found. Complete an analysis first.")

    record_event("report_downloaded", {"diagram_id": diagram_id, "format": fmt})

    pdf_bytes = generate_analysis_report_pdf(session)

    filename = f"archmorph-report-{diagram_id[:8]}.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
            "X-Export-Capability-Next": issue_export_capability(diagram_id),
        },
    )
