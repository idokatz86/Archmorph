"""
Archmorph Integration Tests

Tests that verify the integration between different backend components
working together, including the full analysis flow, service addition,
and question deduplication pipeline.
"""

import copy
import io
import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["RATE_LIMIT_ENABLED"] = "false"

from main import app, SESSION_STORE, IMAGE_STORE


@pytest.fixture(scope="module")
def client():
    """Create a FastAPI TestClient."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def clean_session():
    """Clear stores before/after each test."""
    SESSION_STORE.clear()
    IMAGE_STORE.clear()
    yield
    SESSION_STORE.clear()
    IMAGE_STORE.clear()


# Mock analysis result
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


class TestFullAnalysisFlow:
    """Test the complete analysis → add services → questions → IaC flow."""

    def _upload_and_analyze(self, client, clean_session):
        """Helper to upload and analyze a diagram."""
        # Upload
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = client.post(
            "/api/projects/proj-001/diagrams",
            files={"file": ("arch.png", io.BytesIO(content), "image/png")},
        )
        assert resp.status_code == 200
        diagram_id = resp.json()["diagram_id"]

        # Analyze with mock
        with patch("routers.diagrams.analyze_image", return_value=copy.deepcopy(MOCK_ANALYSIS)), \
             patch("routers.diagrams.classify_image", return_value={
                 "is_architecture_diagram": True,
                 "confidence": 0.95,
                 "image_type": "architecture_diagram",
                 "reason": "Mock"
             }):
            resp = client.post(f"/api/diagrams/{diagram_id}/analyze")
        assert resp.status_code == 200
        return diagram_id

    def test_upload_analyze_questions_flow(self, client, clean_session):
        """Test the full upload → analyze → questions flow."""
        diagram_id = self._upload_and_analyze(client, clean_session)

        # Get questions
        resp = client.post(f"/api/diagrams/{diagram_id}/questions?smart_dedup=true")
        assert resp.status_code == 200
        data = resp.json()
        
        assert "questions" in data
        assert "inferred_answers" in data
        assert data["diagram_id"] == diagram_id

    @patch("service_builder.get_openai_client")
    def test_add_services_then_questions(self, mock_openai, client, clean_session):
        """Test adding services via NL then getting questions with deduplication."""
        diagram_id = self._upload_and_analyze(client, clean_session)

        # Mock OpenAI for service addition
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "services": [
                {"name": "Redis", "full_name": "Azure Cache for Redis", "category": "Database"}
            ],
            "inferred_requirements": ["low latency"]
        })
        mock_openai.return_value.chat.completions.create.return_value = mock_response

        # Add services
        resp = client.post(
            f"/api/diagrams/{diagram_id}/add-services",
            json={"text": "Add Redis cache for production system"}
        )
        assert resp.status_code == 200
        add_result = resp.json()
        assert len(add_result["services_added"]) == 1

        # Get questions - production should be inferred
        resp = client.post(f"/api/diagrams/{diagram_id}/questions?smart_dedup=true")
        assert resp.status_code == 200
        q_data = resp.json()

        # Should have inferred some answers
        assert "inferred_answers" in q_data

    def test_add_services_requires_analysis(self, client, clean_session):
        """Test that add-services fails without prior analysis."""
        resp = client.post(
            "/api/diagrams/nonexistent/add-services",
            json={"text": "Add Redis"}
        )
        assert resp.status_code == 404

    def test_questions_endpoint_returns_smart_defaults(self, client, clean_session):
        """Test that questions endpoint returns smart defaults from analysis."""
        diagram_id = self._upload_and_analyze(client, clean_session)

        resp = client.post(f"/api/diagrams/{diagram_id}/questions")
        assert resp.status_code == 200
        data = resp.json()

        # Should have inferred answers based on architecture patterns
        assert "inferred_answers" in data


class TestServiceAdditionIntegration:
    """Test service addition integrates with other endpoints."""

    def _setup_analyzed_diagram(self, client, clean_session):
        """Helper to set up an analyzed diagram."""
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = client.post(
            "/api/projects/proj-001/diagrams",
            files={"file": ("arch.png", io.BytesIO(content), "image/png")},
        )
        diagram_id = resp.json()["diagram_id"]

        with patch("routers.diagrams.analyze_image", return_value=copy.deepcopy(MOCK_ANALYSIS)), \
             patch("routers.diagrams.classify_image", return_value={
                 "is_architecture_diagram": True,
                 "confidence": 0.95
             }):
            client.post(f"/api/diagrams/{diagram_id}/analyze")
        return diagram_id

    @patch("service_builder.get_openai_client")
    def test_added_services_appear_in_cost_estimate(self, mock_openai, client, clean_session):
        """Test that added services are included in cost estimates."""
        diagram_id = self._setup_analyzed_diagram(client, clean_session)

        # Add Redis
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "services": [
                {"name": "Redis", "full_name": "Azure Cache for Redis", "category": "Database"}
            ],
            "inferred_requirements": []
        })
        mock_openai.return_value.chat.completions.create.return_value = mock_response

        client.post(f"/api/diagrams/{diagram_id}/add-services", json={"text": "Add Redis"})

        # Get cost estimate
        resp = client.get(f"/api/diagrams/{diagram_id}/cost-estimate")
        assert resp.status_code == 200
        cost_data = resp.json()

        # Should have 4 services now (3 original + 1 added)
        assert cost_data["service_count"] == 4

    @patch("service_builder.get_openai_client")
    def test_added_services_persist_in_session(self, mock_openai, client, clean_session):
        """Test that added services persist across requests."""
        diagram_id = self._setup_analyzed_diagram(client, clean_session)

        # Add first service
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "services": [
                {"name": "Redis", "full_name": "Azure Cache for Redis", "category": "Database"}
            ],
            "inferred_requirements": []
        })
        mock_openai.return_value.chat.completions.create.return_value = mock_response

        resp1 = client.post(f"/api/diagrams/{diagram_id}/add-services", json={"text": "Add Redis"})
        assert resp1.json()["services_detected"] == 4

        # Add second service
        mock_response.choices[0].message.content = json.dumps({
            "services": [
                {"name": "CDN", "full_name": "Azure CDN", "category": "Networking"}
            ],
            "inferred_requirements": []
        })

        resp2 = client.post(f"/api/diagrams/{diagram_id}/add-services", json={"text": "Add CDN"})
        assert resp2.json()["services_detected"] == 5

        # Verify session has both additions tracked
        session = SESSION_STORE.get(diagram_id)
        assert len(session.get("user_context", {}).get("natural_language_additions", [])) == 2


class TestQuestionDeduplicationIntegration:
    """Test question deduplication works across the full flow."""

    def _setup_analyzed_diagram(self, client, clean_session):
        """Helper to set up an analyzed diagram."""
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = client.post(
            "/api/projects/proj-001/diagrams",
            files={"file": ("arch.png", io.BytesIO(content), "image/png")},
        )
        diagram_id = resp.json()["diagram_id"]

        analysis = copy.deepcopy(MOCK_ANALYSIS)
        analysis["architecture_patterns"] = ["multi-AZ", "high-availability"]

        with patch("routers.diagrams.analyze_image", return_value=analysis), \
             patch("routers.diagrams.classify_image", return_value={
                 "is_architecture_diagram": True,
                 "confidence": 0.95
             }):
            client.post(f"/api/diagrams/{diagram_id}/analyze")
        return diagram_id

    def test_smart_dedup_can_be_disabled(self, client, clean_session):
        """Test that smart deduplication can be disabled."""
        diagram_id = self._setup_analyzed_diagram(client, clean_session)

        # With dedup enabled
        resp1 = client.post(f"/api/diagrams/{diagram_id}/questions?smart_dedup=true")
        resp1.json()

        # With dedup disabled
        resp2 = client.post(f"/api/diagrams/{diagram_id}/questions?smart_dedup=false")
        data2 = resp2.json()

        # Disabled should have no inferred answers or empty
        assert len(data2.get("inferred_answers", {})) == 0 or "inferred_answers" not in data2


class TestErrorHandling:
    """Test error handling in integration scenarios."""

    def test_add_services_empty_text(self, client, clean_session):
        """Test adding services with empty text."""
        # First set up a diagram
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = client.post(
            "/api/projects/proj-001/diagrams",
            files={"file": ("arch.png", io.BytesIO(content), "image/png")},
        )
        diagram_id = resp.json()["diagram_id"]

        with patch("routers.diagrams.analyze_image", return_value=copy.deepcopy(MOCK_ANALYSIS)), \
             patch("routers.diagrams.classify_image", return_value={
                 "is_architecture_diagram": True,
                 "confidence": 0.95
             }):
            client.post(f"/api/diagrams/{diagram_id}/analyze")

        # Try to add with empty text - should handle gracefully
        resp = client.post(f"/api/diagrams/{diagram_id}/add-services", json={"text": ""})
        # Should return 200 with empty services_added
        assert resp.status_code == 200
        assert resp.json()["services_added"] == []

    def test_questions_without_analysis(self, client, clean_session):
        """Test getting questions without analysis fails properly."""
        resp = client.post("/api/diagrams/fake-diagram/questions")
        assert resp.status_code == 404


# ====================================================================
# NEW — Sprint Integration Tests (refactoring validation)
# ====================================================================


class TestFullPipelineIntegration:
    """Full pipeline: upload → analyze → questions → HLD → IaC → export."""

    def _upload_and_analyze(self, client):
        """Upload + analyze helper, returns diagram_id."""
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = client.post(
            "/api/projects/proj-pipe/diagrams",
            files={"file": ("pipe.png", io.BytesIO(content), "image/png")},
        )
        assert resp.status_code == 200
        diagram_id = resp.json()["diagram_id"]

        with patch("routers.diagrams.analyze_image", return_value=copy.deepcopy(MOCK_ANALYSIS)), \
             patch("routers.diagrams.classify_image", return_value={
                 "is_architecture_diagram": True, "confidence": 0.95,
                 "image_type": "architecture_diagram", "reason": "Mock"
             }):
            resp = client.post(f"/api/diagrams/{diagram_id}/analyze")
        assert resp.status_code == 200
        return diagram_id

    def test_full_pipeline_upload_to_export(self, client, clean_session):
        """Test the complete flow: upload → analyze → questions → HLD → export drawio."""
        diagram_id = self._upload_and_analyze(client)

        # Questions
        resp = client.post(f"/api/diagrams/{diagram_id}/questions?smart_dedup=true")
        assert resp.status_code == 200
        assert resp.json()["total"] > 0

        # Apply answers
        resp = client.post(
            f"/api/diagrams/{diagram_id}/apply-answers",
            json={"environment": "production", "ha_dr": "active_active"},
        )
        assert resp.status_code == 200

        # Generate HLD
        with patch("routers.diagrams.generate_hld") as mock_hld:
            mock_hld.return_value = {
                "title": "Test HLD",
                "services": [],
                "executive_summary": "Test",
                "architecture_overview": {},
            }
            resp = client.post(f"/api/diagrams/{diagram_id}/generate-hld")
        assert resp.status_code == 200
        assert resp.json()["hld"]["title"] == "Test HLD"

        # Get cached HLD
        resp = client.get(f"/api/diagrams/{diagram_id}/hld")
        assert resp.status_code == 200

        # Generate IaC
        resp = client.post(f"/api/diagrams/{diagram_id}/generate?format=terraform")
        assert resp.status_code == 200
        assert "resource" in resp.json()["code"] or "provider" in resp.json()["code"]

        # Export drawio
        resp = client.post(f"/api/diagrams/{diagram_id}/export-diagram?format=drawio")
        assert resp.status_code == 200
        assert resp.json()["format"] == "drawio"

    def test_full_pipeline_with_cost_estimate(self, client, clean_session):
        """Pipeline includes cost estimation after analysis."""
        diagram_id = self._upload_and_analyze(client)

        # Cost estimate
        resp = client.get(f"/api/diagrams/{diagram_id}/cost-estimate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["currency"] == "USD"
        assert data["service_count"] > 0

    # NOTE: migration_assessment, cost_comparison, and migration_runbook tests
    # archived — see _archive/tests/ for original integration tests.


class TestSessionPersistenceIntegration:
    """Session persistence across requests (session store)."""

    def test_session_persists_analysis(self, client, clean_session):
        """Analysis result persists in session store across requests."""
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = client.post(
            "/api/projects/proj-sess/diagrams",
            files={"file": ("sess.png", io.BytesIO(content), "image/png")},
        )
        diagram_id = resp.json()["diagram_id"]

        with patch("routers.diagrams.analyze_image", return_value=copy.deepcopy(MOCK_ANALYSIS)), \
             patch("routers.diagrams.classify_image", return_value={
                 "is_architecture_diagram": True, "confidence": 0.95
             }):
            client.post(f"/api/diagrams/{diagram_id}/analyze")

        # Session should exist
        assert diagram_id in SESSION_STORE
        session = SESSION_STORE.get(diagram_id)
        assert session is not None
        assert "mappings" in session

        # Subsequent requests use same session
        resp = client.post(f"/api/diagrams/{diagram_id}/questions")
        assert resp.status_code == 200

        resp = client.get(f"/api/diagrams/{diagram_id}/cost-estimate")
        assert resp.status_code == 200
        assert resp.json()["service_count"] > 0

    def test_session_isolation_between_diagrams(self, client, clean_session):
        """Different diagrams have independent sessions."""
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

        # Upload two diagrams
        resp1 = client.post(
            "/api/projects/proj-iso/diagrams",
            files={"file": ("d1.png", io.BytesIO(content), "image/png")},
        )
        did1 = resp1.json()["diagram_id"]

        resp2 = client.post(
            "/api/projects/proj-iso/diagrams",
            files={"file": ("d2.png", io.BytesIO(content), "image/png")},
        )
        did2 = resp2.json()["diagram_id"]

        assert did1 != did2

        # Analyze only the first
        with patch("routers.diagrams.analyze_image", return_value=copy.deepcopy(MOCK_ANALYSIS)), \
             patch("routers.diagrams.classify_image", return_value={
                 "is_architecture_diagram": True, "confidence": 0.95
             }):
            client.post(f"/api/diagrams/{did1}/analyze")

        # First has session, second does not
        assert did1 in SESSION_STORE
        assert SESSION_STORE.get(did2) is None or "mappings" not in (SESSION_STORE.get(did2) or {})


class TestAPIVersioningIntegration:
    """API versioning: /api and /api/v1 return same response."""

    def test_health_same_response(self, client, clean_session):
        """GET /api/health and GET /api/v1/health return same data."""
        orig = client.get("/api/health")
        v1 = client.get("/api/v1/health")

        assert orig.status_code == 200
        assert v1.status_code == 200

        orig_data = orig.json()
        v1_data = v1.json()

        assert orig_data["status"] == v1_data["status"]
        assert orig_data["version"] == v1_data["version"]
        assert orig_data["service_catalog"] == v1_data["service_catalog"]

    def test_services_same_response(self, client, clean_session):
        """GET /api/services and GET /api/v1/services return same total."""
        orig = client.get("/api/services")
        v1 = client.get("/api/v1/services")

        assert orig.status_code == 200
        assert v1.status_code == 200
        assert orig.json()["total"] == v1.json()["total"]

    def test_contact_same_response(self, client, clean_session):
        """GET /api/contact and GET /api/v1/contact return same data."""
        orig = client.get("/api/contact")
        v1 = client.get("/api/v1/contact")

        assert orig.status_code == 200
        assert v1.status_code == 200
        assert orig.json() == v1.json()

    def test_flags_same_response(self, client, clean_session):
        """GET /api/flags and GET /api/v1/flags return same flags."""
        orig = client.get("/api/flags")
        v1 = client.get("/api/v1/flags")

        assert orig.status_code == 200
        assert v1.status_code == 200
        assert orig.json()["flags"].keys() == v1.json()["flags"].keys()

    def test_v1_upload_and_analyze_works(self, client, clean_session):
        """Upload and analyze via /api/v1/ routes works the same."""
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = client.post(
            "/api/v1/projects/proj-v1/diagrams",
            files={"file": ("v1.png", io.BytesIO(content), "image/png")},
        )
        assert resp.status_code == 200
        diagram_id = resp.json()["diagram_id"]

        with patch("routers.diagrams.analyze_image", return_value=copy.deepcopy(MOCK_ANALYSIS)), \
             patch("routers.diagrams.classify_image", return_value={
                 "is_architecture_diagram": True, "confidence": 0.95
             }):
            resp = client.post(f"/api/v1/diagrams/{diagram_id}/analyze")
        assert resp.status_code == 200
        assert resp.json()["source_provider"] == "aws"


class TestFeatureFlagsIntegration:
    """Feature flags affecting behavior in integration context."""

    def test_flags_endpoint_returns_all(self, client, clean_session):
        """GET /api/flags returns all configured flags."""
        resp = client.get("/api/flags")
        assert resp.status_code == 200
        flags = resp.json()["flags"]
        assert "dark_mode" in flags
        assert "export_pptx" in flags
        assert "new_ai_model" in flags

    def test_single_flag_lookup(self, client, clean_session):
        """GET /api/flags/<name> returns the flag data."""
        resp = client.get("/api/flags/dark_mode")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "dark_mode"
        assert "enabled" in data
        assert "rollout_percentage" in data

    def test_unknown_flag_404(self, client, clean_session):
        """GET /api/flags/<nonexistent> returns 404."""
        resp = client.get("/api/flags/nonexistent_flag_xyz")
        assert resp.status_code == 404

    def test_update_flag_requires_auth(self, client, clean_session):
        """PUT /api/flags/<name> without admin auth is rejected."""
        resp = client.patch("/api/flags/dark_mode", json={"enabled": False})
        assert resp.status_code in (401, 403, 503)

    def test_flags_available_via_v1(self, client, clean_session):
        """GET /api/v1/flags works the same."""
        resp = client.get("/api/v1/flags")
        assert resp.status_code == 200
        assert "dark_mode" in resp.json()["flags"]


class TestAuditLoggingIntegration:
    """Audit logging captures events during integration flow."""

    def test_audit_log_captures_events(self, client, clean_session):
        """Performing actions generates audit log entries."""
        from audit_logging import get_audit_logs, clear_audit_logs
        clear_audit_logs()

        # Perform several actions
        client.get("/api/services")
        client.get("/api/contact")

        # Upload and analyze
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = client.post(
            "/api/projects/proj-audit/diagrams",
            files={"file": ("aud.png", io.BytesIO(content), "image/png")},
        )
        diagram_id = resp.json()["diagram_id"]

        with patch("routers.diagrams.analyze_image", return_value=copy.deepcopy(MOCK_ANALYSIS)), \
             patch("routers.diagrams.classify_image", return_value={
                 "is_architecture_diagram": True, "confidence": 0.95
             }):
            client.post(f"/api/diagrams/{diagram_id}/analyze")

        # Audit log should have entries (from AuditMiddleware)
        logs = get_audit_logs()
        assert len(logs) > 0

    def test_audit_summary_counts(self, client, clean_session):
        """Audit summary reflects logged events."""
        from audit_logging import get_audit_summary, clear_audit_logs
        clear_audit_logs()

        # Do some requests
        client.get("/api/services")
        client.get("/api/contact")

        summary = get_audit_summary()
        assert "total_events" in summary


class TestChatAndRoadmapIntegration:
    """Chat + roadmap flow integration."""

    def test_chat_and_roadmap_sequence(self, client, clean_session):
        """User can chat and then view roadmap in same session."""
        # Chat
        resp = client.post("/api/chat", json={"message": "What is Archmorph?", "session_id": "int-chat-1"})
        assert resp.status_code == 200
        assert "reply" in resp.json()

        # Roadmap
        resp = client.get("/api/roadmap")
        assert resp.status_code == 200
        data = resp.json()
        assert "timeline" in data
        assert "stats" in data

    def test_chat_history_persists(self, client, clean_session):
        """Chat history is available after sending messages."""
        session = f"int-hist-{id(client)}"
        client.post("/api/chat", json={"message": "Hello", "session_id": session})
        client.post("/api/chat", json={"message": "What can you do?", "session_id": session})

        resp = client.get(f"/api/chat/history/{session}")
        assert resp.status_code == 200
        assert len(resp.json()["messages"]) >= 4  # 2 user + 2 assistant

    def test_chat_clear_works(self, client, clean_session):
        """Clearing chat session removes history."""
        session = f"int-clear-{id(client)}"
        client.post("/api/chat", json={"message": "Hello", "session_id": session})

        resp = client.delete(f"/api/chat/{session}")
        assert resp.status_code == 200
        assert resp.json()["cleared"] is True


class TestServiceCRUDLifecycle:
    """Service CRUD lifecycle: upload → analyze → add services → cost check."""

    @patch("service_builder.get_openai_client")
    def test_service_lifecycle(self, mock_openai, client, clean_session):
        """Add services, verify they appear in costs and questions."""
        # Setup
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = client.post(
            "/api/projects/proj-crud/diagrams",
            files={"file": ("crud.png", io.BytesIO(content), "image/png")},
        )
        diagram_id = resp.json()["diagram_id"]

        with patch("routers.diagrams.analyze_image", return_value=copy.deepcopy(MOCK_ANALYSIS)), \
             patch("routers.diagrams.classify_image", return_value={
                 "is_architecture_diagram": True, "confidence": 0.95
             }):
            client.post(f"/api/diagrams/{diagram_id}/analyze")

        # Add Redis
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "services": [
                {"name": "Redis", "full_name": "Azure Cache for Redis", "category": "Database"}
            ],
            "inferred_requirements": ["caching"]
        })
        mock_openai.return_value.chat.completions.create.return_value = mock_response

        resp = client.post(f"/api/diagrams/{diagram_id}/add-services", json={"text": "Add Redis cache"})
        assert resp.status_code == 200
        assert resp.json()["services_detected"] == 4  # 3 original + Redis

        # Cost estimate should now include 4 services
        resp = client.get(f"/api/diagrams/{diagram_id}/cost-estimate")
        assert resp.status_code == 200
        assert resp.json()["service_count"] == 4

        # Questions should reflect added services
        resp = client.post(f"/api/diagrams/{diagram_id}/questions?smart_dedup=true")
        assert resp.status_code == 200
        assert resp.json()["total"] > 0


class TestAdminDashboardDataIntegrity:
    """Admin dashboard data integrity checks."""

    def test_admin_metrics_structure(self, client, clean_session, monkeypatch):
        """Admin metrics have correct structure."""
        monkeypatch.setattr("admin_auth.ADMIN_SECRET", "test-admin-key")
        monkeypatch.setattr("admin_auth.JWT_SECRET", "test-admin-key:test-salt")
        resp = client.post("/api/admin/login", json={"key": "test-admin-key"})
        assert resp.status_code == 200
        token = resp.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Metrics
        resp = client.get("/api/admin/metrics", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "totals" in data
        assert "total_events" in data

        # Funnel
        resp = client.get("/api/admin/metrics/funnel", headers=headers)
        assert resp.status_code == 200
        assert "total_sessions" in resp.json()

        # Daily
        resp = client.get("/api/admin/metrics/daily?days=7", headers=headers)
        assert resp.status_code == 200
        assert "data" in resp.json()

        # Recent
        resp = client.get("/api/admin/metrics/recent?limit=10", headers=headers)
        assert resp.status_code == 200
        assert "events" in resp.json()

    def test_admin_audit_endpoint(self, client, clean_session, monkeypatch):
        """Admin audit endpoint returns audit log data."""
        monkeypatch.setattr("admin_auth.ADMIN_SECRET", "test-admin-key")
        monkeypatch.setattr("admin_auth.JWT_SECRET", "test-admin-key:test-salt")
        resp = client.post("/api/admin/login", json={"key": "test-admin-key"})
        token = resp.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.get("/api/admin/audit", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "logs" in data or "events" in data

    def test_admin_monitoring_endpoint(self, client, clean_session, monkeypatch):
        """Admin monitoring endpoint returns monitoring data."""
        monkeypatch.setattr("admin_auth.ADMIN_SECRET", "test-admin-key")
        monkeypatch.setattr("admin_auth.JWT_SECRET", "test-admin-key:test-salt")
        resp = client.post("/api/admin/login", json={"key": "test-admin-key"})
        token = resp.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.get("/api/admin/monitoring", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "overview" in data or "latency" in data
