"""
Shared state, dependencies, and models used across Archmorph API routers.
"""

import asyncio
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
_API_PRINCIPAL_SALT = b"archmorph-api-principal-v1"
_API_PRINCIPAL_KDF_ITERATIONS = 120_000

logger = logging.getLogger(__name__)

_api_key_warning_logged = False


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


def require_diagram_access(
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
        if not owner_user_id or not tenant_id:
            logger.debug(
                "deny_diagram_access_missing_user_metadata diagram_id=%s owner=%s tenant=%s",
                diagram_id,
                bool(owner_user_id),
                bool(tenant_id),
            )
            raise ArchmorphException(404, "Diagram not found")
        if owner_user_id != user.id or tenant_id != user.tenant_id:
            raise ArchmorphException(404, "Diagram not found")
        return session

    api_key_principal_id = get_api_key_service_principal(headers)
    if not api_key_principal_id:
        raise ArchmorphException(401, f"Authentication required to {purpose}")

    owner_api_key_id = session.get("_owner_api_key_id")
    if not owner_api_key_id or owner_api_key_id != api_key_principal_id:
        logger.debug(
            "deny_diagram_access_missing_api_principal diagram_id=%s owner_api_key=%s",
            diagram_id,
            bool(owner_api_key_id),
        )
        raise ArchmorphException(404, "Diagram not found")
    return session


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
