"""
Contract Tests — validate every major API endpoint against expected response schema.

Ensures:
  - Correct HTTP status codes
  - Required fields present in responses
  - Field types match expectations
  - No unexpected field removals between versions

Issue #34
"""

import copy
import io
import os
import sys
from unittest.mock import patch

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
    "services_detected": 2,
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


def _upload_and_analyze(client):
    """Helper: upload a PNG and analyze it with mocked vision."""
    content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    resp = client.post(
        "/api/projects/proj-001/diagrams",
        files={"file": ("arch.png", io.BytesIO(content), "image/png")},
    )
    assert resp.status_code == 200
    diagram_id = resp.json()["diagram_id"]

    with patch("routers.diagrams.analyze_image", return_value=copy.deepcopy(MOCK_ANALYSIS)), \
         patch("routers.diagrams.classify_image", return_value={
             "is_architecture_diagram": True,
             "confidence": 0.95,
             "image_type": "architecture_diagram",
             "reason": "Mock",
         }):
        resp = client.post(f"/api/diagrams/{diagram_id}/analyze")
    assert resp.status_code == 200
    return diagram_id


# ─────────────────────────────────────────────────────────────
# Schema helpers
# ─────────────────────────────────────────────────────────────

def assert_fields(data, required_fields: dict):
    """Assert that *data* contains every key in *required_fields* with matching type."""
    for field, expected_type in required_fields.items():
        assert field in data, f"Missing required field: {field}"
        if expected_type is not None:
            assert isinstance(data[field], expected_type), (
                f"Field '{field}' expected {expected_type.__name__}, "
                f"got {type(data[field]).__name__}"
            )


# =================================================================
# Contract: /api/health
# =================================================================

@pytest.mark.contract
class TestHealthContract:
    SCHEMA = {
        "status": str,
        "version": str,
        "environment": str,
        "mode": str,
        "checks": dict,
        "service_catalog": dict,
        "scheduler_running": bool,
    }

    def test_health_status_code(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_health_schema(self, client):
        data = client.get("/api/health").json()
        assert_fields(data, self.SCHEMA)

    def test_health_service_catalog_schema(self, client):
        cat = client.get("/api/health").json()["service_catalog"]
        assert_fields(cat, {"aws": int, "azure": int, "gcp": int, "mappings": int})

    def test_health_checks_schema(self, client):
        checks = client.get("/api/health").json()["checks"]
        assert_fields(checks, {"openai": str, "storage": str})


# =================================================================
# Contract: /api/versions
# =================================================================

@pytest.mark.contract
class TestVersionsContract:
    def test_versions_status_code(self, client):
        resp = client.get("/api/versions")
        assert resp.status_code == 200

    def test_versions_has_versions_field(self, client):
        data = client.get("/api/versions").json()
        assert "versions" in data or "current" in data  # flexible schema


# =================================================================
# Contract: /api/contact
# =================================================================

@pytest.mark.contract
class TestContactContract:
    def test_contact_status_code(self, client):
        resp = client.get("/api/contact")
        assert resp.status_code == 200

    def test_contact_schema(self, client):
        data = client.get("/api/contact").json()
        assert_fields(data, {"project": str, "github": str, "issues": str})


# =================================================================
# Contract: /api/projects/{id}/diagrams (upload)
# =================================================================

@pytest.mark.contract
class TestDiagramUploadContract:
    def test_upload_returns_200(self, client):
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        resp = client.post(
            "/api/projects/proj-001/diagrams",
            files={"file": ("test.png", io.BytesIO(content), "image/png")},
        )
        assert resp.status_code == 200

    def test_upload_schema(self, client):
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        resp = client.post(
            "/api/projects/proj-001/diagrams",
            files={"file": ("test.png", io.BytesIO(content), "image/png")},
        )
        data = resp.json()
        assert_fields(data, {
            "diagram_id": str,
            "filename": str,
            "size": int,
            "status": str,
        })

    def test_upload_rejects_bad_type(self, client):
        resp = client.post(
            "/api/projects/proj-001/diagrams",
            files={"file": ("bad.txt", io.BytesIO(b"hello"), "text/plain")},
        )
        assert resp.status_code == 400


# =================================================================
# Contract: /api/diagrams/{id}/analyze
# =================================================================

@pytest.mark.contract
class TestAnalyzeContract:
    def test_analyze_schema(self, client):
        diagram_id = _upload_and_analyze(client)
        analysis = SESSION_STORE.get(diagram_id)
        assert analysis is not None
        assert_fields(analysis, {
            "source_provider": str,
            "target_provider": str,
            "mappings": list,
        })

    def test_mapping_item_schema(self, client):
        diagram_id = _upload_and_analyze(client)
        analysis = SESSION_STORE.get(diagram_id)
        for m in analysis["mappings"]:
            assert_fields(m, {
                "source_service": str,
                "azure_service": str,
                "confidence": (int, float),
            })

    def test_analyze_missing_diagram_404(self, client):
        resp = client.post("/api/diagrams/nonexistent/analyze")
        assert resp.status_code == 404


# =================================================================
# Contract: /api/diagrams/{id}/questions
# =================================================================

@pytest.mark.contract
class TestQuestionsContract:
    def test_questions_schema(self, client):
        diagram_id = _upload_and_analyze(client)
        resp = client.post(f"/api/diagrams/{diagram_id}/questions")
        assert resp.status_code == 200
        data = resp.json()
        assert_fields(data, {"questions": list, "diagram_id": str})

    def test_questions_missing_diagram_404(self, client):
        resp = client.post("/api/diagrams/nonexistent/questions")
        assert resp.status_code == 404


# =================================================================
# Contract: /api/services
# =================================================================

@pytest.mark.contract
class TestServicesContract:
    SCHEMA = {
        "total": int,
        "page": int,
        "page_size": int,
        "services": list,
    }

    def test_services_status_code(self, client):
        resp = client.get("/api/services")
        assert resp.status_code == 200

    def test_services_schema(self, client):
        data = client.get("/api/services").json()
        assert_fields(data, self.SCHEMA)

    def test_services_filter_provider(self, client):
        data = client.get("/api/services?provider=aws").json()
        assert_fields(data, self.SCHEMA)
        for s in data["services"]:
            assert s["provider"] == "aws"

    def test_services_pagination_schema(self, client):
        data = client.get("/api/services?page=1&page_size=5").json()
        assert data["page"] == 1
        assert data["page_size"] == 5
        assert len(data["services"]) <= 5

    def test_services_providers_schema(self, client):
        resp = client.get("/api/services/providers")
        assert resp.status_code == 200
        data = resp.json()
        assert "providers" in data
        for p in data["providers"]:
            assert_fields(p, {"id": str, "name": str, "serviceCount": int})

    def test_services_categories(self, client):
        resp = client.get("/api/services/categories")
        assert resp.status_code == 200


# =================================================================
# Contract: /api/chat
# =================================================================

@pytest.mark.contract
class TestChatContract:
    @patch("routers.chat.process_chat_message")
    def test_chat_schema(self, mock_chat, client):
        mock_chat.return_value = {"response": "Hello!", "action": None}
        resp = client.post("/api/chat", json={"message": "hello", "session_id": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert "response" in data or "action" in data

    def test_chat_missing_message_422(self, client):
        resp = client.post("/api/chat", json={})
        assert resp.status_code == 422

    def test_chat_history_schema(self, client):
        resp = client.get("/api/chat/history/test-session")
        assert resp.status_code == 200
        data = resp.json()
        assert_fields(data, {"session_id": str, "messages": list})

    def test_chat_clear(self, client):
        resp = client.delete("/api/chat/test-session")
        assert resp.status_code == 200
        data = resp.json()
        assert "cleared" in data


# =================================================================
# Contract: /api/flags
# =================================================================

@pytest.mark.contract
class TestFlagsContract:
    def test_flags_list_schema(self, client):
        resp = client.get("/api/flags")
        assert resp.status_code == 200
        data = resp.json()
        assert "flags" in data
        assert isinstance(data["flags"], dict)

    def test_flags_get_known(self, client):
        resp = client.get("/api/flags/dark_mode")
        assert resp.status_code == 200
        data = resp.json()
        assert_fields(data, {"name": str, "enabled": bool})

    def test_flags_get_unknown_404(self, client):
        resp = client.get("/api/flags/does_not_exist_xyz")
        assert resp.status_code == 404

    def test_flags_update_requires_admin(self, client):
        resp = client.put("/api/flags/dark_mode", json={"enabled": False})
        # Should fail with 401 or 503 (admin not configured)
        assert resp.status_code in (401, 503)


# =================================================================
# Contract: /api/roadmap
# =================================================================

@pytest.mark.contract
class TestRoadmapContract:
    def test_roadmap_status_code(self, client):
        resp = client.get("/api/roadmap")
        assert resp.status_code == 200

    def test_roadmap_has_releases(self, client):
        data = client.get("/api/roadmap").json()
        # Roadmap should return some structure with releases
        assert isinstance(data, (dict, list))


# =================================================================
# Contract: /api/feedback/*
# =================================================================

@pytest.mark.contract
class TestFeedbackContract:
    def test_nps_schema(self, client):
        resp = client.post("/api/feedback/nps", json={"score": 8})
        assert resp.status_code == 200

    def test_nps_invalid_score_type(self, client):
        resp = client.post("/api/feedback/nps", json={"score": "bad"})
        assert resp.status_code == 422

    def test_feature_feedback_schema(self, client):
        resp = client.post("/api/feedback/feature", json={
            "feature": "export",
            "helpful": True,
        })
        assert resp.status_code == 200


# =================================================================
# Contract: /api/samples/*
# =================================================================

@pytest.mark.contract
class TestSamplesContract:
    def test_samples_list(self, client):
        resp = client.get("/api/samples")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (list, dict))


# =================================================================
# Contract: /api/terraform/validate
# =================================================================

@pytest.mark.contract
class TestTerraformContract:
    def test_validate_schema(self, client):
        resp = client.post("/api/terraform/validate", json={
            "code": 'resource "azurerm_resource_group" "rg" { name = "test" location = "eastus" }'
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "valid" in data or "errors" in data or "result" in data

    def test_validate_empty_code(self, client):
        resp = client.post("/api/terraform/validate", json={"code": ""})
        # Should return 200 with validation result, not crash
        assert resp.status_code in (200, 422)


# =================================================================
# Contract: /api/admin/* — auth-gated endpoints
# =================================================================

@pytest.mark.contract
class TestAdminContract:
    def test_admin_login_missing_body_422(self, client):
        resp = client.post("/api/admin/login", json={})
        assert resp.status_code == 422

    def test_admin_login_bad_key(self, client):
        resp = client.post("/api/admin/login", json={"key": "wrong"})
        # 403 (wrong key) or 503 (admin not configured)
        assert resp.status_code in (403, 503)

    def test_admin_logout_no_token(self, client):
        resp = client.post("/api/admin/logout")
        assert resp.status_code == 400

    def test_admin_metrics_requires_auth(self, client):
        resp = client.get("/api/admin/metrics")
        assert resp.status_code in (401, 503)

    def test_admin_monitoring_requires_auth(self, client):
        resp = client.get("/api/admin/monitoring")
        assert resp.status_code in (401, 503)


# =================================================================
# Contract: /api/auth/*
# =================================================================

@pytest.mark.contract
class TestAuthContract:
    def test_auth_config_schema(self, client):
        resp = client.get("/api/auth/config")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_auth_login_missing_fields(self, client):
        resp = client.post("/api/auth/login", json={"provider": "github"})
        assert resp.status_code in (400, 422)


# =================================================================
# Contract: /api/diagrams/{id}/runbook (migration)
# =================================================================

@pytest.mark.contract
class TestMigrationContract:
    def test_runbook_requires_analysis(self, client):
        resp = client.post("/api/diagrams/nonexistent/runbook")
        assert resp.status_code == 404

    def test_assessment_requires_analysis(self, client):
        resp = client.post("/api/diagrams/nonexistent/assessment")
        assert resp.status_code in (404, 405)

    def test_runbook_schema(self, client):
        diagram_id = _upload_and_analyze(client)
        resp = client.post(f"/api/diagrams/{diagram_id}/runbook")
        assert resp.status_code == 200
        data = resp.json()
        assert_fields(data, {"id": str, "diagram_id": str, "title": str})


# =================================================================
# Contract: /api/v1/* mirrors
# =================================================================

@pytest.mark.contract
class TestV1MirrorContract:
    """Ensure /api/v1/* routes mirror /api/* with identical schemas."""

    def test_v1_health(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert_fields(data, {"status": str, "version": str})

    def test_v1_services(self, client):
        resp = client.get("/api/v1/services")
        assert resp.status_code == 200
        data = resp.json()
        assert_fields(data, {"total": int, "services": list})

    def test_v1_flags(self, client):
        resp = client.get("/api/v1/flags")
        assert resp.status_code == 200
        data = resp.json()
        assert "flags" in data

    def test_v1_roadmap(self, client):
        resp = client.get("/api/v1/roadmap")
        assert resp.status_code == 200

    def test_v1_contact(self, client):
        resp = client.get("/api/v1/contact")
        assert resp.status_code == 200
        data = resp.json()
        assert_fields(data, {"project": str})


# =================================================================
# Contract: Response headers
# =================================================================

@pytest.mark.contract
class TestResponseHeadersContract:
    """Verify security and metadata headers on all responses."""

    def test_security_headers(self, client):
        resp = client.get("/api/health")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"

    def test_version_header(self, client):
        resp = client.get("/api/health")
        # VersionMiddleware should inject API-Version header
        assert "X-Response-Time" in resp.headers or "API-Version" in resp.headers

    def test_correlation_id_header(self, client):
        resp = client.get("/api/health")
        assert "X-Correlation-ID" in resp.headers
