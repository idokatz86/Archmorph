"""
Archmorph Backend — Comprehensive Unit Tests
"""

import json
import os
import sys
import io
import copy
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Ensure backend is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Disable rate limiting for tests
os.environ["RATE_LIMIT_ENABLED"] = "false"

from main import app, SESSION_STORE, IMAGE_STORE
from routers.shared import SHARE_STORE, EXPORT_CAPABILITY_STORE
from chatbot import process_chat_message, get_chat_history, clear_chat_session
from usage_metrics import record_event, record_funnel_step, get_metrics_summary, get_funnel_metrics, get_daily_metrics, get_recent_events
from guided_questions import generate_questions, apply_answers
from diagram_export import generate_diagram, get_azure_stencil_id
from services import AWS_SERVICES, AZURE_SERVICES, GCP_SERVICES, CROSS_CLOUD_MAPPINGS
from openai_client import OpenAIServiceError
from export_capabilities import issue_export_capability
from job_queue import job_manager
import shareable_reports
from iac_chat import IAC_CHAT_SESSIONS


# ====================================================================
# Fixtures
# ====================================================================

@pytest.fixture(scope="module")
def client():
    """Create a FastAPI TestClient that skips the lifespan (scheduler)."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def clean_session():
    """Clear SESSION_STORE and IMAGE_STORE before/after each test that needs it."""
    SESSION_STORE.clear()
    IMAGE_STORE.clear()
    IAC_CHAT_SESSIONS.clear()
    yield SESSION_STORE
    SESSION_STORE.clear()
    IMAGE_STORE.clear()
    IAC_CHAT_SESSIONS.clear()


# Mock analysis result used when we don't want to call Azure OpenAI
MOCK_ANALYSIS = {
    "diagram_type": "Test Architecture",
    "source_provider": "aws",
    "target_provider": "azure",
    "architecture_patterns": ["multi-AZ"],
    "services_detected": 3,
    "zones": [
        {
            "id": 1, "name": "Compute", "number": 1,
            "services": [
                {"aws": "Lambda", "azure": "Azure Functions", "confidence": 0.95},
                {"aws": "Amazon S3", "azure": "Azure Blob Storage", "confidence": 0.95},
            ],
        },
        {
            "id": 2, "name": "Database", "number": 2,
            "services": [
                {"aws": "DynamoDB", "azure": "Cosmos DB", "confidence": 0.85},
            ],
        },
    ],
    "mappings": [
        {"source_service": "Lambda", "source_provider": "aws", "azure_service": "Azure Functions", "confidence": 0.95, "notes": "Zone 1 – Compute"},
        {"source_service": "Amazon S3", "source_provider": "aws", "azure_service": "Azure Blob Storage", "confidence": 0.95, "notes": "Zone 1 – Compute"},
        {"source_service": "DynamoDB", "source_provider": "aws", "azure_service": "Cosmos DB", "confidence": 0.85, "notes": "Zone 2 – Database"},
    ],
    "warnings": [],
    "confidence_summary": {"high": 2, "medium": 1, "low": 0, "average": 0.92},
}


@pytest.fixture
def analyzed_diagram(client, clean_session):
    """Upload + analyze a diagram to populate SESSION_STORE, return diagram_id."""
    # Upload
    content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # minimal PNG header
    resp = client.post(
        "/api/projects/proj-001/diagrams",
        files={"file": ("arch.png", io.BytesIO(content), "image/png")},
    )
    assert resp.status_code == 200
    diagram_id = resp.json()["diagram_id"]

    # Analyze (mock the vision analyzer)
    with patch("routers.diagrams.analyze_image", return_value=copy.deepcopy(MOCK_ANALYSIS)), \
         patch("routers.diagrams.classify_image", return_value={"is_architecture_diagram": True, "confidence": 0.95, "image_type": "architecture_diagram", "reason": "Mock"}):
        resp = client.post(f"/api/diagrams/{diagram_id}/analyze")
    assert resp.status_code == 200
    return diagram_id


# ====================================================================
# 1. Health & Metadata
# ====================================================================

class TestHealth:
    def test_health_returns_200(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        # Status may be 'degraded' when OpenAI is not configured (test env)
        assert data["status"] in ("healthy", "degraded")
        from version import __version__
        assert data["version"] == __version__

    def test_health_has_catalog_counts(self, client):
        data = client.get("/api/health").json()
        cat = data["service_catalog"]
        assert cat["aws"] == len(AWS_SERVICES)
        assert cat["azure"] == len(AZURE_SERVICES)
        assert cat["gcp"] == len(GCP_SERVICES)
        assert cat["mappings"] == len(CROSS_CLOUD_MAPPINGS)

    def test_health_has_scheduler_field(self, client):
        data = client.get("/api/health").json()
        assert "scheduler_running" in data


# ====================================================================
# 2. Projects (Removed — stub endpoints deleted per issue #79)
# ====================================================================

class TestProjects:
    def test_create_project_not_found(self, client):
        resp = client.post("/api/projects", json={"name": "Test"})
        assert resp.status_code == 404

    def test_get_project_not_found(self, client):
        resp = client.get("/api/projects/proj-001")
        assert resp.status_code == 404


# ====================================================================
# 3. Diagram Upload
# ====================================================================

class TestDiagramUpload:
    def test_upload_png(self, client):
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        resp = client.post(
            "/api/projects/proj-001/diagrams",
            files={"file": ("test.png", io.BytesIO(content), "image/png")},
        )
        assert resp.status_code == 200
        d = resp.json()
        assert d["status"] == "uploaded"
        assert d["filename"] == "test.png"
        assert d["diagram_id"].startswith("diag-")
        assert d["size"] > 0

    def test_upload_svg(self, client):
        svg = b"<svg></svg>"
        resp = client.post(
            "/api/projects/proj-001/diagrams",
            files={"file": ("arch.svg", io.BytesIO(svg), "image/svg+xml")},
        )
        assert resp.status_code == 200

    def test_upload_rejects_text(self, client):
        resp = client.post(
            "/api/projects/proj-001/diagrams",
            files={"file": ("bad.txt", io.BytesIO(b"hello"), "text/plain")},
        )
        assert resp.status_code == 400


# ====================================================================
# 4. Analyze Diagram
# ====================================================================

class TestAnalyze:
    def _upload(self, client):
        """Helper to upload a diagram and return the diagram_id."""
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = client.post(
            "/api/projects/proj-001/diagrams",
            files={"file": ("test.png", io.BytesIO(content), "image/png")},
        )
        assert resp.status_code == 200
        return resp.json()["diagram_id"]

    def test_analyze_returns_mappings(self, client, clean_session):
        did = self._upload(client)
        with patch("routers.diagrams.analyze_image", return_value=copy.deepcopy(MOCK_ANALYSIS)):
            resp = client.post(f"/api/diagrams/{did}/analyze")
        assert resp.status_code == 200
        data = resp.json()
        assert data["diagram_id"] == did
        assert data["source_provider"] == "aws"
        assert data["target_provider"] == "azure"
        assert len(data["mappings"]) > 0

    def test_analyze_has_zones(self, client, clean_session):
        did = self._upload(client)
        with patch("routers.diagrams.analyze_image", return_value=copy.deepcopy(MOCK_ANALYSIS)):
            data = client.post(f"/api/diagrams/{did}/analyze").json()
        assert "zones" in data
        assert len(data["zones"]) > 0
        for zone in data["zones"]:
            assert "services" in zone
            assert isinstance(zone["services"], list)

    def test_analyze_populates_session_store(self, client, clean_session):
        did = self._upload(client)
        with patch("routers.diagrams.analyze_image", return_value=copy.deepcopy(MOCK_ANALYSIS)):
            client.post(f"/api/diagrams/{did}/analyze")
        assert did in SESSION_STORE

    def test_analyze_confidence_summary(self, client, clean_session):
        did = self._upload(client)
        with patch("routers.diagrams.analyze_image", return_value=copy.deepcopy(MOCK_ANALYSIS)):
            data = client.post(f"/api/diagrams/{did}/analyze").json()
        cs = data["confidence_summary"]
        assert "high" in cs
        assert "medium" in cs
        assert cs["high"] + cs["medium"] + cs.get("low", 0) == len(data["mappings"])

    def test_analyze_requires_upload(self, client, clean_session):
        """Analyze without prior upload should return 404."""
        resp = client.post("/api/diagrams/nonexistent-diag/analyze")
        assert resp.status_code == 404

    def test_analyze_rate_limit_returns_retryable_429(self, client, clean_session):
        did = self._upload(client)
        analysis_error = OpenAIServiceError(
            "Vision analysis is temporarily rate-limited. Please retry shortly.",
            retryable=True,
            status_code=429,
        )

        with patch("routers.diagrams.analyze_image", side_effect=analysis_error), \
             patch("routers.diagrams.classify_image", return_value={"is_architecture_diagram": True, "confidence": 0.95, "image_type": "architecture_diagram", "reason": "Mock"}):
            resp = client.post(f"/api/diagrams/{did}/analyze")

        assert resp.status_code == 429
        assert resp.headers["retry-after"] == "30"
        body = resp.json()
        assert body["error"]["details"]["error"] == "analysis_retryable"
        assert body["error"]["details"]["retry_after_seconds"] == 30


class TestPurge:
    def _upload(self, client):
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = client.post(
            "/api/projects/proj-001/diagrams",
            files={"file": ("test.png", io.BytesIO(content), "image/png")},
        )
        assert resp.status_code == 200
        return resp.json()["diagram_id"]

    def test_purge_clears_server_side_artifacts(self, client, clean_session, tenant_a_auth_headers):
        did = self._upload(client)
        with patch("routers.diagrams.analyze_image", return_value=copy.deepcopy(MOCK_ANALYSIS)):
            analyzed = client.post(f"/api/diagrams/{did}/analyze", headers=tenant_a_auth_headers)
        assert analyzed.status_code == 200
        assert did in SESSION_STORE
        assert did in IMAGE_STORE

        issue_export_capability(did)
        SHARE_STORE.set("share-test", {"diagram_id": did, "kind": "legacy"})
        share = shareable_reports.create_share({"diagram_id": did, "mappings": []})
        job = job_manager.submit("analyze", diagram_id=did)
        IAC_CHAT_SESSIONS[f"{did}:iac"] = [{"role": "user", "content": "test"}]
        assert job_manager.get(job.job_id) is not None
        assert shareable_reports.get_share_stats(share["share_id"]) is not None

        purge = client.delete(f"/api/diagrams/{did}/purge", headers=tenant_a_auth_headers)
        assert purge.status_code == 200
        payload = purge.json()
        assert payload["status"] == "purged"
        assert payload["diagram_id"] == did
        assert payload["purged"]["image"] is True
        assert payload["purged"]["session"] is True
        assert payload["purged"]["jobs"] >= 1
        assert payload["purged"]["iac_chat"] is True

        assert did not in IMAGE_STORE
        assert did not in SESSION_STORE
        assert job_manager.get(job.job_id) is None
        assert shareable_reports.get_share_stats(share["share_id"]) is None
        assert f"{did}:iac" not in IAC_CHAT_SESSIONS
        assert not any(
            (EXPORT_CAPABILITY_STORE.get(key) or {}).get("diagram_id") == did
            for key in EXPORT_CAPABILITY_STORE.keys("*")
        )
        assert not any(
            (SHARE_STORE.get(key) or {}).get("diagram_id") == did
            for key in SHARE_STORE.keys("*")
        )

    def test_purge_rejects_cross_tenant_access(
        self,
        client,
        clean_session,
        tenant_a_auth_headers,
        tenant_b_auth_headers,
    ):
        did = self._upload(client)
        with patch("routers.diagrams.analyze_image", return_value=copy.deepcopy(MOCK_ANALYSIS)):
            analyzed = client.post(f"/api/diagrams/{did}/analyze", headers=tenant_a_auth_headers)
        assert analyzed.status_code == 200

        forbidden = client.delete(f"/api/diagrams/{did}/purge", headers=tenant_b_auth_headers)
        assert forbidden.status_code in (403, 404)


# ====================================================================
# 5. Guided Questions
# ====================================================================

class TestGuidedQuestions:
    def test_generate_questions_returns_list(self):
        services = ["AWS IoT Core", "Amazon S3", "Amazon Kinesis"]
        qs = generate_questions(services)
        assert isinstance(qs, list)
        assert len(qs) >= 5  # should get a reasonable number

    def test_question_has_required_fields(self):
        qs = generate_questions(["Amazon S3"])
        for q in qs:
            assert "id" in q
            assert "question" in q
            assert "type" in q
            assert "options" in q

    def test_questions_endpoint_needs_analysis(self, client, clean_session):
        resp = client.post("/api/diagrams/no-exist/questions")
        assert resp.status_code == 404

    def test_questions_endpoint_with_analysis(self, client, analyzed_diagram):
        resp = client.post(f"/api/diagrams/{analyzed_diagram}/questions")
        assert resp.status_code == 200
        data = resp.json()
        assert "questions" in data
        assert data["total"] > 0

    def test_apply_answers_returns_refined(self):
        analysis = {
            "diagram_id": "test",
            "mappings": [
                {
                    "source_service": "Amazon S3",
                    "source_provider": "aws",
                    "azure_service": "Azure Blob Storage",
                    "confidence": 0.9,
                    "notes": "Storage",
                }
            ],
            "warnings": [],
        }
        answers = {"environment": "production", "ha_dr": "active_active"}
        result = apply_answers(analysis, answers)
        assert result is not analysis  # should be a deep copy
        assert "mappings" in result

    def test_apply_answers_endpoint_404(self, client, clean_session):
        resp = client.post(
            "/api/diagrams/no-exist/apply-answers", json={"environment": "dev"}
        )
        assert resp.status_code == 404

    def test_apply_answers_endpoint_ok(self, client, analyzed_diagram):
        resp = client.post(
            f"/api/diagrams/{analyzed_diagram}/apply-answers",
            json={"environment": "production"},
        )
        assert resp.status_code == 200


# ====================================================================
# 6. Diagram Export
# ====================================================================

class TestDiagramExport:
    def _make_analysis(self):
        return {
            "title": "Test Architecture",
            "zones": [
                {"id": 1, "name": "Ingest", "number": 1, "services": [
                    {"aws": "AWS IoT Core", "azure": "Azure IoT Hub", "confidence": 0.95}
                ]},
                {"id": 2, "name": "Process", "number": 2, "services": [
                    {"aws": "Amazon Kinesis", "azure": "Azure Event Hubs", "confidence": 0.88}
                ]},
            ],
            "mappings": [
                {"source_service": "AWS IoT Core", "azure_service": "Azure IoT Hub", "confidence": 0.95, "notes": "Zone 1"},
                {"source_service": "Amazon Kinesis", "azure_service": "Azure Event Hubs", "confidence": 0.88, "notes": "Zone 2"},
            ],
        }

    def test_generate_excalidraw(self):
        result = generate_diagram(self._make_analysis(), "excalidraw")
        assert result["format"] == "excalidraw"
        assert result["filename"].endswith(".excalidraw")
        content = json.loads(result["content"])
        assert "elements" in content

    def test_generate_drawio(self):
        result = generate_diagram(self._make_analysis(), "drawio")
        assert result["format"] == "drawio"
        assert result["filename"].endswith(".drawio")
        assert "<mxGraphModel" in result["content"] or "<mxfile" in result["content"]

    def test_generate_vsdx(self):
        result = generate_diagram(self._make_analysis(), "vsdx")
        assert result["format"] == "vsdx"
        assert result["filename"].endswith(".vdx")
        assert "VisioDocument" in result["content"]

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            generate_diagram(self._make_analysis(), "pdf")

    def test_export_endpoint_404(self, client, clean_session):
        resp = client.post("/api/diagrams/no-exist/export-diagram?format=drawio")
        assert resp.status_code == 404

    def test_export_endpoint_bad_format(self, client, analyzed_diagram):
        resp = client.post(f"/api/diagrams/{analyzed_diagram}/export-diagram?format=pdf")
        assert resp.status_code == 400

    def test_export_endpoint_drawio(self, client, analyzed_diagram):
        resp = client.post(f"/api/diagrams/{analyzed_diagram}/export-diagram?format=drawio")
        assert resp.status_code == 200
        data = resp.json()
        assert data["format"] == "drawio"
        assert data["content"]

    def test_export_endpoint_excalidraw(self, client, analyzed_diagram):
        resp = client.post(f"/api/diagrams/{analyzed_diagram}/export-diagram?format=excalidraw")
        assert resp.status_code == 200

    def test_azure_stencil_lookup(self):
        sid = get_azure_stencil_id("Azure IoT Hub", "drawio")
        assert sid  # should return something non-empty

    def test_azure_stencil_fuzzy(self):
        sid = get_azure_stencil_id("IoT Hub", "drawio")
        assert sid


# ====================================================================
# 7. IaC Generation
# ====================================================================

class TestIaCGeneration:
    @patch("routers.iac_routes.generate_iac_code", return_value="resource aws_instance {}")
    def test_generate_terraform(self, mock_iac, client, analyzed_diagram):
        resp = client.post(f"/api/diagrams/{analyzed_diagram}/generate?format=terraform")
        assert resp.status_code == 200
        data = resp.json()
        assert data["format"] == "terraform"
        assert "resource" in data["code"] or "provider" in data["code"]

    @patch("routers.iac_routes.generate_iac_code", return_value="resource aws_instance {} param")
    def test_generate_bicep(self, mock_iac, client, analyzed_diagram):
        resp = client.post(f"/api/diagrams/{analyzed_diagram}/generate?format=bicep")
        assert resp.status_code == 200
        data = resp.json()
        assert data["format"] == "bicep"
        assert "resource" in data["code"] or "param" in data["code"]

    def test_generate_bad_format(self, client, analyzed_diagram):
        resp = client.post(f"/api/diagrams/{analyzed_diagram}/generate?format=pulumi")
        assert resp.status_code == 422

    @patch("routers.iac_routes.generate_iac_code", return_value="resource aws_instance {}")
    def test_generate_any_diagram_id(self, mock_iac, client, clean_session):
        SESSION_STORE["any-id"] = copy.deepcopy(MOCK_ANALYSIS)
        resp = client.post("/api/diagrams/any-id/generate?format=terraform")
        assert resp.status_code == 200
        assert "resource" in resp.json()["code"] or "provider" in resp.json()["code"]


# ====================================================================
# 8. Cost Estimate
# ====================================================================

class TestCostEstimate:
    def test_cost_estimate_returns_data(self, client, analyzed_diagram):
        resp = client.get(f"/api/diagrams/{analyzed_diagram}/cost-estimate")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_monthly_estimate" in data
        assert data["currency"] == "USD"
        assert "services" in data
        # With real mappings, we should get priced services
        assert data["service_count"] > 0

    def test_cost_estimate_has_ranges(self, client, analyzed_diagram):
        est = client.get(f"/api/diagrams/{analyzed_diagram}/cost-estimate").json()["total_monthly_estimate"]
        assert "low" in est
        assert "high" in est
        assert est["low"] <= est["high"]

    def test_cost_estimate_nonzero(self, client, analyzed_diagram):
        """Verify analyzed diagram produces non-zero cost estimates."""
        data = client.get(f"/api/diagrams/{analyzed_diagram}/cost-estimate").json()
        # At least some services should have a non-zero price
        priced = [s for s in data["services"] if s["monthly_estimate"] > 0]
        assert len(priced) >= 1, "Expected at least one service with non-zero cost"

    def test_cost_estimate_fallback(self, client):
        """No analysis → returns 404 for unknown diagram."""
        resp = client.get("/api/diagrams/nonexistent-id/cost-estimate")
        assert resp.status_code == 404


# ====================================================================
# 9. Chatbot (GPT-4o AI Assistant)
# ====================================================================

class TestChatbot:
    @patch("chatbot._call_ai_assistant")
    def test_process_general_message(self, mock_ai):
        mock_ai.return_value = {
            "reply": "Archmorph is an AI-powered tool that helps migrate cloud architectures.",
            "action": None,
        }
        result = process_chat_message("test-session-1", "what is archmorph?")
        assert "reply" in result
        assert "Archmorph" in result["reply"]
        mock_ai.assert_called_once()

    @patch("chatbot._call_ai_assistant")
    def test_ai_detects_bug_action(self, mock_ai):
        mock_ai.return_value = {
            "reply": "I understand you found a bug. I can help you report it.",
            "action": {"action": "create_bug", "title": "Export feature bug", "description": "Bug in export"},
        }
        result = process_chat_message("test-bug-1", "there's a bug in the export feature")
        # Should result in pending_action being set
        assert result.get("action") == "issue_draft" or result.get("pending_action") is not None

    @patch("chatbot._call_ai_assistant")
    def test_ai_detects_feature_action(self, mock_ai):
        mock_ai.return_value = {
            "reply": "Great feature idea! Let me help you submit it.",
            "action": {"action": "create_feature", "title": "Dark mode", "description": "Add dark mode support"},
        }
        result = process_chat_message("test-feature-1", "I have a feature request for dark mode")
        assert result.get("action") == "issue_draft" or result.get("pending_action") is not None

    @patch("chatbot._call_ai_assistant")
    def test_chat_history(self, mock_ai):
        mock_ai.return_value = {"reply": "Hello! How can I help you today?", "action": None}
        process_chat_message("test-hist-1", "hello")
        history = get_chat_history("test-hist-1")
        assert len(history) >= 2  # user + assistant

    @patch("chatbot._call_ai_assistant")
    def test_clear_session(self, mock_ai):
        mock_ai.return_value = {"reply": "Hi there!", "action": None}
        process_chat_message("test-clear-1", "hello")
        assert clear_chat_session("test-clear-1") is True
        assert clear_chat_session("test-clear-1") is False  # already cleared

    def test_chat_session_structure(self):
        """Test that chat history returns proper structure"""
        history = get_chat_history("nonexistent-session")
        assert isinstance(history, list)

    @patch("chatbot._call_ai_assistant", return_value={"reply": "Mocked", "action": None})
    def test_chat_endpoint(self, mock_ai, client):
        resp = client.post("/api/chat", json={"message": "what is archmorph?"})
        assert resp.status_code == 200
        assert "reply" in resp.json()

    @patch("chatbot._call_ai_assistant", return_value={"reply": "hi", "action": None})
    def test_chat_history_endpoint(self, mock_ai, client):
        client.post("/api/chat", json={"message": "hi", "session_id": "e2e-hist"})
        resp = client.get("/api/chat/history/e2e-hist")
        assert resp.status_code == 200
        assert len(resp.json()["messages"]) >= 2

    @patch("chatbot._call_ai_assistant", return_value={"reply": "hi", "action": None})
    def test_chat_clear_endpoint(self, mock_ai, client):
        client.post("/api/chat", json={"message": "hi", "session_id": "e2e-del"})
        resp = client.delete("/api/chat/e2e-del")
        assert resp.status_code == 200
        assert resp.json()["cleared"] is True


# ====================================================================
# 10. Usage Metrics (Admin)
# ====================================================================

class TestMetrics:
    def test_record_and_get_summary(self):
        record_event("test_event_unit", {"detail": "test"})
        summary = get_metrics_summary()
        assert summary["total_events"] > 0
        assert "totals" in summary

    def test_funnel_step(self):
        record_funnel_step("test-funnel-diag", "upload")
        record_funnel_step("test-funnel-diag", "analyze")
        funnel = get_funnel_metrics()
        assert funnel["total_sessions"] > 0

    def test_daily_metrics(self):
        data = get_daily_metrics(7)
        assert isinstance(data, list)

    def test_recent_events(self):
        record_event("test_recent_unit", {})
        events = get_recent_events(10)
        assert isinstance(events, list)

    def _get_admin_token(self, client, monkeypatch):
        """Log in via POST /api/admin/login and return Bearer header dict."""
        monkeypatch.setattr("admin_auth.ADMIN_SECRET", "test-admin-key")
        monkeypatch.setattr("admin_auth.JWT_SECRET", "test-admin-key-test-salt-32-byte-value")
        resp = client.post("/api/admin/login", json={"key": "test-admin-key"})
        assert resp.status_code == 200
        token = resp.json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def test_admin_login_wrong_key(self, client, monkeypatch):
        monkeypatch.setattr("admin_auth.ADMIN_SECRET", "test-admin-key")
        resp = client.post("/api/admin/login", json={"key": "wrong-key"})
        assert resp.status_code == 403

    def test_admin_metrics_endpoint_no_auth(self, client, monkeypatch):
        monkeypatch.setattr("admin_auth.ADMIN_SECRET", "test-admin-key")
        monkeypatch.setattr("admin_auth.JWT_SECRET", "test-admin-key-test-salt-32-byte-value")
        resp = client.get("/api/admin/metrics")
        assert resp.status_code == 401

    def test_admin_metrics_endpoint_invalid_token(self, client, monkeypatch):
        monkeypatch.setattr("admin_auth.ADMIN_SECRET", "test-admin-key")
        monkeypatch.setattr("admin_auth.JWT_SECRET", "test-admin-key-test-salt-32-byte-value")
        resp = client.get("/api/admin/metrics", headers={"Authorization": "Bearer bogus-token"})
        assert resp.status_code == 401

    def test_admin_metrics_endpoint_ok(self, client, monkeypatch):
        headers = self._get_admin_token(client, monkeypatch)
        resp = client.get("/api/admin/metrics", headers=headers)
        assert resp.status_code == 200
        assert "totals" in resp.json()

    def test_admin_funnel_endpoint(self, client, monkeypatch):
        headers = self._get_admin_token(client, monkeypatch)
        resp = client.get("/api/admin/metrics/funnel", headers=headers)
        assert resp.status_code == 200
        assert "total_sessions" in resp.json()

    def test_admin_daily_endpoint(self, client, monkeypatch):
        headers = self._get_admin_token(client, monkeypatch)
        resp = client.get("/api/admin/metrics/daily?days=7", headers=headers)
        assert resp.status_code == 200
        assert "data" in resp.json()

    def test_admin_recent_endpoint(self, client, monkeypatch):
        headers = self._get_admin_token(client, monkeypatch)
        resp = client.get("/api/admin/metrics/recent?limit=5", headers=headers)
        assert resp.status_code == 200
        assert "events" in resp.json()

    def test_admin_logout(self, client, monkeypatch):
        headers = self._get_admin_token(client, monkeypatch)
        # Logout should succeed
        resp = client.post("/api/admin/logout", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "logged_out"
        # Token should now be revoked
        resp = client.get("/api/admin/metrics", headers=headers)
        assert resp.status_code == 401


# ====================================================================
# 11. Services Catalog
# ====================================================================

class TestServicesCatalog:
    def test_list_all_services(self, client):
        resp = client.get("/api/services?page_size=200")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == len(AWS_SERVICES) + len(AZURE_SERVICES) + len(GCP_SERVICES)
        assert data["page"] == 1
        assert "total_pages" in data

    def test_filter_by_provider(self, client):
        resp = client.get("/api/services?provider=aws&page_size=200")
        data = resp.json()
        assert data["total"] == len(AWS_SERVICES)
        for s in data["services"]:
            assert s["provider"] == "aws"

    def test_filter_by_category(self, client):
        resp = client.get("/api/services?category=compute&page_size=200")
        data = resp.json()
        assert data["total"] > 0
        for s in data["services"]:
            assert s["category"].lower() == "compute"

    def test_search_services(self, client):
        resp = client.get("/api/services?search=lambda&page_size=200")
        data = resp.json()
        assert data["total"] > 0

    def test_pagination(self, client):
        """Test that pagination returns correct page metadata."""
        resp = client.get("/api/services?page=1&page_size=10")
        data = resp.json()
        assert len(data["services"]) == 10
        assert data["page"] == 1
        assert data["page_size"] == 10
        assert data["total_pages"] > 1

    def test_providers_endpoint(self, client):
        resp = client.get("/api/services/providers")
        assert resp.status_code == 200
        providers = resp.json()["providers"]
        ids = [p["id"] for p in providers]
        assert "aws" in ids
        assert "azure" in ids
        assert "gcp" in ids

    def test_categories_endpoint(self, client):
        resp = client.get("/api/services/categories")
        assert resp.status_code == 200
        cats = resp.json()["categories"]
        assert len(cats) > 0

    def test_mappings_endpoint(self, client):
        resp = client.get("/api/services/mappings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] > 0

    def test_mappings_search(self, client):
        resp = client.get("/api/services/mappings?search=s3")
        data = resp.json()
        assert data["total"] > 0

    def test_specific_service(self, client):
        # Get a known AWS service
        svc_id = AWS_SERVICES[0]["id"]
        resp = client.get(f"/api/services/aws/{svc_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == svc_id

    def test_specific_service_not_found(self, client):
        resp = client.get("/api/services/aws/nonexistent-service")
        assert resp.status_code == 404

    def test_stats_endpoint(self, client):
        resp = client.get("/api/services/stats")
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["totalServices"] > 0
        assert stats["totalMappings"] > 0


# ====================================================================
# 12. Service Updates
# ====================================================================

class TestServiceUpdates:
    def test_status(self, client):
        resp = client.get("/api/service-updates/status")
        assert resp.status_code == 200
        assert "scheduler_running" in resp.json()

    def test_last_update(self, client):
        resp = client.get("/api/service-updates/last")
        assert resp.status_code == 200

    def test_storage_preflight(self, client):
        with patch("routers.services.verify_service_catalog_blob_access", return_value={
            "ok": True,
            "account_url_configured": True,
            "operations": ["write", "read", "list", "delete"],
        }):
            resp = client.post("/api/service-updates/storage-preflight")
        assert resp.status_code == 200
        assert resp.json()["operations"] == ["write", "read", "list", "delete"]

    def test_storage_preflight_failure(self, client):
        with patch("routers.services.verify_service_catalog_blob_access", return_value={
            "ok": False,
            "error": "AZURE_STORAGE_ACCOUNT_URL is not configured",
        }):
            resp = client.post("/api/service-updates/storage-preflight")
        assert resp.status_code == 503
        body = resp.json()
        assert body["error"]["message"] == "Managed identity Blob Storage preflight failed"
        assert body["error"]["details"]["account_url_configured"] is False
        assert "AZURE_STORAGE_ACCOUNT_URL is not configured" not in str(body)


# ====================================================================
# 13. Contact
# ====================================================================

class TestContact:
    def test_contact_returns_info(self, client):
        resp = client.get("/api/contact")
        assert resp.status_code == 200
        data = resp.json()
        assert "github" in data
        assert "issues" in data
        assert "archmorph" in data["github"].lower()


# ====================================================================
# 14. Service Data Quality
# ====================================================================

class TestServiceDataQuality:
    def test_aws_services_not_empty(self):
        assert len(AWS_SERVICES) > 100

    def test_azure_services_not_empty(self):
        assert len(AZURE_SERVICES) > 100

    def test_gcp_services_not_empty(self):
        assert len(GCP_SERVICES) > 50

    def test_mappings_not_empty(self):
        assert len(CROSS_CLOUD_MAPPINGS) > 50

    def test_service_has_required_fields(self):
        for svc in AWS_SERVICES[:10]:
            assert "id" in svc
            assert "name" in svc
            assert "category" in svc

    def test_mapping_has_required_fields(self):
        for m in CROSS_CLOUD_MAPPINGS[:10]:
            assert "aws" in m
            assert "azure" in m
            assert "confidence" in m

    def test_new_mapping_categories_present(self):
        """Issues #60-#67: new mapping categories should exist."""
        categories = {m.get("category") for m in CROSS_CLOUD_MAPPINGS}
        expected = [
            "Hybrid", "AI/ML", "Edge",
            "Observability", "Data Governance", "Zero Trust",
        ]
        for cat in expected:
            assert cat in categories, f"Missing new category {cat}"

    def test_all_mappings_have_required_fields(self):
        """Every mapping (not just first 10) has required fields."""
        for m in CROSS_CLOUD_MAPPINGS:
            assert "aws" in m, f"Mapping missing 'aws': {m}"
            assert "azure" in m, f"Mapping missing 'azure': {m}"
            assert "confidence" in m, f"Mapping missing 'confidence': {m}"
            assert 0 < m["confidence"] <= 1.0

    def test_azure_services_have_unique_ids(self):
        """Azure catalog has unique ids."""
        ids = [s["id"] for s in AZURE_SERVICES]
        assert len(ids) == len(set(ids)), "Duplicate IDs found in Azure"

    def test_gcp_services_have_unique_ids(self):
        """GCP catalog has unique ids."""
        ids = [s["id"] for s in GCP_SERVICES]
        assert len(ids) == len(set(ids)), "Duplicate IDs found in GCP"


# NOTE: TestMigrationAssessment and TestCostComparison archived — see _archive/tests/
