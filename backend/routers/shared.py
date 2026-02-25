"""
Shared state, dependencies, and models used across Archmorph API routers.
"""

import os
import logging
import secrets
from typing import Optional, List

from fastapi import HTTPException, Security, Header
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from slowapi import Limiter
from slowapi.util import get_remote_address

from admin_auth import (
    validate_session_token,
    is_configured as admin_is_configured,
)
from session_store import get_store

# ─────────────────────────────────────────────────────────────
# Rate Limiting
# ─────────────────────────────────────────────────────────────
limiter = Limiter(
    key_func=get_remote_address,
    enabled=os.getenv("RATE_LIMIT_ENABLED", "true").lower() != "false",
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
        if not _api_key_warning_logged:
            logger.warning("ARCHMORPH_API_KEY not set \u2014 API authentication is disabled")
            _api_key_warning_logged = True
        return  # Auth disabled — dev mode
    if not secrets.compare_digest(api_key or "", API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ─────────────────────────────────────────────────────────────
# Admin Auth Dependency
# ─────────────────────────────────────────────────────────────
async def verify_admin_key(
    authorization: Optional[str] = Header(None),
):
    """Verify admin session via Authorization: Bearer <jwt>."""
    if not admin_is_configured():
        raise HTTPException(503, "Admin API not configured")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or malformed Authorization header")

    token = authorization[7:]  # strip "Bearer "
    payload = validate_session_token(token)
    if payload is None:
        raise HTTPException(401, "Invalid or expired session token")
    return payload


# ─────────────────────────────────────────────────────────────
# In-memory Stores (backed by SessionStore abstraction — Issue #69)
# ─────────────────────────────────────────────────────────────

# Session store for analysis results (TTL: 2 hours, max 500 sessions)
SESSION_STORE = get_store("sessions", maxsize=500, ttl=7200)

# Image store keyed by diagram_id → (image_bytes, content_type) (TTL: 2 hours)
# Aligned with SESSION_STORE TTL (7200s) so images don't expire before sessions — Issue #264
# Reduced from 200→50 to limit memory ceiling (50×10MB=500MB vs 2GB) — Issue #294
IMAGE_STORE = get_store("images", maxsize=int(os.getenv("IMAGE_STORE_MAXSIZE", "50")), ttl=7200)

# Share links store (TTL: 24 hours, max 100)
SHARE_STORE = get_store("shares", maxsize=100, ttl=86400)

# ─────────────────────────────────────────────────────────────
# Environment & Config
# ─────────────────────────────────────────────────────────────
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", str(10 * 1024 * 1024)))


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
