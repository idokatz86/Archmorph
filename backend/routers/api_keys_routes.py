from error_envelope import ArchmorphException
"""
Public API Key Management (Issue #259).

CRUD for API keys with scopes, rate limiting, and rotation.
Keys are stored in-memory (thread-safe) with prefix ``arch_``.
"""

import hashlib
import logging
import secrets
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from routers.shared import limiter, verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["API Keys"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_SCOPES: Set[str] = {"read", "write", "admin"}
KEY_PREFIX = "arch_"
DEFAULT_RATE_LIMIT = 100  # requests per minute


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class APIKeyRecord:
    id: str
    name: str
    key_hash: str  # SHA-256 of the full key — never store plaintext
    key_prefix: str  # first 12 chars for identification
    scopes: List[str]
    rate_limit: int  # requests per minute
    created_at: str
    expires_at: Optional[str] = None
    revoked: bool = False
    last_used_at: Optional[str] = None

    def to_dict(self, include_prefix: bool = True) -> Dict[str, Any]:
        d = asdict(self)
        del d["key_hash"]
        if not include_prefix:
            del d["key_prefix"]
        return d


# ---------------------------------------------------------------------------
# Thread-safe store
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_keys: Dict[str, APIKeyRecord] = {}  # id -> record
_hash_index: Dict[str, str] = {}  # key_hash -> id  (for fast lookup by key)

# Rate limiting state: key_id -> deque of timestamps
_rate_windows: Dict[str, deque] = {}


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _generate_key() -> str:
    return KEY_PREFIX + secrets.token_hex(32)


def _check_rate_limit(key_id: str, limit: int) -> bool:
    """Return True if the request is within rate limit, False otherwise."""
    now = time.monotonic()
    window = 60.0  # 1 minute

    with _lock:
        if key_id not in _rate_windows:
            _rate_windows[key_id] = deque()

        dq = _rate_windows[key_id]
        # Evict old entries
        while dq and dq[0] < now - window:
            dq.popleft()

        if len(dq) >= limit:
            return False

        dq.append(now)
        return True


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

def create_api_key(
    name: str,
    scopes: List[str],
    rate_limit: int = DEFAULT_RATE_LIMIT,
    expires_in_days: Optional[int] = None,
) -> tuple[APIKeyRecord, str]:
    """Create a new API key. Returns (record, raw_key)."""
    invalid = [s for s in scopes if s not in VALID_SCOPES]
    if invalid:
        raise ValueError(f"Invalid scopes: {invalid}. Valid: {sorted(VALID_SCOPES)}")
    if not scopes:
        raise ValueError("At least one scope is required")
    if rate_limit < 1 or rate_limit > 10000:
        raise ValueError("rate_limit must be between 1 and 10000")

    raw_key = _generate_key()
    key_hash = _hash_key(raw_key)
    now = datetime.now(timezone.utc)

    expires_at = None
    if expires_in_days and expires_in_days > 0:
        expires_at = (now + timedelta(days=expires_in_days)).isoformat()

    record = APIKeyRecord(
        id=f"ak-{uuid.uuid4().hex[:12]}",
        name=name,
        key_hash=key_hash,
        key_prefix=raw_key[:12],
        scopes=sorted(scopes),
        rate_limit=rate_limit,
        created_at=now.isoformat(),
        expires_at=expires_at,
    )

    with _lock:
        _keys[record.id] = record
        _hash_index[key_hash] = record.id

    logger.info("Created API key %s (%s) scopes=%s", record.id, name, scopes)
    return record, raw_key


def list_api_keys() -> List[Dict[str, Any]]:
    with _lock:
        return [r.to_dict() for r in _keys.values() if not r.revoked]


def get_api_key(key_id: str) -> Optional[APIKeyRecord]:
    with _lock:
        rec = _keys.get(key_id)
        if rec and not rec.revoked:
            return rec
        return None


def revoke_api_key(key_id: str) -> bool:
    with _lock:
        rec = _keys.get(key_id)
        if not rec or rec.revoked:
            return False
        rec.revoked = True
        # Remove from hash index
        _hash_index.pop(rec.key_hash, None)
    logger.info("Revoked API key %s", key_id)
    return True


def rotate_api_key(key_id: str) -> Optional[tuple[APIKeyRecord, str]]:
    """Rotate: revoke old key, create new one with same name/scopes/rate_limit."""
    with _lock:
        old = _keys.get(key_id)
        if not old or old.revoked:
            return None
        # Revoke old
        old.revoked = True
        _hash_index.pop(old.key_hash, None)

    # Create new with same parameters
    return create_api_key(
        name=old.name,
        scopes=old.scopes,
        rate_limit=old.rate_limit,
    )


def validate_api_key_by_raw(raw_key: str) -> Optional[APIKeyRecord]:
    """Validate a raw API key string. Returns record if valid, None otherwise."""
    key_hash = _hash_key(raw_key)
    with _lock:
        key_id = _hash_index.get(key_hash)
        if not key_id:
            return None
        rec = _keys.get(key_id)
        if not rec or rec.revoked:
            return None

        # Check expiry
        if rec.expires_at:
            exp = datetime.fromisoformat(rec.expires_at)
            if datetime.now(timezone.utc) > exp:
                return None

        rec.last_used_at = datetime.now(timezone.utc).isoformat()
        return rec


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------

class CreateKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, description="Human-readable key name")
    scopes: List[str] = Field(..., min_length=1, description="Permission scopes: read, write, admin")
    rate_limit: int = Field(DEFAULT_RATE_LIMIT, ge=1, le=10000, description="Max requests per minute")
    expires_in_days: Optional[int] = Field(None, ge=1, le=365, description="Days until expiry (optional)")


class CreateKeyResponse(BaseModel):
    id: str
    name: str
    key: str = Field(..., description="Full API key — shown only once")
    key_prefix: str
    scopes: List[str]
    rate_limit: int
    created_at: str
    expires_at: Optional[str] = None


class KeyInfo(BaseModel):
    id: str
    name: str
    key_prefix: str
    scopes: List[str]
    rate_limit: int
    created_at: str
    expires_at: Optional[str] = None
    last_used_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
    "/api/keys",
    response_model=CreateKeyResponse,
    summary="Create API key",
    description="Generate a new API key with specified scopes and rate limit. "
                "The full key is returned only once — store it securely.",
)
@limiter.limit("10/minute")
async def create_key(body: CreateKeyRequest, request: Request, _auth=Depends(verify_api_key)):
    invalid = [s for s in body.scopes if s not in VALID_SCOPES]
    if invalid:
        raise ArchmorphException(400, f"Invalid scopes: {invalid}. Valid: {sorted(VALID_SCOPES)}")

    try:
        record, raw_key = create_api_key(
            name=body.name,
            scopes=body.scopes,
            rate_limit=body.rate_limit,
            expires_in_days=body.expires_in_days,
        )
    except ValueError as exc:
        raise ArchmorphException(400, str(exc))

    return CreateKeyResponse(
        id=record.id,
        name=record.name,
        key=raw_key,
        key_prefix=record.key_prefix,
        scopes=record.scopes,
        rate_limit=record.rate_limit,
        created_at=record.created_at,
        expires_at=record.expires_at,
    )


@router.get(
    "/api/keys",
    response_model=List[KeyInfo],
    summary="List API keys",
    description="List all active (non-revoked) API keys. Full key values are never returned.",
)
@limiter.limit("30/minute")
async def list_keys(request: Request, _auth=Depends(verify_api_key)):
    return list_api_keys()


@router.delete(
    "/api/keys/{key_id}",
    summary="Revoke API key",
    description="Permanently revoke an API key. This cannot be undone.",
)
@limiter.limit("10/minute")
async def delete_key(key_id: str, request: Request, _auth=Depends(verify_api_key)):
    if not revoke_api_key(key_id):
        raise ArchmorphException(404, f"API key not found: {key_id}")
    return {"status": "revoked", "key_id": key_id}


@router.post(
    "/api/keys/{key_id}/rotate",
    response_model=CreateKeyResponse,
    summary="Rotate API key",
    description="Revoke the existing key and generate a new one with the same configuration. "
                "The old key is immediately invalidated.",
)
@limiter.limit("5/minute")
async def rotate_key(key_id: str, request: Request, _auth=Depends(verify_api_key)):
    result = rotate_api_key(key_id)
    if not result:
        raise ArchmorphException(404, f"API key not found or already revoked: {key_id}")

    record, raw_key = result
    return CreateKeyResponse(
        id=record.id,
        name=record.name,
        key=raw_key,
        key_prefix=record.key_prefix,
        scopes=record.scopes,
        rate_limit=record.rate_limit,
        created_at=record.created_at,
        expires_at=record.expires_at,
    )
