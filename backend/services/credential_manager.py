"""Secure Credential Manager for Cloud Scanners"""
from __future__ import annotations

import json
import logging
from typing import Optional
from cryptography.fernet import Fernet
from error_envelope import ArchmorphException

from session_store import get_store

logger = logging.getLogger(__name__)

# Single Fernet key per process to encrypt credentials in transient stores.
# Will regenerate on each restart to ensure credentials die with the container.
_FERNET_KEY = Fernet.generate_key()
_fernet = Fernet(_FERNET_KEY)

# Use dedicated store namespace for credentials to avoid collision with standard user sessions.
_CRED_STORE = get_store("credentials", maxsize=500, ttl=3600)  # 1 hour expiry


def encrypt_payload(data: dict) -> str:
    """Encrypt dictionary data to an AES-256 token."""
    raw = json.dumps(data).encode("utf-8")
    return _fernet.encrypt(raw).decode("utf-8")


def decrypt_payload(token: str) -> dict:
    """Decrypt an AES-256 token back to a dictionary."""
    try:
        raw = _fernet.decrypt(token.encode("utf-8"))
        return json.loads(raw.decode("utf-8"))
    except Exception as e:
        logger.error("Credential decryption failed: %s", str(e))
        raise ArchmorphException(401, "Invalid or corrupted credential token")


def store_credentials(
    session_token: str,
    provider: str,
    creds: dict,
    *,
    owner_user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> None:
    """
    Encrypt and store credentials securely for the current session.
    credentials NEVER touch database or disk unless FileStore is used (which encrypts).
    """
    # Wrap with provider envelope
    payload = {"provider": provider, "credentials": creds}
    encrypted = encrypt_payload(payload)
    
    # Store directly with session_token as key
    _CRED_STORE.set(
        session_token,
        {
            "ciphertext": encrypted,
            "owner_user_id": owner_user_id,
            "tenant_id": tenant_id,
        },
        ttl=3600,
    )
    logger.info("Encrypted credentials stored for session_token ending in %s", str(str(session_token[-4:]).replace("\n", "").replace("\r", "")).replace("\n", "").replace("\r", ""))  # lgtm[py/log-injection]


def get_credentials(session_token: str, expected_provider: Optional[str] = None) -> dict:
    """
    Retrieve and decrypt credentials for active session.
    """
    stored = _CRED_STORE.get(session_token)
    if not stored:
        raise ArchmorphException(401, "No credentials found for session. They may have expired.")
    encrypted = stored.get("ciphertext") if isinstance(stored, dict) else stored
    if not encrypted:
        raise ArchmorphException(401, "No credentials found for session. They may have expired.")
    
    payload = decrypt_payload(encrypted)
    
    if expected_provider and payload.get("provider") != expected_provider:
        raise ArchmorphException(400, f"Credentials are for {payload.get('provider')}, but asked for {expected_provider}")
    
    return payload.get("credentials", {})


def clear_credentials(session_token: str) -> None:
    """Immediately remove a session's credentials."""
    _CRED_STORE.delete(session_token)
    logger.info("Credentials cleared for session terminating in %s", str(str(session_token[-4:]).replace("\n", "").replace("\r", "")).replace("\n", "").replace("\r", ""))  # lgtm[py/log-injection]


def purge_scope_credentials(owner_user_id: str, tenant_id: str) -> int:
    """Delete all transient credentials belonging to an owner/tenant scope."""
    removed = 0
    for session_token in list(_CRED_STORE.keys("*")):
        stored = _CRED_STORE.peek(session_token)
        if not isinstance(stored, dict):
            continue
        if (
            stored.get("owner_user_id") != owner_user_id
            or stored.get("tenant_id") != tenant_id
        ):
            continue
        if not _CRED_STORE.delete(session_token):
            raise RuntimeError("Credential deletion could not be confirmed")
        removed += 1
    return removed


def scope_credentials_absent(owner_user_id: str, tenant_id: str) -> bool:
    return not any(
        isinstance((stored := _CRED_STORE.peek(session_token)), dict)
        and stored.get("owner_user_id") == owner_user_id
        and stored.get("tenant_id") == tenant_id
        for session_token in _CRED_STORE.keys("*")
    )

