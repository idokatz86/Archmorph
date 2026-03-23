"""
Archmorph Shareable Reports — Role-based stakeholder report engine.

Generates unique shareable URLs for analysis results with filtered views
for executive, technical, and financial stakeholders.

Thread-safe via RLock. In-memory storage with configurable TTL.
"""

import threading
import secrets
import base64
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Literal, Optional

logger = logging.getLogger(__name__)

_lock = threading.RLock()

# share_id -> share record
_shares: Dict[str, Dict[str, Any]] = {}

# Max shares to prevent unbounded growth
MAX_SHARES = 500
DEFAULT_EXPIRY_DAYS = 30

ViewType = Literal["executive", "technical", "financial"]


def _generate_share_id() -> str:
    """Generate an 8-char URL-safe base64 short ID."""
    return base64.urlsafe_b64encode(secrets.token_bytes(6)).decode("ascii")


def create_share(
    analysis_snapshot: Dict[str, Any],
    creator_id: Optional[str] = None,
    expiry_days: int = DEFAULT_EXPIRY_DAYS,
) -> Dict[str, Any]:
    """Create a shareable report from an analysis snapshot.

    Returns the share record including share_id and share_url.
    """
    now = datetime.now(timezone.utc)
    share_id = _generate_share_id()

    record = {
        "share_id": share_id,
        "analysis_snapshot": analysis_snapshot,
        "creator_id": creator_id,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(days=expiry_days)).isoformat(),
        "view_count": 0,
    }

    with _lock:
        # Evict oldest if at capacity
        if len(_shares) >= MAX_SHARES:
            oldest_key = next(iter(_shares))
            del _shares[oldest_key]
        _shares[share_id] = record

    return {
        "share_id": share_id,
        "share_url": f"/shared/{share_id}",
        "created_at": record["created_at"],
        "expires_at": record["expires_at"],
    }


def get_share(share_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a share record, returning None if expired or missing."""
    with _lock:
        record = _shares.get(share_id)
        if record is None:
            return None
        # Check expiry
        expires_at = datetime.fromisoformat(record["expires_at"])
        if datetime.now(timezone.utc) > expires_at:
            del _shares[share_id]
            return None
        record["view_count"] += 1
        return record


def get_share_stats(share_id: str) -> Optional[Dict[str, Any]]:
    """Return stats for a share without incrementing view count."""
    with _lock:
        record = _shares.get(share_id)
        if record is None:
            return None
        return {
            "share_id": share_id,
            "view_count": record["view_count"],
            "created_at": record["created_at"],
            "expires_at": record["expires_at"],
            "creator_id": record["creator_id"],
        }


def delete_share(share_id: str) -> bool:
    """Revoke a share link. Returns True if it existed."""
    with _lock:
        return _shares.pop(share_id, None) is not None


# ─────────────────────────────────────────────────────────────
# Role-Based View Filtering
# ─────────────────────────────────────────────────────────────

def _extract_executive_view(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Executive view: high-level summary, no code or technical details."""
    services = snapshot.get("services", [])
    cost = snapshot.get("cost_estimate", snapshot.get("cost", {}))
    return {
        "view": "executive",
        "summary": {
            "source_cloud": snapshot.get("source_cloud", "unknown"),
            "target_cloud": snapshot.get("target_cloud", "azure"),
            "service_count": len(services),
            "title": snapshot.get("title", "Cloud Migration Analysis"),
        },
        "cost_estimate": {
            "total_monthly": cost.get("total_monthly", cost.get("total", 0)),
            "currency": cost.get("currency", "USD"),
        },
        "timeline": snapshot.get("timeline", snapshot.get("roadmap", {})),
        "risk_score": snapshot.get("risk_score", snapshot.get("risk", {}).get("score")),
        "confidence_overview": {
            "average": snapshot.get("confidence_avg"),
            "high_count": sum(
                1 for s in services
                if (s.get("confidence") or 0) >= 80
            ),
            "low_count": sum(
                1 for s in services
                if (s.get("confidence") or 0) < 50
            ),
        },
    }


def _extract_technical_view(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Technical view: full service mappings, IaC preview, dependency graph."""
    return {
        "view": "technical",
        "services": snapshot.get("services", []),
        "service_mappings": snapshot.get("service_mappings", snapshot.get("mappings", [])),
        "iac_preview": snapshot.get("iac_code", snapshot.get("iac", {}).get("preview")),
        "dependency_graph": snapshot.get("dependency_graph", snapshot.get("dependencies", [])),
        "sku_translations": snapshot.get("sku_translations", []),
        "compliance_gaps": snapshot.get("compliance_gaps", snapshot.get("compliance", {}).get("gaps", [])),
        "source_cloud": snapshot.get("source_cloud", "unknown"),
        "target_cloud": snapshot.get("target_cloud", "azure"),
    }


def _extract_financial_view(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Financial view: cost breakdown, savings analysis, TCO."""
    cost = snapshot.get("cost_estimate", snapshot.get("cost", {}))
    services = snapshot.get("services", [])
    per_service = []
    for svc in services:
        svc_cost = svc.get("cost") or svc.get("estimated_cost") or {}
        per_service.append({
            "service": svc.get("name") or svc.get("source_service", "unknown"),
            "azure_service": svc.get("azure_service") or svc.get("target_service", ""),
            "monthly_cost": svc_cost.get("monthly", svc_cost) if isinstance(svc_cost, dict) else svc_cost,
        })

    return {
        "view": "financial",
        "cost_breakdown": {
            "total_monthly": cost.get("total_monthly", cost.get("total", 0)),
            "currency": cost.get("currency", "USD"),
            "per_service": per_service,
        },
        "ri_savings": snapshot.get("ri_savings", snapshot.get("reserved_instance_savings")),
        "tco_comparison": snapshot.get("tco_comparison", {
            "note": "TCO comparison requires source cloud cost data",
        }),
    }


_VIEW_EXTRACTORS = {
    "executive": _extract_executive_view,
    "technical": _extract_technical_view,
    "financial": _extract_financial_view,
}


def render_view(
    snapshot: Dict[str, Any],
    view_type: Optional[ViewType] = None,
) -> Dict[str, Any]:
    """Render an analysis snapshot filtered by view type.

    If view_type is None, returns all three views.
    """
    if view_type and view_type in _VIEW_EXTRACTORS:
        return _VIEW_EXTRACTORS[view_type](snapshot)

    return {
        "views": {
            vt: extractor(snapshot)
            for vt, extractor in _VIEW_EXTRACTORS.items()
        },
    }
