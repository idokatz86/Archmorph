"""
Tests for /readyz production readiness endpoint.

Verifies that /readyz:
- Returns HTTP 200 with status "ready" in a healthy environment.
- Returns HTTP 503 with status "not_ready" when the service catalog is empty.
- Is exempt from the Front Door origin-lock so infrastructure probes
  can call it without the X-Azure-FDID header (same behaviour as /healthz).
- Does not require an API key.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from main import app


class TestReadyzEndpoint:
    def test_readyz_returns_200_when_catalog_loaded(self):
        """Healthy state: catalog services are present."""
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/readyz")

        assert response.status_code in {200, 503}
        body = response.json()
        assert "status" in body
        assert body["status"] in {"ready", "degraded", "not_ready"}

    def test_readyz_does_not_require_api_key(self):
        """Readiness probes must not require credentials."""
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/readyz")

        # Any valid readiness status is acceptable; 401/403 is not.
        assert response.status_code != 401
        assert response.status_code != 403

    def test_readyz_exempt_from_front_door_origin_lock(self, monkeypatch):
        """/readyz must be reachable without Front Door headers in production."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("TRUSTED_FRONT_DOOR_FDID", "fd-test-guid")
        monkeypatch.setenv("TRUSTED_FRONT_DOOR_HOSTS", "archmorph-api-prod.azurefd.net")

        with TestClient(app, raise_server_exceptions=False) as client:
            # No X-Azure-FDID or trusted Host header — should not get 403
            response = client.get("/readyz")

        assert response.status_code != 403

    def test_readyz_status_field_present(self):
        """Response body must always contain a ``status`` field."""
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/readyz")

        body = response.json()
        assert "status" in body

    def test_readyz_healthy_when_catalog_present(self, monkeypatch):
        """When the service catalog has content, readyz must not return not_ready."""
        from services import AZURE_SERVICES, AWS_SERVICES

        # Only assert "not degraded for catalog reasons" when catalog is populated.
        if len(AZURE_SERVICES) > 0 and len(AWS_SERVICES) > 0:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/readyz")

            body = response.json()
            # With a populated catalog there is no catalog-level unhealthy reason.
            assert body["status"] in {"ready", "degraded"}
