"""Route tests for architect review queue endpoints (#1137)."""

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from main import app
from routers.shared import SESSION_STORE


@pytest.fixture(autouse=True)
def clean_review_queue_sessions():
    SESSION_STORE.clear()
    yield
    SESSION_STORE.clear()


def _seed_session(diagram_id="diag-review-routes", *, owner_user_id="user-a", tenant_id="tenant-a"):
    session = {
        "diagram_id": diagram_id,
        "_owner_user_id": owner_user_id,
        "_tenant_id": tenant_id,
        "mappings": [
            {"source_service": "MysterySvc", "azure_service": "ReviewTarget", "confidence": 0.42},
        ],
        "warnings": ["Encryption at rest is not configured."],
        "assumptions": [
            {"id": "ha", "question": "Is high availability required?", "assumed_answer": "Yes"},
        ],
    }
    SESSION_STORE[diagram_id] = session
    return session


def test_review_queue_returns_items_and_summary(tenant_a, tenant_a_auth_headers):
    diagram_id = "diag-review-list"

    with TestClient(app, raise_server_exceptions=False) as client:
        _seed_session(diagram_id, owner_user_id=tenant_a["user_id"], tenant_id=tenant_a["tenant_id"])
        response = client.get(f"/api/diagrams/{diagram_id}/review-queue", headers=tenant_a_auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["diagram_id"] == diagram_id
    assert data["summary"]["total"] >= 2
    assert any(item["bucket"] == "low_confidence" for item in data["items"])


def test_review_queue_summary_uses_user_session_auth(tenant_a, tenant_a_auth_headers):
    diagram_id = "diag-review-summary"

    with TestClient(app, raise_server_exceptions=False) as client:
        _seed_session(diagram_id, owner_user_id=tenant_a["user_id"], tenant_id=tenant_a["tenant_id"])
        response = client.get(f"/api/diagrams/{diagram_id}/review-queue/summary", headers=tenant_a_auth_headers)

    assert response.status_code == 200
    assert response.json()["summary"]["gated"] is True


def test_review_queue_tolerates_malformed_dispositions(tenant_a, tenant_a_auth_headers):
    diagram_id = "diag-review-malformed-dispositions"

    with TestClient(app, raise_server_exceptions=False) as client:
        session = _seed_session(diagram_id, owner_user_id=tenant_a["user_id"], tenant_id=tenant_a["tenant_id"])
        session["review_queue_dispositions"] = ["not", "a", "dict"]
        response = client.get(f"/api/diagrams/{diagram_id}/review-queue", headers=tenant_a_auth_headers)

    assert response.status_code == 200
    assert response.json()["summary"]["unresolved"] > 0


def test_review_queue_disposition_persists_and_marks_risk(tenant_a, tenant_a_auth_headers):
    diagram_id = "diag-review-disposition"

    with TestClient(app, raise_server_exceptions=False) as client:
        _seed_session(diagram_id, owner_user_id=tenant_a["user_id"], tenant_id=tenant_a["tenant_id"])
        queue_response = client.get(f"/api/diagrams/{diagram_id}/review-queue", headers=tenant_a_auth_headers)
        assert queue_response.status_code == 200
        item_id = queue_response.json()["items"][0]["id"]
        response = client.post(
            f"/api/diagrams/{diagram_id}/review-queue/{item_id}/disposition",
            json={"action": "mark_risk", "edited_text": "Accepted as an explicit migration risk."},
            headers=tenant_a_auth_headers,
        )

    assert response.status_code == 200
    session = SESSION_STORE[diagram_id]
    assert session["review_queue_dispositions"][item_id]["action"] == "mark_risk"
    assert any(item["id"] == item_id for item in session.get("risk_annotations", []))


def test_review_queue_disposition_replaces_malformed_dispositions(tenant_a, tenant_a_auth_headers):
    diagram_id = "diag-review-replace-malformed-dispositions"

    with TestClient(app, raise_server_exceptions=False) as client:
        session = _seed_session(diagram_id, owner_user_id=tenant_a["user_id"], tenant_id=tenant_a["tenant_id"])
        session["review_queue_dispositions"] = "not-a-dict"
        queue_response = client.get(f"/api/diagrams/{diagram_id}/review-queue", headers=tenant_a_auth_headers)
        assert queue_response.status_code == 200
        item_id = queue_response.json()["items"][0]["id"]
        response = client.post(
            f"/api/diagrams/{diagram_id}/review-queue/{item_id}/disposition",
            json={"action": "accept"},
            headers=tenant_a_auth_headers,
        )

    assert response.status_code == 200
    assert SESSION_STORE[diagram_id]["review_queue_dispositions"][item_id]["action"] == "accept"


def test_review_queue_rejects_cross_tenant_access(tenant_a, tenant_a_auth_headers, tenant_b_auth_headers):
    diagram_id = "diag-review-cross-tenant"

    with TestClient(app, raise_server_exceptions=False) as client:
        _seed_session(diagram_id, owner_user_id=tenant_a["user_id"], tenant_id=tenant_a["tenant_id"])
        allowed = client.get(f"/api/diagrams/{diagram_id}/review-queue", headers=tenant_a_auth_headers)
        denied = client.get(f"/api/diagrams/{diagram_id}/review-queue", headers=tenant_b_auth_headers)

    assert allowed.status_code == 200
    assert denied.status_code in (403, 404)


def test_review_queue_invalid_action_returns_422(tenant_a, tenant_a_auth_headers):
    diagram_id = "diag-review-invalid-action"

    with TestClient(app, raise_server_exceptions=False) as client:
        _seed_session(diagram_id, owner_user_id=tenant_a["user_id"], tenant_id=tenant_a["tenant_id"])
        queue_response = client.get(f"/api/diagrams/{diagram_id}/review-queue", headers=tenant_a_auth_headers)
        assert queue_response.status_code == 200
        item_id = queue_response.json()["items"][0]["id"]
        response = client.post(
            f"/api/diagrams/{diagram_id}/review-queue/{item_id}/disposition",
            json={"action": "not-real"},
            headers=tenant_a_auth_headers,
        )

    assert response.status_code == 422
