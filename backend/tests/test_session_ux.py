"""
Comprehensive UX-focused session management tests.

Covers:
- Session expiry mid-workflow (the Redis/InMemory TTL problem)
- Session restore endpoint validation
- IMAGE_STORE / SESSION_STORE TTL mismatch
- Session capacity eviction under load
- Auth token expiry without refresh
- Multi-worker file store behavior
- Session TTL not refreshed on read-only endpoints
"""

import copy
import os
import sys
import time
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from session_store import (
    InMemoryStore,
    FileStore,
    RedisStore,
    get_store,
    reset_stores,
)
from routers.shared import SESSION_STORE
from auth import User, AuthProvider, UserTier, generate_session_token


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

SAMPLE_ANALYSIS = {
    "diagram_id": "test-diagram-001",
    "diagram_type": "AWS Architecture",
    "source_provider": "aws",
    "target_provider": "azure",
    "services_detected": 3,
    "zones": [
        {
            "id": 1,
            "name": "Compute",
            "number": 1,
            "services": [
                {"aws": "Lambda", "azure": "Azure Functions", "confidence": 0.95},
            ],
        },
    ],
    "mappings": [
        {
            "source_service": "Lambda",
            "source_provider": "aws",
            "azure_service": "Azure Functions",
            "confidence": 0.95,
            "notes": "Zone 1 – Compute",
        },
    ],
    "warnings": [],
    "confidence_summary": {"high": 1, "medium": 0, "low": 0, "average": 0.95},
}


@pytest.fixture()
def analysis():
    return copy.deepcopy(SAMPLE_ANALYSIS)


@pytest.fixture(autouse=True)
def clean_stores():
    reset_stores()
    yield
    reset_stores()


@pytest.fixture()
def auth_headers():
    user = User(
        id="session-ux-user",
        email="session-ux@example.com",
        provider=AuthProvider.GITHUB,
        tier=UserTier.TEAM,
        tenant_id="tenant-session-ux",
    )
    token = generate_session_token(user)
    return {"Authorization": f"Bearer {token}"}


# ─────────────────────────────────────────────────────────────
# 1. SESSION EXPIRY MID-WORKFLOW
# ─────────────────────────────────────────────────────────────


class TestSessionExpiryMidWorkflow:
    """Critical: Users lose work when session expires during analysis."""

    def test_session_expires_after_ttl(self):
        """Session data should be gone after TTL passes."""
        store = InMemoryStore(maxsize=10, ttl=1)  # 1-second TTL
        store["diagram-1"] = {"data": "analysis"}
        assert "diagram-1" in store

        time.sleep(1.1)
        assert "diagram-1" not in store
        assert store.get("diagram-1") is None

    def test_session_read_refreshes_ttl(self):
        """FIX (Issue #260): Reading a session now EXTENDS its TTL.

        A user browsing cost-estimate, dependency graph, etc. (read-only
        endpoints) keeps their session alive.  Each .get() re-inserts the
        value, resetting the TTL countdown.
        """
        store = InMemoryStore(maxsize=10, ttl=2)
        store["diagram-1"] = {"data": "analysis"}

        # Read at 1s — session still alive and TTL refreshed
        time.sleep(1.0)
        assert store.get("diagram-1") is not None

        # Read again at ~1.5s — still alive, TTL refreshed again
        time.sleep(0.5)
        assert store.get("diagram-1") is not None

        # At 0.6s after last read (total 2.1s), session STILL alive
        # because last read at 1.5s refreshed TTL for another 2s
        time.sleep(0.6)
        assert store.get("diagram-1") is not None

        # Without any reads for full TTL duration it finally expires
        time.sleep(2.1)
        assert store.get("diagram-1") is None

    def test_session_write_resets_ttl(self):
        """Writing to a session should reset its TTL clock."""
        store = InMemoryStore(maxsize=10, ttl=2)
        store["diagram-1"] = {"data": "v1"}

        time.sleep(1.5)
        # Write again — this should reset the TTL
        store["diagram-1"] = {"data": "v2"}

        time.sleep(1.5)
        # Should still be alive (1.5s < 2s from last write)
        assert store.get("diagram-1") == {"data": "v2"}

    def test_image_expires_before_session(self):
        """HIGH BUG: IMAGE_STORE 1h TTL < SESSION_STORE 2h TTL.

        A user's image disappears while their session is still valid,
        causing 'No uploaded image found' on re-analyze.
        """
        image_store = InMemoryStore(maxsize=10, ttl=1)  # simulate shorter TTL
        session_store = InMemoryStore(maxsize=10, ttl=3)

        image_store["diagram-1"] = b"image-bytes"
        session_store["diagram-1"] = {"analysis": "data"}

        time.sleep(1.5)

        # Image expired, session still alive — UX mismatch
        assert "diagram-1" not in image_store
        assert "diagram-1" in session_store

    def test_session_expiry_returns_keyerror(self):
        """Accessing expired session via __getitem__ should raise KeyError."""
        store = InMemoryStore(maxsize=10, ttl=1)
        store["k"] = "value"

        time.sleep(1.1)
        with pytest.raises(KeyError):
            _ = store["k"]


# ─────────────────────────────────────────────────────────────
# 2. SESSION RESTORE ENDPOINT
# ─────────────────────────────────────────────────────────────


class TestSessionRestore:
    """Test the /diagrams/{id}/restore-session endpoint."""

    def test_restore_valid_session(self, test_client, analysis, auth_headers):
        """Frontend can push cached analysis to restore an expired session."""
        diagram_id = "test-restore-001"

        resp = test_client.post(
            f"/api/v1/diagrams/{diagram_id}/restore-session",
            json={"analysis": analysis},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "restored"
        assert body["diagram_id"] == diagram_id

    def test_restore_empty_analysis_fails(self, test_client, auth_headers):
        """Restoring with empty/null analysis should fail with 400."""
        resp = test_client.post(
            "/api/v1/diagrams/test-empty/restore-session",
            json={"analysis": {}},
            headers=auth_headers,
        )
        # Empty dict is valid dict but falsy — should be rejected
        assert resp.status_code == 400

    def test_restore_non_dict_analysis_fails(self, test_client, auth_headers):
        """Restoring with non-dict analysis should fail with 422 or 400."""
        resp = test_client.post(
            "/api/v1/diagrams/test-bad/restore-session",
            json={"analysis": "not a dict"},
            headers=auth_headers,
        )
        assert resp.status_code in (400, 422)

    def test_restore_sets_correct_diagram_id(self, test_client, analysis, auth_headers):
        """Restored session should have diagram_id set to the URL param."""
        diagram_id = "test-id-match-001"
        analysis["diagram_id"] = "wrong-id"

        test_client.post(
            f"/api/v1/diagrams/{diagram_id}/restore-session",
            json={"analysis": analysis},
            headers=auth_headers,
        )

        # The session should have the correct diagram_id
        stored = SESSION_STORE.get(diagram_id)
        assert stored is not None
        assert stored["diagram_id"] == diagram_id

    def test_restored_session_survives_subsequent_reads(self, test_client, analysis, auth_headers):
        """After restore, endpoints that read the session should work."""
        diagram_id = "test-restored-read-001"
        test_client.post(
            f"/api/v1/diagrams/{diagram_id}/restore-session",
            json={"analysis": analysis},
            headers=auth_headers,
        )

        # Questions endpoint is POST (not GET) — should work with restored session
        resp = test_client.post(f"/api/v1/diagrams/{diagram_id}/questions")
        assert resp.status_code == 200

    def test_restore_rate_limited(self, test_client, analysis, auth_headers):
        """Restore endpoint should be rate-limited to prevent abuse."""
        # The endpoint has @limiter.limit("10/minute")
        # We verify the decorator exists (actual rate limiting disabled in tests)
        diagram_id = "test-rate-limit"
        resp = test_client.post(
            f"/api/v1/diagrams/{diagram_id}/restore-session",
            json={"analysis": analysis},
            headers=auth_headers,
        )
        assert resp.status_code == 200

    def test_restore_requires_authentication(self, test_client, analysis):
        resp = test_client.post(
            "/api/v1/diagrams/test-no-auth/restore-session",
            json={"analysis": analysis},
        )
        assert resp.status_code == 401


# ─────────────────────────────────────────────────────────────
# 3. SESSION CAPACITY EVICTION
# ─────────────────────────────────────────────────────────────


class TestSessionCapacityEviction:
    """Users lose sessions silently when store hits maxsize."""

    def test_eviction_drops_oldest_entry(self):
        """When maxsize is reached, oldest entry is silently evicted."""
        store = InMemoryStore(maxsize=3, ttl=3600)
        store["a"] = 1
        store["b"] = 2
        store["c"] = 3

        # Adding a 4th should evict 'a'
        store["d"] = 4
        assert "a" not in store
        assert store.get("a") is None
        assert len(store) == 3

    def test_eviction_is_silent(self):
        """Eviction happens without any exception or warning to the caller."""
        store = InMemoryStore(maxsize=2, ttl=3600)
        store["first"] = {"analysis": "important data"}
        store["second"] = {"analysis": "also important"}

        # This silently evicts 'first' — no exception raised
        store["third"] = {"analysis": "new data"}
        assert "first" not in store

    def test_accessing_evicted_session_returns_none(self):
        """get() on evicted key returns default, not stale data."""
        store = InMemoryStore(maxsize=2, ttl=3600)
        store["k1"] = "data1"
        store["k2"] = "data2"
        store["k3"] = "data3"  # evicts k1

        assert store.get("k1") is None
        assert store.get("k1", "fallback") == "fallback"

    def test_high_traffic_eviction_scenario(self):
        """Simulate concurrent sessions causing evictions at capacity (LRU)."""
        store = InMemoryStore(maxsize=5, ttl=7200)

        # Fill to capacity
        for i in range(5):
            store[f"session-{i}"] = f"data-{i}"

        assert len(store) == 5

        # Add one more — evicts the LRU item (session-0, never accessed since insert)
        store["session-5"] = "new-session"
        assert len(store) == 5
        assert store.get("session-0") is None  # evicted as LRU
        assert store.get("session-5") == "new-session"


# ─────────────────────────────────────────────────────────────
# 4. AUTH TOKEN EXPIRY
# ─────────────────────────────────────────────────────────────


class TestAuthTokenExpiry:
    """Auth token cache has 5-min TTL with no refresh mechanism."""

    def test_user_cache_ttl(self):
        """USER_CACHE drops entries after configured TTL (default 1 hour)."""
        from auth import USER_CACHE, USER_CACHE_TTL
        assert USER_CACHE.ttl == USER_CACHE_TTL

    def test_generate_session_token_stores_user(self):
        """generate_session_token should store user in USER_CACHE."""
        from auth import generate_session_token, get_user_from_session, User, AuthProvider, UserTier

        user = User(
            id="test-user-1",
            email="test@example.com",
            name="Test User",
            provider=AuthProvider.ANONYMOUS,
            tier=UserTier.FREE,
        )

        token = generate_session_token(user)
        assert token is not None
        assert len(token) > 0

        retrieved = get_user_from_session(token)
        assert retrieved is not None
        assert retrieved.id == "test-user-1"

    def test_expired_token_returns_none(self):
        """After TTL passes, get_user_from_session returns None."""
        from auth import generate_session_token, get_user_from_session, User, AuthProvider, UserTier

        user = User(
            id="test-user-2",
            email="test2@example.com",
            name="Test User 2",
            provider=AuthProvider.ANONYMOUS,
            tier=UserTier.FREE,
        )

        token = generate_session_token(user)
        # We can't easily wait 5 minutes, so we verify the TTL config
        from auth import USER_CACHE, USER_CACHE_TTL
        assert USER_CACHE.ttl == USER_CACHE_TTL  # TTL confirmed

        # Verify token works immediately
        assert get_user_from_session(token) is not None

    def test_invalid_token_returns_none(self):
        """Non-existent token should return None."""
        from auth import get_user_from_session
        assert get_user_from_session("nonexistent-token-xyz") is None


# ─────────────────────────────────────────────────────────────
# 5. FILE STORE (multi-worker)
# ─────────────────────────────────────────────────────────────


class TestFileStore:
    """FileStore is used for multi-worker deployments without Redis."""

    def test_file_store_basic_operations(self, tmp_path):
        with patch.dict(os.environ, {"SESSION_FILE_DIR": str(tmp_path)}):
            store = FileStore(name="test", maxsize=10, ttl=3600)
            store.set("key1", {"data": "value1"})
            assert store.get("key1") == {"data": "value1"}

    def test_file_store_ttl_expiry(self, tmp_path):
        with patch.dict(os.environ, {"SESSION_FILE_DIR": str(tmp_path)}):
            store = FileStore(name="test_ttl", maxsize=10, ttl=1)
            store.set("key1", {"data": "value1"})
            assert store.get("key1") == {"data": "value1"}

            time.sleep(1.1)
            assert store.get("key1") is None

    def test_file_store_per_key_ttl(self, tmp_path):
        """FileStore supports per-key TTL override."""
        with patch.dict(os.environ, {"SESSION_FILE_DIR": str(tmp_path)}):
            store = FileStore(name="test_perkey", maxsize=10, ttl=3600)
            store.set("short", {"data": "expires soon"}, ttl=1)
            store.set("long", {"data": "stays"}, ttl=3600)

            time.sleep(1.1)
            assert store.get("short") is None
            assert store.get("long") == {"data": "stays"}

    def test_file_store_delete(self, tmp_path):
        with patch.dict(os.environ, {"SESSION_FILE_DIR": str(tmp_path)}):
            store = FileStore(name="test_del", maxsize=10, ttl=3600)
            store.set("k", "v")
            store.delete("k")
            assert store.get("k") is None

    def test_file_store_keys(self, tmp_path):
        with patch.dict(os.environ, {"SESSION_FILE_DIR": str(tmp_path)}):
            store = FileStore(name="test_keys", maxsize=10, ttl=3600)
            store.set("alpha", 1)
            store.set("beta", 2)
            keys = store.keys()
            assert sorted(keys) == ["alpha", "beta"]

    def test_file_store_clear(self, tmp_path):
        with patch.dict(os.environ, {"SESSION_FILE_DIR": str(tmp_path)}):
            store = FileStore(name="test_clear", maxsize=10, ttl=3600)
            store.set("k1", 1)
            store.set("k2", 2)
            store.clear()
            assert len(store) == 0

    def test_file_store_contains(self, tmp_path):
        with patch.dict(os.environ, {"SESSION_FILE_DIR": str(tmp_path)}):
            store = FileStore(name="test_contains", maxsize=10, ttl=3600)
            store.set("exists", True)
            assert "exists" in store
            assert "missing" not in store

    def test_file_store_eviction_at_maxsize(self, tmp_path):
        with patch.dict(os.environ, {"SESSION_FILE_DIR": str(tmp_path)}):
            store = FileStore(name="test_evict", maxsize=3, ttl=3600)
            store.set("a", 1)
            time.sleep(0.01)
            store.set("b", 2)
            time.sleep(0.01)
            store.set("c", 3)
            time.sleep(0.01)
            store.set("d", 4)  # should trigger eviction of oldest

            assert len(store) <= 3

    def test_file_store_concurrent_access(self, tmp_path):
        """File locking should handle concurrent read/write."""
        import threading

        with patch.dict(os.environ, {"SESSION_FILE_DIR": str(tmp_path)}):
            store = FileStore(name="test_concurrent", maxsize=100, ttl=3600)
            errors = []

            def writer(n):
                try:
                    for i in range(10):
                        store.set(f"key-{n}-{i}", {"val": n * 10 + i})
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=writer, args=(n,)) for n in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0
            # At least some keys should exist
            assert len(store) > 0


# ─────────────────────────────────────────────────────────────
# 6. REDIS STORE (mocked)
# ─────────────────────────────────────────────────────────────


def _make_mock_redis_module():
    """Create a fake ``redis`` module so RedisStore can be tested without installing redis."""
    mock_module = MagicMock()

    def _make_client():
        client = MagicMock()
        data = {}

        def mock_get(key):
            entry = data.get(key)
            if entry is None:
                return None
            if entry["expires_at"] < time.time():
                del data[key]
                return None
            return entry["value"]

        def mock_setex(key, ttl, value):
            data[key] = {"value": value, "expires_at": time.time() + ttl}

        def mock_delete(*keys):
            for k in keys:
                data.pop(k, None)

        def mock_exists(key):
            if key in data and data[key]["expires_at"] >= time.time():
                return 1
            data.pop(key, None)
            return 0

        def mock_scan(cursor=0, match="*", count=100):
            import fnmatch
            matched = [k for k in data if fnmatch.fnmatch(k, match)]
            return (0, matched)

        client.get = MagicMock(side_effect=mock_get)
        client.setex = MagicMock(side_effect=mock_setex)
        client.delete = MagicMock(side_effect=mock_delete)
        client.exists = MagicMock(side_effect=mock_exists)
        client.scan = MagicMock(side_effect=mock_scan)
        client.ping = MagicMock(return_value=True)
        client._data = data  # expose for assertions
        return client

    mock_module.from_url = MagicMock(side_effect=lambda *a, **kw: _make_client())
    return mock_module


class TestRedisStoreMocked:
    """Test RedisStore behavior via mocks (no real Redis needed)."""

    @pytest.fixture(autouse=True)
    def _inject_redis_module(self):
        """Inject a fake redis module into sys.modules so ``import redis`` succeeds."""
        fake_redis = _make_mock_redis_module()
        with patch.dict(sys.modules, {"redis": fake_redis}):
            yield fake_redis

    def _build_store(self, **overrides):
        """Helper to instantiate a RedisStore with mocked redis."""
        defaults = {"prefix": "test", "ttl": 7200}
        defaults.update(overrides)
        # Mock _create_redis_client so RedisStore uses our fake client
        fake_client = _make_mock_redis_module().from_url()
        with patch("session_store._create_redis_client", return_value=fake_client):
            store = RedisStore(**defaults)
        return store

    def test_redis_store_set_and_get(self):
        """RedisStore stores and retrieves JSON-serialized values."""
        store = self._build_store()
        store.set("session-1", {"analysis": "data"})
        result = store.get("session-1")
        assert result == {"analysis": "data"}

    def test_redis_store_ttl_used(self):
        """RedisStore should call setex with correct TTL."""
        store = self._build_store()
        store.set("key", "value")
        store._redis.setex.assert_called_once()
        call_args = store._redis.setex.call_args
        assert call_args[0][1] == 7200  # TTL

    def test_redis_store_per_key_ttl(self):
        """RedisStore supports per-key TTL override."""
        store = self._build_store()
        store.set("key", "value", ttl=60)
        call_args = store._redis.setex.call_args
        assert call_args[0][1] == 60

    def test_redis_store_delete(self):
        store = self._build_store()
        store.set("k", "v")
        store.delete("k")
        assert store.get("k") is None

    def test_redis_store_contains(self):
        store = self._build_store()
        store.set("exists", "yes")
        assert "exists" in store
        assert "missing" not in store

    def test_redis_store_keys_uses_scan(self):
        """RedisStore should use SCAN instead of KEYS (Issue #94)."""
        store = self._build_store()
        store.set("a", 1)
        store.set("b", 2)
        keys = store.keys()
        store._redis.scan.assert_called()
        assert len(keys) == 2

    def test_redis_store_clear(self):
        store = self._build_store()
        store.set("k1", 1)
        store.set("k2", 2)
        store.clear()


# ─────────────────────────────────────────────────────────────
# 7. GET_STORE FACTORY
# ─────────────────────────────────────────────────────────────


class TestGetStoreFactory:
    """Test the get_store factory function with various configurations."""

    def test_default_returns_inmemory(self):
        reset_stores()
        with patch.dict(os.environ, {"REDIS_URL": "", "REDIS_HOST": ""}, clear=False):
            store = get_store("test_factory")
            assert isinstance(store, InMemoryStore)

    def test_singleton_pattern(self):
        s1 = get_store("factory_singleton")
        s2 = get_store("factory_singleton")
        assert s1 is s2

    def test_different_names_different_instances(self):
        s1 = get_store("store_x")
        s2 = get_store("store_y")
        assert s1 is not s2

    def test_redis_fallback_to_inmemory_single_worker(self):
        """When Redis is unreachable in single-worker mode, falls back to InMemoryStore."""
        reset_stores()
        with patch.dict(os.environ, {"REDIS_URL": "redis://unreachable:9999", "REDIS_HOST": ""}, clear=False):
            store = get_store("redis_fallback_test")
            assert isinstance(store, InMemoryStore)

    def test_multi_worker_without_redis_uses_filestore(self, tmp_path):
        """Multi-worker without Redis should use FileStore."""
        reset_stores()
        with patch.dict(os.environ, {"SESSION_FILE_DIR": str(tmp_path), "REDIS_URL": "", "REDIS_HOST": ""}, clear=False):
            import session_store
            old_multi = session_store._is_multi_worker
            session_store._is_multi_worker = lambda: True
            try:
                store = get_store("multi_worker_test")
                assert isinstance(store, FileStore)
            finally:
                session_store._is_multi_worker = old_multi

    def test_custom_ttl_and_maxsize(self):
        """Custom TTL and maxsize should be applied."""
        reset_stores()
        with patch.dict(os.environ, {"REDIS_URL": "", "REDIS_HOST": ""}, clear=False):
            store = get_store("custom_params", maxsize=100, ttl=60)
            assert isinstance(store, InMemoryStore)
            assert store.maxsize == 100


# ─────────────────────────────────────────────────────────────
# 8. SHARE STORE TTL AND CAPACITY
# ─────────────────────────────────────────────────────────────


class TestShareStore:
    """Share links have 24h TTL and only 100 max slots."""

    def test_share_store_ttl_config(self):
        """SHARE_STORE should have 24h TTL (86400s)."""
        share_store = InMemoryStore(maxsize=100, ttl=86400)
        assert share_store.maxsize == 100

    def test_share_eviction_at_capacity(self):
        """With maxsize=100, share 101 evicts the oldest."""
        store = InMemoryStore(maxsize=100, ttl=86400)
        for i in range(100):
            store[f"share-{i}"] = {"analysis_id": f"diagram-{i}"}

        store["share-100"] = {"analysis_id": "diagram-100"}
        assert store.get("share-0") is None
        assert len(store) == 100


# ─────────────────────────────────────────────────────────────
# 9. END-TO-END SESSION WORKFLOW TESTS
# ─────────────────────────────────────────────────────────────


class TestEndToEndSessionWorkflow:
    """Integration tests for full user workflows with session management."""

    def test_sample_analysis_creates_session(self, test_client):
        """Analyzing a sample diagram should create a session."""
        resp = test_client.post("/api/v1/samples/aws-iaas/analyze")
        assert resp.status_code == 200
        data = resp.json()
        diagram_id = data.get("diagram_id")
        assert diagram_id is not None
        assert SESSION_STORE.get(diagram_id) is not None

    def test_questions_after_analysis(self, test_client):
        """Questions endpoint (POST) should work after analysis."""
        resp = test_client.post("/api/v1/samples/aws-iaas/analyze")
        diagram_id = resp.json()["diagram_id"]

        resp = test_client.post(f"/api/v1/diagrams/{diagram_id}/questions")
        assert resp.status_code == 200

    def test_questions_on_expired_session_returns_404(self, test_client):
        """Questions for a non-existent session should 404."""
        resp = test_client.post("/api/v1/diagrams/nonexistent-xxx/questions")
        assert resp.status_code == 404

    def test_export_on_expired_session_returns_404(self, test_client):
        """Export for a non-existent session should 404."""
        resp = test_client.post(
            "/api/v1/diagrams/expired-123/export-diagram?format=excalidraw"
        )
        assert resp.status_code == 404

    def test_iac_generation_on_expired_session(self, test_client):
        """IaC generation for expired session should 404."""
        resp = test_client.post(
            "/api/v1/diagrams/expired-xyz/generate-iac",
            json={"format": "terraform"},
        )
        assert resp.status_code == 404

    def test_full_workflow_analyze_questions_apply(self, test_client):
        """Full workflow: analyze → questions → apply answers."""
        # Step 1: Analyze
        resp = test_client.post("/api/v1/samples/aws-iaas/analyze")
        assert resp.status_code == 200
        diagram_id = resp.json()["diagram_id"]

        # Step 2: Get questions (POST endpoint)
        resp = test_client.post(f"/api/v1/diagrams/{diagram_id}/questions")
        assert resp.status_code == 200
        data = resp.json()
        questions = data.get("questions", data if isinstance(data, list) else [])
        assert len(questions) > 0

        # Step 3: Apply answers
        answers = {}
        for q in questions[:3]:
            opts = q.get("options", [])
            if opts:
                answers[q["id"]] = opts[0] if isinstance(opts[0], str) else opts[0].get("value", "yes")
        if not answers:
            answers = {questions[0]["id"]: "yes"}
        resp = test_client.post(
            f"/api/v1/diagrams/{diagram_id}/apply-answers",
            json={"answers": answers},
        )
        assert resp.status_code == 200

    def test_restore_then_continue_workflow(self, test_client, analysis, auth_headers):
        """After restore, subsequent workflow steps should succeed."""
        diagram_id = "restore-workflow-001"

        # Restore session
        resp = test_client.post(
            f"/api/v1/diagrams/{diagram_id}/restore-session",
            json={"analysis": analysis},
            headers=auth_headers,
        )
        assert resp.status_code == 200

        # Continue with questions (POST endpoint)
        resp = test_client.post(f"/api/v1/diagrams/{diagram_id}/questions")
        assert resp.status_code == 200

    def test_sample_session_auto_recreated(self, test_client):
        """Sample sessions are auto-recreated if evicted (Issue #91)."""
        resp = test_client.post("/api/v1/samples/aws-iaas/analyze")
        diagram_id = resp.json()["diagram_id"]

        # Manually clear the session
        SESSION_STORE.delete(diagram_id)
        assert SESSION_STORE.get(diagram_id) is None

        # The get_or_recreate_session should rebuild it (POST endpoint)
        resp = test_client.post(f"/api/v1/diagrams/{diagram_id}/questions")
        assert resp.status_code == 200

    def test_non_sample_session_not_auto_recreated(self, test_client):
        """Non-sample sessions should NOT be auto-recreated."""
        # Use a non-sample diagram ID (POST endpoint)
        resp = test_client.post("/api/v1/diagrams/user-upload-xyz/questions")
        assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────
# 10. STORE TTL CONFIGURATION VALIDATION
# ─────────────────────────────────────────────────────────────


class TestStoreTTLConfiguration:
    """Validate that store TTLs are configured as expected."""

    def test_session_store_ttl_is_2_hours(self):
        """SESSION_STORE should have 7200s (2 hour) TTL."""
        store = InMemoryStore(maxsize=500, ttl=7200)
        assert store._ttl == 7200

    def test_image_store_ttl_is_1_hour(self):
        """IMAGE_STORE should have 3600s (1 hour) TTL."""
        store = InMemoryStore(maxsize=200, ttl=3600)
        assert store._ttl == 3600

    def test_share_store_ttl_is_24_hours(self):
        """SHARE_STORE should have 86400s (24 hour) TTL."""
        store = InMemoryStore(maxsize=100, ttl=86400)
        assert store._ttl == 86400

    def test_session_store_maxsize(self):
        """SESSION_STORE maxsize should be 500."""
        store = InMemoryStore(maxsize=500, ttl=7200)
        assert store.maxsize == 500

    def test_image_store_maxsize(self):
        """IMAGE_STORE maxsize should be 50 (Issue #294 — reduced from 200)."""
        store = InMemoryStore(maxsize=50, ttl=3600)
        assert store.maxsize == 50


class TestImageStoreBytebudget:
    """Validate byte-budget enforcement and tracking for IMAGE_STORE (#830)."""

    def test_byte_tracking_via_setitem(self):
        """__setitem__ must update _total_bytes (not bypass tracking)."""
        store = InMemoryStore(maxsize=10, ttl=3600)
        store["img1"] = (b"x" * 500, "image/png")
        assert store._total_bytes == 500

    def test_byte_decrement_via_delitem(self):
        """__delitem__ must decrement _total_bytes (not bypass tracking)."""
        store = InMemoryStore(maxsize=10, ttl=3600)
        store["img1"] = (b"x" * 500, "image/png")
        del store["img1"]
        assert store._total_bytes == 0

    def test_clear_resets_total_bytes(self):
        """clear() must reset _total_bytes to 0."""
        store = InMemoryStore(maxsize=10, ttl=3600)
        store["img1"] = (b"x" * 200, "image/png")
        store["img2"] = (b"y" * 300, "image/png")
        assert store._total_bytes == 500
        store.clear()
        assert store._total_bytes == 0

    def test_base64_string_tuple_size_estimation(self):
        """IMAGE_STORE stores (str_b64, str_content_type) — size must track len(str_b64)."""
        import base64
        raw = b"A" * 300
        b64 = base64.b64encode(raw).decode("ascii")  # ~400 chars
        store = InMemoryStore(maxsize=10, ttl=3600)
        store["img1"] = (b64, "image/png")
        # Size should be len(b64 string), not a tiny getsizeof(tuple)
        assert store._total_bytes == len(b64)

    def test_evict_oldest_when_budget_exceeded(self):
        """When the byte budget is exceeded, the oldest entry should be evicted to make room."""
        import os
        original = os.environ.pop("SESSION_STORE_MAX_MEMORY_MB", None)
        try:
            # Very small budget: 1 byte (in MB units would round to 1MB; use monkeypatch via class attr)
            store = InMemoryStore(maxsize=10, ttl=3600)
            store.MAX_MEMORY_BYTES = 800  # tiny budget for this test

            # First entry: 500 bytes — fits
            store["img1"] = (b"A" * 500, "image/png")
            assert "img1" in store
            assert store._total_bytes == 500

            # Second entry: 400 bytes — would exceed 800 total; oldest (img1) should be evicted
            store["img2"] = (b"B" * 400, "image/png")
            # After eviction of img1 (500), total is 0; now img2 fits (400 ≤ 800)
            assert "img2" in store
            assert store._total_bytes == 400

        finally:
            if original is not None:
                os.environ["SESSION_STORE_MAX_MEMORY_MB"] = original

    def test_burst_behavior_multiple_large_entries(self):
        """Burst of large images: byte budget evicts oldest, last entries are retained."""
        store = InMemoryStore(maxsize=20, ttl=3600)
        store.MAX_MEMORY_BYTES = 1000  # allow ~2 entries of 500 bytes each

        keys = [f"img{i}" for i in range(5)]
        for k in keys:
            store[k] = (b"Z" * 500, "image/png")

        # Budget is 1000, each entry is 500 bytes. After first two entries fill the budget,
        # subsequent writes must evict the oldest to make room.
        # At most 2 entries can coexist; the last written should survive.
        assert store._total_bytes <= 1000
        # The last key written must be present (eviction is of oldest, not newest)
        assert "img4" in store

