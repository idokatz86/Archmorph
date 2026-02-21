"""
Archmorph Admin Authentication — JWT-based admin session management.

Flow:
  1. Admin enters the ADMIN_KEY in the frontend login form
  2. POST /api/admin/login  → validates key, returns a short-lived JWT
  3. Subsequent admin API calls include  Authorization: Bearer <jwt>
  4. POST /api/admin/logout → revokes the token (optional)

The ADMIN_KEY never leaves the server; only a signed JWT goes to the
browser and is held in React state (memory-only, not localStorage).
"""

import os
import secrets
import logging
from datetime import datetime, timezone, timedelta
from threading import Lock
from typing import Dict, Optional

from jose import jwt, JWTError  # python-jose[cryptography] already in requirements

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────
ADMIN_SECRET = os.getenv("ARCHMORPH_ADMIN_KEY", "")

# JWT signing key — derived from admin secret + random salt generated at startup.
# If the container restarts, existing tokens become invalid (acceptable trade-off).
_JWT_SALT = secrets.token_urlsafe(32)
JWT_SECRET = f"{ADMIN_SECRET}:{_JWT_SALT}" if ADMIN_SECRET else ""
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("ADMIN_SESSION_TTL_MINUTES", "60"))

# ── Token revocation (in-memory blacklist) ───────────────────
# Maps JTI → expiry timestamp (for cleanup)
_revoked_tokens: Dict[str, float] = {}
_revoke_lock = Lock()


def _cleanup_revoked() -> None:
    """Remove expired JTIs from the revocation dict (prevents unbounded growth)."""
    now = datetime.now(timezone.utc).timestamp()
    with _revoke_lock:
        expired = [jti for jti, exp_ts in _revoked_tokens.items() if exp_ts < now]
        for jti in expired:
            del _revoked_tokens[jti]


# ── Public API ───────────────────────────────────────────────

def verify_admin_secret(candidate: str) -> bool:
    """Check whether *candidate* matches the configured ADMIN_KEY (timing-safe)."""
    if not ADMIN_SECRET:
        return False
    return secrets.compare_digest(candidate, ADMIN_SECRET)


def create_session_token() -> str:
    """Issue a short-lived JWT for an authenticated admin session."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "admin",
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRE_MINUTES),
        "jti": secrets.token_urlsafe(16),  # unique token ID for revocation
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def validate_session_token(token: str) -> Optional[dict]:
    """
    Validate a JWT session token.

    Returns the decoded payload on success, or None if the token is
    invalid, expired, or revoked.
    """
    if not JWT_SECRET:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
    # Check revocation
    jti = payload.get("jti", "")
    with _revoke_lock:
        if jti in _revoked_tokens:
            return None
    return payload


def revoke_token(token: str) -> bool:
    """Add a token's JTI to the revocation dict. Returns True if successful."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return False
    jti = payload.get("jti", "")
    if not jti:
        return False
    exp_ts = float(payload.get("exp", 0))
    with _revoke_lock:
        _revoked_tokens[jti] = exp_ts
    # Periodic cleanup
    if len(_revoked_tokens) > 100:
        _cleanup_revoked()
    return True


def is_configured() -> bool:
    """Return True when the admin key is properly configured."""
    return bool(ADMIN_SECRET)
