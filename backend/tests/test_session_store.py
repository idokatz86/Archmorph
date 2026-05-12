"""Tests for session_store module — pluggable session storage (Issue #69)."""

import os
import sys
import time
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from session_store import InMemoryStore, SessionStore, get_store, reset_stores, session_store_readiness


@pytest.fixture(autouse=True)
def clean_stores():
    reset_stores()
    yield
    reset_stores()


class TestInMemoryStore:
    def test_set_and_get(self):
        store = InMemoryStore(maxsize=10, ttl=300)
        store.set("k1", {"data": 42})
        assert store.get("k1") == {"data": 42}

    def test_get_default(self):
        store = InMemoryStore()
        assert store.get("missing") is None
        assert store.get("missing", "fallback") == "fallback"

    def test_dict_access(self):
        store = InMemoryStore()
        store["a"] = 1
        assert store["a"] == 1
        assert "a" in store
        del store["a"]
        assert "a" not in store

    def test_keys(self):
        store = InMemoryStore()
        store["x"] = 1
        store["y"] = 2
        assert sorted(store.keys()) == ["x", "y"]

    def test_keys_pattern(self):
        store = InMemoryStore()
        store["session:1"] = "a"
        store["session:2"] = "b"
        store["image:1"] = "c"
        assert sorted(store.keys("session:*")) == ["session:1", "session:2"]

    def test_len(self):
        store = InMemoryStore(maxsize=10, ttl=300)
        assert len(store) == 0
        store["k"] = "v"
        assert len(store) == 1

    def test_maxsize(self):
        store = InMemoryStore(maxsize=42, ttl=300)
        assert store.maxsize == 42

    def test_delete_missing_key(self):
        store = InMemoryStore()
        store.delete("nonexistent")  # Should not raise

    def test_keyerror_on_missing(self):
        store = InMemoryStore()
        with pytest.raises(KeyError):
            _ = store["nope"]

    def test_overwrite(self):
        store = InMemoryStore()
        store["k"] = 1
        store["k"] = 2
        assert store["k"] == 2

    def test_overwrite_updates_tracked_bytes(self):
        store = InMemoryStore()
        store["img"] = (b"a" * 400, "image/png")
        store["img"] = (b"b" * 100, "image/png")
        assert store._total_bytes == 100

    def test_expired_entries_are_reconciled_from_tracked_bytes(self):
        store = InMemoryStore(maxsize=10, ttl=1)
        store["img"] = (b"x" * 200, "image/png")
        assert store._total_bytes == 200
        time.sleep(1.1)
        assert store.get("img") is None
        assert store._total_bytes == 0

    def test_large_upload_residency_evicts_oldest_when_budget_exceeded(self):
        store = InMemoryStore(maxsize=10, ttl=300)
        store.MAX_MEMORY_BYTES = 3_000_000

        store["upload-1"] = ("A" * 2_000_000, "image/png")
        store["upload-2"] = ("B" * 2_000_000, "image/png")

        assert "upload-2" in store
        assert store._total_bytes <= store.MAX_MEMORY_BYTES


class TestGetStore:
    def test_returns_inmemory_by_default(self):
        store = get_store("test_default")
        assert isinstance(store, InMemoryStore)

    def test_singleton_per_name(self):
        s1 = get_store("singleton_test", maxsize=10, ttl=60)
        s2 = get_store("singleton_test", maxsize=999, ttl=999)
        assert s1 is s2  # second call returns same instance

    def test_different_names_different_stores(self):
        s1 = get_store("store_a")
        s2 = get_store("store_b")
        assert s1 is not s2

    @patch.dict(os.environ, {"REDIS_URL": "redis://localhost:9999", "REDIS_HOST": ""})
    def test_redis_fallback_to_inmemory(self):
        """When Redis is unreachable, should fall back to InMemoryStore."""
        reset_stores()
        import session_store
        store = session_store.get_store("redis_fail_test")
        assert isinstance(store, InMemoryStore)

    def test_session_store_readiness_shape(self):
        readiness = session_store_readiness()
        assert readiness["backend"] in {"memory", "file", "redis"}
        assert "ready_for_horizontal_scale" in readiness
        assert "scale_blocked" in readiness

    @patch.dict(os.environ, {
        "ENVIRONMENT": "production",
        "WEB_CONCURRENCY": "1",
        "UVICORN_WORKERS": "1",
        "CONTAINER_APP_REPLICA_COUNT": "1",
        "CONTAINER_APP_MIN_REPLICAS": "1",
        "REDIS_URL": "",
        "REDIS_HOST": "",
        "REQUIRE_REDIS": "",
    })
    def test_optional_redis_single_replica_does_not_block_scale(self):
        readiness = session_store_readiness()
        assert readiness["backend"] == "file"
        assert readiness["requires_redis_for_scale"] is False
        assert readiness["scale_blocked"] is False

    @patch.dict(os.environ, {
        "ENVIRONMENT": "production",
        "WEB_CONCURRENCY": "2",
        "REDIS_URL": "",
        "REDIS_HOST": "",
        "REQUIRE_REDIS": "",
    })
    def test_multi_worker_without_redis_blocks_horizontal_scale(self):
        readiness = session_store_readiness()
        assert readiness["multi_worker"] is True
        assert readiness["requires_redis_for_scale"] is True
        assert readiness["scale_blocked"] is True
        assert readiness["scale_blocked_reason"]

    @patch.dict(os.environ, {
        "ENVIRONMENT": "production",
        "WEB_CONCURRENCY": "1",
        "CONTAINER_APP_MIN_REPLICAS": "2",
        "REDIS_URL": "",
        "REDIS_HOST": "",
        "REQUIRE_REDIS": "",
    })
    def test_declared_multi_replica_without_redis_blocks_horizontal_scale(self):
        readiness = session_store_readiness()
        assert readiness["declared_replica_count"] == 2
        assert readiness["multi_replica"] is True
        assert readiness["requires_redis_for_scale"] is True
        assert readiness["scale_blocked"] is True


class TestSessionStoreInterface:
    """Verify the abstract interface raises NotImplementedError."""

    def test_get_raises(self):
        with pytest.raises(NotImplementedError):
            SessionStore().get("k")

    def test_set_raises(self):
        with pytest.raises(NotImplementedError):
            SessionStore().set("k", "v")

    def test_delete_raises(self):
        with pytest.raises(NotImplementedError):
            SessionStore().delete("k")

    def test_keys_raises(self):
        with pytest.raises(NotImplementedError):
            SessionStore().keys()


def test_redisstore_warning_logs_are_sanitized(monkeypatch, caplog):
    import session_store

    class _FakeRedis:
        def ping(self):
            return True

        def get(self, *_args, **_kwargs):
            return None

        def setex(self, *_args, **_kwargs):
            return None

        def delete(self, *_args, **_kwargs):
            return 1

    class _FailingBreaker:
        def call(self, *_args, **_kwargs):
            raise RuntimeError("breaker\nfailure\rpayload")

    monkeypatch.setattr(session_store, "_create_redis_client", lambda: _FakeRedis())
    monkeypatch.setattr("circuit_breakers.redis_breaker", _FailingBreaker())

    store = session_store.RedisStore(prefix="test")

    with caplog.at_level("WARNING", logger="session_store"):
        assert store.get("bad\nkey", default="fallback") == "fallback"
        store.set("bad\rkey", {"v": 1})
        store.delete("bad\r\nkey")

    warning_records = [
        r for r in caplog.records if r.levelname == "WARNING" and r.name == "session_store"
    ]
    assert len(warning_records) == 3
    for record in warning_records:
        message = record.getMessage()
        assert "\n" not in message
        assert "\r" not in message
        assert "error_type=RuntimeError" in message
        assert "badkey" not in message
        assert "breaker" not in message
        assert "payload" not in message
