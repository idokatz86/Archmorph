"""
Archmorph Cost Dashboard Router — Cost & Token Observability API (Issue #392).

Endpoints for enterprise cost visibility:
  - Aggregate overview, per-agent, per-model breakdowns
  - Timeseries data (hourly/daily/weekly)
  - Top consumers ranking
  - Budget CRUD with utilization tracking
  - Active alerts
  - CSV export

Security (#843): All endpoints require API-key authentication.  The tenant context
is derived from the authenticated API key; callers may NOT override it via a
``tenant_id`` query parameter (any such parameter is rejected with 400).
"""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from routers.shared import CredentialContext, require_api_write, verify_api_key
from cost_metering import (
    CostMeter,
    CostOverviewResponse,
    AgentCostResponse,
    ModelCostResponse,
    TimeseriesPoint,
    TopConsumer,
    BudgetCreateRequest,
    BudgetUpdateRequest,
    BudgetUtilization,
    CostAlert,
    CostScope,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/cost",
    tags=["Cost & Token Observability"],
)


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid ISO datetime: {value}")


def _reject_tenant_id_override(tenant_id: Optional[str] = Query(None)) -> None:
    """Dependency that rejects explicit ``tenant_id`` query parameters (#843).

    Tenant context must be resolved from the authenticated user, not from
    client-supplied query strings which could be used to access another
    tenant's cost data.
    """
    if tenant_id is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "tenant_id query parameter is not accepted on cost endpoints. "
                "The tenant is resolved from your authenticated API key."
            ),
        )


def _cost_scope(context: CredentialContext, *, global_view: bool = False) -> CostScope:
    if global_view and not context.has_scope("admin"):
        raise HTTPException(status_code=403, detail="Admin scope is required for global cost visibility")
    if context.kind.value == "development":
        return CostScope(
            owner_user_id="development",
            tenant_id="development",
            actor_kind="development",
            global_admin=global_view,
        )
    try:
        return CostScope.from_credential(context, global_admin=global_view)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Canonical caller scope is required") from exc


# ─────────────────────────────────────────────────────────────
# Overview
# ─────────────────────────────────────────────────────────────

@router.get("/overview", response_model=CostOverviewResponse, dependencies=[Depends(_reject_tenant_id_override)])
async def cost_overview(
    since: Optional[str] = Query(None, description="ISO datetime lower bound"),
    until: Optional[str] = Query(None, description="ISO datetime upper bound"),
    global_view: bool = Query(False, alias="global", description="Explicit admin-only global view"),
    context: CredentialContext = Depends(verify_api_key),
):
    """Aggregate cost/token summary — total spend, total tokens, active agents."""
    meter = CostMeter.instance()
    return meter.get_overview(
        since=_parse_iso(since),
        until=_parse_iso(until),
        scope=_cost_scope(context, global_view=global_view),
    )


# ─────────────────────────────────────────────────────────────
# Per-agent breakdown
# ─────────────────────────────────────────────────────────────

@router.get("/agents/{agent_id}", response_model=AgentCostResponse)
async def agent_cost(agent_id: str, context: CredentialContext = Depends(verify_api_key)):
    """Per-agent cost breakdown: spend, tokens, models used."""
    meter = CostMeter.instance()
    return meter.get_agent_cost(agent_id, scope=_cost_scope(context))


# ─────────────────────────────────────────────────────────────
# Per-model breakdown
# ─────────────────────────────────────────────────────────────

@router.get("/models", response_model=List[ModelCostResponse])
async def model_breakdown(context: CredentialContext = Depends(verify_api_key)):
    """Per-model cost breakdown sorted by spend descending."""
    meter = CostMeter.instance()
    return meter.get_model_breakdown(scope=_cost_scope(context))


# ─────────────────────────────────────────────────────────────
# Timeseries
# ─────────────────────────────────────────────────────────────

@router.get("/timeseries", response_model=List[TimeseriesPoint])
async def timeseries(
    granularity: str = Query("hourly", pattern="^(hourly|daily|weekly)$"),
    since: Optional[str] = Query(None, description="ISO datetime lower bound"),
    until: Optional[str] = Query(None, description="ISO datetime upper bound"),
    context: CredentialContext = Depends(verify_api_key),
):
    """Cost over time with configurable granularity (hourly/daily/weekly)."""
    meter = CostMeter.instance()
    return meter.get_timeseries(
        granularity=granularity,
        since=_parse_iso(since),
        until=_parse_iso(until),
        scope=_cost_scope(context),
    )


# ─────────────────────────────────────────────────────────────
# Top consumers
# ─────────────────────────────────────────────────────────────

@router.get("/top-consumers", response_model=List[TopConsumer])
async def top_consumers(
    limit: int = Query(10, ge=1, le=100, description="Max results"),
    context: CredentialContext = Depends(verify_api_key),
):
    """Top agents/operations by cost."""
    meter = CostMeter.instance()
    return meter.get_top_consumers(limit=limit, scope=_cost_scope(context))


# ─────────────────────────────────────────────────────────────
# Budget CRUD
# ─────────────────────────────────────────────────────────────

@router.post("/budgets", response_model=BudgetUtilization, status_code=201)
async def create_budget(
    payload: BudgetCreateRequest,
    context: CredentialContext = Depends(require_api_write),
):
    """Create a budget rule for an agent."""
    meter = CostMeter.instance()
    scope = _cost_scope(context)
    rule = meter.create_budget(payload, scope=scope)
    # Return with utilization info
    budgets = meter.list_budgets(scope=scope)
    for b in budgets:
        if b.id == rule.id:
            return b
    # Fallback — shouldn't happen
    return BudgetUtilization(
        id=rule.id,
        agent_id=rule.agent_id,
        amount_usd=rule.amount_usd,
        period=rule.period,
        current_spend=0.0,
        utilization_pct=0.0,
        alert_thresholds=rule.alert_thresholds,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


@router.get("/budgets", response_model=List[BudgetUtilization])
async def list_budgets(context: CredentialContext = Depends(verify_api_key)):
    """List all budget rules with current utilization percentage."""
    meter = CostMeter.instance()
    return meter.list_budgets(scope=_cost_scope(context))


@router.put("/budgets/{budget_id}", response_model=BudgetUtilization)
async def update_budget(
    budget_id: str,
    payload: BudgetUpdateRequest,
    context: CredentialContext = Depends(require_api_write),
):
    """Update an existing budget rule."""
    meter = CostMeter.instance()
    try:
        meter.update_budget(budget_id, payload, scope=_cost_scope(context))
    except KeyError:
        raise HTTPException(status_code=404, detail="Budget not found")
    budgets = meter.list_budgets(scope=_cost_scope(context))
    for b in budgets:
        if b.id == budget_id:
            return b
    raise HTTPException(status_code=404, detail="Budget not found")


# ─────────────────────────────────────────────────────────────
# Alerts
# ─────────────────────────────────────────────────────────────

@router.get("/alerts", response_model=List[CostAlert])
async def get_alerts(
    active_only: bool = Query(True, description="Only unacknowledged alerts"),
    context: CredentialContext = Depends(verify_api_key),
):
    """Active cost alerts — budget exceeded or approaching limit."""
    meter = CostMeter.instance()
    return meter.get_alerts(active_only=active_only, scope=_cost_scope(context))


# ─────────────────────────────────────────────────────────────
# CSV Export
# ─────────────────────────────────────────────────────────────

@router.get("/export")
async def export_csv(
    since: Optional[str] = Query(None, description="ISO datetime lower bound"),
    until: Optional[str] = Query(None, description="ISO datetime upper bound"),
    context: CredentialContext = Depends(verify_api_key),
):
    """Export cost records as CSV."""
    meter = CostMeter.instance()
    csv_data = meter.export_csv(
        since=_parse_iso(since),
        until=_parse_iso(until),
        scope=_cost_scope(context),
    )
    return StreamingResponse(
        iter([csv_data]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=archmorph_costs.csv"},
    )
