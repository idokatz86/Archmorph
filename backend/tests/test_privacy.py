"""
Tests for GDPR / Privacy compliance routes (Issue #145).
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client for the Archmorph API."""
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from main import app
    return TestClient(app, raise_server_exceptions=False)


# ─────────────────────────────────────────────────────────────
# Legal Documents
# ─────────────────────────────────────────────────────────────
class TestLegalDocuments:
    def test_list_legal_documents(self, client):
        resp = client.get("/api/privacy/legal-documents")
        assert resp.status_code == 200
        data = resp.json()
        assert "documents" in data
        docs = data["documents"]
        assert len(docs) >= 5
        names = {d["document"] for d in docs}
        assert "privacy_policy" in names
        assert "terms_of_service" in names
        assert "cookie_policy" in names
        assert "ai_disclaimer" in names
        assert "data_processing_agreement" in names

    def test_list_legal_documents_structure(self, client):
        resp = client.get("/api/privacy/legal-documents")
        for doc in resp.json()["documents"]:
            assert "version" in doc
            assert "effective_date" in doc
            assert "last_updated" in doc
            assert "url" in doc

    def test_get_specific_legal_document(self, client):
        resp = client.get("/api/privacy/legal-documents/privacy_policy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["document"] == "privacy_policy"
        assert "version" in data

    def test_get_nonexistent_legal_document(self, client):
        resp = client.get("/api/privacy/legal-documents/nonexistent")
        assert resp.status_code == 404

    def test_get_terms_of_service(self, client):
        resp = client.get("/api/privacy/legal-documents/terms_of_service")
        assert resp.status_code == 200
        assert resp.json()["document"] == "terms_of_service"

    def test_get_cookie_policy(self, client):
        resp = client.get("/api/privacy/legal-documents/cookie_policy")
        assert resp.status_code == 200
        assert resp.json()["document"] == "cookie_policy"

    def test_get_ai_disclaimer(self, client):
        resp = client.get("/api/privacy/legal-documents/ai_disclaimer")
        assert resp.status_code == 200
        assert resp.json()["document"] == "ai_disclaimer"

    def test_get_dpa(self, client):
        resp = client.get("/api/privacy/legal-documents/data_processing_agreement")
        assert resp.status_code == 200
        assert resp.json()["document"] == "data_processing_agreement"


# ─────────────────────────────────────────────────────────────
# Cookie Consent
# ─────────────────────────────────────────────────────────────
class TestCookieConsent:
    def test_save_consent_default(self, client):
        resp = client.post("/api/privacy/consent", json={
            "consent": {"necessary": True, "analytics": False, "marketing": False, "functional": False},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "saved"
        assert data["consent"]["necessary"] is True
        assert "session_id" in data

    def test_save_consent_with_session_id(self, client):
        resp = client.post("/api/privacy/consent", json={
            "consent": {"necessary": True, "analytics": True},
            "session_id": "test-session-123",
        })
        assert resp.status_code == 200
        assert resp.json()["session_id"] == "test-session-123"

    def test_save_consent_necessary_forced_true(self, client):
        """Necessary cookies cannot be opted out of."""
        resp = client.post("/api/privacy/consent", json={
            "consent": {"necessary": False, "analytics": True},
        })
        assert resp.status_code == 200
        assert resp.json()["consent"]["necessary"] is True

    def test_get_consent_saved(self, client):
        # Save first
        client.post("/api/privacy/consent", json={
            "consent": {"analytics": True, "marketing": True},
            "session_id": "get-test-sess",
        })
        # Retrieve
        resp = client.get("/api/privacy/consent/get-test-sess")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "saved"
        assert data["consent"]["analytics"] is True

    def test_get_consent_default(self, client):
        resp = client.get("/api/privacy/consent/nonexistent-session")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "default"
        assert data["consent"]["necessary"] is True
        assert data["consent"]["analytics"] is False

    def test_consent_has_timestamp(self, client):
        resp = client.post("/api/privacy/consent", json={
            "consent": {"analytics": True},
            "session_id": "ts-test",
        })
        assert "recorded_at" in resp.json()


# ─────────────────────────────────────────────────────────────
# DSAR (Data Subject Access Request)
# ─────────────────────────────────────────────────────────────
class TestDSAR:
    def test_submit_dsar_export(self, client):
        resp = client.post("/api/privacy/dsar", json={
            "email": "user@example.com",
            "request_type": "export",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["request_type"] == "export"
        assert "request_id" in data
        assert "30 days" in data["message"]

    def test_submit_dsar_deletion(self, client):
        resp = client.post("/api/privacy/dsar", json={
            "email": "user@example.com",
            "request_type": "deletion",
        })
        assert resp.status_code == 200
        assert resp.json()["request_type"] == "deletion"

    def test_submit_dsar_with_reason(self, client):
        resp = client.post("/api/privacy/dsar", json={
            "email": "user@example.com",
            "request_type": "export",
            "reason": "I want a copy of my data",
        })
        assert resp.status_code == 200

    def test_submit_dsar_invalid_type(self, client):
        resp = client.post("/api/privacy/dsar", json={
            "email": "user@example.com",
            "request_type": "invalid",
        })
        assert resp.status_code == 422

    def test_submit_dsar_missing_email(self, client):
        resp = client.post("/api/privacy/dsar", json={
            "request_type": "export",
        })
        assert resp.status_code == 422

    def test_get_dsar_status(self, client):
        # Submit first
        submit = client.post("/api/privacy/dsar", json={
            "email": "track@example.com",
            "request_type": "export",
        })
        request_id = submit.json()["request_id"]

        # Check status
        resp = client.get(f"/api/privacy/dsar/{request_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["request_id"] == request_id
        assert data["status"] == "pending"

    def test_get_dsar_status_not_found(self, client):
        resp = client.get("/api/privacy/dsar/nonexistent-id")
        assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────
# Data Deletion
# ─────────────────────────────────────────────────────────────
class TestDataDeletion:
    def test_delete_data_confirmed(self, client):
        resp = client.post("/api/privacy/delete", json={
            "email": "delete@example.com",
            "confirm": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert "request_id" in data

    def test_delete_data_not_confirmed(self, client):
        resp = client.post("/api/privacy/delete", json={
            "email": "delete@example.com",
            "confirm": False,
        })
        assert resp.status_code == 400

    def test_delete_data_with_reason(self, client):
        resp = client.post("/api/privacy/delete", json={
            "email": "delete@example.com",
            "confirm": True,
            "reason": "Moving to competitor",
        })
        assert resp.status_code == 200

    def test_delete_data_missing_email(self, client):
        resp = client.post("/api/privacy/delete", json={
            "confirm": True,
        })
        assert resp.status_code == 422

    def test_delete_data_missing_confirm(self, client):
        resp = client.post("/api/privacy/delete", json={
            "email": "delete@example.com",
        })
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────
# Data Practices
# ─────────────────────────────────────────────────────────────
class TestDataPractices:
    def test_get_data_practices(self, client):
        resp = client.get("/api/privacy/data-practices")
        assert resp.status_code == 200
        data = resp.json()
        assert "controller" in data
        assert "data_categories" in data
        assert "rights" in data
        assert "data_transfers" in data
        assert "automated_decisions" in data

    def test_data_practices_has_required_fields(self, client):
        data = client.get("/api/privacy/data-practices").json()
        assert data["dpo_contact"] is not None
        assert len(data["data_categories"]) >= 3
        assert len(data["rights"]) >= 6

    def test_data_practices_categories_structure(self, client):
        data = client.get("/api/privacy/data-practices").json()
        for cat in data["data_categories"]:
            assert "category" in cat
            assert "purpose" in cat
            assert "legal_basis" in cat
            assert "retention" in cat

    def test_data_practices_automated_decisions(self, client):
        data = client.get("/api/privacy/data-practices").json()
        ad = data["automated_decisions"]
        assert ad["present"] is True
        assert "human_oversight" in ad

    def test_data_practices_transfer_safeguards(self, client):
        data = client.get("/api/privacy/data-practices").json()
        assert "safeguards" in data["data_transfers"]
