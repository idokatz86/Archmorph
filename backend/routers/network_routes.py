"""
Network Topology Routes — VPC→VNet translation, CIDR planning, NSG rules, route tables.
"""

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import Field
from strict_models import StrictBaseModel
from typing import Any, Dict, Optional
import logging

from routers.shared import authorize_diagram_access, limiter, require_diagram_access, verify_api_key
from error_envelope import ArchmorphException
from source_provider import normalize_source_provider
from network_translator import (
    translate_network_topology,
    translate_gcp_network,
    plan_subnets,
    validate_cidr,
    validate_no_overlaps,
    DEFAULT_VNET_CIDR,
    DEFAULT_SUBNET_PREFIX,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory cache for generated topologies (keyed by diagram_id)
_topology_cache: Dict[str, dict] = {}


# ─────────────────────────────────────────────────────────────
# Request / Response Models
# ─────────────────────────────────────────────────────────────

class NetworkTopologyRequest(StrictBaseModel):
    """Optional overrides for network topology generation."""
    vnet_cidr: str = Field(default=DEFAULT_VNET_CIDR, description="VNet address space CIDR")
    subnet_prefix: int = Field(default=DEFAULT_SUBNET_PREFIX, ge=16, le=29, description="Subnet prefix length")
    vnet_name: Optional[str] = Field(default=None, description="Override VNet name")
    network_overrides: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Explicit network data (subnets, security_groups, route_tables) to translate",
    )


# ─────────────────────────────────────────────────────────────
# POST /api/diagrams/{diagram_id}/network-topology
# ─────────────────────────────────────────────────────────────

@router.post("/api/diagrams/{diagram_id}/network-topology", dependencies=[Depends(require_diagram_access)])
@limiter.limit("10/minute")
async def generate_network_topology(
    request: Request,
    diagram_id: str,
    body: Optional[NetworkTopologyRequest] = None,
    _auth=Depends(verify_api_key),
):
    """Generate Azure network topology translation from a diagram's analysis.

    Reads the analysis result from the session store, extracts networking
    constructs (VPC, subnets, security groups, route tables), and produces
    an Azure-equivalent VNet plan with NSGs, route tables, and NAT gateway.
    """
    session = authorize_diagram_access(request, diagram_id, purpose="generate network topology")

    analysis = session.get("analysis")
    if not analysis:
        raise ArchmorphException(400, f"Diagram {diagram_id} has no analysis result. Run analysis first.")

    params = body or NetworkTopologyRequest()

    try:
        validate_cidr(params.vnet_cidr)
    except ValueError:
        raise ArchmorphException(400, f"Invalid CIDR: {params.vnet_cidr}")

    # If explicit network overrides provided, merge into analysis
    effective_analysis = dict(analysis)
    if params.network_overrides:
        effective_analysis["network"] = params.network_overrides

    try:
        provider = normalize_source_provider(effective_analysis.get("source_provider"))
    except ValueError as exc:
        raise ArchmorphException(400, str(exc))

    try:
        if provider == "gcp":
            network_data = effective_analysis.get("network", {})
            topology = translate_gcp_network(
                network_data,
                vnet_cidr=params.vnet_cidr,
                subnet_prefix=params.subnet_prefix,
                vnet_name=params.vnet_name,
            )
        else:
            topology = translate_network_topology(
                effective_analysis,
                vnet_cidr=params.vnet_cidr,
                subnet_prefix=params.subnet_prefix,
                vnet_name=params.vnet_name,
            )
    except ValueError as exc:
        raise ArchmorphException(400, str(exc))

    result = topology.to_dict()
    _topology_cache[diagram_id] = result

    logger.info("Network topology generated for %s: %s topology, %d subnets, %d NSGs",
                diagram_id.replace('\n', '').replace('\r', ''), result["topology_type"],
                len(result["vnet"]["subnets"]), len(result["nsgs"]))

    return {"status": "ok", "diagram_id": diagram_id, "network_topology": result}


# ─────────────────────────────────────────────────────────────
# GET /api/diagrams/{diagram_id}/network-topology
# ─────────────────────────────────────────────────────────────

@router.get("/api/diagrams/{diagram_id}/network-topology", dependencies=[Depends(require_diagram_access)])
@limiter.limit("30/minute")
async def get_network_topology(
    request: Request,
    diagram_id: str,
    response: Response = None,
    _auth=Depends(verify_api_key),
    _session=Depends(require_diagram_access),
):
    """Retrieve cached network topology for a diagram.

    Returns 404 if no topology has been generated yet.
    """
    cached = _topology_cache.get(diagram_id)
    if not cached:
        raise ArchmorphException(
            404,
            f"No network topology for diagram {diagram_id}. "
            "POST /api/diagrams/{diagram_id}/network-topology first.",
        )

    if response:
        response.headers["Cache-Control"] = "private, max-age=120"

    return {"status": "ok", "diagram_id": diagram_id, "network_topology": cached}


# ─────────────────────────────────────────────────────────────
# GET /api/network/cidr-calculator
# ─────────────────────────────────────────────────────────────

@router.get("/api/network/cidr-calculator")
@limiter.limit("30/minute")
async def cidr_calculator(
    request: Request,
    response: Response,
    vnet_cidr: str = Query(default=DEFAULT_VNET_CIDR, description="VNet CIDR block"),
    subnet_count: int = Query(default=4, ge=1, le=256, description="Number of subnets to create"),
    subnet_prefix: int = Query(default=DEFAULT_SUBNET_PREFIX, ge=16, le=29, description="Subnet prefix length"),
):
    """Calculate non-overlapping subnet CIDRs for a given VNet address space.

    Utility endpoint — no diagram or analysis required.
    """
    try:
        validate_cidr(vnet_cidr)
    except ValueError:
        raise ArchmorphException(400, f"Invalid CIDR: {vnet_cidr}")

    try:
        subnets = plan_subnets(vnet_cidr, subnet_count, subnet_prefix)
    except ValueError as exc:
        raise ArchmorphException(400, str(exc))

    overlap_warnings = validate_no_overlaps(subnets)

    response.headers["Cache-Control"] = "public, max-age=300"

    return {
        "vnet_cidr": vnet_cidr,
        "subnet_count": subnet_count,
        "subnet_prefix": f"/{subnet_prefix}",
        "subnets": subnets,
        "warnings": overlap_warnings,
    }
