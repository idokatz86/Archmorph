"""
Tests for Archmorph API Versioning Module
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Disable rate limiting for tests
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

import pytest
from fastapi.testclient import TestClient

from api_versioning import (
    get_api_versions, create_versioned_router,
    API_V1, CURRENT_VERSION, SUPPORTED_VERSIONS,
)
from main import app


# ────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    """Create a FastAPI TestClient."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ────────────────────────────────────────────────────────────
# Unit tests — api_versioning module
# ────────────────────────────────────────────────────────────

class TestAPIVersioning:
    """Tests for API versioning functionality."""

    def test_get_api_versions_structure(self):
        """get_api_versions returns expected structure."""
        result = get_api_versions()

        assert "current_version" in result
        assert "supported_versions" in result
        assert "deprecated_versions" in result
        assert "versions" in result
        assert "migration_guide" in result

    def test_current_version_is_v1(self):
        """Current API version should be v1."""
        assert CURRENT_VERSION == API_V1
        assert CURRENT_VERSION == "v1"

    def test_v1_is_supported(self):
        """V1 should be in supported versions."""
        assert API_V1 in SUPPORTED_VERSIONS

    def test_version_info_contains_v1(self):
        """Version info should contain v1 details."""
        result = get_api_versions()

        assert API_V1 in result["versions"]
        v1_info = result["versions"][API_V1]

        assert "version" in v1_info
        assert "status" in v1_info
        assert "released" in v1_info
        assert "changes" in v1_info
        assert v1_info["status"] == "stable"

    def test_create_versioned_router(self):
        """create_versioned_router creates router with correct prefix."""
        router = create_versioned_router("v1")

        assert router.prefix == "/api/v1"
        assert "API V1" in router.tags

    def test_create_versioned_router_with_prefix(self):
        """create_versioned_router handles additional prefix."""
        router = create_versioned_router("v2", prefix="/admin")

        assert router.prefix == "/api/v2/admin"
        assert "API V2" in router.tags


class TestAPIVersionConstants:
    """Tests for API version constants."""

    def test_api_v1_constant(self):
        """API_V1 constant is correct."""
        assert API_V1 == "v1"

    def test_supported_versions_is_list(self):
        """SUPPORTED_VERSIONS is a list."""
        assert isinstance(SUPPORTED_VERSIONS, list)
        assert len(SUPPORTED_VERSIONS) >= 1


# ────────────────────────────────────────────────────────────
# Integration tests — v1 route mirroring
# ────────────────────────────────────────────────────────────

class TestV1RouteMirroring:
    """All /api/* routes should also be accessible at /api/v1/*."""

    def test_v1_health(self, client):
        """GET /api/v1/health mirrors /api/health."""
        original = client.get("/api/health")
        v1 = client.get("/api/v1/health")

        assert v1.status_code == 200
        assert v1.json()["status"] == original.json()["status"]
        assert v1.json()["version"] == original.json()["version"]

    def test_v1_versions(self, client):
        """GET /api/v1/versions mirrors /api/versions."""
        v1 = client.get("/api/v1/versions")
        assert v1.status_code == 200
        data = v1.json()
        assert data["current_version"] == "v1"
        assert "v1" in data["supported_versions"]

    def test_v1_contact(self, client):
        """GET /api/v1/contact mirrors /api/contact."""
        v1 = client.get("/api/v1/contact")
        assert v1.status_code == 200
        assert v1.json()["project"] == "Archmorph"

    def test_v1_services(self, client):
        """GET /api/v1/services mirrors /api/services."""
        v1 = client.get("/api/v1/services")
        assert v1.status_code == 200

    def test_v1_samples(self, client):
        """GET /api/v1/samples mirrors /api/samples."""
        v1 = client.get("/api/v1/samples")
        assert v1.status_code == 200

    def test_v1_roadmap(self, client):
        """GET /api/v1/roadmap mirrors /api/roadmap."""
        v1 = client.get("/api/v1/roadmap")
        assert v1.status_code == 200

    def test_v1_auth_config(self, client):
        """GET /api/v1/auth/config mirrors /api/auth/config."""
        v1 = client.get("/api/v1/auth/config")
        assert v1.status_code == 200

    def test_original_routes_still_work(self, client):
        """Original /api/* routes must continue working."""
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/versions").status_code == 200
        assert client.get("/api/services").status_code == 200


# ────────────────────────────────────────────────────────────
# Integration tests — X-API-Version response header
# ────────────────────────────────────────────────────────────

class TestVersionHeaders:
    """Responses should include X-API-Version and X-API-Deprecated headers."""

    def test_version_header_on_unversioned_route(self, client):
        """Unversioned /api/* routes get X-API-Version = current."""
        resp = client.get("/api/health")
        assert resp.headers.get("x-api-version") == "v1"

    def test_version_header_on_v1_route(self, client):
        """Versioned /api/v1/* routes get X-API-Version = v1."""
        resp = client.get("/api/v1/health")
        assert resp.headers.get("x-api-version") == "v1"

    def test_deprecated_header_false(self, client):
        """V1 is not deprecated so header should be 'false'."""
        resp = client.get("/api/v1/health")
        assert resp.headers.get("x-api-deprecated") == "false"

    def test_version_header_on_versions_endpoint(self, client):
        """The /api/versions endpoint also includes version headers."""
        resp = client.get("/api/versions")
        assert resp.headers.get("x-api-version") == "v1"

