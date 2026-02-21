"""
Archmorph Session Store — pluggable storage abstraction (Issue #69, Phase 1).

Provides a dict-like ``SessionStore`` that defaults to an in-memory
``cachetools.TTLCache`` and can optionally use Redis when ``REDIS_URL``
is set.

Usage::

    from session_store import get_store

    store = get_store("sessions", maxsize=500, ttl=7200)
    store["key"] = value
    val = store.get("key")
"""

import logging
import os
from typing import Any, Iterator, List, Optional

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

    # ── dict-like dunder methods ──────────────────────────

    def __getitem__(self, key: str) -> Any:
        val = self.get(key)
        if val is None:
            raise KeyError(key)
        return val

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __delitem__(self, key: str) -> None:
        self.delete(key)

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

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
        return [k[prefix_len:] for k in self._redis.keys(full_pattern)]

    def clear(self) -> None:
        keys = self._redis.keys(f"{self._prefix}:*")
        if keys:
            self._redis.delete(*keys)

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
_stores: dict[str, SessionStore] = {}

REDIS_URL = os.getenv("REDIS_URL", "")


def get_store(name: str, *, maxsize: int = 500, ttl: int = 7200) -> SessionStore:
    """Return a named ``SessionStore`` instance (singleton per name).

    When ``REDIS_URL`` is set, all stores use Redis.  Otherwise the
    default in-memory TTLCache backend is used.

    Args:
        name: Logical store name (e.g. ``"sessions"``, ``"images"``).
        maxsize: Maximum items (in-memory only).
        ttl: Time-to-live in seconds.

    Returns:
        A ``SessionStore`` instance.
    """
    if name in _stores:
        return _stores[name]

    if REDIS_URL:
        try:
            store: SessionStore = RedisStore(
                url=REDIS_URL, prefix=f"archmorph:{name}", maxsize=maxsize, ttl=ttl,
            )
        except Exception as exc:
            logger.warning("Redis unavailable (%s) — falling back to in-memory for '%s'", exc, name)
            store = InMemoryStore(maxsize=maxsize, ttl=ttl)
    else:
        store = InMemoryStore(maxsize=maxsize, ttl=ttl)

    _stores[name] = store
    return store


def reset_stores():
    """Clear the store registry (useful for testing)."""
    _stores.clear()
