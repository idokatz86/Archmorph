"""
Shared state, dependencies, and models used across Archmorph API routers.
"""

import os
import secrets
from typing import Optional, List

from fastapi import HTTPException, Security, Header
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from cachetools import TTLCache

from slowapi import Limiter
from slowapi.util import get_remote_address

from admin_auth import (
    validate_session_token,
    is_configured as admin_is_configured,
)

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


async def verify_api_key(api_key: Optional[str] = Security(API_KEY_HEADER)):
    """Verify API key if authentication is enabled."""
    if not API_KEY:
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
# In-memory Stores
# ─────────────────────────────────────────────────────────────

# In-memory session store for analysis results (TTL: 2 hours, max 500 sessions)
SESSION_STORE: TTLCache = TTLCache(maxsize=500, ttl=7200)

# In-memory image store keyed by diagram_id → (image_bytes, content_type) (TTL: 1 hour, max 200)
IMAGE_STORE: TTLCache = TTLCache(maxsize=200, ttl=3600)

# Share links store (TTL: 24 hours, max 100)
SHARE_STORE: TTLCache = TTLCache(maxsize=100, ttl=86400)  # 24 hour TTL

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
