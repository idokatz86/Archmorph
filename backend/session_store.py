"""
Archmorph Session Store — pluggable storage abstraction (Issue #69, Phase 1).

Provides a dict-like ``SessionStore`` that defaults to an in-memory
``cachetools.TTLCache`` and can optionally use Redis when ``REDIS_URL``
is set.

Issue #121 — When running with multiple workers (``--workers > 1``) and no
Redis URL configured, a **FileStore** backend is used to share state across
workers via the filesystem.  Pure in-memory mode is restricted to single-
worker deployments to prevent data loss.

Usage::

    from session_store import get_store

    store = get_store("sessions", maxsize=500, ttl=7200)
    store["key"] = value
    val = store.get("key")
"""

import logging
import os
import threading
import json as _json
import time as _time
import fcntl
from pathlib import Path
from typing import Any, List, Optional

from cachetools import TTLCache
from log_sanitizer import safe

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Abstract interface
# ─────────────────────────────────────────────────────────────

class SessionStore:
    """Dict-like session store with pluggable backend.

    Supports ``__getitem__``, ``__setitem__``, ``__delitem__``,
    ``__contains__``, ``__len__``, ``.get()``, and ``.keys()``
    so it is a drop-in replacement for ``cachetools.TTLCache``.
    """

    def get(self, key: str, default: Any = None) -> Any:
        raise NotImplementedError

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def keys(self, pattern: str = "*") -> List[str]:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError

    # Sentinel for __contains__ — distinguishes "key absent" from "value is None"
    _MISSING = object()

    # ── dict-like dunder methods ──────────────────────────

    def __getitem__(self, key: str) -> Any:
        val = self.get(key, self._MISSING)
        if val is self._MISSING:
            raise KeyError(key)
        return val

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __delitem__(self, key: str) -> None:
        self.delete(key)

    def __contains__(self, key: str) -> bool:
        return self.get(key, self._MISSING) is not self._MISSING

    def __len__(self) -> int:
        return len(self.keys())

    @property
    def maxsize(self) -> int:  # pragma: no cover
        return 0


# ─────────────────────────────────────────────────────────────
# In-memory backend (default)
# ─────────────────────────────────────────────────────────────

class InMemoryStore(SessionStore):
    """In-memory TTLCache backend — identical behaviour to the old raw TTLCache."""

    # Maximum total memory budget for a single store (default 512MB)
    MAX_MEMORY_BYTES = int(os.getenv("SESSION_STORE_MAX_MEMORY_MB", "512")) * 1024 * 1024

    def __init__(self, maxsize: int = 500, ttl: int = 7200):
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)
        self._maxsize = maxsize
        self._ttl = ttl
        self._total_bytes = 0  # approximate memory tracking (Issue #294)

    # ── public API ────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        val = self._cache.get(key)
        if val is None:
            return default
        # Refresh TTL by re-inserting the value (Issue #260)
        self._cache[key] = val
        return val

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        # Estimate entry size and enforce memory budget (Issue #294)
        import sys
        entry_size = sys.getsizeof(value) if value is not None else 0
        if isinstance(value, (bytes, bytearray)):
            entry_size = len(value)
        elif isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], (bytes, str)):
            # IMAGE_STORE stores (bytes, content_type) or (str_base64, content_type) tuples.
            # For base64 strings len() counts characters (~33% larger than raw bytes),
            # which is intentional — we budget the actual stored bytes, not the decoded size.
            entry_size = len(value[0])

        # Evict oldest entries until there is room or the cache is empty
        evicted_keys = []
        while self._total_bytes + entry_size > self.MAX_MEMORY_BYTES and self._cache:
            oldest_key = next(iter(self._cache))
            self.delete(oldest_key)
            evicted_keys.append(oldest_key)

        if evicted_keys:
            logger.warning(
                "InMemoryStore memory budget exceeded (%d + %d > %s bytes) — evicted %d oldest entries",
                self._total_bytes, entry_size, self.MAX_MEMORY_BYTES, len(evicted_keys),
            )

        if self._total_bytes + entry_size > self.MAX_MEMORY_BYTES:
            logger.warning(
                "InMemoryStore memory budget still exceeded after eviction — rejecting entry",
            )
            return

        # TTLCache doesn't support per-key TTL; use the store-wide TTL
        self._cache[key] = value
        self._total_bytes += entry_size

    def delete(self, key: str) -> None:
        val = self._cache.pop(key, None)
        if val is not None:
            import sys
            if isinstance(val, (bytes, bytearray)):
                self._total_bytes -= len(val)
            elif isinstance(val, tuple) and len(val) == 2 and isinstance(val[0], (bytes, str)):
                self._total_bytes -= len(val[0])
            else:
                self._total_bytes -= sys.getsizeof(val)

    def keys(self, pattern: str = "*") -> List[str]:
        if pattern == "*":
            return list(self._cache.keys())
        # Simple glob-style pattern support
        import fnmatch
        return [k for k in self._cache.keys() if fnmatch.fnmatch(k, pattern)]

    def clear(self) -> None:
        self._cache.clear()
        self._total_bytes = 0

    # ── dict-like overrides ───────────────────────────────

    def __getitem__(self, key: str) -> Any:
        return self._cache[key]  # raises KeyError natively

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __delitem__(self, key: str) -> None:
        self.delete(key)

    def __contains__(self, key: str) -> bool:
        return key in self._cache

    def __len__(self) -> int:
        return len(self._cache)

    @property
    def maxsize(self) -> int:
        return self._maxsize


# ─────────────────────────────────────────────────────────────
# File-backed store (multi-worker without Redis — Issue #121)
# ─────────────────────────────────────────────────────────────

class FileStore(SessionStore):
    """File-backed session store for multi-worker deployments without Redis.

    Each key is stored as a JSON file under ``base_dir/store_name/``.
    File locking (``fcntl.flock``) ensures atomicity across workers.
    TTL is enforced by storing expiry timestamps alongside values.
    """

    def __init__(self, name: str, maxsize: int = 500, ttl: int = 7200):
        import tempfile
        self._base = Path(os.getenv("SESSION_FILE_DIR", os.path.join(tempfile.gettempdir(), "archmorph_sessions"))) / name
        self._base.mkdir(parents=True, exist_ok=True)
        self._ttl = ttl
        self._maxsize = maxsize
        logger.info("File-backed session store: %s (ttl=%ds)", self._base, ttl)

    def _path(self, key: str) -> Path:
        # Sanitize key to filesystem-safe name
        safe = key.replace("/", "_").replace("..", "_")
        return self._base / f"{safe}.json"

    def _read(self, path: Path) -> Any:
        """Read a file, return value if not expired, else None."""
        if not path.exists():
            return None
        try:
            with open(path, "r") as f:
                fcntl.flock(f, fcntl.LOCK_SH)
                try:
                    data = _json.load(f)
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
            if data.get("expires_at", 0) < _time.time():
                path.unlink(missing_ok=True)
                return None
            return data.get("value")
        except (ValueError, OSError, KeyError):
            return None

    def get(self, key: str, default: Any = None) -> Any:
        path = self._path(key)
        val = self._read(path)
        if val is None:
            return default
        # Refresh TTL on read to keep active sessions alive (Issue #260)
        self._touch_ttl(path)
        return val

    def _touch_ttl(self, path: Path) -> None:
        """Refresh the expiry timestamp of a file-backed entry."""
        if not path.exists():
            return
        try:
            with open(path, "r+") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    data = _json.load(f)
                    data["expires_at"] = _time.time() + self._ttl
                    f.seek(0)
                    f.truncate()
                    _json.dump(data, f, default=str)
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except (ValueError, OSError):
            pass  # Best-effort TTL refresh

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        self._evict_if_full()
        path = self._path(key)
        payload = {"value": value, "expires_at": _time.time() + (ttl or self._ttl)}
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                _json.dump(payload, f, default=str)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        tmp.rename(path)  # Atomic on POSIX

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def keys(self, pattern: str = "*") -> List[str]:
        import fnmatch
        result = []
        for p in self._base.glob("*.json"):
            name = p.stem
            if self._read(p) is not None:
                if pattern == "*" or fnmatch.fnmatch(name, pattern):
                    result.append(name)
        return result

    def clear(self) -> None:
        for p in self._base.glob("*.json"):
            p.unlink(missing_ok=True)

    def __contains__(self, key: str) -> bool:
        return self._read(self._path(key)) is not None

    def __len__(self) -> int:
        # Count non-expired files without full JSON parse (#297 — was O(n) parse).
        # Only check mtime + stat, read expiry cheaply via _read for expired items.
        now = _time.time()
        count = 0
        for p in self._base.glob("*.json"):
            try:
                # Quick stat-based age check: if file is younger than TTL, count it
                if now - p.stat().st_mtime < self._ttl:
                    count += 1
                else:
                    # File older than TTL — check actual expires_at (may have been refreshed)
                    if self._read(p) is not None:
                        count += 1
            except OSError:
                continue
        return count

    @property
    def maxsize(self) -> int:
        return self._maxsize

    def _evict_if_full(self) -> None:
        """Remove oldest expired entries when store exceeds maxsize."""
        files = sorted(self._base.glob("*.json"), key=lambda p: p.stat().st_mtime)
        while len(files) >= self._maxsize:
            oldest = files.pop(0)
            oldest.unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────
# Redis connection helper — Entra ID or URL-based auth
# ─────────────────────────────────────────────────────────────

def _create_redis_client(*, decode_responses: bool = True, socket_connect_timeout: int = 5):
    """Create a Redis client using Entra ID token auth or a connection URL.

    Auth strategy (checked in order):
      1. ``REDIS_HOST`` set → Entra ID (``DefaultAzureCredential``) over TLS
      2. ``REDIS_URL``  set → traditional URL-based auth (access key / password)

    Raises ``RuntimeError`` when neither variable is set.
    """
    import redis as _redis

    host = os.getenv("REDIS_HOST", "")
    url = os.getenv("REDIS_URL", "")

    if host:
        # ── Entra ID token-based auth ─────────────────────
        from azure.identity import DefaultAzureCredential

        credential = DefaultAzureCredential()
        token = credential.get_token("https://redis.azure.com/.default")

        # username = Object-ID of the managed identity (from access-policy)
        # password = Entra ID access token
        principal_id = os.getenv(
            "AZURE_CLIENT_ID",  # user-assigned MI
            os.getenv("IDENTITY_PRINCIPAL_ID", ""),  # explicit override
        )
        # If no explicit principal ID, use the token's oid claim
        if not principal_id:
            import base64
            import json as _j
            # JWT: header.payload.signature — decode the payload
            payload = token.token.split(".")[1]
            payload += "=" * (4 - len(payload) % 4)  # pad base64
            claims = _j.loads(base64.urlsafe_b64decode(payload))
            principal_id = claims.get("oid", "")

        client = _redis.Redis(
            host=host,
            port=int(os.getenv("REDIS_PORT", "6380")),
            ssl=True,
            username=principal_id,
            password=token.token,
            decode_responses=decode_responses,
            socket_connect_timeout=socket_connect_timeout,
        )
        client.ping()
        logger.info("Redis connected via Entra ID (host=%s, principal=%s…)", host, principal_id[:8])
        return client

    if url:
        # ── Traditional URL-based auth ────────────────────
        client = _redis.from_url(
            url,
            decode_responses=decode_responses,
            socket_connect_timeout=socket_connect_timeout,
        )
        client.ping()
        logger.info("Redis connected via URL")
        return client

    raise RuntimeError("Neither REDIS_HOST nor REDIS_URL is configured")


def redis_configured() -> bool:
    """Return True if Redis env vars are set (Entra ID or URL)."""
    return bool(os.getenv("REDIS_HOST", "") or os.getenv("REDIS_URL", ""))


# ─────────────────────────────────────────────────────────────
# Redis backend (optional — activated when REDIS_HOST or REDIS_URL is set)
# ─────────────────────────────────────────────────────────────

class RedisStore(SessionStore):
    """Redis-backed session store.

    Supports Entra ID token auth (``REDIS_HOST``) or traditional URL
    auth (``REDIS_URL``).  Values are serialized as JSON.
    """

    def __init__(self, prefix: str = "archmorph", maxsize: int = 0, ttl: int = 7200):
        import json as _json
        self._redis = _create_redis_client()
        self._json = _json
        self._prefix = prefix
        self._ttl = ttl
        self._maxsize = maxsize or 10_000
        logger.info("Redis session store ready (prefix=%s)", prefix)

    def _key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    def get(self, key: str, default: Any = None) -> Any:
        from circuit_breakers import redis_breaker
        try:
            raw = redis_breaker.call(self._redis.get, self._key(key))
        except Exception as exc:
            logger.warning("Redis GET failed for '%s': %s — returning default", safe(key), safe(exc))
            return default
        if raw is None:
            return default
        # Refresh TTL on read to keep active sessions alive (Issue #260)
        try:
            self._redis.expire(self._key(key), self._ttl)
        except Exception:
            pass  # nosec B110 — Non-critical TTL refresh is best-effort
        try:
            return self._json.loads(raw)
        except (self._json.JSONDecodeError, TypeError):
            return raw

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        from circuit_breakers import redis_breaker
        try:
            payload = self._json.dumps(value, default=str)
            redis_breaker.call(self._redis.setex, self._key(key), ttl or self._ttl, payload)
        except Exception as exc:
            logger.warning("Redis SET failed for '%s': %s — data not persisted", safe(key), safe(exc))

    def delete(self, key: str) -> None:
        from circuit_breakers import redis_breaker
        try:
            redis_breaker.call(self._redis.delete, self._key(key))
        except Exception as exc:
            logger.warning("Redis DELETE failed for '%s': %s", safe(key), safe(exc))

    def keys(self, pattern: str = "*") -> List[str]:
        full_pattern = f"{self._prefix}:{pattern}"
        prefix_len = len(self._prefix) + 1
        result = []
        cursor = 0
        while True:
            cursor, batch = self._redis.scan(cursor=cursor, match=full_pattern, count=100)
            result.extend(k[prefix_len:] for k in batch)
            if cursor == 0:
                break
        return result

    def clear(self) -> None:
        cursor = 0
        while True:
            cursor, batch = self._redis.scan(cursor=cursor, match=f"{self._prefix}:*", count=100)
            if batch:
                self._redis.delete(*batch)
            if cursor == 0:
                break

    def __contains__(self, key: str) -> bool:
        return self._redis.exists(self._key(key)) > 0

    def __len__(self) -> int:
        return len(self.keys())

    @property
    def maxsize(self) -> int:
        return self._maxsize


# ─────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────
_stores_lock = threading.Lock()
_stores: dict[str, SessionStore] = {}

REDIS_URL = os.getenv("REDIS_URL", "")  # kept for backward compat
REDIS_HOST = os.getenv("REDIS_HOST", "")  # Entra ID mode
WORKER_COUNT = int(os.getenv("WEB_CONCURRENCY", os.getenv("UVICORN_WORKERS", "1")))
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
REQUIRE_REDIS = os.getenv("REQUIRE_REDIS", os.getenv("ENFORCE_REDIS", "")).lower() in ("1", "true", "yes")


def _env_int(name: str, default: int = 1) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _is_multi_worker() -> bool:
    """Detect if the application is running with multiple workers."""
    return _env_int("WEB_CONCURRENCY", _env_int("UVICORN_WORKERS", WORKER_COUNT)) > 1


def _declared_replica_count() -> int:
    """Return the deployment-declared replica count, if provided."""
    return max(
        _env_int("CONTAINER_APP_REPLICA_COUNT", 1),
        _env_int("CONTAINER_APP_MIN_REPLICAS", 1),
    )


def _is_multi_replica() -> bool:
    """Detect if the deployment has declared multiple active/min replicas."""
    return _declared_replica_count() > 1


def _is_production() -> bool:
    """Detect if the application is running in a production-like environment."""
    return os.getenv("ENVIRONMENT", ENVIRONMENT).lower() in ("production", "prod", "staging")


def _redis_required() -> bool:
    """Return True when Redis is an explicit hard dependency."""
    return os.getenv(
        "REQUIRE_REDIS",
        os.getenv("ENFORCE_REDIS", "true" if REQUIRE_REDIS else ""),
    ).lower() in ("1", "true", "yes")


def session_store_backend() -> str:
    """Return the backend family selected by current environment config."""
    if redis_configured():
        return "redis"
    if _is_production() or _is_multi_worker():
        return "file"
    return "memory"


def session_store_readiness() -> dict[str, Any]:
    """Return operator-facing readiness metadata for release gates."""
    backend = session_store_backend()
    redis_ready = backend == "redis"
    requires_redis_for_scale = _is_multi_worker() or _is_multi_replica()
    scale_blocked = requires_redis_for_scale and not redis_ready
    return {
        "backend": backend,
        "redis_configured": redis_configured(),
        "require_redis": _redis_required(),
        "production_like": _is_production(),
        "multi_worker": _is_multi_worker(),
        "declared_replica_count": _declared_replica_count(),
        "multi_replica": _is_multi_replica(),
        "requires_redis_for_scale": requires_redis_for_scale,
        "ready_for_horizontal_scale": redis_ready,
        "scale_blocked": scale_blocked,
        "scale_blocked_reason": (
            "Redis is required when WEB_CONCURRENCY/UVICORN_WORKERS or declared replicas exceed 1"
            if scale_blocked
            else None
        ),
    }


def get_store(name: str, *, maxsize: int = 500, ttl: int = 7200) -> SessionStore:
    """Return a named ``SessionStore`` instance (singleton per name).

    Backend selection (Issues #121, #262, #286):
      1. ``REDIS_URL`` set → Redis (recommended for all environments)
      2. Production/staging without Redis → FileStore + loud warning
      3. Multi-worker without Redis → FileStore
      4. Dev single-worker → InMemoryStore

    Args:
        name: Logical store name (e.g. ``"sessions"``, ``"images"``).
        maxsize: Maximum items (in-memory / file store).
        ttl: Time-to-live in seconds.

    Returns:
        A ``SessionStore`` instance.
    """
    if name in _stores:
        return _stores[name]

    with _stores_lock:
        if name in _stores:
            return _stores[name]

        if redis_configured():
            try:
                store: SessionStore = RedisStore(
                    prefix=f"archmorph:{name}", maxsize=maxsize, ttl=ttl,
                )
            except Exception as exc:
                logger.warning("Redis unavailable (%s) — falling back for '%s'", exc, name)
                if REQUIRE_REDIS:
                    raise RuntimeError("REQUIRE_REDIS is set but Redis is unavailable") from exc
                if _is_production() or _is_multi_worker():
                    logger.warning(
                        "⚠️  PRODUCTION/MULTI-WORKER without Redis — using FileStore for '%s'. "
                        "Set REDIS_URL for production deployments. (Issues #262, #286)",
                        name,
                    )
                    store = FileStore(name=name, maxsize=maxsize, ttl=ttl)
                else:
                    store = InMemoryStore(maxsize=maxsize, ttl=ttl)
        elif _is_production():
            # Issue #262/#286 — In production, NEVER use InMemoryStore.
            # Data is lost on every deploy/restart.
            if REQUIRE_REDIS:
                raise RuntimeError("REQUIRE_REDIS is set but REDIS_HOST/REDIS_URL is not configured")
            logger.error(
                "🚨 PRODUCTION without REDIS_URL — using FileStore for '%s'. "
                "ALL session data will be lost on container restart! "
                "Set REDIS_URL immediately. (Issues #262, #286)",
                name,
            )
            store = FileStore(name=name, maxsize=maxsize, ttl=ttl)
        elif _is_multi_worker():
            logger.warning(
                "⚠️  MULTI-WORKER MODE without REDIS_URL — using FileStore for '%s'. "
                "Sessions stored on local filesystem. Set REDIS_URL for production.",
                name,
            )
            store = FileStore(name=name, maxsize=maxsize, ttl=ttl)
        else:
            logger.info(
                "Development mode: using InMemoryStore for '%s' (data lost on restart). "
                "Set REDIS_URL for persistent sessions.",
                name,
            )
            store = InMemoryStore(maxsize=maxsize, ttl=ttl)

        _stores[name] = store
    return store


def reset_stores():
    """Clear the store registry (useful for testing)."""
    _stores.clear()
