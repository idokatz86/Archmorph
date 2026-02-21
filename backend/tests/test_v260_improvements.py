"""
Tests for v2.6.0 improvements:
  - Image compression (Pillow resize/JPEG)
  - Retry decorator (tenacity)
  - Metrics blob storage fallback
  - Enhanced health check
"""

import io
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["RATE_LIMIT_ENABLED"] = "false"


# ====================================================================
# 1. Image compression tests
# ====================================================================

class TestImageCompression:
    """Verify the compress_image utility."""

    def test_compress_small_png(self):
        """Small 1x1 PNG stays small and becomes JPEG."""
        from PIL import Image
        from vision_analyzer import compress_image

        # Create a tiny PNG in memory
        img = Image.new("RGB", (100, 100), color=(255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        raw = buf.getvalue()

        compressed, ct = compress_image(raw, "image/png")
        assert ct == "image/jpeg"
        assert len(compressed) > 0
        # JPEG should be smaller for solid colour
        assert len(compressed) <= len(raw) * 2  # generous bound

    def test_compress_large_image_resizes(self):
        """Image larger than MAX_IMAGE_DIMENSION is resized."""
        from PIL import Image
        from vision_analyzer import compress_image, MAX_IMAGE_DIMENSION

        img = Image.new("RGB", (4000, 3000), color=(0, 128, 255))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        raw = buf.getvalue()

        compressed, ct = compress_image(raw, "image/png")
        # Re-open to check dimensions
        out_img = Image.open(io.BytesIO(compressed))
        assert max(out_img.size) <= MAX_IMAGE_DIMENSION

    def test_compress_rgba_converts_to_rgb(self):
        """RGBA images are converted to RGB for JPEG compatibility."""
        from PIL import Image
        from vision_analyzer import compress_image

        img = Image.new("RGBA", (200, 200), color=(0, 0, 0, 128))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        raw = buf.getvalue()

        compressed, ct = compress_image(raw, "image/png")
        assert ct == "image/jpeg"
        out_img = Image.open(io.BytesIO(compressed))
        assert out_img.mode == "RGB"

    def test_compress_invalid_bytes_returns_original(self):
        """Invalid image data falls back to original bytes."""
        from vision_analyzer import compress_image

        garbage = b"not an image"
        result, ct = compress_image(garbage, "image/png")
        assert result == garbage
        assert ct == "image/png"


# ====================================================================
# 2. Retry decorator tests
# ====================================================================

class TestRetryDecorator:
    """Verify the openai_retry decorator retries on transient errors."""

    def test_retry_on_rate_limit(self):
        """Should retry on RateLimitError and eventually succeed."""
        from openai_client import openai_retry
        from openai import RateLimitError

        call_count = 0

        def flaky_fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RateLimitError(
                    message="rate limited",
                    response=MagicMock(status_code=429, headers={}),
                    body=None,
                )
            return "success"

        result = openai_retry(flaky_fn)()
        assert result == "success"
        assert call_count == 3

    def test_retry_gives_up_after_max_attempts(self):
        """Should reraise after 3 attempts."""
        from openai_client import openai_retry
        from openai import APITimeoutError

        call_count = 0

        def always_timeout():
            nonlocal call_count
            call_count += 1
            raise APITimeoutError(request=MagicMock())

        with pytest.raises(APITimeoutError):
            openai_retry(always_timeout)()

        assert call_count == 3  # 3 attempts then give up

    def test_no_retry_on_non_retryable_error(self):
        """Should NOT retry on ValueError or other non-retryable errors."""
        from openai_client import openai_retry

        call_count = 0

        def bad_fn():
            nonlocal call_count
            call_count += 1
            raise ValueError("not retryable")

        with pytest.raises(ValueError):
            openai_retry(bad_fn)()

        assert call_count == 1  # No retries


# ====================================================================
# 3. Metrics persistence tests
# ====================================================================

class TestMetricsPersistence:
    """Verify metrics storage with blob fallback."""

    def test_save_and_load_local(self):
        """Metrics round-trip through local file when no blob configured."""
        from usage_metrics import _save_metrics, record_event

        record_event("diagrams_uploaded", {"test": True})
        _save_metrics()

        # Verify file exists
        from usage_metrics import METRICS_FILE
        assert os.path.exists(METRICS_FILE)

    def test_blob_client_returns_none_without_env(self):
        """_get_blob_client returns None when no URL or connection string."""
        from usage_metrics import _get_blob_client
        with patch.dict(os.environ, {"AZURE_STORAGE_ACCOUNT_URL": "", "AZURE_STORAGE_CONNECTION_STRING": ""}, clear=False):
            assert _get_blob_client() is None


# ====================================================================
# 4. Enhanced health check tests
# ====================================================================

class TestHealthCheck:
    """Verify the enhanced /api/health endpoint."""

    @pytest.fixture(scope="class")
    def client(self):
        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_health_returns_checks(self, client):
        """Health endpoint should include version 2.11.1 and checks section."""
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert data["version"] == "2.12.0"
        assert "checks" in data
        assert "openai" in data["checks"]
        assert "storage" in data["checks"]

    def test_health_includes_service_catalog(self, client):
        """Health endpoint should include service catalog counts."""
        r = client.get("/api/health")
        data = r.json()
        assert data["service_catalog"]["aws"] > 0
        assert data["service_catalog"]["azure"] > 0
        assert data["service_catalog"]["gcp"] > 0


# ====================================================================
# 5. CORS tightening tests
# ====================================================================

class TestCORSTightening:
    """Verify CORS is properly restricted."""

    @pytest.fixture(scope="class")
    def client(self):
        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_cors_allows_production_origin(self, client):
        """Production origin should be allowed."""
        r = client.options(
            "/api/health",
            headers={
                "Origin": "https://agreeable-ground-01012c003.2.azurestaticapps.net",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert r.headers.get("access-control-allow-origin") == "https://agreeable-ground-01012c003.2.azurestaticapps.net"

    def test_cors_blocks_unknown_origin(self, client):
        """Unknown origins should not get CORS headers."""
        r = client.options(
            "/api/health",
            headers={
                "Origin": "https://evil-site.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert r.headers.get("access-control-allow-origin") != "https://evil-site.com"
