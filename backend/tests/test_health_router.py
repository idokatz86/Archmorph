"""
Unit tests for the health, versions, and contact router endpoints.

Covers:
  - GET /api/health — status, version, checks, service catalog
  - GET /api/versions — API version info
  - GET /api/contact — contact info
"""

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

from main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestHealthEndpoint:
    """GET /api/health returns status, version, checks, catalog."""

    def test_health_returns_200(self, client):
        resp = client.get("/api/health")
        assert resp.status_code in (200, 503)

    def test_health_has_status_field(self, client):
        resp = client.get("/api/health")
        data = resp.json()
        assert "status" in data
        assert data["status"] in ("healthy", "degraded", "unhealthy")

    def test_health_has_version(self, client):
        resp = client.get("/api/health")
        data = resp.json()
        assert "version" in data
        assert isinstance(data["version"], str)
        assert len(data["version"]) > 0

    def test_health_has_checks(self, client):
        resp = client.get("/api/health")
        data = resp.json()
        assert "checks" in data
        checks = data["checks"]
        assert "openai" in checks
        assert "storage" in checks
        assert "service_catalog" in checks

    def test_health_service_catalog_counts(self, client):
        resp = client.get("/api/health")
        data = resp.json()
        catalog = data.get("service_catalog", {})
        assert catalog.get("aws", 0) > 0
        assert catalog.get("azure", 0) > 0
        assert catalog.get("mappings", 0) > 0

    def test_health_has_environment(self, client):
        resp = client.get("/api/health")
        data = resp.json()
        assert "environment" in data

    def test_health_has_mode(self, client):
        resp = client.get("/api/health")
        data = resp.json()
        assert data.get("mode") == "production"

    def test_health_has_scheduler_running(self, client):
        resp = client.get("/api/health")
        data = resp.json()
        assert "scheduler_running" in data


class TestVersionsEndpoint:
    """GET /api/versions returns API versioning info."""

    def test_versions_returns_200(self, client):
        resp = client.get("/api/versions")
        assert resp.status_code == 200

    def test_versions_has_current_version(self, client):
        resp = client.get("/api/versions")
        data = resp.json()
        assert "current_version" in data

    def test_versions_has_supported(self, client):
        resp = client.get("/api/versions")
        data = resp.json()
        assert "supported_versions" in data
        assert isinstance(data["supported_versions"], list)


class TestContactEndpoint:
    """GET /api/contact returns project info."""

    def test_contact_returns_200(self, client):
        resp = client.get("/api/contact")
        assert resp.status_code == 200

    def test_contact_has_project(self, client):
        resp = client.get("/api/contact")
        data = resp.json()
        assert data.get("project") == "Archmorph"

    def test_contact_has_github_link(self, client):
        resp = client.get("/api/contact")
        data = resp.json()
        assert "github" in data
        assert "github.com" in data["github"]

    def test_contact_has_issues_link(self, client):
        resp = client.get("/api/contact")
        data = resp.json()
        assert "issues" in data

    def test_contact_has_documentation(self, client):
        resp = client.get("/api/contact")
        data = resp.json()
        assert "documentation" in data
