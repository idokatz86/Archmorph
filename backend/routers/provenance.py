from error_envelope import ArchmorphException
"""
Provenance routes — structured confidence evidence for service mappings.

    GET /api/diagrams/{diagram_id}/provenance                 — summary for all mappings
    GET /api/diagrams/{diagram_id}/provenance/{service_name}  — detail for one mapping
"""

from fastapi import APIRouter, Request, Depends
import logging

from routers.shared import limiter, require_diagram_access, verify_api_key
from confidence_provenance import build_provenance, build_provenance_summary

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/diagrams/{diagram_id}/provenance", dependencies=[Depends(require_diagram_access)])
@limiter.limit("30/minute")
async def get_provenance_summary(request: Request, diagram_id: str, _auth=Depends(verify_api_key)):
    """Get confidence provenance summary for all mappings in a diagram analysis."""
    session = require_diagram_access(request, diagram_id, purpose="view provenance")

    mappings = session.get("mappings", [])
    if not mappings:
        raise ArchmorphException(404, f"No service mappings found in analysis for diagram {diagram_id}.")

    summary = build_provenance_summary(mappings)
    summary["diagram_id"] = diagram_id
    return summary


@router.get("/api/diagrams/{diagram_id}/provenance/{service_name}", dependencies=[Depends(require_diagram_access)])
@limiter.limit("30/minute")
async def get_provenance_detail(request: Request, diagram_id: str, service_name: str, _auth=Depends(verify_api_key)):
    """Get detailed confidence provenance for a specific service mapping."""
    session = require_diagram_access(request, diagram_id, purpose="view provenance details")

    mappings = session.get("mappings", [])
    if not mappings:
        raise ArchmorphException(404, f"No service mappings found in analysis for diagram {diagram_id}.")

    # Find the mapping by source service name (case-insensitive)
    target_mapping = None
    sn_lower = service_name.lower()
    for m in mappings:
        src = m.get("source_service", "")
        if isinstance(src, dict):
            src = src.get("name", src.get("short_name", ""))
        if str(src).lower() == sn_lower:
            target_mapping = m
            break

    if target_mapping is None:
        available = [
            (m.get("source_service") if isinstance(m.get("source_service"), str) else m.get("source_service", {}).get("name", ""))
            for m in mappings
        ]
        raise ArchmorphException(
            404,
            f"Service '{service_name}' not found in analysis. Available: {', '.join(available)}",
        )

    provenance = build_provenance(target_mapping)
    provenance["diagram_id"] = diagram_id
    return provenance
