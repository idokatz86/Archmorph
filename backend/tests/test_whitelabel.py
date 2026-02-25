"""Tests for whitelabel module (#281)."""
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from whitelabel import router, DEFAULT_BRANDING


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestWhitelabelDefaults:
    def test_default_branding_exists(self):
        assert "product_name" in DEFAULT_BRANDING
        assert "tagline" in DEFAULT_BRANDING

    def test_get_default_config(self, client):
        resp = client.get("/whitelabel/default-config")
        assert resp.status_code == 200
        data = resp.json()
        assert "branding" in data
        assert "product_name" in data["branding"]


class TestPartnerRegistration:
    def test_register_partner(self, client):
        resp = client.post("/whitelabel/partners", json={
            "partner_name": "TestCo",
            "contact_email": "test@example.com",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "partner_id" in data
        assert "api_key" in data

    def test_list_partners(self, client):
        resp = client.get("/whitelabel/partners")
        assert resp.status_code == 200
        data = resp.json()
        assert "partners" in data


class TestBrandingConfig:
    def test_get_branding_unknown_partner(self, client):
        resp = client.get("/whitelabel/config/nonexistent")
        # Returns default branding for unknown partners
        assert resp.status_code in (200, 404)
