"""Customer-safe data lifecycle and trust receipt helpers."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

TRUST_RECEIPT_SCHEMA_VERSION = "2026-05-25"


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


CONTENT_RETENTION_CLASS = os.getenv("ARCHMORPH_CONTENT_RETENTION_CLASS", "ephemeral-analysis")
CONTENT_RETENTION_SECONDS = _int_env("ARCHMORPH_CONTENT_RETENTION_SECONDS", 2 * 60 * 60)
AUDIT_SECURITY_LOG_RETENTION_DAYS = _int_env("ARCHMORPH_AUDIT_SECURITY_LOG_RETENTION_DAYS", 30)
PURGE_CLIENT_CACHE_TARGETS = [
    "sessionStorage:archmorph_session_<diagram_id>",
    "sessionStorage:archmorph_img_<diagram_id>",
    "sessionStorage:archmorph_session",
    "sessionStorage:archmorph_active_diagram",
    "sessionStorage:archmorph_pending_upload_reauth",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _receipt_id(diagram_id: str, generated_at: str) -> str:
    digest = hashlib.sha256(f"{diagram_id}:{generated_at}".encode("utf-8")).hexdigest()
    return f"tr-{digest[:16]}"


def _default_artifacts(image_present: bool, session_present: bool, project_present: bool) -> Dict[str, Any]:
    return {
        "uploaded_content": "present" if image_present else "not_present",
        "analysis_session": "present" if session_present else "not_present",
        "project_index": "tracked" if project_present else "not_present",
        "share_links": "not_checked",
        "export_capabilities": "not_checked",
        "async_jobs": "not_checked",
        "iac_chat": "not_checked",
    }


def build_trust_receipt(
    diagram_id: str,
    *,
    project_id: Optional[str] = None,
    uploaded_at: Optional[str] = None,
    generated_at: Optional[datetime] = None,
    image_present: bool = False,
    session_present: bool = False,
    export_capability_expires_in: Optional[int] = None,
    artifact_status: Optional[Dict[str, Any]] = None,
    purge: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a customer-safe receipt for one diagram analysis lifecycle."""
    now = generated_at or _now()
    generated_iso = _iso(now)
    uploaded_dt = _parse_iso(uploaded_at)
    expires_at = _iso(uploaded_dt + timedelta(seconds=CONTENT_RETENTION_SECONDS)) if uploaded_dt else None
    purge_status = purge.get("status") if isinstance(purge, dict) else "not_requested"

    return {
        "schema_version": TRUST_RECEIPT_SCHEMA_VERSION,
        "receipt_id": _receipt_id(diagram_id, generated_iso),
        "generated_at": generated_iso,
        "correlation_id": diagram_id,
        "diagram_id": diagram_id,
        "project_id": project_id,
        "status": "purged" if purge_status == "purged" else "active",
        "retention": {
            "class": CONTENT_RETENTION_CLASS,
            "customer_content_ttl_seconds": CONTENT_RETENTION_SECONDS,
            "uploaded_at": _iso(uploaded_dt) if uploaded_dt else None,
            "expires_at": expires_at,
        },
        "export_capability": {
            "status": "issued" if export_capability_expires_in else "not_issued",
            "expires_in_seconds": export_capability_expires_in,
        },
        "ai_processing": {
            "processor": "Azure OpenAI",
            "purpose": "architecture analysis and Azure migration mapping",
            "training_use": "not_used_by_archmorph_for_model_training",
        },
        "artifacts": artifact_status or _default_artifacts(image_present, session_present, bool(project_id)),
        "purge": purge or {
            "status": "not_requested",
            "server_content_deleted": False,
            "client_cache_action": "clear_session_storage_after_successful_purge",
            "client_cache_targets": PURGE_CLIENT_CACHE_TARGETS,
        },
        "audit_security_logs": {
            "retained": True,
            "retention_class": "security-audit",
            "retention_days": AUDIT_SECURITY_LOG_RETENTION_DAYS,
            "contains_customer_content": False,
            "scope": "operational metadata such as correlation id, project id, event type, and deletion outcome",
        },
    }


def attach_trust_receipt(payload: Dict[str, Any], diagram_id: str, **kwargs: Any) -> Dict[str, Any]:
    """Return payload with a trust_receipt field added."""
    payload["trust_receipt"] = build_trust_receipt(diagram_id, **kwargs)
    return payload