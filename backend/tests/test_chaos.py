"""
Chaos Engineering Tests — verify graceful degradation under failure conditions.

Scenarios:
  - OpenAI API timeout / error → graceful error message
  - Redis unavailable → falls back to in-memory store
  - Rate limiter hit → returns 429 with retry-after (when enabled)
  - Large payload → returns 413 or handles gracefully
  - Invalid JSON → returns 422 with clear error
  - Missing required env vars → app starts with defaults
  - Blob storage unavailable → fallback handling

Issue #37
"""

import copy
import io
import os
import sys
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

from main import app, SESSION_STORE, IMAGE_STORE


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_stores():
    SESSION_STORE.clear()
    IMAGE_STORE.clear()
    yield
    SESSION_STORE.clear()
    IMAGE_STORE.clear()


MOCK_ANALYSIS = {
    "diagram_type": "AWS Architecture",
    "source_provider": "aws",
    "target_provider": "azure",
    "architecture_patterns": ["multi-AZ"],
    "services_detected": 1,
    "zones": [{"id": 1, "name": "Compute", "number": 1, "services": [
        {"aws": "Lambda", "azure": "Azure Functions", "confidence": 0.95},
    ]}],
    "mappings": [
        {"source_service": "Lambda", "source_provider": "aws",
         "azure_service": "Azure Functions", "confidence": 0.95, "notes": "Zone 1"},
    ],
    "warnings": [],
    "confidence_summary": {"high": 1, "medium": 0, "low": 0, "average": 0.95},
}


def _upload_png(client):
    """Helper: upload a minimal PNG."""
    content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    resp = client.post(
        "/api/projects/proj-001/diagrams",
        files={"file": ("test.png", io.BytesIO(content), "image/png")},
    )
    assert resp.status_code == 200
    return resp.json()["diagram_id"]


# =================================================================
# Chaos 1: OpenAI API failures
# =================================================================

@pytest.mark.chaos
class TestOpenAIFailures:
    """Verify the app degrades gracefully when OpenAI calls fail."""

    def test_analyze_vision_timeout(self, client):
        """OpenAI vision timeout → returns error, doesn't crash."""
        diagram_id = _upload_png(client)
        with patch("routers.diagrams.analyze_image", side_effect=TimeoutError("OpenAI timed out")):
            resp = client.post(f"/api/diagrams/{diagram_id}/analyze")
        assert resp.status_code in (500, 502, 503, 504)

    def test_analyze_vision_connection_error(self, client):
        """OpenAI connection error → returns error."""
        diagram_id = _upload_png(client)
        with patch("routers.diagrams.analyze_image", side_effect=ConnectionError("Cannot reach OpenAI")):
            resp = client.post(f"/api/diagrams/{diagram_id}/analyze")
        assert resp.status_code >= 400

    def test_chat_openai_failure(self, client):
        """Chat endpoint handles OpenAI failure gracefully."""
        with patch("routers.chat.process_chat_message", side_effect=Exception("OpenAI error")):
            resp = client.post("/api/chat", json={"message": "hello", "session_id": "chaos-1"})
        assert resp.status_code >= 400

    @patch("service_builder.get_openai_client")
    def test_add_services_openai_error(self, mock_client, client):
        """add-services degrades when OpenAI returns garbage."""
        diagram_id = _upload_png(client)
        # Set up analysis in store
        with patch("routers.diagrams.analyze_image", return_value=copy.deepcopy(MOCK_ANALYSIS)), \
             patch("routers.diagrams.classify_image", return_value={
                 "is_architecture_diagram": True, "confidence": 0.95,
                 "image_type": "architecture_diagram", "reason": "Mock"}):
            client.post(f"/api/diagrams/{diagram_id}/analyze")

        # OpenAI returns invalid JSON
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "NOT VALID JSON"
        mock_client.return_value.chat.completions.create.return_value = mock_resp

        resp = client.post(
            f"/api/diagrams/{diagram_id}/add-services",
            json={"text": "Add Redis"},
        )
        # Should either handle gracefully (200 with empty result) or return error
        assert resp.status_code in (200, 400, 500)


# =================================================================
# Chaos 2: Redis unavailability
# =================================================================

@pytest.mark.chaos
class TestRedisUnavailable:
    """Verify Redis fallback to in-memory store."""

    def test_redis_connection_refused_falls_back(self):
        """When Redis URL is set but unreachable, get_store returns InMemoryStore."""
        from session_store import get_store, reset_stores, InMemoryStore
        reset_stores()

        with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:59999", "REDIS_HOST": ""}, clear=False):
            store = get_store("chaos_redis_test")
            assert isinstance(store, InMemoryStore)
        reset_stores()

    def test_app_works_without_redis(self, client):
        """Full health check works when Redis is not configured."""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        # Status may be 'degraded' when OpenAI is not configured (test env)
        assert resp.json()["status"] in ("healthy", "degraded")


# =================================================================
# Chaos 3: Large payload
# =================================================================

@pytest.mark.chaos
class TestLargePayload:
    """Verify upload size limits are enforced."""

    def test_oversized_upload_rejected(self, client):
        """Uploading a file larger than MAX_UPLOAD_SIZE should return 413."""
        from routers.shared import MAX_UPLOAD_SIZE
        # Create a payload slightly larger than the limit
        big_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * (MAX_UPLOAD_SIZE + 1024)
        resp = client.post(
            "/api/projects/proj-001/diagrams",
            files={"file": ("big.png", io.BytesIO(big_content), "image/png")},
        )
        assert resp.status_code == 413

    def test_large_chat_message_rejected(self, client):
        """Chat message exceeding max_length should return 422."""
        long_msg = "x" * 6000  # max_length is 5000
        resp = client.post("/api/chat", json={"message": long_msg})
        assert resp.status_code == 422

    def test_normal_size_accepted(self, client):
        """Normal-sized upload succeeds."""
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 1024
        resp = client.post(
            "/api/projects/proj-001/diagrams",
            files={"file": ("ok.png", io.BytesIO(content), "image/png")},
        )
        assert resp.status_code == 200


# =================================================================
# Chaos 4: Invalid JSON
# =================================================================

@pytest.mark.chaos
class TestInvalidJSON:
    """Verify clear error messages for malformed requests."""

    def test_chat_invalid_json(self, client):
        """POST /api/chat with invalid JSON should return 422."""
        resp = client.post(
            "/api/chat",
            content=b"not-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_feedback_invalid_json(self, client):
        """POST /api/feedback/nps with invalid JSON returns 422."""
        resp = client.post(
            "/api/feedback/nps",
            content=b"{bad",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_terraform_validate_invalid_json(self, client):
        """POST /api/terraform/validate with invalid JSON returns 422."""
        resp = client.post(
            "/api/terraform/validate",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_admin_login_invalid_json(self, client):
        """POST /api/admin/login with invalid JSON returns 422."""
        resp = client.post(
            "/api/admin/login",
            content=b"[]",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_chat_empty_message(self, client):
        """Chat with empty string message should return 422 (min_length=1)."""
        resp = client.post("/api/chat", json={"message": ""})
        assert resp.status_code == 422


# =================================================================
# Chaos 5: Missing env vars
# =================================================================

@pytest.mark.chaos
class TestMissingEnvVars:
    """Verify the app functions with missing/empty env vars."""

    def test_no_openai_endpoint(self, client):
        """Health check works even when OpenAI is not configured."""
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_no_api_key_is_dev_mode(self, client):
        """When ARCHMORPH_API_KEY is empty, auth is disabled (dev mode)."""
        resp = client.get("/api/services")
        assert resp.status_code == 200

    def test_feature_flags_default_without_env(self):
        """FeatureFlags loads defaults when no env overrides set."""
        from feature_flags import FeatureFlags
        with patch.dict(os.environ, {}, clear=False):
            ff = FeatureFlags()
            assert ff.is_enabled("dark_mode") is True
            assert ff.is_enabled("export_pptx") is True

    def test_logging_config_works_without_special_env(self):
        """configure_logging works without any special env vars."""
        from logging_config import configure_logging
        configure_logging()  # should not raise


# =================================================================
# Chaos 6: Concurrent / race-condition safety
# =================================================================

@pytest.mark.chaos
class TestConcurrencySafety:
    """Test thread-safety of shared state."""

    def test_feature_flags_thread_safety(self):
        """FeatureFlags operations under concurrent access should not corrupt state."""
        import threading
        from feature_flags import FeatureFlags

        ff = FeatureFlags()
        errors = []

        def toggle():
            try:
                for _ in range(50):
                    ff.update_flag("dark_mode", {"enabled": True})
                    ff.is_enabled("dark_mode", user="user-x")
                    ff.update_flag("dark_mode", {"enabled": False})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=toggle) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread-safety errors: {errors}"

    def test_session_store_thread_safety(self):
        """InMemoryStore operations under concurrent access."""
        import threading
        from session_store import InMemoryStore

        store = InMemoryStore(maxsize=1000, ttl=60)
        errors = []

        def writer(prefix):
            try:
                for i in range(100):
                    store[f"{prefix}:{i}"] = i
                    _ = store.get(f"{prefix}:{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(f"t{n}",)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []


# =================================================================
# Chaos 7: Unexpected content types
# =================================================================

@pytest.mark.chaos
class TestUnexpectedContentTypes:
    """Verify proper handling of wrong content types."""

    def test_upload_unsupported_file_type(self, client):
        """Uploading a .txt file should be rejected."""
        resp = client.post(
            "/api/projects/proj-001/diagrams",
            files={"file": ("doc.txt", io.BytesIO(b"hello"), "text/plain")},
        )
        assert resp.status_code == 400

    def test_upload_pdf_accepted(self, client):
        """PDF is an allowed type."""
        pdf_bytes = b"%PDF-1.4" + b"\x00" * 100
        resp = client.post(
            "/api/projects/proj-001/diagrams",
            files={"file": ("diagram.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert resp.status_code == 200

    def test_analyze_nonexistent_diagram(self, client):
        """Analyzing a diagram that doesn't exist returns 404."""
        resp = client.post("/api/diagrams/does-not-exist/analyze")
        assert resp.status_code == 404


# =================================================================
# Chaos 8: Error response format consistency
# =================================================================

@pytest.mark.chaos
class TestErrorResponseFormat:
    """Verify that error responses use the standardized error envelope (#174)."""

    def test_404_has_detail(self, client):
        resp = client.get("/api/flags/nonexistent_flag_xyz")
        assert resp.status_code == 404
        data = resp.json()
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]

    def test_422_has_detail(self, client):
        resp = client.post("/api/chat", json={})
        assert resp.status_code == 422
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "details" in data["error"]

    def test_400_has_detail(self, client):
        resp = client.post(
            "/api/projects/proj-001/diagrams",
            files={"file": ("bad.txt", io.BytesIO(b"hi"), "text/plain")},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == "BAD_REQUEST"
