"""
End-to-End Local Tests for Archmorph Backend.

Simulates the complete user journey using the FastAPI TestClient:
  Upload → Analyze → Questions → Apply Answers → HLD → IaC → Cost → Export

These tests verify the full pipeline without external dependencies.
"""

import copy
import io
import json
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
    "architecture_patterns": ["multi-AZ", "serverless", "event-driven"],
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


def _upload_and_analyze(client):
    """Helper: upload + analyze, returns diagram_id."""
    content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    resp = client.post(
        "/api/projects/proj-e2e/diagrams",
        files={"file": ("e2e.png", io.BytesIO(content), "image/png")},
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


class TestE2EFullPipeline:
    """End-to-end: upload → analyze → questions → apply → HLD → IaC → cost → export."""

    def test_complete_aws_to_azure_pipeline(self, client, clean_session):
        """Full pipeline from upload to export."""
        # Step 1: Upload & Analyze
        diagram_id = _upload_and_analyze(client)

        # Step 2: Get guided questions
        resp = client.post(f"/api/diagrams/{diagram_id}/questions?smart_dedup=true")
        assert resp.status_code == 200
        q_data = resp.json()
        assert q_data["total"] > 0
        assert "questions" in q_data

        # Step 3: Apply answers
        resp = client.post(
            f"/api/diagrams/{diagram_id}/apply-answers",
            json={"environment": "production", "ha_dr": "active_active"},
        )
        assert resp.status_code == 200

        # Step 4: Generate HLD
        with patch("routers.diagrams.generate_hld") as mock_hld:
            mock_hld.return_value = {
                "title": "E2E Test HLD",
                "services": [
                    {"azure_service": "Azure Functions", "source_service": "Lambda", "justification": "Serverless compute"},
                ],
                "executive_summary": "Migration plan for e2e test.",
                "architecture_overview": {"description": "Serverless architecture"},
            }
            resp = client.post(f"/api/diagrams/{diagram_id}/generate-hld")
        assert resp.status_code == 200
        assert resp.json()["hld"]["title"] == "E2E Test HLD"

        # Step 5: Retrieve cached HLD
        resp = client.get(f"/api/diagrams/{diagram_id}/hld")
        assert resp.status_code == 200

        # Step 6: Generate IaC (Terraform)
        resp = client.post(f"/api/diagrams/{diagram_id}/generate?format=terraform")
        assert resp.status_code == 200
        iac = resp.json()
        assert "code" in iac
        assert "resource" in iac["code"] or "provider" in iac["code"]

        # Step 7: Cost estimate
        resp = client.get(f"/api/diagrams/{diagram_id}/cost-estimate")
        assert resp.status_code == 200
        cost = resp.json()
        assert cost["currency"] == "USD"
        assert cost["service_count"] > 0

        # Step 8: Export diagram
        resp = client.post(f"/api/diagrams/{diagram_id}/export-diagram?format=drawio")
        assert resp.status_code == 200
        assert resp.json()["format"] == "drawio"

    def test_sample_e2e_pipeline(self, client, clean_session):
        """Sample diagrams go through the same pipeline without AI calls."""
        # Analyze sample
        resp = client.post("/api/samples/aws-iaas/analyze")
        assert resp.status_code == 200
        diagram_id = resp.json()["diagram_id"]

        # Questions
        resp = client.post(f"/api/diagrams/{diagram_id}/questions")
        assert resp.status_code == 200
        assert resp.json()["total"] > 0

        # Apply answers
        resp = client.post(
            f"/api/diagrams/{diagram_id}/apply-answers",
            json={"answers": {}},
        )
        assert resp.status_code == 200

        # Cost estimate
        resp = client.get(f"/api/diagrams/{diagram_id}/cost-estimate")
        assert resp.status_code == 200
        assert resp.json()["service_count"] > 0

        # IaC generation
        resp = client.post(f"/api/diagrams/{diagram_id}/generate?format=terraform")
        assert resp.status_code == 200

        # Export diagram
        resp = client.post(f"/api/diagrams/{diagram_id}/export-diagram?format=excalidraw")
        assert resp.status_code == 200

    def test_migration_assessment_e2e(self, client, clean_session):
        """Migration assessment works after analysis."""
        diagram_id = _upload_and_analyze(client)

        resp = client.get(f"/api/diagrams/{diagram_id}/migration-assessment")
        assert resp.status_code == 200
        data = resp.json()
        assert "overall_score" in data
        assert "risk_level" in data

    def test_best_practices_e2e(self, client, clean_session):
        """Best practices available after analysis."""
        diagram_id = _upload_and_analyze(client)

        resp = client.get(f"/api/diagrams/{diagram_id}/best-practices")
        assert resp.status_code == 200
        data = resp.json()
        assert "recommendations" in data

    def test_cost_comparison_e2e(self, client, clean_session):
        """Cost comparison across providers after analysis."""
        diagram_id = _upload_and_analyze(client)

        resp = client.get(f"/api/diagrams/{diagram_id}/cost-comparison")
        assert resp.status_code == 200
        data = resp.json()
        assert "providers" in data
        assert "aws" in data["providers"]
        assert "azure" in data["providers"]

    def test_share_link_e2e(self, client, clean_session):
        """Share link creation and retrieval."""
        diagram_id = _upload_and_analyze(client)

        # Create share
        resp = client.post(f"/api/diagrams/{diagram_id}/share")
        assert resp.status_code == 200
        share_id = resp.json()["share_id"]

        # Retrieve share
        resp = client.get(f"/api/shared/{share_id}")
        assert resp.status_code == 200
        assert resp.json()["read_only"] is True


class TestE2EErrorPaths:
    """End-to-end error path validation."""

    def test_analyze_without_upload_404(self, client, clean_session):
        resp = client.post("/api/diagrams/nonexistent-id/analyze")
        assert resp.status_code == 404

    def test_questions_without_analysis_404(self, client, clean_session):
        resp = client.post("/api/diagrams/nonexistent-id/questions")
        assert resp.status_code == 404

    def test_cost_without_analysis_returns_gracefully(self, client, clean_session):
        resp = client.get("/api/diagrams/nonexistent-id/cost-estimate")
        # Cost estimate gracefully returns 200 with zero services for unknown diagrams
        assert resp.status_code in (200, 404)

    def test_export_without_analysis_404(self, client, clean_session):
        resp = client.post("/api/diagrams/nonexistent-id/export-diagram?format=drawio")
        assert resp.status_code == 404

    def test_share_without_analysis_404(self, client, clean_session):
        resp = client.post("/api/diagrams/nonexistent-id/share")
        assert resp.status_code == 404


class TestE2EMultiDiagram:
    """E2E: multiple diagrams don't interfere."""

    def test_two_diagrams_independent(self, client, clean_session):
        """Two diagrams analyzed separately have independent sessions."""
        d1 = _upload_and_analyze(client)
        d2 = _upload_and_analyze(client)

        assert d1 != d2

        # Both have cost estimates
        r1 = client.get(f"/api/diagrams/{d1}/cost-estimate")
        r2 = client.get(f"/api/diagrams/{d2}/cost-estimate")
        assert r1.status_code == 200
        assert r2.status_code == 200

        # Both have questions
        r1 = client.post(f"/api/diagrams/{d1}/questions")
        r2 = client.post(f"/api/diagrams/{d2}/questions")
        assert r1.status_code == 200
        assert r2.status_code == 200
