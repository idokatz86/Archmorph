"""
Archmorph Cost Dashboard Router — Cost & Token Observability API (Issue #392).

Endpoints for enterprise cost visibility:
  - Aggregate overview, per-agent, per-model breakdowns
  - Timeseries data (hourly/daily/weekly)
  - Top consumers ranking
  - Budget CRUD with utilization tracking
  - Active alerts
  - CSV export
"""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

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
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cost", tags=["Cost & Token Observability"])


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid ISO datetime: {value}")


# ─────────────────────────────────────────────────────────────
# Overview
# ─────────────────────────────────────────────────────────────

@router.get("/overview", response_model=CostOverviewResponse)
async def cost_overview(
    since: Optional[str] = Query(None, description="ISO datetime lower bound"),
    until: Optional[str] = Query(None, description="ISO datetime upper bound"),
):
    """Aggregate cost/token summary — total spend, total tokens, active agents."""
    meter = CostMeter.instance()
    return meter.get_overview(since=_parse_iso(since), until=_parse_iso(until))


# ─────────────────────────────────────────────────────────────
# Per-agent breakdown
# ─────────────────────────────────────────────────────────────

@router.get("/agents/{agent_id}", response_model=AgentCostResponse)
async def agent_cost(agent_id: str):
    """Per-agent cost breakdown: spend, tokens, models used."""
    meter = CostMeter.instance()
    return meter.get_agent_cost(agent_id)


# ─────────────────────────────────────────────────────────────
# Per-model breakdown
# ─────────────────────────────────────────────────────────────

@router.get("/models", response_model=List[ModelCostResponse])
async def model_breakdown():
    """Per-model cost breakdown sorted by spend descending."""
    meter = CostMeter.instance()
    return meter.get_model_breakdown()


# ─────────────────────────────────────────────────────────────
# Timeseries
# ─────────────────────────────────────────────────────────────

@router.get("/timeseries", response_model=List[TimeseriesPoint])
async def timeseries(
    granularity: str = Query("hourly", regex="^(hourly|daily|weekly)$"),
    since: Optional[str] = Query(None, description="ISO datetime lower bound"),
    until: Optional[str] = Query(None, description="ISO datetime upper bound"),
):
    """Cost over time with configurable granularity (hourly/daily/weekly)."""
    meter = CostMeter.instance()
    return meter.get_timeseries(
        granularity=granularity,
        since=_parse_iso(since),
        until=_parse_iso(until),
    )


# ─────────────────────────────────────────────────────────────
# Top consumers
# ─────────────────────────────────────────────────────────────

@router.get("/top-consumers", response_model=List[TopConsumer])
async def top_consumers(
    limit: int = Query(10, ge=1, le=100, description="Max results"),
):
    """Top agents/operations by cost."""
    meter = CostMeter.instance()
    return meter.get_top_consumers(limit=limit)


# ─────────────────────────────────────────────────────────────
# Budget CRUD
# ─────────────────────────────────────────────────────────────

@router.post("/budgets", response_model=BudgetUtilization, status_code=201)
async def create_budget(payload: BudgetCreateRequest):
    """Create a budget rule for an agent."""
    meter = CostMeter.instance()
    rule = meter.create_budget(payload)
    # Return with utilization info
    budgets = meter.list_budgets()
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
async def list_budgets():
    """List all budget rules with current utilization percentage."""
    meter = CostMeter.instance()
    return meter.list_budgets()


@router.put("/budgets/{budget_id}", response_model=BudgetUtilization)
async def update_budget(budget_id: str, payload: BudgetUpdateRequest):
    """Update an existing budget rule."""
    meter = CostMeter.instance()
    try:
        meter.update_budget(budget_id, payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="Budget not found")
    budgets = meter.list_budgets()
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
):
    """Active cost alerts — budget exceeded or approaching limit."""
    meter = CostMeter.instance()
    return meter.get_alerts(active_only=active_only)


# ─────────────────────────────────────────────────────────────
# CSV Export
# ─────────────────────────────────────────────────────────────

@router.get("/export")
async def export_csv(
    since: Optional[str] = Query(None, description="ISO datetime lower bound"),
    until: Optional[str] = Query(None, description="ISO datetime upper bound"),
):
    """Export cost records as CSV."""
    meter = CostMeter.instance()
    csv_data = meter.export_csv(since=_parse_iso(since), until=_parse_iso(until))
    return StreamingResponse(
        iter([csv_data]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=archmorph_costs.csv"},
    )
