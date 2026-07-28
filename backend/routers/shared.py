"""
Shared state, dependencies, and models used across Archmorph API routers.
"""

import asyncio
import copy
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum
import json
import os
import logging
import secrets
import hashlib
import hmac
from collections import OrderedDict
from functools import partial
from typing import FrozenSet, Optional, List

from fastapi import Security, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from strict_models import StrictBaseModel

from slowapi import Limiter
from slowapi.util import get_remote_address
from limits import parse as parse_rate_limit

from admin_auth import (
    validate_session_token,
    is_configured as admin_is_configured,
)
from error_envelope import ArchmorphException
from session_store import get_store
from starlette.concurrency import run_in_threadpool

# ─────────────────────────────────────────────────────────────
# Rate Limiting
# ─────────────────────────────────────────────────────────────
_redis_url = os.getenv("REDIS_URL", "")
_redis_host = os.getenv("REDIS_HOST", "")
_configured_rate_limit_storage = os.getenv("RATE_LIMIT_STORAGE", "").strip()


def _rate_limit_storage_uri() -> str:
    """Resolve a shared limiter backend without treating REDIS_HOST as local.

    ``limits`` can construct URL-authenticated Redis storage directly. Azure
    Managed Redis configured through ``REDIS_HOST`` uses rotating Entra tokens,
    so that mode must provide an explicit shared ``RATE_LIMIT_STORAGE`` adapter
    URI rather than silently falling back to one process's memory.
    """
    return _configured_rate_limit_storage or _redis_url or "memory://"


_rate_limit_storage = _rate_limit_storage_uri()
limiter = Limiter(
    key_func=get_remote_address,
    enabled=os.getenv("RATE_LIMIT_ENABLED", "true").lower() != "false",
    default_limits=["200/minute"],  # Global burst protection (#377)
    storage_uri=_rate_limit_storage,
)

# ─────────────────────────────────────────────────────────────
# API Key Authentication
# ─────────────────────────────────────────────────────────────
API_KEY = os.getenv("ARCHMORPH_API_KEY", "")  # Empty = auth disabled (dev mode)
API_KEY_ROTATED = os.getenv("ARCHMORPH_API_KEY_ROTATED", "")
API_KEY_PRINCIPAL_ID = os.getenv("ARCHMORPH_API_KEY_PRINCIPAL_ID", "").strip()
API_KEY_ALLOW_LEGACY_OVERLAP = os.getenv(
    "ARCHMORPH_API_KEY_ALLOW_LEGACY_OVERLAP",
    "false",
).lower() == "true"
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
ADMIN_BEARER = HTTPBearer(auto_error=False)
USER_BEARER = HTTPBearer(auto_error=False)

logger = logging.getLogger(__name__)

_api_key_warning_logged = False
_DEV_PRINCIPAL_SALT = secrets.token_bytes(32)


class CredentialKind(str, Enum):
    """Supported authenticated caller kinds."""

    STATIC = "static"
    MANAGED = "managed"
    BEARER = "bearer"
    ADMIN = "admin"
    DEVELOPMENT = "development"


@dataclass(frozen=True)
class CredentialContext:
    """Secret-free, stable authentication result used by authorization."""

    kind: CredentialKind
    principal_id: str
    key_id: Optional[str]
    scopes: FrozenSet[str]
    rate_limit: Optional[int]
    tenant_id: Optional[str]
    owner_user_id: Optional[str]

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes or "admin" in self.scopes


_credential_context_var: ContextVar[Optional[CredentialContext]] = ContextVar(
    "archmorph_credential_context",
    default=None,
)


def set_request_credential_context(
    request: Optional[Request],
    context: CredentialContext,
) -> CredentialContext:
    """Expose one secret-free authenticated identity to middleware and workers."""
    _credential_context_var.set(context)
    if request is not None:
        request.state.credential_context = context
    return context


def current_credential_context() -> Optional[CredentialContext]:
    """Return the credential context propagated through the current task/thread."""
    return _credential_context_var.get()


def rate_limit_readiness() -> dict[str, object]:
    """Return whether rate limits are shared when horizontal scale is possible."""
    from session_store import _declared_replica_count, _is_multi_worker

    enabled = os.getenv("RATE_LIMIT_ENABLED", "true").lower() != "false"
    multi_replica = _declared_replica_count() > 1
    multi_worker = _is_multi_worker()
    storage_uri = (
        os.getenv("RATE_LIMIT_STORAGE", "").strip()
        or os.getenv("REDIS_URL", "").strip()
        or "memory://"
    )
    shared = storage_uri.startswith(("redis://", "rediss://"))
    redis_host = os.getenv("REDIS_HOST", "").strip()
    configured_storage = os.getenv("RATE_LIMIT_STORAGE", "").strip()
    entra_host_requires_adapter = bool(redis_host and not configured_storage)
    shared_required = enabled and (multi_replica or multi_worker)
    ready = not shared_required or shared
    return {
        "enabled": enabled,
        "storage": "shared" if shared else "local",
        "shared": shared,
        "shared_required": shared_required,
        "multi_worker": multi_worker,
        "declared_replica_count": _declared_replica_count(),
        "multi_replica": multi_replica,
        "entra_host_requires_adapter": entra_host_requires_adapter,
        "ready": ready,
        "reason": (
            "RATE_LIMIT_STORAGE must use a shared Redis-compatible URI when "
            "REDIS_HOST/Entra mode or horizontal production scale is enabled"
            if not ready
            else None
        ),
    }


def _safe_log_value(value: object) -> str:
    return str(value).replace("\n", "").replace("\r", "")


def _static_principal_id() -> str:
    """Return the configured non-secret static service principal."""
    return API_KEY_PRINCIPAL_ID or "static-service"


def _legacy_static_principal_id() -> Optional[str]:
    """Return the pre-migration secret-derived ID without exposing key material."""
    if not API_KEY or not API_KEY_PRINCIPAL_ID:
        return None
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        API_KEY.encode("utf-8"),
        b"archmorph-api-principal-v1",
        120_000,
    ).hex()[:24]
    return f"api-key:legacy-{digest}"


def _static_key_matches(api_key: Optional[str]) -> bool:
    """Apply one overlap/cutover policy to every static-key auth surface."""
    presented = api_key or ""
    if API_KEY_ROTATED and secrets.compare_digest(presented, API_KEY_ROTATED):
        return True
    return bool(
        API_KEY
        and secrets.compare_digest(presented, API_KEY)
        and (not API_KEY_ROTATED or API_KEY_ALLOW_LEGACY_OVERLAP)
    )


def _enforce_managed_key_rate_limit(context: CredentialContext) -> None:
    """Atomically enforce a managed key's shared requests-per-minute budget."""
    if context.kind is not CredentialKind.MANAGED or context.rate_limit is None:
        return
    rate = parse_rate_limit(f"{context.rate_limit}/minute")
    try:
        allowed = limiter._limiter.hit(rate, "managed-api-key", context.principal_id)
    except Exception as exc:
        logger.error(
            "managed_api_key_rate_limit_failed principal_id=%s error_type=%s",
            _safe_log_value(context.principal_id),
            type(exc).__name__,
        )
        raise ArchmorphException(
            503,
            "API key rate-limit service is unavailable",
            headers={"Retry-After": "5"},
        ) from exc
    if not allowed:
        raise ArchmorphException(
            429,
            "API key rate limit exceeded",
            details={"error": "api_key_rate_limited"},
            headers={"Retry-After": "60"},
        )


def _managed_credential(api_key: str) -> Optional[CredentialContext]:
    from routers.api_keys_routes import validate_api_key_by_raw

    record = validate_api_key_by_raw(api_key)
    if record is None:
        return None
    context = CredentialContext(
        kind=CredentialKind.MANAGED,
        principal_id=f"api-key:{record.principal_id}",
        key_id=record.id,
        scopes=frozenset(record.scopes),
        rate_limit=record.rate_limit,
        tenant_id=f"service:{record.principal_id}",
        owner_user_id=f"api-key:{record.principal_id}",
    )
    _enforce_managed_key_rate_limit(context)
    return context


def _authenticate_api_key(api_key: Optional[str], *, required: bool) -> CredentialContext:
    """Authenticate a static or managed key without returning raw material."""
    global _api_key_warning_logged
    if not API_KEY:
        environment = (os.getenv("ENVIRONMENT") or os.getenv("ENV") or "production").lower()
        if required or environment in ("production", "prod", "staging"):
            raise ArchmorphException(status_code=500, detail="Server misconfiguration: API key not set")
        if not _api_key_warning_logged:
            logger.warning("ARCHMORPH_API_KEY not set — API authentication is disabled (dev mode only)")
            _api_key_warning_logged = True
        return CredentialContext(
            kind=CredentialKind.DEVELOPMENT,
            principal_id="development",
            key_id=None,
            scopes=frozenset({"read", "write", "admin"}),
            rate_limit=None,
            tenant_id=None,
            owner_user_id=None,
        )
    if _static_key_matches(api_key):
        principal_id = f"api-key:{_static_principal_id()}"
        return CredentialContext(
            kind=CredentialKind.STATIC,
            principal_id=principal_id,
            key_id="static",
            scopes=frozenset({"read", "write", "admin"}),
            rate_limit=None,
            tenant_id=f"service:{_static_principal_id()}",
            owner_user_id=principal_id,
        )
    if api_key and (context := _managed_credential(api_key)) is not None:
        return context
    raise ArchmorphException(status_code=401, detail="Invalid or missing API key")


async def verify_api_key(
    api_key: Optional[str] = Security(API_KEY_HEADER),
    request: Request = None,
) -> CredentialContext:
    """Verify a key and enforce least privilege from the HTTP method."""
    context = getattr(getattr(request, "state", None), "credential_context", None)
    if context is None:
        context = _authenticate_api_key(api_key, required=False)
    route = request.scope.get("route") if request is not None else None
    path_template = getattr(route, "path", request.url.path if request is not None else "")
    required_scope = route_effect_scope(request.method, path_template) if request is not None else None
    if required_scope is None:
        required_scope = "read" if request is None or request.method in {"GET", "HEAD", "OPTIONS"} else "write"
    if not context.has_scope(required_scope):
        raise ArchmorphException(403, f"API key scope '{required_scope}' is required")
    return set_request_credential_context(request, context)


async def verify_api_key_required(
    api_key: Optional[str] = Security(API_KEY_HEADER),
    request: Request = None,
) -> CredentialContext:
    """Verify API key for server-to-server routes, even in dev/test mode."""
    context = getattr(getattr(request, "state", None), "credential_context", None)
    if context is None:
        context = _authenticate_api_key(api_key, required=True)
    if context.kind is not CredentialKind.STATIC:
        raise ArchmorphException(status_code=403, detail="Static service administrator required")
    return set_request_credential_context(request, context)


def require_api_scope(scope: str):
    """Build a route dependency requiring one managed-key scope."""
    if scope not in {"read", "write", "admin"}:
        raise ValueError("Unsupported API key scope")

    async def dependency(
        api_key: Optional[str] = Security(API_KEY_HEADER),
        request: Request = None,
    ) -> CredentialContext:
        context = getattr(getattr(request, "state", None), "credential_context", None)
        if context is None:
            context = _authenticate_api_key(api_key, required=False)
        if not context.has_scope(scope):
            raise ArchmorphException(403, f"API key scope '{scope}' is required")
        return set_request_credential_context(request, context)

    dependency.__name__ = f"require_api_{scope}"
    return dependency


require_api_read = require_api_scope("read")
require_api_write = require_api_scope("write")
require_api_admin = require_api_scope("admin")


ROUTE_EFFECT_SCOPE_MANIFEST: dict[tuple[str, str], str] = {
    # GET compatibility routes that persist generated artifacts/state.
    ("GET", "/api/diagrams/{diagram_id}/hld"): "write",
    ("GET", "/api/diagrams/{diagram_id}/cost-assumptions"): "write",
    ("GET", "/api/diagrams/{diagram_id}/cost-estimate/export"): "write",
    ("GET", "/api/diagrams/{diagram_id}/migration-timeline/export"): "write",
    ("GET", "/api/diagrams/{diagram_id}/report"): "write",
    ("GET", "/api/replay/{replay_id}/export"): "write",
    ("POST", "/api/diagrams/{diagram_id}/export-diagram"): "write",
    ("POST", "/api/diagrams/{diagram_id}/export-architecture-package"): "write",
    ("POST", "/api/diagrams/{diagram_id}/export-hld"): "write",
    ("POST", "/api/diagrams/{diagram_id}/export-package"): "write",
    ("POST", "/api/diagrams/{diagram_id}/generate-hld"): "write",
    ("POST", "/api/diagrams/{diagram_id}/generate-hld-async"): "write",
    ("POST", "/api/diagrams/{diagram_id}/generate"): "write",
    ("POST", "/api/diagrams/{diagram_id}/generate-async"): "write",
    ("POST", "/api/diagrams/{diagram_id}/iac-chat"): "write",
    ("DELETE", "/api/diagrams/{diagram_id}/iac-chat"): "write",
    ("POST", "/api/diagrams/{diagram_id}/cost-estimate/configure"): "write",
    ("POST", "/api/diagrams/{diagram_id}/restore-session"): "write",
    # Explicit mutation routes whose verb already communicates the effect.
    ("POST", "/api/diagrams/{diagram_id}/migration-timeline"): "write",
    ("POST", "/api/diagrams/{diagram_id}/network-topology"): "write",
    ("POST", "/api/diagrams/{diagram_id}/review-queue/{item_id}/disposition"): "write",
    ("POST", "/api/diagrams/{diagram_id}/versions"): "write",
    ("POST", "/api/diagrams/{diagram_id}/versions/save"): "write",
    ("POST", "/api/diagrams/{diagram_id}/versions/{version}/branch"): "write",
    ("POST", "/api/diagrams/{diagram_id}/versions/{version_number}/restore"): "write",
    ("POST", "/api/replay/record"): "write",
    ("POST", "/api/replay/events"): "write",
    ("POST", "/api/cost/budgets"): "write",
    ("PUT", "/api/cost/budgets/{budget_id}"): "write",
}


def route_effect_scope(method: str, path_template: str) -> Optional[str]:
    """Return explicit effect scope, resolving v1 mirrors to their base path."""
    normalized_path = path_template
    if normalized_path.startswith("/api/v1/"):
        normalized_path = "/api/" + normalized_path[len("/api/v1/"):]
    return ROUTE_EFFECT_SCOPE_MANIFEST.get((method.upper(), normalized_path))


async def enforce_route_effect_scope(
    request: Request,
    api_key: Optional[str] = Security(API_KEY_HEADER),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(USER_BEARER),
) -> Optional[CredentialContext]:
    """Enforce effect scope for any manifest-listed route, regardless of verb."""
    route = request.scope.get("route")
    path_template = getattr(route, "path", request.url.path)
    required_scope = route_effect_scope(request.method, path_template)
    if required_scope is None:
        return None
    context = await verify_api_key_or_user_session(
        request,
        api_key=api_key,
        credentials=credentials,
    )
    if not context.has_scope(required_scope):
        raise ArchmorphException(403, f"API key scope '{required_scope}' is required")
    return set_request_credential_context(request, context)


async def verify_api_key_or_user_session(
    request: Request,
    api_key: Optional[str] = Security(API_KEY_HEADER),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(USER_BEARER),
) -> CredentialContext:
    """Allow either the service API key or a signed-in user bearer session."""
    existing = getattr(request.state, "credential_context", None)
    if existing is not None:
        return existing
    try:
        return await verify_api_key(api_key, request=request)
    except ArchmorphException as exc:
        if exc.status_code != 401:
            raise

        from auth import get_user_from_request_headers

        user = get_user_from_request_headers(dict(request.headers))
        if credentials is not None and credentials.scheme.lower() == "bearer" and user:
            owner_user_id = (
                user.provider_subject
                if user.provider.value == "azure_ad_b2c" and user.provider_subject
                else user.id
            )
            context = CredentialContext(
                kind=CredentialKind.BEARER,
                principal_id=f"user:{owner_user_id}",
                key_id=None,
                scopes=frozenset({"read", "write"}),
                rate_limit=None,
                tenant_id=user.tenant_id,
                owner_user_id=owner_user_id,
            )
            return set_request_credential_context(request, context)
        raise ArchmorphException(status_code=401, detail="Invalid or missing API key or user session") from exc


async def require_api_read_or_user_session(
    context: CredentialContext = Security(verify_api_key_or_user_session),
) -> CredentialContext:
    """Require read scope for API keys or accept a signed-in user."""
    return context


async def require_api_write_or_user_session(
    context: CredentialContext = Security(verify_api_key_or_user_session),
) -> CredentialContext:
    """Require write scope for API keys or accept a signed-in user."""
    return context


def get_api_key_service_principal(headers: dict) -> Optional[str]:
    """Return a stable API-key service principal ID for a verified key."""
    api_key = headers.get("x-api-key")
    if API_KEY and _static_key_matches(api_key):
        return f"api-key:{_static_principal_id()}"
    if api_key:
        from routers.api_keys_routes import validate_api_key_by_raw

        record = validate_api_key_by_raw(api_key)
        if record is not None:
            return f"api-key:{record.principal_id}"
    if not API_KEY:
        # Dev/test compatibility: isolate arbitrary supplied keys only within
        # this process. These random-salted IDs are never durable principals.
        if not api_key:
            return None
        digest = hmac.new(
            _DEV_PRINCIPAL_SALT,
            api_key.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:24]
        return f"api-key:development-{digest}"
    return None


def get_request_durable_principal(request: Request) -> Optional[dict]:
    """Map user or API-key authentication to a stable durable identity."""
    from auth import get_user_from_request_headers

    headers = dict(request.headers)
    user = get_user_from_request_headers(headers)
    if user:
        owner_user_id = (
            user.provider_subject
            if user.provider.value == "azure_ad_b2c" and user.provider_subject
            else user.id
        )
        legacy_owner_user_ids = []
        if user.provider.value == "azure_ad_b2c" and user.id != owner_user_id:
            # Before provider subjects became canonical, direct B2C writes used
            # ``User.id``. The alias is accepted only from the currently
            # verified B2C principal and only for guarded default-tenant rehome.
            legacy_owner_user_ids.append(user.id)
        return {
            "owner_user_id": owner_user_id,
            "tenant_id": user.tenant_id,
            "owner_api_key_id": None,
            "legacy_owner_user_ids": legacy_owner_user_ids,
            "legacy_owner_scopes": [],
        }
    api_key_id = get_api_key_service_principal(headers)
    if api_key_id:
        principal_id = api_key_id.split(":", 1)[-1]
        legacy_owner_user_ids = []
        legacy_static = _legacy_static_principal_id()
        if legacy_static and legacy_static != api_key_id:
            legacy_owner_user_ids.append(legacy_static)
        legacy_owner_scopes = [
            {
                "owner_user_id": legacy_static,
                "tenant_id": f"service:{legacy_static.split(':', 1)[-1]}",
            }
        ] if legacy_static and legacy_static != api_key_id else []
        return {
            "owner_user_id": api_key_id,
            "tenant_id": f"service:{principal_id}",
            "owner_api_key_id": api_key_id,
            "legacy_owner_user_ids": legacy_owner_user_ids,
            "legacy_owner_scopes": legacy_owner_scopes,
        }
    return None


def has_canonical_durable_principal(request: Request) -> bool:
    """Return whether this request must use canonical durable state."""
    principal = get_request_durable_principal(request)
    return bool(
        principal
        and principal["tenant_id"]
        and (principal["owner_api_key_id"] is None or API_KEY)
    )


# ─────────────────────────────────────────────────────────────
# Admin Auth Dependency
# ─────────────────────────────────────────────────────────────
async def verify_admin_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(ADMIN_BEARER),
    api_key: Optional[str] = Security(API_KEY_HEADER),
    request: Request = None,
):
    """Verify an admin bearer session or an admin/static API credential."""
    if not isinstance(api_key, str):
        api_key = None
    if api_key:
        context = _authenticate_api_key(api_key, required=True)
        if context.kind is CredentialKind.STATIC or context.has_scope("admin"):
            return context
        raise ArchmorphException(403, "Administrator credential required")

    if not admin_is_configured():
        raise ArchmorphException(503, "Admin API not configured")

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ArchmorphException(401, "Missing or malformed Authorization header")

    token = credentials.credentials
    payload = validate_session_token(token)
    if payload is None:
        raise ArchmorphException(401, "Invalid or expired session token")
    return payload


def get_bearer_token_from_headers(headers: dict) -> Optional[str]:
    """Extract Bearer token from request headers."""
    auth_header = headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


def require_authenticated_user(request: Request):
    """Fail-closed auth dependency for routes that require a signed-in user."""
    from auth import get_user_from_request_headers

    user = get_user_from_request_headers(dict(request.headers))
    if not user:
        raise ArchmorphException(401, "Authentication required")
    return user


def require_authenticated_user_context(request: Request) -> dict:
    """Return legacy dict context for authenticated user-only routes."""
    user = require_authenticated_user(request)
    context = user.to_dict()
    context["org_id"] = user.tenant_id

    token = get_bearer_token_from_headers(dict(request.headers))
    if token:
        context["session_token"] = token
    return context


def _load_diagram_session_for_access(diagram_id: str) -> Optional[dict]:
    session = SESSION_STORE.get(diagram_id)
    if session is not None:
        return session
    if not diagram_id.startswith("sample-"):
        return None

    from routers.samples import get_or_recreate_session

    return get_or_recreate_session(diagram_id)


def _load_durable_diagram_session(request: Request, diagram_id: str) -> Optional[dict]:
    """Hydrate a lost analysis cache from the caller's tenant-scoped SQL record."""
    principal = get_request_durable_principal(request)
    if principal is None or not principal["tenant_id"]:
        return None

    from database import SessionLocal
    from workspace_store import (
        get_analysis_by_diagram,
        load_analysis_state,
        rehome_legacy_analysis_scope,
    )

    db = SessionLocal()
    try:
        from workspace_store import diagram_is_tombstoned, rehome_legacy_owner_scope

        legacy_scope_rehomed = False
        for legacy_scope in principal.get("legacy_owner_scopes", []):
            summary = rehome_legacy_owner_scope(
                db,
                owner_user_ids=[legacy_scope["owner_user_id"]],
                source_tenant_id=legacy_scope["tenant_id"],
                target_tenant_id=principal["tenant_id"],
                target_owner_user_id=principal["owner_user_id"],
            )
            legacy_scope_rehomed = legacy_scope_rehomed or bool(summary["rehomed"])

        if diagram_is_tombstoned(
            db,
            diagram_id=diagram_id,
            owner_user_id=principal["owner_user_id"],
            tenant_id=principal["tenant_id"],
        ):
            return {"_durable_tombstone": True}
        legacy_owner_user_id = next(
            (
                owner_user_id
                for owner_user_id in [
                    principal["owner_user_id"],
                    *principal.get("legacy_owner_user_ids", []),
                ]
                if get_analysis_by_diagram(
                    db,
                    diagram_id=diagram_id,
                    owner_user_id=owner_user_id,
                    tenant_id="default_tenant",
                ) is not None
            ),
            None,
        )
        if legacy_owner_user_id is not None:
            status = rehome_legacy_analysis_scope(
                db,
                diagram_id=diagram_id,
                owner_user_id=legacy_owner_user_id,
                source_tenant_id="default_tenant",
                target_tenant_id=principal["tenant_id"],
                target_owner_user_id=principal["owner_user_id"],
            )
            if status != "rehomed":
                return None
        durable = load_analysis_state(
            db,
            diagram_id=diagram_id,
            owner_user_id=principal["owner_user_id"],
            tenant_id=principal["tenant_id"],
            session_store=SESSION_STORE,
            cache_owner_api_key_id=principal["owner_api_key_id"],
            allow_legacy_cache_rehome=(
                legacy_owner_user_id is not None or legacy_scope_rehomed
            ),
            cache_legacy_owner_user_ids=principal.get("legacy_owner_user_ids", []),
        )
        if durable is not None or principal["owner_api_key_id"] is not None:
            return durable

        from project_store import PROJECT_READ_ROLES, resolve_diagram_access

        member_access = resolve_diagram_access(
            db,
            diagram_id,
            caller_user_id=principal["owner_user_id"],
            tenant_id=principal["tenant_id"],
            allowed_roles=PROJECT_READ_ROLES,
        )
        if member_access is None:
            return None
        _analysis, project, _role = member_access
        return load_analysis_state(
            db,
            diagram_id=diagram_id,
            owner_user_id=project.owner_user_id,
            tenant_id=principal["tenant_id"],
            session_store=SESSION_STORE,
        )
    except Exception as exc:
        logger.warning(
            "durable_analysis_hydration_failed diagram_id=%s error_type=%s",
            _safe_log_value(diagram_id),
            type(exc).__name__,
        )
        return None
    finally:
        db.close()


def _is_public_diagram_session(diagram_id: str, session: Optional[dict]) -> bool:
    if diagram_id.startswith("sample-"):
        return True
    if not isinstance(session, dict):
        return False
    return bool(
        session.get("is_sample")
        or session.get("is_template")
        or session.get("is_starter")
    )


async def authorize_diagram_access_async(
    request: Request,
    diagram_id: str,
    purpose: str = "access",
) -> dict:
    """Async authorization wrapper for routes that may trigger durable rehome."""
    return await run_in_threadpool(
        partial(authorize_diagram_access, request, diagram_id, purpose)
    )


def authorize_diagram_access(
    request: Request,
    diagram_id: str,
    purpose: str = "access",
) -> dict:
    """Authorize access to a session-backed diagram resource.

    Public sample/template sessions are explicitly exempt. All other sessions
    require either the owning authenticated user within the same tenant, or the
    owning API-key principal that created the private session.
    """
    from auth import get_user_from_request_headers

    route = request.scope.get("route")
    path_template = getattr(route, "path", request.url.path)
    required_effect_scope = route_effect_scope(request.method, path_template)
    if required_effect_scope:
        context = getattr(request.state, "credential_context", None)
        if context is None and request.headers.get("x-api-key"):
            context = _authenticate_api_key(
                request.headers.get("x-api-key"),
                required=False,
            )
            set_request_credential_context(request, context)
        if context is not None and not context.has_scope(required_effect_scope):
            raise ArchmorphException(
                403,
                f"API key scope '{required_effect_scope}' is required",
            )

    session = _load_diagram_session_for_access(diagram_id)
    principal = get_request_durable_principal(request)
    if has_canonical_durable_principal(request):
        cached_version = session.get("_analysis_version") if isinstance(session, dict) else None
        durable_session = _load_durable_diagram_session(request, diagram_id)
        if durable_session is not None:
            if durable_session.get("_durable_tombstone"):
                raise ArchmorphException(404, "Diagram not found")
            durable_version = durable_session.get("_analysis_version")
            try:
                cache_is_current = (
                    cached_version is not None
                    and int(cached_version) == int(durable_version)
                )
            except (TypeError, ValueError):
                cache_is_current = False
            if not cache_is_current:
                session = durable_session
    elif session is None:
        session = _load_durable_diagram_session(request, diagram_id)
    if _is_public_diagram_session(diagram_id, session):
        if session is None:
            raise ArchmorphException(404, "Diagram not found")
        return session

    if session is None:
        raise ArchmorphException(404, "Diagram not found")

    headers = dict(request.headers)
    user = get_user_from_request_headers(headers)
    if user:
        owner_user_id = session.get("_owner_user_id")
        tenant_id = session.get("_tenant_id")
        principal = get_request_durable_principal(request)
        expected_owner_user_id = principal["owner_user_id"] if principal else user.id
        accepted_legacy_owner_ids = {
            expected_owner_user_id,
            *(principal.get("legacy_owner_user_ids", []) if principal else []),
        }
        if owner_user_id in accepted_legacy_owner_ids and tenant_id == "default_tenant":
            try:
                if principal is None or not principal["tenant_id"]:
                    raise ArchmorphException(404, "Diagram not found")

                from database import SessionLocal
                from workspace_store import (
                    get_analysis_by_diagram,
                    load_analysis_state,
                    rehome_legacy_analysis_scope,
                )

                db = SessionLocal()
                try:
                    legacy_analysis = get_analysis_by_diagram(
                        db,
                        diagram_id=diagram_id,
                        owner_user_id=owner_user_id,
                        tenant_id="default_tenant",
                    )
                    target_analysis = get_analysis_by_diagram(
                        db,
                        diagram_id=diagram_id,
                        owner_user_id=principal["owner_user_id"],
                        tenant_id=principal["tenant_id"],
                    )
                    migrated_session = None
                    if legacy_analysis is None and target_analysis is not None:
                        migrated_session = load_analysis_state(
                            db,
                            diagram_id=diagram_id,
                            owner_user_id=principal["owner_user_id"],
                            tenant_id=principal["tenant_id"],
                            session_store=SESSION_STORE,
                            allow_legacy_cache_rehome=True,
                            cache_legacy_owner_user_ids=principal.get(
                                "legacy_owner_user_ids",
                                [],
                            ),
                        )
                    elif legacy_analysis is not None and target_analysis is None:
                        status = rehome_legacy_analysis_scope(
                            db,
                            diagram_id=diagram_id,
                            owner_user_id=owner_user_id,
                            source_tenant_id="default_tenant",
                            target_tenant_id=principal["tenant_id"],
                            target_owner_user_id=principal["owner_user_id"],
                        )
                        if status == "rehomed":
                            migrated_session = load_analysis_state(
                                db,
                                diagram_id=diagram_id,
                                owner_user_id=principal["owner_user_id"],
                                tenant_id=principal["tenant_id"],
                                session_store=SESSION_STORE,
                                allow_legacy_cache_rehome=True,
                                cache_legacy_owner_user_ids=principal.get(
                                    "legacy_owner_user_ids",
                                    [],
                                ),
                            )
                finally:
                    db.close()
                if migrated_session is not None:
                    from usage_metrics import record_event

                    record_event(
                        "legacy_tenant_cache_rehomed",
                        {
                            "diagram_id": diagram_id,
                            "owner_user_id": user.id,
                            "source": "durable_target",
                        },
                    )
                    return migrated_session
                if migrated_session is None and (legacy_analysis is not None or target_analysis is not None):
                    from usage_metrics import record_event

                    record_event(
                        "legacy_tenant_cache_conflict",
                        {"diagram_id": diagram_id, "owner_user_id": user.id},
                    )
                    raise ArchmorphException(404, "Diagram not found")

                persist_diagram_mutation(
                    request,
                    diagram_id,
                    session,
                    label="legacy-default-tenant-cache-rehome",
                    allow_legacy_cache_rehome=True,
                )
                session = SESSION_STORE.peek(diagram_id) or session
                from usage_metrics import record_event

                record_event(
                    "legacy_tenant_cache_rehomed",
                    {"diagram_id": diagram_id, "owner_user_id": user.id},
                )
                return session
            except Exception as exc:
                logger.warning(
                    "legacy_tenant_cache_rehome_failed diagram_id=%s error_type=%s",
                    _safe_log_value(diagram_id),
                    type(exc).__name__,
                )
                raise ArchmorphException(404, "Diagram not found") from exc
        if not owner_user_id or not tenant_id:
            logger.debug(
                "deny_diagram_access_missing_user_metadata diagram_id=%s owner=%s tenant=%s",
                _safe_log_value(diagram_id),
                bool(owner_user_id),
                bool(tenant_id),
            )
            raise ArchmorphException(404, "Diagram not found")
        if owner_user_id != expected_owner_user_id or tenant_id != user.tenant_id:
            if principal is None or tenant_id != principal.get("tenant_id"):
                raise ArchmorphException(404, "Diagram not found")
            from database import SessionLocal
            from project_store import (
                PROJECT_EDIT_ROLES,
                PROJECT_READ_ROLES,
                resolve_diagram_access,
            )

            allowed_roles = (
                PROJECT_READ_ROLES
                if request.method in {"GET", "HEAD", "OPTIONS"}
                else PROJECT_EDIT_ROLES
            )
            db = SessionLocal()
            try:
                resolved = resolve_diagram_access(
                    db,
                    diagram_id,
                    caller_user_id=expected_owner_user_id,
                    tenant_id=principal["tenant_id"],
                    allowed_roles=allowed_roles,
                )
            finally:
                db.close()
            if resolved is None:
                raise ArchmorphException(404, "Diagram not found")
        return session

    api_key_principal_id = get_api_key_service_principal(headers)
    if not api_key_principal_id:
        raise ArchmorphException(401, f"Authentication required to {purpose}")

    owner_api_key_id = session.get("_owner_api_key_id")
    if not owner_api_key_id or owner_api_key_id != api_key_principal_id:
        logger.debug(
            "deny_diagram_access_missing_api_principal diagram_id=%s owner_api_key=%s",
            _safe_log_value(diagram_id),
            bool(owner_api_key_id),
        )
        raise ArchmorphException(404, "Diagram not found")
    return session


def require_diagram_access(request: Request, diagram_id: str) -> dict:
    """FastAPI dependency wrapper for diagram access checks."""
    if request.url.path.endswith(f"/diagrams/{diagram_id}/purge"):
        return require_diagram_or_purge_access(request, diagram_id)
    return authorize_diagram_access(request, diagram_id)


def require_diagram_or_purge_access(request: Request, diagram_id: str) -> dict:
    """Authorize a live diagram or its same-owner durable purge receipt."""
    try:
        return authorize_diagram_access(request, diagram_id, purpose="purge a diagram")
    except ArchmorphException as exc:
        if exc.status_code != 404:
            raise
    principal = get_request_durable_principal(request)
    if principal is None or not principal.get("tenant_id"):
        raise ArchmorphException(404, "Diagram not found")
    from database import SessionLocal
    from models.workspace import PurgeOperation

    db = SessionLocal()
    try:
        operation = db.query(PurgeOperation).filter(
            PurgeOperation.scope_type == "diagram",
            PurgeOperation.scope_id == diagram_id,
            PurgeOperation.owner_user_id == principal["owner_user_id"],
            PurgeOperation.tenant_id == principal["tenant_id"],
        ).first()
        if operation is None:
            raise ArchmorphException(404, "Diagram not found")
        return {"purge_operation_id": operation.id, "status": operation.status}
    finally:
        db.close()


def persist_diagram_mutation(
    request: Request,
    diagram_id: str,
    snapshot: dict,
    *,
    artifact_type: Optional[str] = None,
    artifact_format: Optional[str] = None,
    artifact_content: Optional[str] = None,
    expected_version: Optional[int] = None,
    label: Optional[str] = None,
    restored_from: Optional[int] = None,
    allow_legacy_cache_rehome: bool = False,
):
    """Persist an authenticated mutation, then project its committed version.

    Public compatibility flows without a durable principal remain transient.
    User and API-key mutations use the same repository/UoW and fail closed when
    PostgreSQL cannot commit them.
    """
    detached_snapshot = copy.deepcopy(snapshot)
    if _is_public_diagram_session(diagram_id, detached_snapshot):
        if not SESSION_STORE.set(diagram_id, detached_snapshot):
            raise ArchmorphException(503, "Analysis cache is temporarily unavailable")
        return None
    principal = get_request_durable_principal(request)
    if principal is None:
        if not SESSION_STORE.set(diagram_id, detached_snapshot):
            raise ArchmorphException(503, "Analysis cache is temporarily unavailable")
        return None
    if principal["owner_api_key_id"] is not None and not API_KEY:
        if not SESSION_STORE.set(diagram_id, detached_snapshot):
            raise ArchmorphException(503, "Analysis cache is temporarily unavailable")
        return None
    existing_owner = detached_snapshot.get("_owner_user_id") or detached_snapshot.get("_owner_api_key_id")
    if existing_owner is None and principal["owner_api_key_id"] is None:
        from auth import get_user_from_request_headers

        user = get_user_from_request_headers(dict(request.headers))
        if user is None:
            if not SESSION_STORE.set(diagram_id, detached_snapshot):
                raise ArchmorphException(503, "Analysis cache is temporarily unavailable")
            return None
    if not principal["tenant_id"]:
        raise ArchmorphException(
            401,
            "Authenticated tenant context is required for durable analysis state.",
            details={"error": "tenant_context_required"},
        )

    if principal["owner_api_key_id"] is None:
        from database import SessionLocal
        from project_store import PROJECT_EDIT_ROLES, resolve_diagram_principal

        db = SessionLocal()
        try:
            project_principal = resolve_diagram_principal(
                db,
                diagram_id,
                caller_user_id=principal["owner_user_id"],
                tenant_id=principal["tenant_id"],
                allowed_roles=PROJECT_EDIT_ROLES,
            )
        finally:
            db.close()
        if project_principal is not None:
            principal = {**principal, **project_principal}

    from database import SessionLocal
    from workspace_store import (
        AnalysisCacheWriteError,
        AnalysisVersionConflictError,
        DurableAnalysisPersistenceError,
        persist_analysis_mutation,
    )

    db = SessionLocal()
    try:
        snapshot_version = detached_snapshot.get("_analysis_version")
        if restored_from is None and snapshot_version is not None:
            try:
                snapshot_version = int(snapshot_version)
            except (TypeError, ValueError) as exc:
                raise AnalysisVersionConflictError("Invalid immutable analysis version") from exc
            if expected_version is None:
                expected_version = snapshot_version
        operation = label or artifact_type or "analysis-mutation"
        raw_body = getattr(request, "_body", b"")
        if not isinstance(raw_body, bytes):
            raw_body = str(raw_body).encode("utf-8")
        supplied_idempotency_key = request.headers.get("idempotency-key")
        request_material = json.dumps(
            {
                "diagram_id": diagram_id,
                "operation": operation,
                "method": request.method,
                "path": request.url.path,
                "query": sorted(request.query_params.multi_items()),
                "body_hash": hashlib.sha256(raw_body).hexdigest(),
                "idempotency_key_hash": (
                    hashlib.sha256(supplied_idempotency_key.encode("utf-8")).hexdigest()
                    if supplied_idempotency_key
                    else None
                ),
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        request_hash = hashlib.sha256(request_material.encode("utf-8")).hexdigest()
        return persist_analysis_mutation(
            db,
            owner_user_id=principal["owner_user_id"],
            tenant_id=principal["tenant_id"],
            diagram_id=diagram_id,
            snapshot=detached_snapshot,
            session_store=SESSION_STORE,
            cache_owner_api_key_id=principal["owner_api_key_id"],
            artifact_type=artifact_type,
            artifact_format=artifact_format,
            artifact_content=artifact_content,
            expected_version=expected_version,
            operation=operation,
            request_hash=request_hash,
            label=label,
            restored_from=restored_from,
            cache_required=True,
            allow_legacy_cache_rehome=allow_legacy_cache_rehome,
            cache_legacy_owner_user_ids=(
                principal.get("legacy_owner_user_ids", [])
                if allow_legacy_cache_rehome
                else None
            ),
        )
    except AnalysisVersionConflictError as exc:
        try:
            from workspace_store import load_analysis_state

            load_analysis_state(
                db,
                diagram_id=diagram_id,
                owner_user_id=principal["owner_user_id"],
                tenant_id=principal["tenant_id"],
                session_store=SESSION_STORE,
                cache_owner_api_key_id=principal["owner_api_key_id"],
                allow_legacy_cache_rehome=allow_legacy_cache_rehome,
                cache_legacy_owner_user_ids=principal.get("legacy_owner_user_ids", []),
            )
        except Exception:
            logger.warning("analysis_cache_rehydrate_after_conflict_failed diagram_id=%s", _safe_log_value(diagram_id))
        raise ArchmorphException(
            409,
            "Analysis changed while this operation was running.",
            details={"error": "analysis_version_conflict"},
        ) from exc
    except AnalysisCacheWriteError as exc:
        raise ArchmorphException(
            503,
            "Analysis cache is temporarily unavailable. The durable record was saved; retry to continue.",
            details={"error": "analysis_cache_unavailable", "durable_saved": True},
            headers={"Retry-After": "5"},
        ) from exc
    except (DurableAnalysisPersistenceError, ValueError) as exc:
        raise ArchmorphException(
            503,
            "Analysis persistence is temporarily unavailable. Please retry shortly.",
            details={"error": "analysis_persistence_unavailable"},
            headers={"Retry-After": "30"},
        ) from exc
    finally:
        db.close()


async def persist_diagram_mutation_async(
    request: Request,
    diagram_id: str,
    snapshot: dict,
    **kwargs,
):
    """Run the synchronous canonical mutation UoW in Starlette's threadpool."""
    return await run_in_threadpool(
        partial(
            persist_diagram_mutation,
            request,
            diagram_id,
            snapshot,
            **kwargs,
        )
    )


# ─────────────────────────────────────────────────────────────
# Stores (#494 — Redis-backed in production, InMemory for dev)
# ─────────────────────────────────────────────────────────────

# Session store for analysis results (TTL: 2 hours, max 500 sessions)
SESSION_STORE = get_store("sessions", maxsize=500, ttl=7200)

# Image store keyed by diagram_id -> (image_bytes, content_type) (TTL: 2 hours)
# Aligned with SESSION_STORE TTL (7200s) so images don't expire before sessions
# Reduced from 200->50 to limit memory ceiling (50x10MB=500MB vs 2GB) — Issue #294
IMAGE_STORE = get_store("images", maxsize=int(os.getenv("IMAGE_STORE_MAXSIZE", "50")), ttl=7200)

# Optional versioned project read projection. PostgreSQL is authoritative;
# project authorization and membership must never consult this cache.
PROJECT_STORE = get_store("projects", maxsize=500, ttl=7200)

# Share links store (TTL: 24 hours, max 100)
SHARE_STORE = get_store("shares", maxsize=100, ttl=86400)

# One-time generated-artifact export capabilities (TTL configured in
# export_capabilities.py; store TTL matches session lifetime as an upper bound).
EXPORT_CAPABILITY_STORE = get_store("export_capabilities", maxsize=2000, ttl=7200)

# Production guard: warn if in-memory stores are used in production (#494)
_env = os.getenv("ENVIRONMENT", "development").lower()
if _env in ("production", "prod", "staging") and not _redis_url:
    logger.warning(
        "PRODUCTION WITHOUT REDIS: SESSION_STORE, IMAGE_STORE, SHARE_STORE use file-backed local storage. "
        "Data may be LOST on deploy/restart and will not scale across replicas. Set REDIS_URL or REDIS_HOST. (#494)"
    )

# ─────────────────────────────────────────────────────────────
# Environment & Config
# ─────────────────────────────────────────────────────────────
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", str(10 * 1024 * 1024)))


def generate_session_id(prefix: str) -> str:
    """Return a URL-safe, high-entropy session identifier."""
    return f"{prefix}-{secrets.token_urlsafe(16)}"


# ─────────────────────────────────────────────────────────────
# Per-session asyncio lock (#336) — prevents concurrent writes
# from corrupting session data in the store.
# ─────────────────────────────────────────────────────────────
_MAX_SESSION_LOCKS = 1024
_session_locks: OrderedDict[str, asyncio.Lock] = OrderedDict()
_session_locks_guard = asyncio.Lock()


async def get_session_lock(session_id: str) -> asyncio.Lock:
    """Return an asyncio.Lock for *session_id*, bounded to _MAX_SESSION_LOCKS."""
    async with _session_locks_guard:
        if session_id in _session_locks:
            _session_locks.move_to_end(session_id)
            return _session_locks[session_id]
        # Evict oldest if at capacity
        while len(_session_locks) >= _MAX_SESSION_LOCKS:
            _session_locks.popitem(last=False)
        lock = asyncio.Lock()
        _session_locks[session_id] = lock
        return lock


# ─────────────────────────────────────────────────────────────
# General Pydantic Models
# ─────────────────────────────────────────────────────────────
class Project(StrictBaseModel):
    id: Optional[str] = None
    name: str
    description: Optional[str] = None


class ServiceMapping(StrictBaseModel):
    source_service: str
    source_provider: str
    azure_service: str
    confidence: float
    notes: Optional[str] = None


class AnalysisResult(StrictBaseModel):
    diagram_id: str
    services_detected: int
    mappings: List[ServiceMapping]
    warnings: List[str] = []
