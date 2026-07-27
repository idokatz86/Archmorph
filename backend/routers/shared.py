"""
Shared state, dependencies, and models used across Archmorph API routers.
"""

import asyncio
import copy
import os
import logging
import secrets
import hashlib
from collections import OrderedDict
from functools import lru_cache
from typing import Optional, List

from fastapi import Security, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from strict_models import StrictBaseModel

from slowapi import Limiter
from slowapi.util import get_remote_address

from admin_auth import (
    validate_session_token,
    is_configured as admin_is_configured,
)
from error_envelope import ArchmorphException
from session_store import get_store

# ─────────────────────────────────────────────────────────────
# Rate Limiting
# ─────────────────────────────────────────────────────────────
_redis_url = os.getenv("REDIS_URL", "")
_rate_limit_storage = os.getenv("RATE_LIMIT_STORAGE", _redis_url or "memory://")
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
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
ADMIN_BEARER = HTTPBearer(auto_error=False)
USER_BEARER = HTTPBearer(auto_error=False)
_API_PRINCIPAL_SALT = b"archmorph-api-principal-v1"
_API_PRINCIPAL_KDF_ITERATIONS = 120_000

logger = logging.getLogger(__name__)

_api_key_warning_logged = False


def _safe_log_value(value: object) -> str:
    return str(value).replace("\n", "").replace("\r", "")


async def verify_api_key(api_key: Optional[str] = Security(API_KEY_HEADER)):
    """Verify API key if authentication is enabled."""
    global _api_key_warning_logged
    if not API_KEY:
        environment = (os.getenv("ENVIRONMENT") or os.getenv("ENV") or "production").lower()
        if environment in ("production", "prod", "staging"):
            raise ArchmorphException(status_code=500, detail="Server misconfiguration: API key not set")
        if not _api_key_warning_logged:
            logger.warning("ARCHMORPH_API_KEY not set — API authentication is disabled (dev mode only)")
            _api_key_warning_logged = True
        return  # Auth disabled — dev mode only
    if not secrets.compare_digest(api_key or "", API_KEY):
        raise ArchmorphException(status_code=401, detail="Invalid or missing API key")


async def verify_api_key_required(api_key: Optional[str] = Security(API_KEY_HEADER)):
    """Verify API key for server-to-server routes, even in dev/test mode."""
    if not API_KEY:
        raise ArchmorphException(status_code=500, detail="Server misconfiguration: API key not set")
    if not secrets.compare_digest(api_key or "", API_KEY):
        raise ArchmorphException(status_code=401, detail="Invalid or missing API key")


async def verify_api_key_or_user_session(
    request: Request,
    api_key: Optional[str] = Security(API_KEY_HEADER),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(USER_BEARER),
):
    """Allow either the service API key or a signed-in user bearer session."""
    try:
        return await verify_api_key(api_key)
    except ArchmorphException as exc:
        if exc.status_code != 401:
            raise

        from auth import get_user_from_request_headers

        if credentials is not None and credentials.scheme.lower() == "bearer" and get_user_from_request_headers(dict(request.headers)):
            return
        raise ArchmorphException(status_code=401, detail="Invalid or missing API key or user session") from exc


def get_api_key_service_principal(headers: dict) -> Optional[str]:
    """Return a stable API-key service principal ID for a verified key."""
    api_key = headers.get("x-api-key")
    if API_KEY:
        if not secrets.compare_digest(api_key or "", API_KEY):
            return None
        key_material = api_key
    else:
        # Dev mode (API key auth disabled): only derive principal when a key is supplied.
        key_material = api_key
        if not key_material:
            return None
    digest = _derive_api_key_principal_digest(key_material)
    return f"api-key:{digest}"


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
        }
    api_key_id = get_api_key_service_principal(headers)
    if api_key_id:
        digest = api_key_id.split(":", 1)[-1]
        return {
            "owner_user_id": api_key_id,
            "tenant_id": f"service:{digest}",
            "owner_api_key_id": api_key_id,
            "legacy_owner_user_ids": [],
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


@lru_cache(maxsize=32)
def _derive_api_key_principal_digest(key_material: str) -> str:
    """Derive a stable opaque principal ID from API-key material."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        key_material.encode("utf-8"),
        _API_PRINCIPAL_SALT,
        _API_PRINCIPAL_KDF_ITERATIONS,
    ).hex()[:24]


# ─────────────────────────────────────────────────────────────
# Admin Auth Dependency
# ─────────────────────────────────────────────────────────────
async def verify_admin_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(ADMIN_BEARER),
):
    """Verify admin session via Authorization: Bearer <jwt>."""
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
        return load_analysis_state(
            db,
            diagram_id=diagram_id,
            owner_user_id=principal["owner_user_id"],
            tenant_id=principal["tenant_id"],
            session_store=SESSION_STORE,
            cache_owner_api_key_id=principal["owner_api_key_id"],
            allow_legacy_cache_rehome=legacy_owner_user_id is not None,
            cache_legacy_owner_user_ids=principal.get("legacy_owner_user_ids", []),
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

    session = _load_diagram_session_for_access(diagram_id)
    if session is None:
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
    return authorize_diagram_access(request, diagram_id)


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

    from database import SessionLocal
    from workspace_store import (
        AnalysisCacheWriteError,
        AnalysisVersionConflictError,
        DurableAnalysisPersistenceError,
        persist_analysis_mutation,
    )

    db = SessionLocal()
    try:
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
            label=label,
            cache_required=True,
            allow_legacy_cache_rehome=allow_legacy_cache_rehome,
            cache_legacy_owner_user_ids=(
                principal.get("legacy_owner_user_ids", [])
                if allow_legacy_cache_rehome
                else None
            ),
        )
    except AnalysisVersionConflictError as exc:
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


# ─────────────────────────────────────────────────────────────
# Stores (#494 — Redis-backed in production, InMemory for dev)
# ─────────────────────────────────────────────────────────────

# Session store for analysis results (TTL: 2 hours, max 500 sessions)
SESSION_STORE = get_store("sessions", maxsize=500, ttl=7200)

# Image store keyed by diagram_id -> (image_bytes, content_type) (TTL: 2 hours)
# Aligned with SESSION_STORE TTL (7200s) so images don't expire before sessions
# Reduced from 200->50 to limit memory ceiling (50x10MB=500MB vs 2GB) — Issue #294
IMAGE_STORE = get_store("images", maxsize=int(os.getenv("IMAGE_STORE_MAXSIZE", "50")), ttl=7200)

# Multi-diagram project store keyed by project_id -> metadata (TTL: 2 hours).
# Separate diagram->project index keeps existing diagram routes compatible while
# allowing analysis completion to update parent project status (#241).
PROJECT_STORE = get_store("projects", maxsize=500, ttl=7200)
DIAGRAM_PROJECT_STORE = get_store("diagram_projects", maxsize=1000, ttl=7200)

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
