"""
Regression Tests for Archmorph Backend.

These tests verify that critical user journeys continue to work correctly
across cross-module boundaries. They act as a regression safety net for
refactoring and feature additions.

Covers:
  - Health + Version consistency
  - Service catalog integrity
  - Sample diagram full flow
  - Feature flags read/write
  - Chat + Roadmap regression
  - Admin authentication + metrics flow
  - Error envelope format consistency
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


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def clean_session():
    SESSION_STORE.clear()
    IMAGE_STORE.clear()
    yield
    SESSION_STORE.clear()
    IMAGE_STORE.clear()


MOCK_ANALYSIS = {
    "diagram_type": "AWS Architecture",
    "source_provider": "aws",
    "target_provider": "azure",
    "architecture_patterns": ["multi-AZ", "serverless"],
    "services_detected": 3,
    "zones": [
        {
            "id": 1, "name": "Compute", "number": 1,
            "services": [
                {"aws": "Lambda", "azure": "Azure Functions", "confidence": 0.95},
            ],
        },
        {
            "id": 2, "name": "Storage", "number": 2,
            "services": [
                {"aws": "S3", "azure": "Azure Blob Storage", "confidence": 0.95},
            ],
        },
    ],
    "mappings": [
        {"source_service": "Lambda", "source_provider": "aws", "azure_service": "Azure Functions", "confidence": 0.95},
        {"source_service": "S3", "source_provider": "aws", "azure_service": "Azure Blob Storage", "confidence": 0.95},
        {"source_service": "DynamoDB", "source_provider": "aws", "azure_service": "Azure Cosmos DB", "confidence": 0.85},
    ],
    "warnings": [],
    "confidence_summary": {"high": 2, "medium": 1, "low": 0, "average": 0.92},
}


class TestHealthAndVersionRegression:
    """Regression: health and version endpoints remain consistent."""

    def test_health_version_matches_version_module(self, client):
        from version import __version__
        resp = client.get("/api/health")
        assert resp.json()["version"] == __version__

    def test_health_catalog_counts_positive(self, client):
        resp = client.get("/api/health")
        catalog = resp.json()["service_catalog"]
        assert catalog["aws"] > 0
        assert catalog["azure"] > 0
        assert catalog["gcp"] > 0
        assert catalog["mappings"] > 0

    def test_versions_endpoint_includes_v1(self, client):
        resp = client.get("/api/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert "v1" in str(data)


class TestServiceCatalogRegression:
    """Regression: service catalog endpoints return consistent data."""

    def test_services_total_positive(self, client):
        resp = client.get("/api/services")
        assert resp.status_code == 200
        assert resp.json()["total"] > 0

    def test_services_stats_consistent(self, client):
        resp = client.get("/api/services/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totalServices"] > 0
        assert data["totalMappings"] > 0

    def test_services_providers_list(self, client):
        resp = client.get("/api/services/providers")
        assert resp.status_code == 200
        provider_ids = [p["id"] for p in resp.json()["providers"]]
        assert "aws" in provider_ids
        assert "azure" in provider_ids
        assert "gcp" in provider_ids


class TestSampleDiagramRegression:
    """Regression: sample diagram flow works end-to-end."""

    def test_sample_list_and_analyze(self, client, clean_session):
        # List samples
        resp = client.get("/api/samples")
        assert resp.status_code == 200
        samples = resp.json()["samples"]
        assert len(samples) > 0

        # Analyze first sample
        sample_id = samples[0]["id"]
        resp = client.post(f"/api/samples/{sample_id}/analyze")
        assert resp.status_code == 200
        diagram_id = resp.json()["diagram_id"]

        # Verify questions work
        resp = client.post(f"/api/diagrams/{diagram_id}/questions")
        assert resp.status_code == 200
        assert resp.json()["total"] > 0

        # Verify cost estimate works
        resp = client.get(f"/api/diagrams/{diagram_id}/cost-estimate")
        assert resp.status_code == 200
        assert resp.json()["service_count"] > 0

    def test_sample_recreate_after_eviction(self, client, clean_session):
        """Sample sessions should auto-recreate after eviction."""
        # Analyze a sample
        resp = client.post("/api/samples/aws-iaas/analyze")
        assert resp.status_code == 200
        diagram_id = resp.json()["diagram_id"]

        # Verify session exists
        assert diagram_id in SESSION_STORE

        # Evict and verify recreation works
        SESSION_STORE.delete(diagram_id)
        assert diagram_id not in SESSION_STORE

        # Access should recreate
        resp = client.get(f"/api/diagrams/{diagram_id}/cost-estimate")
        assert resp.status_code == 200


class TestFeatureFlagsRegression:
    """Regression: feature flags return expected structure."""

    def test_flags_list_structure(self, client):
        resp = client.get("/api/flags")
        assert resp.status_code == 200
        flags = resp.json()["flags"]
        assert isinstance(flags, dict)
        assert "dark_mode" in flags

    def test_single_flag_structure(self, client):
        resp = client.get("/api/flags/dark_mode")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "dark_mode"
        assert "enabled" in data
        assert "rollout_percentage" in data

    def test_unknown_flag_returns_404(self, client):
        resp = client.get("/api/flags/totally_fake_flag_xyz")
        assert resp.status_code == 404


class TestChatAndRoadmapRegression:
    """Regression: chat and roadmap endpoints."""

    def test_chat_responds(self, client):
        resp = client.post("/api/chat", json={
            "message": "Hello",
            "session_id": "regression-chat-1",
        })
        assert resp.status_code == 200
        assert "reply" in resp.json()

    def test_roadmap_structure(self, client):
        resp = client.get("/api/roadmap")
        assert resp.status_code == 200
        data = resp.json()
        assert "timeline" in data
        assert "stats" in data


class TestAdminFlowRegression:
    """Regression: admin login and metrics flow."""

    def test_admin_login_and_metrics(self, client, monkeypatch):
        monkeypatch.setattr("admin_auth.ADMIN_SECRET", "reg-test-key")
        monkeypatch.setattr("admin_auth.JWT_SECRET", "reg-test-key:salt")

        # Login
        resp = client.post("/api/admin/login", json={"key": "reg-test-key"})
        assert resp.status_code == 200
        token = resp.json()["token"]

        # Metrics
        headers = {"Authorization": f"Bearer {token}"}
        resp = client.get("/api/admin/metrics", headers=headers)
        assert resp.status_code == 200
        assert "totals" in resp.json()

    def test_admin_unauthorized_without_token(self, client):
        resp = client.get("/api/admin/metrics")
        assert resp.status_code in (401, 403, 503)


class TestErrorFormatRegression:
    """Regression: error responses have consistent envelope format."""

    def test_404_has_error_envelope(self, client):
        resp = client.post("/api/diagrams/nonexistent/questions")
        assert resp.status_code == 404
        data = resp.json()
        assert "error" in data
        error = data["error"]
        assert "code" in error
        assert "message" in error
        assert "correlation_id" in error

    def test_404_code_is_not_found(self, client):
        resp = client.post("/api/diagrams/nonexistent/questions")
        assert resp.json()["error"]["code"] == "NOT_FOUND"


class TestUploadAnalyzeRegression:
    """Regression: the core upload → analyze pipeline."""

    def test_upload_returns_diagram_id(self, client, clean_session):
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = client.post(
            "/api/projects/proj-reg/diagrams",
            files={"file": ("reg.png", io.BytesIO(content), "image/png")},
        )
        assert resp.status_code == 200
        assert "diagram_id" in resp.json()

    def test_analyze_returns_mappings(self, client, clean_session):
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = client.post(
            "/api/projects/proj-reg2/diagrams",
            files={"file": ("reg2.png", io.BytesIO(content), "image/png")},
        )
        diagram_id = resp.json()["diagram_id"]

        with patch("routers.diagrams.analyze_image", return_value=copy.deepcopy(MOCK_ANALYSIS)), \
             patch("routers.diagrams.classify_image", return_value={
                 "is_architecture_diagram": True, "confidence": 0.95,
                 "image_type": "architecture_diagram", "reason": "Mock"
             }):
            resp = client.post(f"/api/diagrams/{diagram_id}/analyze")
        assert resp.status_code == 200
        assert len(resp.json()["mappings"]) == 3

    def test_nonexistent_diagram_404(self, client, clean_session):
        resp = client.post("/api/diagrams/no-such-id/questions")
        assert resp.status_code == 404
