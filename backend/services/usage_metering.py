"""Usage Metering Service for Stripe billing (Issue #106).

Tracks per-organization & per-user usage, enforces quotas, and
reports usage to Stripe for metered billing (if configured).
"""

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# Stripe metered billing config
# ─────────────────────────────────────────────────────────
STRIPE_METER_ANALYSIS = os.getenv("STRIPE_METER_ANALYSIS", "")
STRIPE_METER_IAC = os.getenv("STRIPE_METER_IAC", "")
STRIPE_METER_HLD = os.getenv("STRIPE_METER_HLD", "")

_stripe_available = False
try:
    import stripe
    if os.getenv("STRIPE_SECRET_KEY"):
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
        _stripe_available = True
except ImportError:
    pass


# ─────────────────────────────────────────────────────────
# In-memory usage tracking (replaced by DB in prod)
# ─────────────────────────────────────────────────────────
_usage: Dict[str, Dict[str, int]] = {}  # key = org_id:YYYY-MM → {metric: count}
_lock = threading.Lock()

METRICS = [
    "analyses",
    "iac_downloads",
    "hld_generations",
    "cost_estimates",
    "ai_suggestions",
    "risk_scores",
    "compliance_checks",
    "infra_imports",
]


def _usage_key(org_id: str) -> str:
    """Monthly partition key: org_id:YYYY-MM."""
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return f"{org_id}:{month}"


def record_usage(
    org_id: str,
    metric: str,
    count: int = 1,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Record usage for an organization.

    Parameters
    ----------
    org_id : str
        Organization ID.
    metric : str
        Metric name (e.g. "analyses", "iac_downloads").
    count : int
        Number of units to record.
    user_id : str, optional
        User who triggered the usage.

    Returns
    -------
    dict
        Current usage for the metric this month.
    """
    key = _usage_key(org_id)

    with _lock:
        if key not in _usage:
            _usage[key] = {m: 0 for m in METRICS}
        _usage[key][metric] = _usage[key].get(metric, 0) + count

    current = _usage[key][metric]

    # Report to Stripe metered billing (async, non-blocking)
    _report_to_stripe(org_id, metric, count)

    logger.debug(
        "Usage recorded: org=%s metric=%s count=%d total=%d user=%s",
        org_id, metric, count, current, user_id,
    )

    return {"org_id": org_id, "metric": metric, "current": current, "period": key.split(":")[1]}


def get_usage(org_id: str) -> Dict[str, Any]:
    """Get current month's usage for an organization."""
    key = _usage_key(org_id)
    with _lock:
        usage = _usage.get(key, {m: 0 for m in METRICS})
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return {
        "org_id": org_id,
        "period": month,
        "usage": dict(usage),
    }


def check_quota(
    org_id: str,
    metric: str,
    limit: int,
) -> Dict[str, Any]:
    """Check if usage is within quota.

    Returns
    -------
    dict
        allowed: bool, current: int, limit: int, remaining: int
    """
    key = _usage_key(org_id)
    with _lock:
        current = _usage.get(key, {}).get(metric, 0)

    remaining = max(0, limit - current)
    return {
        "allowed": current < limit,
        "current": current,
        "limit": limit,
        "remaining": remaining,
        "metric": metric,
    }


def reset_usage(org_id: str, metric: Optional[str] = None) -> None:
    """Reset usage counters (for testing or admin override)."""
    key = _usage_key(org_id)
    with _lock:
        if key in _usage:
            if metric:
                _usage[key][metric] = 0
            else:
                _usage[key] = {m: 0 for m in METRICS}


def get_all_usage_stats() -> Dict[str, Any]:
    """Admin: get usage stats across all organizations."""
    with _lock:
        total_orgs = len(set(k.split(":")[0] for k in _usage.keys()))
        total_usage = {}
        for key, metrics in _usage.items():
            for m, v in metrics.items():
                total_usage[m] = total_usage.get(m, 0) + v

    return {
        "total_organizations": total_orgs,
        "aggregate_usage": total_usage,
        "period": datetime.now(timezone.utc).strftime("%Y-%m"),
    }


def _report_to_stripe(org_id: str, metric: str, count: int) -> None:
    """Report usage to Stripe for metered billing (best-effort)."""
    if not _stripe_available:
        return

    meter_map = {
        "analyses": STRIPE_METER_ANALYSIS,
        "iac_downloads": STRIPE_METER_IAC,
        "hld_generations": STRIPE_METER_HLD,
    }

    meter_id = meter_map.get(metric)
    if not meter_id:
        return

    try:
        stripe.billing.MeterEvent.create(
            event_name=meter_id,
            payload={
                "value": str(count),
                "stripe_customer_id": org_id,
            },
        )
    except Exception as e:
        logger.warning("Failed to report usage to Stripe: %s", e)
