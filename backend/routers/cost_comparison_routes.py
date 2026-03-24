"""
Multi-Cloud Cost Comparison routes (#499).

Estimate and compare monthly costs for an Archmorph analysis across
AWS, Azure, and GCP.
"""

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from error_envelope import ArchmorphException
from routers.shared import limiter
from session_store import get_store
from services.multi_cloud_cost import estimate_costs, get_pricing_catalog

logger = logging.getLogger(__name__)

router = APIRouter()

_cost_cache = get_store("cost_comparison", maxsize=200, ttl=3600)


# ── Request / Response Models ────────────────────────────────

class CostServiceInput(BaseModel):
    name: str
    type: str
    provider: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    dependencies: Optional[List[str]] = None


class CostZoneInput(BaseModel):
    name: str = Field(..., description="Category name (Compute, Storage, etc.)")
    services: List[CostServiceInput]


class CostCompareRequest(BaseModel):
    zones: List[CostZoneInput]


# ─────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/api/cost/compare")
@limiter.limit("10/minute")
async def compare_costs(request: Request, body: CostCompareRequest):
    """Estimate and compare monthly costs across AWS, Azure, and GCP.

    Accepts an Archmorph analysis schema (zones with services) and
    returns a side-by-side cost comparison with TCO analysis and
    savings recommendations.
    """
    if not body.zones:
        raise ArchmorphException(400, "At least one zone is required")

    # Cache key from payload hash
    payload_json = json.dumps([z.model_dump() for z in body.zones], sort_keys=True)
    cache_key = f"cost:{hashlib.sha256(payload_json.encode()).hexdigest()[:16]}"

    cached = _cost_cache.get(cache_key)
    if cached:
        logger.debug("Cost comparison cache hit: %s", cache_key)
        return cached

    zones_data = [z.model_dump() for z in body.zones]
    result = estimate_costs(zones_data)

    _cost_cache.set(cache_key, result)
    logger.info(
        "Cost comparison: %d services estimated, cheapest=%s",
        result["total_services_estimated"],
        result["cheapest_cloud"],
    )
    return result


@router.get("/api/cost/pricing-catalog")
async def pricing_catalog(request: Request):
    """Return available pricing data for all supported service tiers."""
    return get_pricing_catalog()
