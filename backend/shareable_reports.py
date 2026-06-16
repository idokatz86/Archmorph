"""
Archmorph Shareable Reports — Role-based stakeholder report engine.

Generates unique shareable URLs for analysis results with filtered views
for executive, architect, DevOps, security, and FinOps stakeholders.

Sensitive fields (raw session IDs, bearer tokens) are redacted before the
snapshot is stored so that public share links never expose internal secrets.
Artifact visibility (customer-private vs public sample) is preserved in the
share record so UI can display the correct badge.

Thread-safe via RLock. In-memory storage with configurable TTL.
"""

import threading
import secrets
import base64
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Literal, Optional

logger = logging.getLogger(__name__)

_lock = threading.RLock()

# share_id -> share record
_shares: Dict[str, Dict[str, Any]] = {}

# Max shares to prevent unbounded growth
MAX_SHARES = 500
DEFAULT_EXPIRY_DAYS = 30

ViewType = Literal[
    "executive",
    "architect",
    "devops",
    "security",
    "finops",
    # Legacy aliases kept for backward compatibility
    "technical",
    "financial",
]

# Regex patterns for sensitive values that must never appear in share snapshots.
# Matches common token/secret patterns: Bearer tokens, base64-ish JWT segments,
# UUIDs used as session keys, and archmorph_session_token-style values.
_SENSITIVE_KEY_RE = re.compile(
    r"(token|secret|password|bearer|session_id|api_key|credential|private_key)",
    re.IGNORECASE,
)
_SENSITIVE_VALUE_RE = re.compile(
    r"^(Bearer\s+\S+|ey[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}(\.[A-Za-z0-9_\-]*)?)$"
)


def _redact_value(value: Any) -> Any:
    """Return a redacted placeholder if *value* looks like a secret string."""
    if isinstance(value, str) and _SENSITIVE_VALUE_RE.match(value):
        return "[REDACTED]"
    return value


def _redact_sensitive(obj: Any, _depth: int = 0) -> Any:
    """Recursively redact keys or values that appear to be secrets.

    Traverses dicts/lists up to depth 10 to avoid unbounded recursion on
    pathological inputs.  Keys matching _SENSITIVE_KEY_RE have their values
    replaced with ``[REDACTED]`` regardless of format.
    """
    if _depth > 10:
        return obj
    if isinstance(obj, dict):
        result: Dict[str, Any] = {}
        for k, v in obj.items():
            if isinstance(k, str) and _SENSITIVE_KEY_RE.search(k):
                result[k] = "[REDACTED]"
            else:
                result[k] = _redact_sensitive(v, _depth + 1)
        return result
    if isinstance(obj, list):
        return [_redact_sensitive(item, _depth + 1) for item in obj]
    return _redact_value(obj)


def _generate_share_id() -> str:
    """Generate an 8-char URL-safe base64 short ID."""
    return base64.urlsafe_b64encode(secrets.token_bytes(6)).decode("ascii")


def create_share(
    analysis_snapshot: Dict[str, Any],
    creator_id: Optional[str] = None,
    creator_tenant_id: Optional[str] = None,
    creator_api_principal_id: Optional[str] = None,
    expiry_days: int = DEFAULT_EXPIRY_DAYS,
    is_sample: bool = False,
) -> Dict[str, Any]:
    """Create a shareable report from an analysis snapshot.

    Sensitive values (raw tokens, session IDs) are redacted from the stored
    snapshot so that public share links never expose internal secrets.

    ``is_sample`` marks the snapshot as a public demo artifact so the UI can
    display a distinct badge for customer-private vs public sample content.

    Returns the share record including share_id and share_url.
    """
    now = datetime.now(timezone.utc)
    share_id = _generate_share_id()

    # Redact any sensitive values before storage
    safe_snapshot = _redact_sensitive(analysis_snapshot)

    record = {
        "share_id": share_id,
        "analysis_snapshot": safe_snapshot,
        "creator_id": creator_id,
        "creator_tenant_id": creator_tenant_id,
        "creator_api_principal_id": creator_api_principal_id,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(days=expiry_days)).isoformat(),
        "view_count": 0,
        "is_sample": bool(is_sample),
        "revoked": False,
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
        "is_sample": record["is_sample"],
    }


def get_share(share_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a share record, returning None if expired, revoked, or missing."""
    with _lock:
        record = _shares.get(share_id)
        if record is None:
            return None
        # Treat manually revoked shares as expired/missing
        if record.get("revoked"):
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
            "creator_tenant_id": record.get("creator_tenant_id"),
            "creator_api_principal_id": record.get("creator_api_principal_id"),
            "is_sample": record.get("is_sample", False),
            "revoked": record.get("revoked", False),
        }


def delete_share(share_id: str) -> bool:
    """Revoke a share link. Marks as revoked rather than deleting so audit
    trails and use-after-revocation detection remain possible.
    Returns True if the share existed (whether or not already revoked)."""
    with _lock:
        record = _shares.get(share_id)
        if record is None:
            return False
        record["revoked"] = True
        return True


def purge_diagram_shares(diagram_id: str) -> int:
    """Delete share links whose snapshots are tied to *diagram_id*."""
    removed = 0
    with _lock:
        for share_id, record in list(_shares.items()):
            snapshot = record.get("analysis_snapshot") or {}
            if snapshot.get("diagram_id") == diagram_id:
                del _shares[share_id]
                removed += 1
    return removed


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


def _extract_architect_view(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Architect review: service mappings, dependency graph, architecture decisions.

    No raw IaC code is included; only a preview summary is exposed so that
    internal implementation details stay out of stakeholder share links.
    """
    services = snapshot.get("services", [])
    iac_raw = snapshot.get("iac_code", snapshot.get("iac", {}).get("preview"))
    # Only surface a short preview (first 500 chars) to avoid leaking full templates
    iac_preview: Optional[str] = (iac_raw[:500] + "…") if isinstance(iac_raw, str) and len(iac_raw) > 500 else iac_raw
    return {
        "view": "architect",
        "source_cloud": snapshot.get("source_cloud", "unknown"),
        "target_cloud": snapshot.get("target_cloud", "azure"),
        "services": [
            {
                "source_service": svc.get("source_service", svc.get("name", "unknown")),
                "azure_service": svc.get("azure_service", svc.get("target_service", "")),
                "confidence": svc.get("confidence"),
                "notes": svc.get("notes", svc.get("migration_notes")),
            }
            for svc in services
        ],
        "service_mappings": snapshot.get("service_mappings", snapshot.get("mappings", [])),
        "dependency_graph": snapshot.get("dependency_graph", snapshot.get("dependencies", [])),
        "sku_translations": snapshot.get("sku_translations", []),
        "iac_format": snapshot.get("iac_format"),
        "iac_preview": iac_preview,
        "architecture_decisions": snapshot.get("architecture_decisions", snapshot.get("decisions", [])),
        "dr_readiness": snapshot.get("dr_readiness"),
        "alz_profile": snapshot.get("alz_profile"),
    }


def _extract_devops_view(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """DevOps / IaC handoff view: infrastructure config and deployment notes.

    Exposes enough for a DevOps engineer to understand the target IaC shape
    without surfacing raw bearer tokens, session IDs, or export credentials.
    """
    iac_raw = snapshot.get("iac_code", snapshot.get("iac", {}).get("preview"))
    iac_hash = snapshot.get("iac_code_hash", snapshot.get("iac_hash"))
    iac_format = snapshot.get("iac_format", "terraform")
    return {
        "view": "devops",
        "source_cloud": snapshot.get("source_cloud", "unknown"),
        "target_cloud": snapshot.get("target_cloud", "azure"),
        "iac_format": iac_format,
        "iac_code": iac_raw,
        "iac_code_hash": iac_hash,
        "services": [
            {
                "source_service": svc.get("source_service", svc.get("name", "unknown")),
                "azure_service": svc.get("azure_service", svc.get("target_service", "")),
                "iac_resource_type": svc.get("iac_resource_type"),
                "region": svc.get("region"),
                "tier": svc.get("tier"),
            }
            for svc in snapshot.get("services", [])
        ],
        "deployment_notes": snapshot.get("deployment_notes", snapshot.get("next_steps", [])),
        "regions": snapshot.get("regions", []),
        "landing_zone": snapshot.get("landing_zone", snapshot.get("alz_profile")),
    }


def _extract_security_view(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Security / risk view: compliance gaps, risk scores, security findings.

    Does not expose raw credentials, export tokens, or session data.
    """
    risk = snapshot.get("risk", {}) if isinstance(snapshot.get("risk"), dict) else {}
    compliance = snapshot.get("compliance", {}) if isinstance(snapshot.get("compliance"), dict) else {}
    return {
        "view": "security",
        "source_cloud": snapshot.get("source_cloud", "unknown"),
        "target_cloud": snapshot.get("target_cloud", "azure"),
        "risk_score": snapshot.get("risk_score", risk.get("score")),
        "risk_level": snapshot.get("risk_level", risk.get("level")),
        "risk_factors": snapshot.get("risk_factors", risk.get("factors", [])),
        "compliance_gaps": snapshot.get(
            "compliance_gaps",
            compliance.get("gaps", []),
        ),
        "compliance_frameworks": snapshot.get(
            "compliance_frameworks",
            compliance.get("frameworks", []),
        ),
        "security_findings": snapshot.get("security_findings", []),
        "data_classification": snapshot.get("data_classification"),
        "network_exposure": snapshot.get("network_exposure"),
        "encryption_status": snapshot.get("encryption_status"),
        "identity_model": snapshot.get("identity_model"),
        "risks_and_mitigations": snapshot.get("risks_and_mitigations", []),
    }


def _extract_finops_view(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """FinOps / cost view: cost breakdown, RI savings, TCO, per-service costs."""
    cost = snapshot.get("cost_estimate", snapshot.get("cost", {}))
    if not isinstance(cost, dict):
        cost = {}
    services = snapshot.get("services", [])
    per_service: List[Dict[str, Any]] = []
    for svc in services:
        svc_cost = svc.get("cost") or svc.get("estimated_cost") or {}
        per_service.append({
            "service": svc.get("name") or svc.get("source_service", "unknown"),
            "azure_service": svc.get("azure_service") or svc.get("target_service", ""),
            "monthly_cost": (
                svc_cost.get("monthly", svc_cost)
                if isinstance(svc_cost, dict)
                else svc_cost
            ),
            "annual_cost": svc_cost.get("annual") if isinstance(svc_cost, dict) else None,
            "sku": svc.get("sku") or svc.get("tier"),
        })

    return {
        "view": "finops",
        "cost_breakdown": {
            "total_monthly": cost.get("total_monthly", cost.get("total", 0)),
            "total_annual": cost.get("total_annual"),
            "currency": cost.get("currency", "USD"),
            "per_service": per_service,
        },
        "ri_savings": snapshot.get("ri_savings", snapshot.get("reserved_instance_savings")),
        "tco_comparison": snapshot.get(
            "tco_comparison",
            {"note": "TCO comparison requires source cloud cost data"},
        ),
        "cost_assumptions": snapshot.get("cost_assumptions", []),
        "savings_opportunities": snapshot.get("savings_opportunities", []),
        "budget_alert": snapshot.get("budget_alert"),
    }


_VIEW_EXTRACTORS = {
    "executive": _extract_executive_view,
    "architect": _extract_architect_view,
    "devops": _extract_devops_view,
    "security": _extract_security_view,
    "finops": _extract_finops_view,
    # Legacy aliases — kept for backward compatibility
    "technical": _extract_technical_view,
    "financial": _extract_financial_view,
}


def render_view(
    snapshot: Dict[str, Any],
    view_type: Optional[ViewType] = None,
) -> Dict[str, Any]:
    """Render an analysis snapshot filtered by view type.

    Supports the five role-based views (executive, architect, devops, security,
    finops) as well as the legacy aliases (technical, financial).

    If view_type is None, returns all canonical role views.
    """
    if view_type and view_type in _VIEW_EXTRACTORS:
        return _VIEW_EXTRACTORS[view_type](snapshot)

    # Default: return all canonical role views (exclude legacy aliases)
    canonical = ("executive", "architect", "devops", "security", "finops")
    return {
        "views": {
            vt: _VIEW_EXTRACTORS[vt](snapshot)
            for vt in canonical
        },
    }
