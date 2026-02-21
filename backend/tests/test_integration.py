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
