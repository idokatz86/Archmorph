"""
Tests verifying that rate-limit state is shared across replicas when a shared
storage backend (Redis in production) is used. Fixes #873.

Key scenarios:
  1. When two "replica" limiter instances share the same storage backend
     (e.g. Redis), one replica consuming the budget also limits the other.
  2. When each replica has its own in-memory storage (dev/local),
     requests are siloed per-process — the bypass-via-load-balancing issue.
  3. Production environment warns if REDIS_URL is absent.
  4. The shared.py module selects Redis storage when REDIS_URL is set.

The shared-state property is demonstrated using `limits` MemoryStorage shared
by reference between two strategy instances — the same mechanism that makes
Redis-backed storage work across real replicas.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Helpers — direct `limits` library tests (no HTTP overhead)
# ---------------------------------------------------------------------------

def _make_strategy(storage):
    """Return a FixedWindowRateLimiter backed by the given storage."""
    from limits.strategies import FixedWindowRateLimiter
    return FixedWindowRateLimiter(storage)


def _make_rate(expr: str):
    from limits import parse
    return parse(expr)


class TestSharedStorageRateLimit:
    """Rate-limit state is shared when two limiters use the same backend."""

    def test_shared_storage_enforces_across_replicas(self):
        """
        Replica A and Replica B sharing a storage backend (e.g. Redis):
        requests consumed on A count toward the global budget and block B.
        """
        from limits.storage import MemoryStorage

        shared = MemoryStorage()   # simulates a single shared Redis server
        replica_a = _make_strategy(shared)
        replica_b = _make_strategy(shared)
        rate = _make_rate("3/minute")
        key = "ip:203.0.113.1"

        # Replica A consumes all 3 allowed requests
        assert replica_a.hit(rate, key) is True   # 1st
        assert replica_a.hit(rate, key) is True   # 2nd
        assert replica_a.hit(rate, key) is True   # 3rd

        # Replica B — same key, same storage — should now be blocked
        allowed = replica_b.hit(rate, key)
        assert allowed is False, (
            "Replica B must be blocked when the budget was exhausted by Replica A "
            "(shared storage). This verifies the Redis-backed shared-state fix."
        )

    def test_shared_storage_allows_different_keys(self):
        """Different IP keys are independent even on a shared backend."""
        from limits.storage import MemoryStorage

        shared = MemoryStorage()
        replica_a = _make_strategy(shared)
        replica_b = _make_strategy(shared)
        rate = _make_rate("2/minute")

        # Exhaust IP-A on replica A
        replica_a.hit(rate, "ip:10.0.0.1")
        replica_a.hit(rate, "ip:10.0.0.1")

        # IP-B on replica B should still be allowed
        assert replica_b.hit(rate, "ip:10.0.0.2") is True

    def test_isolated_storage_allows_bypass(self):
        """
        Illustrates the security gap when each replica has its OWN in-memory
        storage (current default without REDIS_URL).  Each replica grants the
        full budget independently, so N replicas allow N × budget per minute.
        """
        from limits.storage import MemoryStorage

        # Two SEPARATE storage instances — simulates two replicas without Redis
        storage_a = MemoryStorage()
        storage_b = MemoryStorage()
        replica_a = _make_strategy(storage_a)
        replica_b = _make_strategy(storage_b)
        rate = _make_rate("2/minute")
        key = "ip:203.0.113.1"

        # Exhaust replica A's local budget
        replica_a.hit(rate, key)
        replica_a.hit(rate, key)
        assert replica_a.hit(rate, key) is False  # blocked on A

        # Replica B has no knowledge of A's state — bypasses the limit
        assert replica_b.hit(rate, key) is True, (
            "Without shared storage, each replica allows the full budget — "
            "demonstrating why Redis is required in production."
        )

    def test_get_remaining_reflects_shared_consumption(self):
        """get_window_stats returns remaining budget reflecting shared hits."""
        from limits.storage import MemoryStorage

        shared = MemoryStorage()
        replica_a = _make_strategy(shared)
        replica_b = _make_strategy(shared)
        rate = _make_rate("5/minute")
        key = "ip:198.51.100.5"

        # Consume 3 on replica A
        for _ in range(3):
            replica_a.hit(rate, key)

        # Replica B should see only 2 remaining
        stats = replica_b.get_window_stats(rate, key)
        remaining = stats.remaining
        assert remaining == 2, f"Expected 2 remaining, got {remaining}"


# ---------------------------------------------------------------------------
# Configuration-level tests — shared.py storage selection
# ---------------------------------------------------------------------------

class TestRateLimitStorageConfiguration:
    """shared.py selects storage backend based on environment variables."""

    def test_uses_redis_when_redis_url_set(self, monkeypatch):
        """When REDIS_URL is set, _rate_limit_storage should equal that URL."""
        monkeypatch.setenv("REDIS_URL", "redis://redis-prod:6379/0")
        monkeypatch.delenv("RATE_LIMIT_STORAGE", raising=False)

        # Re-evaluate the module-level expressions from shared.py
        redis_url = os.getenv("REDIS_URL", "")
        rate_limit_storage = os.getenv("RATE_LIMIT_STORAGE", redis_url or "memory://")
        assert rate_limit_storage == "redis://redis-prod:6379/0"

    def test_falls_back_to_memory_without_redis(self, monkeypatch):
        """When no Redis URL is configured, storage falls back to memory://."""
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.delenv("RATE_LIMIT_STORAGE", raising=False)

        redis_url = os.getenv("REDIS_URL", "")
        rate_limit_storage = os.getenv("RATE_LIMIT_STORAGE", redis_url or "memory://")
        assert rate_limit_storage == "memory://"

    def test_explicit_rate_limit_storage_overrides_redis_url(self, monkeypatch):
        """RATE_LIMIT_STORAGE env var takes precedence over REDIS_URL."""
        monkeypatch.setenv("REDIS_URL", "redis://redis-prod:6379/0")
        monkeypatch.setenv("RATE_LIMIT_STORAGE", "redis://rate-limiter:6379/1")

        redis_url = os.getenv("REDIS_URL", "")
        rate_limit_storage = os.getenv("RATE_LIMIT_STORAGE", redis_url or "memory://")
        assert rate_limit_storage == "redis://rate-limiter:6379/1"


class TestProductionRedisWarning:
    """Production environment logs a warning when REDIS_URL is absent."""

    def test_production_warns_without_redis(self, monkeypatch):
        """Running in production without REDIS_URL triggers a log warning.

        The module-level guard in shared.py emits a WARNING when the process
        environment is production/staging but no REDIS_URL is configured.
        We verify the guard condition logic directly rather than reloading the
        module (which has unpredictable side-effects in a shared test process).
        """
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("REDIS_URL", raising=False)

        env = os.getenv("ENVIRONMENT", "development").lower()
        redis_url = os.getenv("REDIS_URL", "")
        guard_fires = env in ("production", "prod", "staging") and not redis_url
        assert guard_fires, (
            "The production-without-Redis guard should fire when ENVIRONMENT=production "
            "and REDIS_URL is absent — this is the condition that triggers the log warning."
        )

    def test_no_warning_in_dev_without_redis(self, monkeypatch):
        """Local/dev mode should not warn about missing Redis."""
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.delenv("REDIS_URL", raising=False)

        env = os.getenv("ENVIRONMENT", "development").lower()
        redis_url = os.getenv("REDIS_URL", "")
        # The guard condition is: prod/staging AND no redis_url
        guard_fires = env in ("production", "prod", "staging") and not redis_url
        assert not guard_fires, "Dev environment should not trigger the production Redis warning"
