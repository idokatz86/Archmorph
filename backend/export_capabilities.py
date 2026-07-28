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
RESTORE_CAPABILITY_SCOPE = "session:restore"
DEFAULT_EXPORT_CAPABILITY_TTL_SECONDS = 15 * 60


@dataclass(frozen=True)
class ExportCapability:
    """Validated capability metadata returned by the FastAPI dependency."""

    token_digest: str
    diagram_id: str
    scope: str
    expires_at: float
    record: dict


def _principal_marker(request: Request) -> Optional[str]:
    from routers.shared import get_request_durable_principal

    principal = get_request_durable_principal(request)
    if principal is None or not principal.get("tenant_id"):
        return None
    actor_kind = "api" if principal.get("owner_api_key_id") else "user"
    return f"{actor_kind}:{principal['tenant_id']}:{principal['owner_user_id']}"


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
    environment = (os.getenv("ENVIRONMENT") or os.getenv("ENV") or "production").lower()
    return environment not in {
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


def issue_export_capability(
    diagram_id: str,
    *,
    ttl_seconds: Optional[int] = None,
    principal_marker: Optional[str] = None,
    scope: str = EXPORT_CAPABILITY_SCOPE,
) -> str:
    """Issue an opaque, URL-safe, single-use export capability for a diagram."""
    ttl = ttl_seconds or _ttl_seconds()
    token = secrets.token_urlsafe(32)
    token_digest = _digest(token)
    expires_at = time.time() + ttl
    EXPORT_CAPABILITY_STORE.set(
        token_digest,
        {
            "diagram_id": diagram_id,
            "scope": scope,
            "principal_marker": principal_marker,
            "expires_at": expires_at,
            "issued_at": time.time(),
        },
        ttl=ttl,
    )
    _audit("issued", diagram_id, token_digest)
    return token


def attach_export_capability(payload, diagram_id: str, *, principal_marker: Optional[str] = None):
    """Return *payload* with a freshly issued ``export_capability`` field."""
    token = issue_export_capability(diagram_id, principal_marker=principal_marker)
    if isinstance(payload, dict):
        return {
            **payload,
            "export_capability": token,
            "export_capability_expires_in": _ttl_seconds(),
        }
    return payload


def consume_export_capability(capability: Optional[ExportCapability]) -> None:
    """Atomically consume a previously validated export capability."""
    if capability is None:
        return
    try:
        consumed = EXPORT_CAPABILITY_STORE.pop(capability.token_digest)
    except Exception as exc:
        _audit("consume_unconfirmed", capability.diagram_id, capability.token_digest)
        raise ArchmorphException(
            503,
            "Export capability consumption could not be confirmed",
        ) from exc
    if consumed is None or consumed != capability.record:
        _audit("consume_replayed", capability.diagram_id, capability.token_digest)
        raise ArchmorphException(401, "Invalid or replayed export capability")
    _audit("consumed", capability.diagram_id, capability.token_digest)


async def verify_export_capability(
    request: Request,
    diagram_id: str,
    x_export_capability: Optional[str] = Header(None, alias=EXPORT_CAPABILITY_HEADER),
    export_token: Optional[str] = Query(None, include_in_schema=False),
) -> Optional[ExportCapability]:
    """Validate a one-time export capability without consuming it.

    ``X-Export-Capability`` is the preferred transport because it avoids token
    leakage through URLs. ``export_token`` remains as a hidden query fallback
    for curl/manual local testing only.
    """
    if not export_capability_required():
        _audit("bypass_disabled", diagram_id)
        return None

    environment = (os.getenv("ENVIRONMENT") or os.getenv("ENV") or "production").lower()
    if export_token and environment not in {"dev", "development", "local", "test"}:
        _audit("query_token_rejected", diagram_id)
        raise ArchmorphException(400, "Query-string export capabilities are disabled outside local development")

    token = x_export_capability or export_token
    if not token:
        _audit("missing", diagram_id)
        raise ArchmorphException(401, "Missing export capability")

    token_digest = _digest(token)
    record = EXPORT_CAPABILITY_STORE.peek(token_digest)
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

    bound_principal = record.get("principal_marker")
    caller_principal = _principal_marker(request)
    if bound_principal and not secrets.compare_digest(str(bound_principal), caller_principal or ""):
        _audit("wrong_principal", diagram_id, token_digest)
        raise ArchmorphException(404, "Diagram not found")

    expires_at = float(record.get("expires_at", 0))
    if expires_at < time.time():
        EXPORT_CAPABILITY_STORE.delete(token_digest)
        _audit("expired", diagram_id, token_digest)
        raise ArchmorphException(401, "Expired export capability")

    _audit("validated", diagram_id, token_digest)
    return ExportCapability(
        token_digest=token_digest,
        diagram_id=diagram_id,
        scope=str(record.get("scope")),
        expires_at=expires_at,
        record=dict(record),
    )


def issue_restore_capability(
    request: Request,
    diagram_id: str,
    *,
    db=None,
    owner_user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    payload_hash: Optional[str] = None,
    ttl_seconds: Optional[int] = None,
) -> str:
    """Issue a signed wrapper around a server-held one-time restore nonce."""
    import jwt
    from auth import JWT_ALGORITHM, JWT_SECRET
    from database import SessionLocal
    from routers.shared import get_request_durable_principal
    from workspace_store import issue_restore_grant

    principal_marker = _principal_marker(request)
    if not principal_marker:
        raise ArchmorphException(401, "Authentication required")
    principal = get_request_durable_principal(request)
    owner_user_id = owner_user_id or (principal or {}).get("owner_user_id")
    tenant_id = tenant_id or (principal or {}).get("tenant_id")
    if not owner_user_id or not tenant_id:
        raise ArchmorphException(401, "Authentication required")
    owns_session = db is None
    db = db or SessionLocal()
    ttl = ttl_seconds or _ttl_seconds()
    try:
        nonce, generation, expected_version = issue_restore_grant(
            db,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            diagram_id=diagram_id,
            ttl_seconds=ttl,
            payload_hash=payload_hash,
        )
    except ValueError as exc:
        raise ArchmorphException(404, "Diagram not found") from exc
    finally:
        if owns_session:
            db.close()
    now = int(time.time())
    return jwt.encode(
        {
            "scope": RESTORE_CAPABILITY_SCOPE,
            "diagram_id": diagram_id,
            "principal_digest": _digest(principal_marker),
            "actor_kind": "api_key" if principal_marker.startswith("api:") else "user",
            "generation": generation,
            "expected_version": expected_version,
            "payload_hash": payload_hash,
            "nonce": nonce,
            "jti": secrets.token_urlsafe(12),
            "iat": now,
            "exp": now + ttl,
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def decode_restore_capability(request: Request, diagram_id: str, token: Optional[str]) -> Optional[dict]:
    """Validate signed restore claims without consulting diagram existence."""
    import jwt
    from auth import JWT_ALGORITHM, JWT_SECRET

    if not token:
        return None
    caller_principal = _principal_marker(request)
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        payload = {}
    valid = bool(
        payload.get("scope") == RESTORE_CAPABILITY_SCOPE
        and payload.get("diagram_id") == diagram_id
        and caller_principal
        and secrets.compare_digest(
            str(payload.get("principal_digest") or ""),
            _digest(caller_principal or ""),
        )
        and isinstance(payload.get("generation"), int)
        and isinstance(payload.get("expected_version"), int)
        and isinstance(payload.get("nonce"), str)
    )
    _audit("restore_validated" if valid else "restore_denied", diagram_id, _digest(token))
    return payload if valid else None


def verify_restore_capability(request: Request, diagram_id: str, token: Optional[str]) -> bool:
    """Compatibility predicate for callers that only inspect signed claims."""
    return decode_restore_capability(request, diagram_id, token) is not None
