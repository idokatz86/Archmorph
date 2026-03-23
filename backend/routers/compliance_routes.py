"""
Compliance Framework Mapping & Gap Analysis routes (Issue #239).

Endpoints for mapping Azure services to compliance controls (SOC 2, HIPAA,
PCI-DSS, GDPR, ISO 27001, FedRAMP), identifying gaps, and exporting reports.
"""

from fastapi import APIRouter, Depends, Query, Request
from typing import List, Optional
import logging

from error_envelope import ArchmorphException
from routers.shared import limiter, verify_api_key
from routers.samples import get_or_recreate_session
from compliance_mapper import (
    map_compliance,
    get_compliance_gaps,
    export_compliance_report,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _parse_frameworks(frameworks: Optional[str]) -> List[str]:
    """Split comma-separated framework query param into a list."""
    if not frameworks:
        return []
    return [f.strip() for f in frameworks.split(",") if f.strip()]


@router.get("/api/diagrams/{diagram_id}/compliance")
@limiter.limit("20/minute")
async def compliance_mapping(
    request: Request,
    diagram_id: str,
    frameworks: Optional[str] = Query(
        None,
        description="Comma-separated framework IDs: soc2, hipaa, pci_dss, gdpr, iso27001, fedramp",
    ),
    _auth=Depends(verify_api_key),
):
    """Map detected Azure services to compliance framework controls.

    Returns per-framework readiness scores, covered controls, gaps,
    and prioritised remediation recommendations.
    """
    analysis = get_or_recreate_session(diagram_id)
    if not analysis:
        raise ArchmorphException(
            404, f"No analysis found for diagram {diagram_id}. Run /analyze first."
        )

    fw_list = _parse_frameworks(frameworks)
    result = map_compliance(analysis, fw_list)
    return {"diagram_id": diagram_id, **result}


@router.get("/api/diagrams/{diagram_id}/compliance/gaps")
@limiter.limit("20/minute")
async def compliance_gaps(
    request: Request,
    diagram_id: str,
    frameworks: Optional[str] = Query(None),
    _auth=Depends(verify_api_key),
):
    """Return gap analysis sorted by severity across requested frameworks."""
    analysis = get_or_recreate_session(diagram_id)
    if not analysis:
        raise ArchmorphException(
            404, f"No analysis found for diagram {diagram_id}. Run /analyze first."
        )

    fw_list = _parse_frameworks(frameworks)
    result = get_compliance_gaps(analysis, fw_list)
    return {"diagram_id": diagram_id, **result}


@router.get("/api/diagrams/{diagram_id}/compliance/export")
@limiter.limit("10/minute")
async def compliance_export(
    request: Request,
    diagram_id: str,
    frameworks: Optional[str] = Query(None),
    format: str = Query("json", pattern="^(json|md)$"),
    _auth=Depends(verify_api_key),
):
    """Export compliance report as JSON or Markdown."""
    analysis = get_or_recreate_session(diagram_id)
    if not analysis:
        raise ArchmorphException(
            404, f"No analysis found for diagram {diagram_id}. Run /analyze first."
        )

    fw_list = _parse_frameworks(frameworks)
    result = export_compliance_report(analysis, fw_list, fmt=format)
    return {"diagram_id": diagram_id, **result}
