"""One-time capability tokens for generated artifact exports (#671)."""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import time
from dataclasses import dataclass
from functools import partial
from typing import Optional

from fastapi import Header, Request
from starlette.concurrency import run_in_threadpool

from error_envelope import ArchmorphException
from routers.shared import EXPORT_CAPABILITY_STORE

logger = logging.getLogger(__name__)

EXPORT_CAPABILITY_HEADER = "X-Export-Capability"
EXPORT_CAPABILITY_SCOPE = "artifact:export"
EXPORT_CAPABILITY_ANY_FORMAT = "*"
EXPORT_CAPABILITY_ANY_INTENT = EXPORT_CAPABILITY_SCOPE
RESTORE_CAPABILITY_SCOPE = "session:restore"
DEFAULT_EXPORT_CAPABILITY_TTL_SECONDS = 15 * 60

_EXPORT_ROUTE_CONTRACTS = frozenset(
    {
        ("architecture_diagram", "excalidraw"),
        ("architecture_diagram", "drawio"),
        ("architecture_diagram", "vsdx"),
        ("architecture_diagram", "landing-zone-svg"),
        ("architecture_package", "html"),
        ("architecture_package", "svg"),
        ("hld", "docx"),
        ("hld", "pdf"),
        ("hld", "pptx"),
        ("migration_package", "zip"),
        ("analysis_report", "pdf"),
        ("cost_estimate", "csv"),
        ("migration_timeline", "json"),
        ("migration_timeline", "md"),
        ("migration_timeline", "csv"),
    }
)


@dataclass(frozen=True)
class ExportCapability:
    """Validated capability metadata returned by the FastAPI dependency."""

    token_digest: str
    diagram_id: str
    scope: str
    expires_at: float
    record: dict


@dataclass(frozen=True)
class ExportCapabilityBinding:
    """Secret-free canonical scope attached to a private export capability."""

    principal_marker: str
    owner_user_id: str
    tenant_id: str
    analysis_id: str
    project_id: str
    analysis_version: int

    def to_record(self) -> dict:
        return {
            "binding_version": 1,
            "principal_marker": self.principal_marker,
            "owner_user_id": self.owner_user_id,
            "tenant_id": self.tenant_id,
            "analysis_id": self.analysis_id,
            "project_id": self.project_id,
            "analysis_version": self.analysis_version,
        }


def _principal_marker(request: Request) -> Optional[str]:
    from routers.shared import get_request_durable_principal

    principal = get_request_durable_principal(request)
    if principal is None or not principal.get("tenant_id"):
        return None
    actor_kind = "api" if principal.get("owner_api_key_id") else "user"
    return f"{actor_kind}:{principal['tenant_id']}:{principal['owner_user_id']}"


def _principal_marker_from_identity(
    *,
    owner_user_id: str,
    tenant_id: str,
    owner_api_key_id: Optional[str],
) -> str:
    actor_kind = "api" if owner_api_key_id else "user"
    return f"{actor_kind}:{tenant_id}:{owner_user_id}"


def _normalize_route_path(path: str) -> str:
    if path.startswith("/api/v1/"):
        return "/api/" + path[len("/api/v1/") :]
    return path


def _request_export_contract(request: Request) -> tuple[str, str]:
    """Return the bounded export intent/format represented by a route call."""
    route = request.scope.get("route")
    path = _normalize_route_path(getattr(route, "path", request.url.path))
    query = request.query_params
    if path.endswith("/export-diagram"):
        return "architecture_diagram", query.get("format", "excalidraw").lower()
    if path.endswith("/export-architecture-package"):
        return "architecture_package", query.get("format", "html").lower()
    if path.endswith("/export-hld"):
        return "hld", query.get("format", "").lower()
    if path.endswith("/export-package"):
        return "migration_package", "zip"
    if path.endswith("/report"):
        return "analysis_report", query.get("format", "pdf").lower()
    if path.endswith("/cost-estimate/export"):
        return "cost_estimate", "csv"
    if path.endswith("/migration-timeline/export"):
        return "migration_timeline", query.get("format", "json").lower()
    return EXPORT_CAPABILITY_ANY_INTENT, EXPORT_CAPABILITY_ANY_FORMAT


def _resolve_durable_binding_for_identity(
    diagram_id: str,
    *,
    caller_owner_user_id: str,
    tenant_id: str,
    owner_api_key_id: Optional[str],
) -> Optional[ExportCapabilityBinding]:
    """Resolve one exact active analysis/project scope from PostgreSQL authority."""
    from database import SessionLocal
    from models.workspace import Analysis, Workspace
    from project_store import PROJECT_READ_ROLES, resolve_diagram_access

    db = SessionLocal()
    try:
        if owner_api_key_id:
            row = (
                db.query(Analysis, Workspace)
                .join(
                    Workspace,
                    Workspace.id == Analysis.workspace_id,
                )
                .filter(
                    Analysis.diagram_id == diagram_id,
                    Analysis.owner_user_id == caller_owner_user_id,
                    Analysis.tenant_id == tenant_id,
                    Workspace.owner_user_id == caller_owner_user_id,
                    Workspace.tenant_id == tenant_id,
                    Workspace.status == "active",
                )
                .first()
            )
            if row is None:
                return None
            analysis, project = row
        else:
            resolved = resolve_diagram_access(
                db,
                diagram_id,
                caller_user_id=caller_owner_user_id,
                tenant_id=tenant_id,
                allowed_roles=PROJECT_READ_ROLES,
            )
            if resolved is None:
                return None
            analysis, project, _role = resolved
        return ExportCapabilityBinding(
            principal_marker=_principal_marker_from_identity(
                owner_user_id=caller_owner_user_id,
                tenant_id=tenant_id,
                owner_api_key_id=owner_api_key_id,
            ),
            owner_user_id=project.owner_user_id,
            tenant_id=tenant_id,
            analysis_id=analysis.id,
            project_id=project.id,
            analysis_version=int(analysis.current_version or 0),
        )
    finally:
        db.close()


def _is_public_export_session(diagram_id: str) -> bool:
    from routers.shared import SESSION_STORE

    session = SESSION_STORE.peek(diagram_id)
    return bool(
        isinstance(session, dict)
        and (
            diagram_id.startswith("sample-")
            or session.get("is_sample")
            or session.get("is_template")
        )
    )


async def export_capability_binding_for_request(
    request: Request,
    diagram_id: str,
) -> Optional[ExportCapabilityBinding]:
    """Resolve a request's canonical caller plus exact durable export scope."""
    from routers.shared import get_request_durable_principal

    principal = get_request_durable_principal(request)
    if principal is None or not principal.get("tenant_id"):
        return None
    return await run_in_threadpool(
        partial(
            _resolve_durable_binding_for_identity,
            diagram_id,
            caller_owner_user_id=principal["owner_user_id"],
            tenant_id=principal["tenant_id"],
            owner_api_key_id=principal.get("owner_api_key_id"),
        )
    )


def issue_export_capability_for_identity(
    diagram_id: str,
    *,
    caller_owner_user_id: str,
    tenant_id: str,
    owner_api_key_id: Optional[str] = None,
    ttl_seconds: Optional[int] = None,
    issued_intent: str = EXPORT_CAPABILITY_ANY_INTENT,
    issued_format: str = EXPORT_CAPABILITY_ANY_FORMAT,
) -> str:
    """Issue for a trusted canonical identity after durable authorization."""
    binding = _resolve_durable_binding_for_identity(
        diagram_id,
        caller_owner_user_id=caller_owner_user_id,
        tenant_id=tenant_id,
        owner_api_key_id=owner_api_key_id,
    )
    if binding is None:
        raise ArchmorphException(404, "Diagram not found")
    return issue_export_capability(
        diagram_id,
        ttl_seconds=ttl_seconds,
        binding=binding,
        issued_intent=issued_intent,
        issued_format=issued_format,
    )


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
    # Tokens have high entropy; this digest is an indexed capability identifier.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()  # codeql[py/weak-sensitive-data-hashing]


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
    binding: Optional[ExportCapabilityBinding] = None,
    scope: str = EXPORT_CAPABILITY_SCOPE,
    issued_intent: str = EXPORT_CAPABILITY_ANY_INTENT,
    issued_format: str = EXPORT_CAPABILITY_ANY_FORMAT,
) -> str:
    """Issue an opaque, URL-safe, single-use export capability for a diagram."""
    ttl = ttl_seconds or _ttl_seconds()
    token = secrets.token_urlsafe(32)
    token_digest = _digest(token)
    expires_at = time.time() + ttl
    record = {
        "diagram_id": diagram_id,
        "scope": scope,
        "binding_version": 0,
        "principal_marker": principal_marker,
        "intent": issued_intent,
        "format": issued_format,
        "issued_intent": issued_intent,
        "issued_format": issued_format,
        "authorized_contracts": [
            {"intent": intent, "format": format_name}
            for intent, format_name in sorted(_EXPORT_ROUTE_CONTRACTS)
        ],
        "expires_at": expires_at,
        "issued_at": time.time(),
    }
    if binding is not None:
        if principal_marker and not secrets.compare_digest(
            principal_marker,
            binding.principal_marker,
        ):
            raise ValueError("Export capability principal binding mismatch")
        record.update(binding.to_record())
    stored = EXPORT_CAPABILITY_STORE.set(
        token_digest,
        record,
        ttl=ttl,
    )
    if not stored:
        _audit("issue_store_failed", diagram_id, token_digest)
        raise ArchmorphException(
            503,
            "Export capability issuance is temporarily unavailable",
        )
    _audit("issued", diagram_id, token_digest)
    return token


def attach_export_capability(
    payload,
    diagram_id: str,
    *,
    principal_marker: Optional[str] = None,
    binding: Optional[ExportCapabilityBinding] = None,
    issued_intent: str = EXPORT_CAPABILITY_ANY_INTENT,
    issued_format: str = EXPORT_CAPABILITY_ANY_FORMAT,
):
    """Return *payload* with a freshly issued ``export_capability`` field."""
    token = issue_export_capability(
        diagram_id,
        principal_marker=principal_marker,
        binding=binding,
        issued_intent=issued_intent,
        issued_format=issued_format,
    )
    if isinstance(payload, dict):
        return {
            **payload,
            "export_capability": token,
            "export_capability_expires_in": _ttl_seconds(),
        }
    return payload


async def issue_export_capability_for_request(
    request: Request,
    diagram_id: str,
    *,
    ttl_seconds: Optional[int] = None,
    issued_intent: Optional[str] = None,
    issued_format: Optional[str] = None,
) -> str:
    """Issue a capability bound to the request caller and durable diagram."""
    binding = await export_capability_binding_for_request(request, diagram_id)
    if (
        binding is None
        and export_capability_required()
        and not _is_public_export_session(diagram_id)
    ):
        raise ArchmorphException(404, "Diagram not found")
    route_intent, route_format = _request_export_contract(request)
    return issue_export_capability(
        diagram_id,
        ttl_seconds=ttl_seconds,
        binding=binding,
        principal_marker=_principal_marker(request) if binding is None else None,
        issued_intent=issued_intent or route_intent,
        issued_format=issued_format or route_format,
    )


async def attach_export_capability_for_request(
    payload,
    request: Request,
    diagram_id: str,
    *,
    issued_intent: Optional[str] = None,
    issued_format: Optional[str] = None,
):
    """Attach a request- and resource-bound successor capability."""
    token = await issue_export_capability_for_request(
        request,
        diagram_id,
        issued_intent=issued_intent,
        issued_format=issued_format,
    )
    if isinstance(payload, dict):
        return {
            **payload,
            "export_capability": token,
            "export_capability_expires_in": _ttl_seconds(),
        }
    return payload


async def issue_export_capability_for_persisted_job(
    manager,
    job_id: str,
    diagram_id: str,
    *,
    issued_intent: str = EXPORT_CAPABILITY_ANY_INTENT,
    issued_format: str = EXPORT_CAPABILITY_ANY_FORMAT,
) -> str:
    """Issue from the persisted canonical job envelope, never request state."""
    job = manager.get_persisted(job_id)
    if job is None or job.diagram_id != diagram_id:
        raise ArchmorphException(503, "Persisted job identity is unavailable")
    if job.owner_user_id and not job.owner_api_key_id and job.tenant_id:
        caller_owner_user_id = job.owner_user_id
        owner_api_key_id = None
    elif job.owner_api_key_id and not job.owner_user_id and job.tenant_id:
        caller_owner_user_id = job.owner_api_key_id
        owner_api_key_id = job.owner_api_key_id
    else:
        raise ArchmorphException(503, "Persisted job identity is incomplete")
    binding = await run_in_threadpool(
        partial(
            _resolve_durable_binding_for_identity,
            diagram_id,
            caller_owner_user_id=caller_owner_user_id,
            tenant_id=job.tenant_id,
            owner_api_key_id=owner_api_key_id,
        )
    )
    if binding is None:
        raise ArchmorphException(404, "Diagram not found")
    return issue_export_capability(
        diagram_id,
        binding=binding,
        issued_intent=issued_intent,
        issued_format=issued_format,
    )


async def attach_export_capability_for_persisted_job(
    payload,
    manager,
    job_id: str,
    diagram_id: str,
    *,
    issued_intent: str = EXPORT_CAPABILITY_ANY_INTENT,
    issued_format: str = EXPORT_CAPABILITY_ANY_FORMAT,
    allow_missing_durable_scope: bool = False,
):
    """Attach a capability derived exclusively from a persisted job envelope."""
    try:
        token = await issue_export_capability_for_persisted_job(
            manager,
            job_id,
            diagram_id,
            issued_intent=issued_intent,
            issued_format=issued_format,
        )
    except ArchmorphException as exc:
        if not allow_missing_durable_scope or exc.status_code != 404:
            raise
        _audit("job_successor_not_issued_without_durable_scope", diagram_id)
        return payload
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
) -> Optional[ExportCapability]:
    """Validate a one-time export capability without consuming it.

    Capabilities are accepted only through ``X-Export-Capability`` so raw
    tokens never become part of browser history, proxy access logs, or URLs.
    """
    if any(
        key in request.query_params for key in ("export_token", "export_capability")
    ):
        _audit("query_token_rejected", diagram_id)
        raise ArchmorphException(400, "Export capabilities are not accepted in URLs")

    if not export_capability_required():
        _audit("bypass_disabled", diagram_id)
        return None

    token = x_export_capability
    if not token:
        _audit("missing", diagram_id)
        raise ArchmorphException(401, "Missing export capability")

    token_digest = _digest(token)
    record = EXPORT_CAPABILITY_STORE.peek(token_digest)
    if not isinstance(record, dict):
        _audit("unknown_or_replayed", diagram_id, token_digest)
        raise ArchmorphException(401, "Invalid or unavailable export capability")

    if record.get("scope") != EXPORT_CAPABILITY_SCOPE:
        EXPORT_CAPABILITY_STORE.delete(token_digest)
        _audit("wrong_scope", diagram_id, token_digest)
        raise ArchmorphException(401, "Invalid or unavailable export capability")

    if record.get("diagram_id") != diagram_id:
        _audit("wrong_diagram", diagram_id, token_digest)
        raise ArchmorphException(401, "Invalid or unavailable export capability")

    try:
        expires_at = float(record.get("expires_at", 0))
        binding_version = int(record.get("binding_version", 0) or 0)
    except (TypeError, ValueError):
        EXPORT_CAPABILITY_STORE.delete(token_digest)
        _audit("malformed", diagram_id, token_digest)
        raise ArchmorphException(401, "Invalid or unavailable export capability")
    if expires_at < time.time():
        EXPORT_CAPABILITY_STORE.delete(token_digest)
        _audit("expired", diagram_id, token_digest)
        raise ArchmorphException(401, "Invalid or unavailable export capability")

    if not (
        isinstance(record.get("intent"), str)
        and isinstance(record.get("format"), str)
        and secrets.compare_digest(
            record["intent"], str(record.get("issued_intent", ""))
        )
        and secrets.compare_digest(
            record["format"], str(record.get("issued_format", ""))
        )
    ):
        EXPORT_CAPABILITY_STORE.delete(token_digest)
        _audit("malformed_scope", diagram_id, token_digest)
        raise ArchmorphException(401, "Invalid or unavailable export capability")

    requested_contract = _request_export_contract(request)
    authorized_contracts = {
        (item.get("intent"), item.get("format"))
        for item in record.get("authorized_contracts", [])
        if isinstance(item, dict)
    }
    if requested_contract not in authorized_contracts:
        _audit("wrong_contract", diagram_id, token_digest)
        raise ArchmorphException(401, "Invalid or unavailable export capability")

    if binding_version == 1:
        current_binding = await export_capability_binding_for_request(
            request, diagram_id
        )
        expected = current_binding.to_record() if current_binding is not None else {}
        binding_fields = (
            "principal_marker",
            "owner_user_id",
            "tenant_id",
            "analysis_id",
            "project_id",
        )
        if any(
            not secrets.compare_digest(
                str(record.get(field, "")), str(expected.get(field, ""))
            )
            for field in binding_fields
        ):
            _audit("wrong_binding", diagram_id, token_digest)
            raise ArchmorphException(401, "Invalid or unavailable export capability")
    elif binding_version != 0 or not _is_public_export_session(diagram_id):
        _audit("unbound_private_capability", diagram_id, token_digest)
        raise ArchmorphException(401, "Invalid or unavailable export capability")

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
