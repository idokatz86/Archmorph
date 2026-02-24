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

    def __init__(self, maxsize: int = 500, ttl: int = 7200):
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)
        self._maxsize = maxsize
        self._ttl = ttl

    # ── public API ────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        return self._cache.get(key, default)

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        # TTLCache doesn't support per-key TTL; use the store-wide TTL
        self._cache[key] = value

    def delete(self, key: str) -> None:
        self._cache.pop(key, None)

    def keys(self, pattern: str = "*") -> List[str]:
        if pattern == "*":
            return list(self._cache.keys())
        # Simple glob-style pattern support
        import fnmatch
        return [k for k in self._cache.keys() if fnmatch.fnmatch(k, pattern)]

    def clear(self) -> None:
        self._cache.clear()

    # ── dict-like overrides ───────────────────────────────

    def __getitem__(self, key: str) -> Any:
        return self._cache[key]  # raises KeyError natively

    def __setitem__(self, key: str, value: Any) -> None:
        self._cache[key] = value

    def __delitem__(self, key: str) -> None:
        del self._cache[key]

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
        self._base = Path(os.getenv("SESSION_FILE_DIR", "/tmp/archmorph_sessions")) / name  # nosec B108
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
        val = self._read(self._path(key))
        return val if val is not None else default

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
        # Count files on disk without reading/parsing each one (avoids O(n) I/O).
        # Returns an upper-bound: expired files are lazily cleaned on read/evict,
        # so the count may include expired entries.  Callers use this for capacity
        # warnings (diagrams.py) and eviction triggers — an overcount is safe
        # (triggers warnings/eviction slightly early, never late).
        return sum(1 for _ in self._base.glob("*.json"))

    @property
    def maxsize(self) -> int:
        return self._maxsize

    def _evict_if_full(self) -> None:
        """Remove oldest entries when store exceeds maxsize.

        Uses a single sorted pass and deletes from the front of the
        pre-sorted list to avoid O(n²) repeated ``pop(0)`` on a list.
        """
        files = sorted(self._base.glob("*.json"), key=lambda p: p.stat().st_mtime)
        if len(files) < self._maxsize:
            return
        to_remove = len(files) - self._maxsize + 1  # free at least one slot
        for p in files[:to_remove]:
            p.unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────
# Redis backend (optional — activated when REDIS_URL is set)
# ─────────────────────────────────────────────────────────────

class RedisStore(SessionStore):
    """Redis-backed session store.

    Requires the ``redis`` package.  Values are serialized as JSON.
    """

    def __init__(self, url: str, prefix: str = "archmorph", maxsize: int = 0, ttl: int = 7200):
        import redis as _redis  # optional import
        import json as _json
        self._redis = _redis.from_url(url, decode_responses=True)
        self._redis.ping()  # Verify connectivity eagerly; raises on failure
        self._json = _json
        self._prefix = prefix
        self._ttl = ttl
        self._maxsize = maxsize or 10_000
        logger.info("Redis session store connected (%s, prefix=%s)", url, prefix)

    def _key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    def get(self, key: str, default: Any = None) -> Any:
        raw = self._redis.get(self._key(key))
        if raw is None:
            return default
        try:
            return self._json.loads(raw)
        except (self._json.JSONDecodeError, TypeError):
            return raw

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        payload = self._json.dumps(value, default=str)
        self._redis.setex(self._key(key), ttl or self._ttl, payload)

    def delete(self, key: str) -> None:
        self._redis.delete(self._key(key))

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
        # Count keys via SCAN without materializing a full list.
        count = 0
        cursor = 0
        while True:
            cursor, batch = self._redis.scan(
                cursor=cursor, match=f"{self._prefix}:*", count=100,
            )
            count += len(batch)
            if cursor == 0:
                break
        return count

    @property
    def maxsize(self) -> int:
        return self._maxsize


# ─────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────
_stores_lock = threading.Lock()
_stores: dict[str, SessionStore] = {}

REDIS_URL = os.getenv("REDIS_URL", "")
WORKER_COUNT = int(os.getenv("WEB_CONCURRENCY", os.getenv("UVICORN_WORKERS", "1")))


def _is_multi_worker() -> bool:
    """Detect if the application is running with multiple workers."""
    return WORKER_COUNT > 1


def get_store(name: str, *, maxsize: int = 500, ttl: int = 7200) -> SessionStore:
    """Return a named ``SessionStore`` instance (singleton per name).

    Backend selection (Issue #121 — multi-worker safety):
      1. ``REDIS_URL`` set → Redis
      2. Multi-worker (``--workers > 1``) → FileStore (shared via filesystem)
      3. Single worker → InMemoryStore

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

        if REDIS_URL:
            try:
                store: SessionStore = RedisStore(
                    url=REDIS_URL, prefix=f"archmorph:{name}", maxsize=maxsize, ttl=ttl,
                )
            except Exception as exc:
                logger.warning("Redis unavailable (%s) — falling back for '%s'", exc, name)
                if _is_multi_worker():
                    logger.warning(
                        "Multi-worker mode detected without Redis — using FileStore for '%s'. "
                        "Set REDIS_URL for production deployments.",
                        name,
                    )
                    store = FileStore(name=name, maxsize=maxsize, ttl=ttl)
                else:
                    store = InMemoryStore(maxsize=maxsize, ttl=ttl)
        elif _is_multi_worker():
            logger.warning(
                "⚠️  MULTI-WORKER MODE without REDIS_URL — using FileStore for '%s'. "
                "Sessions stored on local filesystem. Set REDIS_URL for production.",
                name,
            )
            store = FileStore(name=name, maxsize=maxsize, ttl=ttl)
        else:
            store = InMemoryStore(maxsize=maxsize, ttl=ttl)

        _stores[name] = store
    return store


def reset_stores():
    """Clear the store registry (useful for testing)."""
    _stores.clear()
