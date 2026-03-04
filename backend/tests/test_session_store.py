"""Tests for session_store module — pluggable session storage (Issue #69)."""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from session_store import InMemoryStore, SessionStore, get_store, reset_stores


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
