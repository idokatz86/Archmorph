"""
Archmorph — Legal Router Unit Tests
Tests for routers/legal.py (Issue #108)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient


# ────────────────────────────────────────────────────────────────────
# App fixture — minimal FastAPI app with legal router
# ────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def client():
    from fastapi import FastAPI
    from routers.legal import router as legal_router

    app = FastAPI()
    app.include_router(legal_router)
    return TestClient(app)


# ====================================================================
# GET /api/legal/terms
# ====================================================================

class TestTermsEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/api/legal/terms")
        assert resp.status_code == 200

    def test_returns_sections(self, client):
        data = client.get("/api/legal/terms").json()
        assert "sections" in data or "terms" in data or "content" in data


# ====================================================================
# GET /api/legal/privacy
# ====================================================================

class TestPrivacyEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/api/legal/privacy")
        assert resp.status_code == 200

    def test_returns_content(self, client):
        data = client.get("/api/legal/privacy").json()
        assert len(data) > 0


# ====================================================================
# GET /api/legal/ai-disclaimer
# ====================================================================

class TestAIDisclaimerEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/api/legal/ai-disclaimer")
        assert resp.status_code == 200


# ====================================================================
# GET /api/legal/cookies
# ====================================================================

class TestCookiesEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/api/legal/cookies")
        assert resp.status_code == 200

    def test_returns_categories(self, client):
        data = client.get("/api/legal/cookies").json()
        assert "categories" in data or isinstance(data, list) or len(data) > 0


# ====================================================================
# POST /api/legal/cookies/consent
# ====================================================================

class TestCookieConsent:
    def test_post_consent(self, client):
        resp = client.post("/api/legal/cookies/consent", json={
            "user_id": "test-user-001",
            "necessary": True,
            "analytics": True,
            "preferences": False,
        })
        assert resp.status_code in (200, 201)

    def test_get_consent(self, client):
        # First save consent
        client.post("/api/legal/cookies/consent", json={
            "user_id": "test-user-002",
            "necessary": True,
            "analytics": False,
            "preferences": False,
        })
        resp = client.get("/api/legal/cookies/consent/test-user-002")
        assert resp.status_code in (200, 404)


# ====================================================================
# POST /api/legal/data-deletion (GDPR)
# ====================================================================

class TestDataDeletion:
    def test_submit_request(self, client):
        resp = client.post("/api/legal/data-deletion", json={
            "user_id": "gdpr-test-001",
            "email": "gdpr@test.com",
            "reason": "Right to erasure",
        })
        assert resp.status_code in (200, 201, 202)

    def test_returns_request_id(self, client):
        resp = client.post("/api/legal/data-deletion", json={
            "user_id": "gdpr-test-002",
            "email": "gdpr2@test.com",
        })
        data = resp.json()
        assert "request_id" in data or "id" in data or "status" in data
