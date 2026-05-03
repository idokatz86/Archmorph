"""
Shared state, dependencies, and models used across Archmorph API routers.
"""

import asyncio
import os
import logging
import secrets
from collections import OrderedDict
from typing import Optional, List

from fastapi import Security, Header
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

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

logger = logging.getLogger(__name__)

_api_key_warning_logged = False


async def verify_api_key(api_key: Optional[str] = Security(API_KEY_HEADER)):
    """Verify API key if authentication is enabled."""
    global _api_key_warning_logged
    if not API_KEY:
        if os.getenv("ENV", "development").lower() in ("production", "prod", "staging"):
            raise ArchmorphException(status_code=500, detail="Server misconfiguration: API key not set")
        if not _api_key_warning_logged:
            logger.warning("ARCHMORPH_API_KEY not set — API authentication is disabled (dev mode only)")
            _api_key_warning_logged = True
        return  # Auth disabled — dev mode only
    if not secrets.compare_digest(api_key or "", API_KEY):
        raise ArchmorphException(status_code=401, detail="Invalid or missing API key")


# ─────────────────────────────────────────────────────────────
# Admin Auth Dependency
# ─────────────────────────────────────────────────────────────
async def verify_admin_key(
    authorization: Optional[str] = Header(None),
):
    """Verify admin session via Authorization: Bearer <jwt>."""
    if not admin_is_configured():
        raise ArchmorphException(503, "Admin API not configured")

    if not authorization or not authorization.startswith("Bearer "):
        raise ArchmorphException(401, "Missing or malformed Authorization header")

    token = authorization[7:]  # strip "Bearer "
    payload = validate_session_token(token)
    if payload is None:
        raise ArchmorphException(401, "Invalid or expired session token")
    return payload


# ─────────────────────────────────────────────────────────────
# Stores (#494 — Redis-backed in production, InMemory for dev)
# ─────────────────────────────────────────────────────────────

# Session store for analysis results (TTL: 2 hours, max 500 sessions)
SESSION_STORE = get_store("sessions", maxsize=500, ttl=7200)

# Image store keyed by diagram_id -> (image_bytes, content_type) (TTL: 2 hours)
# Aligned with SESSION_STORE TTL (7200s) so images don't expire before sessions
# Reduced from 200->50 to limit memory ceiling (50x10MB=500MB vs 2GB) — Issue #294
IMAGE_STORE = get_store("images", maxsize=int(os.getenv("IMAGE_STORE_MAXSIZE", "50")), ttl=7200)

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
class Project(BaseModel):
    id: Optional[str] = None
    name: str
    description: Optional[str] = None


class ServiceMapping(BaseModel):
    source_service: str
    source_provider: str
    azure_service: str
    confidence: float
    notes: Optional[str] = None


class AnalysisResult(BaseModel):
    diagram_id: str
    services_detected: int
    mappings: List[ServiceMapping]
    warnings: List[str] = []
