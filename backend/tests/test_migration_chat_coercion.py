"""Regression test for React error #31 on the migration-chat endpoint.

Mirrors the iac-chat fix (#623). When the LLM returns ``related_services``
as objects (e.g. ``[{"type": "azure", "message": "Azure SQL"}]``) instead
of strings, the API boundary must flatten them to strings so the frontend
can render the badges without crashing.
"""
from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def analyzed_diagram(client):
    from main import SESSION_STORE, IMAGE_STORE
    SESSION_STORE.clear()
    IMAGE_STORE.clear()

    content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    resp = client.post(
        "/api/projects/proj-mchat/diagrams",
        files={"file": ("arch.png", io.BytesIO(content), "image/png")},
    )
    diagram_id = resp.json()["diagram_id"]

    mock_analysis = {
        "diagram_type": "Test", "source_provider": "aws", "target_provider": "azure",
        "architecture_patterns": [], "services_detected": 1,
        "zones": [{"id": 1, "name": "Web", "number": 1, "services": [
            {"aws": "RDS", "azure": "Azure SQL", "confidence": 0.9},
        ]}],
        "mappings": [{"source_service": "RDS", "source_provider": "aws",
                      "azure_service": "Azure SQL", "confidence": 0.9}],
        "warnings": [],
        "confidence_summary": {"high": 1, "medium": 0, "low": 0, "average": 0.9},
    }
    with patch("routers.diagrams.analyze_image", return_value=mock_analysis):
        client.post(f"/api/diagrams/{diagram_id}/analyze")

    yield diagram_id
    SESSION_STORE.clear()
    IMAGE_STORE.clear()


def _make_completion(payload: dict) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = json.dumps(payload)
    response.choices[0].finish_reason = "stop"
    return response


class TestMigrationChatCoercion:
    @patch("openai_client.get_openai_client")
    def test_object_related_services_are_flattened(
        self, mock_get_client, client, analyzed_diagram
    ):
        # Simulate the misbehaving model response that triggered React #31.
        bad_payload = {
            "reply": "You should consider Azure SQL and Cosmos DB.",
            "related_services": [
                {"type": "database", "message": "Azure SQL"},
                {"name": "Cosmos DB"},
                "Azure Cache for Redis",
            ],
        }
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_completion(bad_payload)
        mock_get_client.return_value = mock_client

        resp = client.post(
            f"/api/diagrams/{analyzed_diagram}/migration-chat",
            json={"message": "What database should I use?"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Every item must be a string — never an object — so the frontend
        # cannot crash with React error #31.
        assert all(isinstance(s, str) for s in body["related_services"]), body
        assert body["related_services"] == [
            "Azure SQL",
            "Cosmos DB",
            "Azure Cache for Redis",
        ]

    @patch("openai_client.get_openai_client")
    def test_string_related_services_pass_through(
        self, mock_get_client, client, analyzed_diagram
    ):
        good_payload = {
            "reply": "Use Azure SQL.",
            "related_services": ["Azure SQL", "Azure Cache for Redis"],
        }
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_completion(good_payload)
        mock_get_client.return_value = mock_client

        resp = client.post(
            f"/api/diagrams/{analyzed_diagram}/migration-chat",
            json={"message": "What database should I use?"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["related_services"] == ["Azure SQL", "Azure Cache for Redis"]
