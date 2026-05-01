"""
Admin Retention Routes — Sprint 0 (Retention Initiative E6).

Exposes Day-7 first-time-user return rate to the admin dashboard.

Endpoints (mirrored at /api/v1/* by the v1 aggregator):
  - GET  /api/admin/retention/day7      — single-cohort summary (default = D-7)
  - GET  /api/admin/retention/baseline  — rolling N-day baseline
  - GET  /api/admin/retention/taxonomy  — canonical event taxonomy

All endpoints require admin auth via ``Depends(verify_admin_key)``.
Aggregate output only — no per-user data is returned.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from error_envelope import ArchmorphException
from routers.shared import limiter, verify_admin_key

import retention as retention_mod

logger = logging.getLogger(__name__)

router = APIRouter()


def _parse_iso_day(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ArchmorphException(400, f"Invalid date '{value}': expected YYYY-MM-DD") from exc


@router.get("/api/admin/retention/day7")
@limiter.limit("30/minute")
async def admin_retention_day7(
    request: Request,
    cohort_day: Optional[str] = Query(
        None,
        description="Cohort day in YYYY-MM-DD (UTC). Defaults to D-7 (today minus 7).",
    ),
    window_days: int = Query(
        1, ge=0, le=3,
        description="±N days around D+7 to count as a return. Default 1 (days 6/7/8).",
    ),
    _admin=Depends(verify_admin_key),
):
    """Day-7 return rate for a single cohort day."""
    parsed = _parse_iso_day(cohort_day)
    if parsed is None:
        parsed = (datetime.now(timezone.utc).date() - timedelta(days=7))
    result = retention_mod.compute_day7_return_rate(
        cohort_day=parsed, window_days=window_days
    )
    return {
        "enabled": retention_mod.ENABLED,
        "result": result.to_dict(),
        "kpi_target": 0.35,
    }


@router.get("/api/admin/retention/baseline")
@limiter.limit("30/minute")
async def admin_retention_baseline(
    request: Request,
    lookback_days: int = Query(
        30, ge=1, le=90,
        description="Number of cohort days (each >= 7 days old) to aggregate.",
    ),
    _admin=Depends(verify_admin_key),
):
    """Rolling baseline of Day-7 return rate across the last N completed cohorts."""
    return retention_mod.get_baseline(lookback_days=lookback_days)


@router.get("/api/admin/retention/taxonomy")
@limiter.limit("30/minute")
async def admin_retention_taxonomy(
    request: Request,
    _admin=Depends(verify_admin_key),
):
    """Canonical event taxonomy for Sprint 0 instrumentation."""
    return {
        "events": retention_mod.get_event_taxonomy(),
        "version": "1.0.0",
        "source": "docs/EVENT_TAXONOMY.md",
    }
