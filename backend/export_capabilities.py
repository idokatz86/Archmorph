"""One-time capability tokens for generated artifact exports (#671)."""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import time
from dataclasses import dataclass
from typing import Optional

from fastapi import Header, Query, Request

from error_envelope import ArchmorphException
from routers.shared import EXPORT_CAPABILITY_STORE

logger = logging.getLogger(__name__)

EXPORT_CAPABILITY_HEADER = "X-Export-Capability"
EXPORT_CAPABILITY_SCOPE = "artifact:export"
DEFAULT_EXPORT_CAPABILITY_TTL_SECONDS = 15 * 60


@dataclass(frozen=True)
class ExportCapability:
    """Validated capability metadata returned by the FastAPI dependency."""

    token_digest: str
    diagram_id: str
    scope: str
    expires_at: float


def _ttl_seconds() -> int:
    raw = os.getenv(
        "EXPORT_CAPABILITY_TTL_SECONDS",
        str(DEFAULT_EXPORT_CAPABILITY_TTL_SECONDS),
    )
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_EXPORT_CAPABILITY_TTL_SECONDS


def export_capability_required() -> bool:
    """Return whether export capability checks are enforced.

    Production/staging default to fail-closed. Local development can opt out
    explicitly with ``ARCHMORPH_EXPORT_CAPABILITY_REQUIRED=false`` for manual
    API exploration and old scripts.
    """
    raw = os.getenv("ARCHMORPH_EXPORT_CAPABILITY_REQUIRED")
    if raw is not None:
        return raw.strip().lower() not in {"0", "false", "no", "off"}
    return os.getenv("ENVIRONMENT", "production").lower() not in {
        "dev",
        "development",
        "local",
        "test",
    }


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _audit(reason: str, diagram_id: str, token_digest: Optional[str] = None) -> None:
    details = {"diagram_id": diagram_id, "reason": reason}
    if token_digest:
        details["token_digest_prefix"] = token_digest[:12]
    try:
        from usage_metrics import record_event

        record_event("export_capability_audit", details)
    except Exception:  # pragma: no cover - audit must not block auth decisions
        logger.debug("export capability audit failed", exc_info=True)


def issue_export_capability(diagram_id: str, *, ttl_seconds: Optional[int] = None) -> str:
    """Issue an opaque, URL-safe, single-use export capability for a diagram."""
    ttl = ttl_seconds or _ttl_seconds()
    token = secrets.token_urlsafe(32)
    token_digest = _digest(token)
    expires_at = time.time() + ttl
    EXPORT_CAPABILITY_STORE.set(
        token_digest,
        {
            "diagram_id": diagram_id,
            "scope": EXPORT_CAPABILITY_SCOPE,
            "expires_at": expires_at,
            "issued_at": time.time(),
        },
        ttl=ttl,
    )
    _audit("issued", diagram_id, token_digest)
    return token


def attach_export_capability(payload, diagram_id: str):
    """Return *payload* with a freshly issued ``export_capability`` field."""
    token = issue_export_capability(diagram_id)
    if isinstance(payload, dict):
        return {
            **payload,
            "export_capability": token,
            "export_capability_expires_in": _ttl_seconds(),
        }
    return payload


async def verify_export_capability(
    request: Request,
    diagram_id: str,
    x_export_capability: Optional[str] = Header(None, alias=EXPORT_CAPABILITY_HEADER),
    export_token: Optional[str] = Query(None, include_in_schema=False),
) -> Optional[ExportCapability]:
    """Validate and consume a one-time export capability.

    ``X-Export-Capability`` is the preferred transport because it avoids token
    leakage through URLs. ``export_token`` remains as a hidden query fallback
    for curl/manual local testing.
    """
    if not export_capability_required():
        _audit("bypass_disabled", diagram_id)
        return None

    token = x_export_capability or export_token
    if not token:
        _audit("missing", diagram_id)
        raise ArchmorphException(401, "Missing export capability")

    token_digest = _digest(token)
    record = EXPORT_CAPABILITY_STORE.get(token_digest)
    if not record:
        _audit("unknown_or_replayed", diagram_id, token_digest)
        raise ArchmorphException(401, "Invalid or replayed export capability")

    if record.get("scope") != EXPORT_CAPABILITY_SCOPE:
        EXPORT_CAPABILITY_STORE.delete(token_digest)
        _audit("wrong_scope", diagram_id, token_digest)
        raise ArchmorphException(403, "Export capability is not authorized for this operation")

    if record.get("diagram_id") != diagram_id:
        _audit("wrong_diagram", diagram_id, token_digest)
        raise ArchmorphException(403, "Export capability is not authorized for this diagram")

    expires_at = float(record.get("expires_at", 0))
    if expires_at < time.time():
        EXPORT_CAPABILITY_STORE.delete(token_digest)
        _audit("expired", diagram_id, token_digest)
        raise ArchmorphException(401, "Expired export capability")

    EXPORT_CAPABILITY_STORE.delete(token_digest)
    _audit("validated", diagram_id, token_digest)
    return ExportCapability(
        token_digest=token_digest,
        diagram_id=diagram_id,
        scope=str(record.get("scope")),
        expires_at=expires_at,
    )
