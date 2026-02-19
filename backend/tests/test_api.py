"""
Archmorph Backend — Comprehensive Unit Tests
"""

import json
import os
import sys
import io
import copy
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

# Ensure backend is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from main import app, SESSION_STORE
from chatbot import process_chat_message, get_chat_history, clear_chat_session, _detect_intent, _detect_labels, _find_faq_answer
from usage_metrics import record_event, record_funnel_step, get_metrics_summary, get_funnel_metrics, get_daily_metrics, get_recent_events
from guided_questions import generate_questions, apply_answers
from diagram_export import generate_diagram, get_azure_stencil_id
from services import AWS_SERVICES, AZURE_SERVICES, GCP_SERVICES, CROSS_CLOUD_MAPPINGS


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
    """Clear SESSION_STORE before/after each test that needs it."""
    SESSION_STORE.clear()
    yield SESSION_STORE
    SESSION_STORE.clear()


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

    # Analyze
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
        assert data["status"] == "healthy"
        assert data["version"] == "2.1.0"

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
# 2. Projects (Stubs)
# ====================================================================

class TestProjects:
    def test_create_project(self, client):
        resp = client.post("/api/projects", json={"name": "Test"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "created"

    def test_get_project(self, client):
        resp = client.get("/api/projects/proj-001")
        assert resp.status_code == 200
        assert "diagrams" in resp.json()


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
    def test_analyze_returns_mappings(self, client, clean_session):
        resp = client.post("/api/diagrams/diag-001/analyze")
        assert resp.status_code == 200
        data = resp.json()
        assert data["diagram_id"] == "diag-001"
        assert data["source_provider"] == "aws"
        assert data["target_provider"] == "azure"
        assert len(data["mappings"]) > 0

    def test_analyze_has_zones(self, client, clean_session):
        data = client.post("/api/diagrams/diag-001/analyze").json()
        assert "zones" in data
        assert len(data["zones"]) > 0
        # Each zone should have a services list
        for zone in data["zones"]:
            assert "services" in zone
            assert isinstance(zone["services"], list)

    def test_analyze_populates_session_store(self, client, clean_session):
        client.post("/api/diagrams/diag-001/analyze")
        assert "diag-001" in SESSION_STORE

    def test_analyze_confidence_summary(self, client, clean_session):
        data = client.post("/api/diagrams/diag-001/analyze").json()
        cs = data["confidence_summary"]
        assert "high" in cs
        assert "medium" in cs
        assert cs["high"] + cs["medium"] + cs.get("low", 0) == len(data["mappings"])


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
    def test_generate_terraform(self, client, analyzed_diagram):
        resp = client.post(f"/api/diagrams/{analyzed_diagram}/generate?format=terraform")
        assert resp.status_code == 200
        data = resp.json()
        assert data["format"] == "terraform"
        assert "resource" in data["code"] or "provider" in data["code"]

    def test_generate_bicep(self, client, analyzed_diagram):
        resp = client.post(f"/api/diagrams/{analyzed_diagram}/generate?format=bicep")
        assert resp.status_code == 200
        data = resp.json()
        assert data["format"] == "bicep"
        assert "resource" in data["code"] or "param" in data["code"]

    def test_generate_bad_format(self, client, analyzed_diagram):
        resp = client.post(f"/api/diagrams/{analyzed_diagram}/generate?format=pulumi")
        assert resp.status_code == 400

    def test_generate_any_diagram_id(self, client, clean_session):
        # IaC generation currently returns hardcoded code for any diagram_id
        resp = client.post("/api/diagrams/any-id/generate?format=terraform")
        assert resp.status_code == 200
        assert "resource" in resp.json()["code"] or "provider" in resp.json()["code"]


# ====================================================================
# 8. Cost Estimate
# ====================================================================

class TestCostEstimate:
    def test_cost_estimate_returns_data(self, client):
        resp = client.get("/api/diagrams/diag-001/cost-estimate")
        assert resp.status_code == 200
        data = resp.json()
        assert "monthly_estimate" in data
        assert data["currency"] == "USD"
        assert "services" in data
        assert len(data["services"]) > 0

    def test_cost_estimate_has_ranges(self, client):
        est = client.get("/api/diagrams/diag-001/cost-estimate").json()["monthly_estimate"]
        assert est["low"] < est["medium"] < est["high"]


# ====================================================================
# 9. Chatbot
# ====================================================================

class TestChatbot:
    def test_detect_intent_general(self):
        assert _detect_intent("hello how are you") == "general"

    def test_detect_intent_issue(self):
        assert _detect_intent("create a github issue about broken export") == "create_issue"

    def test_detect_intent_report_bug(self):
        assert _detect_intent("i found a bug in the diagram") == "create_issue"

    def test_detect_labels(self):
        labels = _detect_labels("there is a bug in the export feature")
        assert "bug" in labels

    def test_faq_answer(self):
        answer = _find_faq_answer("what is archmorph")
        assert answer is not None

    def test_process_general_message(self):
        result = process_chat_message("test-session-1", "what is archmorph?")
        assert "reply" in result
        assert result["action"] is None or result["action"] == "issue_draft" or result["reply"]

    def test_chat_history(self):
        process_chat_message("test-hist-1", "hello")
        history = get_chat_history("test-hist-1")
        assert len(history) >= 2  # user + assistant

    def test_clear_session(self):
        process_chat_message("test-clear-1", "hello")
        assert clear_chat_session("test-clear-1") is True
        assert clear_chat_session("test-clear-1") is False  # already cleared

    def test_chat_endpoint(self, client):
        resp = client.post("/api/chat", json={"message": "what is archmorph?"})
        assert resp.status_code == 200
        assert "reply" in resp.json()

    def test_chat_history_endpoint(self, client):
        client.post("/api/chat", json={"message": "hi", "session_id": "e2e-hist"})
        resp = client.get("/api/chat/history/e2e-hist")
        assert resp.status_code == 200
        assert len(resp.json()["messages"]) >= 2

    def test_chat_clear_endpoint(self, client):
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

    def test_admin_metrics_endpoint_403(self, client):
        resp = client.get("/api/admin/metrics?key=wrong-key")
        assert resp.status_code == 403

    def test_admin_metrics_endpoint_ok(self, client):
        resp = client.get("/api/admin/metrics?key=archmorph-admin-2025")
        assert resp.status_code == 200
        assert "totals" in resp.json()

    def test_admin_funnel_endpoint(self, client):
        resp = client.get("/api/admin/metrics/funnel?key=archmorph-admin-2025")
        assert resp.status_code == 200
        assert "total_sessions" in resp.json()

    def test_admin_daily_endpoint(self, client):
        resp = client.get("/api/admin/metrics/daily?key=archmorph-admin-2025&days=7")
        assert resp.status_code == 200
        assert "data" in resp.json()

    def test_admin_recent_endpoint(self, client):
        resp = client.get("/api/admin/metrics/recent?key=archmorph-admin-2025&limit=5")
        assert resp.status_code == 200
        assert "events" in resp.json()


# ====================================================================
# 11. Services Catalog
# ====================================================================

class TestServicesCatalog:
    def test_list_all_services(self, client):
        resp = client.get("/api/services")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] > 0
        assert data["total"] == len(AWS_SERVICES) + len(AZURE_SERVICES) + len(GCP_SERVICES)

    def test_filter_by_provider(self, client):
        resp = client.get("/api/services?provider=aws")
        data = resp.json()
        assert data["total"] == len(AWS_SERVICES)
        for s in data["services"]:
            assert s["provider"] == "aws"

    def test_filter_by_category(self, client):
        resp = client.get("/api/services?category=compute")
        data = resp.json()
        assert data["total"] > 0
        for s in data["services"]:
            assert s["category"].lower() == "compute"

    def test_search_services(self, client):
        resp = client.get("/api/services?search=lambda")
        data = resp.json()
        assert data["total"] > 0

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


# ====================================================================
# 13. Contact
# ====================================================================

class TestContact:
    def test_contact_returns_info(self, client):
        resp = client.get("/api/contact")
        assert resp.status_code == 200
        data = resp.json()
        assert "email" in data
        assert data["email"] == "send2katz@gmail.com"


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
