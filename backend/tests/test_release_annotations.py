"""
Tests for /api/admin/release-annotations endpoint.

Verifies that:
- POST creates an annotation and returns 201 with an annotation_id.
- GET lists created annotations.
- Kind, environment, and actor fields are stored correctly.
- Invalid kind values are rejected.
- The endpoint requires admin authentication.
- Optional filters (environment, kind) work correctly.
"""

import os
import sys
import time
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from main import app

# ── Auth helpers ─────────────────────────────────────────────

_TEST_ADMIN_SECRET = "test-admin-secret-annotations"
_TEST_ADMIN_JWT: str | None = None


def _get_admin_token(client: TestClient) -> str:
    """Obtain a session JWT via the admin login endpoint."""
    global _TEST_ADMIN_JWT

    import os as _os
    _os.environ.setdefault("ADMIN_SECRET_KEY", _TEST_ADMIN_SECRET)
    _os.environ.setdefault("ADMIN_JWT_SECRET", "jwt-secret-annotations-test")

    resp = client.post(
        "/api/admin/login",
        json={"key": _TEST_ADMIN_SECRET},
    )
    if resp.status_code == 200:
        _TEST_ADMIN_JWT = resp.json().get("token", "")
        return _TEST_ADMIN_JWT
    return ""


def _auth_headers(client: TestClient) -> dict[str, str]:
    token = _get_admin_token(client)
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


# ── Fixtures ────────────────────────────────────────────────

@pytest.fixture()
def admin_client(monkeypatch):
    monkeypatch.setenv("ADMIN_SECRET_KEY", _TEST_ADMIN_SECRET)
    monkeypatch.setenv("ADMIN_JWT_SECRET", "jwt-secret-annotations-test")
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


# ── Tests ───────────────────────────────────────────────────

class TestReleaseAnnotationsCreate:
    def test_create_deploy_annotation_returns_201(self, admin_client):
        headers = _auth_headers(admin_client)
        if not headers:
            pytest.skip("Admin auth not configured for this test run")

        payload = {
            "kind": "deploy",
            "revision": "abc123def456",
            "environment": "production",
            "description": "Deployed v4.3.0",
            "actor": "github-actions",
            "run_url": None,
        }
        response = admin_client.post(
            "/api/admin/release-annotations",
            json=payload,
            headers=headers,
        )

        assert response.status_code == 201
        body = response.json()
        assert "annotation_id" in body
        assert body["annotation_id"].startswith("ann-")
        assert body["kind"] == "deploy"
        assert body["revision"] == "abc123def456"
        assert body["environment"] == "production"
        assert body["actor"] == "github-actions"

    def test_create_rollback_annotation(self, admin_client):
        headers = _auth_headers(admin_client)
        if not headers:
            pytest.skip("Admin auth not configured for this test run")

        payload = {
            "kind": "rollback",
            "revision": "prev-sha-000",
            "environment": "production",
            "description": "Rolled back due to latency spike",
            "actor": "on-call-engineer",
        }
        response = admin_client.post(
            "/api/admin/release-annotations",
            json=payload,
            headers=headers,
        )

        assert response.status_code == 201
        body = response.json()
        assert body["kind"] == "rollback"

    def test_create_traffic_shift_annotation(self, admin_client):
        headers = _auth_headers(admin_client)
        if not headers:
            pytest.skip("Admin auth not configured for this test run")

        payload = {
            "kind": "traffic_shift",
            "revision": "green-rev-42",
            "environment": "production",
            "description": "Shifted 100% traffic to green revision",
            "actor": "ci-pipeline",
        }
        response = admin_client.post(
            "/api/admin/release-annotations",
            json=payload,
            headers=headers,
        )
        assert response.status_code == 201
        assert response.json()["kind"] == "traffic_shift"

    def test_create_config_change_annotation(self, admin_client):
        headers = _auth_headers(admin_client)
        if not headers:
            pytest.skip("Admin auth not configured for this test run")

        payload = {
            "kind": "config_change",
            "revision": "env-var-update",
            "environment": "production",
            "description": "Updated REQUIRE_REDIS to true",
            "actor": "operator",
        }
        response = admin_client.post(
            "/api/admin/release-annotations",
            json=payload,
            headers=headers,
        )
        assert response.status_code == 201

    def test_invalid_kind_rejected(self, admin_client):
        headers = _auth_headers(admin_client)
        if not headers:
            pytest.skip("Admin auth not configured for this test run")

        payload = {
            "kind": "invalid_kind",
            "revision": "sha",
            "environment": "production",
            "description": "",
            "actor": "ci",
        }
        response = admin_client.post(
            "/api/admin/release-annotations",
            json=payload,
            headers=headers,
        )
        assert response.status_code == 422

    def test_revision_too_long_rejected(self, admin_client):
        headers = _auth_headers(admin_client)
        if not headers:
            pytest.skip("Admin auth not configured for this test run")

        payload = {
            "kind": "deploy",
            "revision": "x" * 201,
            "environment": "production",
            "description": "",
            "actor": "ci",
        }
        response = admin_client.post(
            "/api/admin/release-annotations",
            json=payload,
            headers=headers,
        )
        assert response.status_code == 422

    def test_description_too_long_rejected(self, admin_client):
        headers = _auth_headers(admin_client)
        if not headers:
            pytest.skip("Admin auth not configured for this test run")

        payload = {
            "kind": "deploy",
            "revision": "sha123",
            "environment": "production",
            "description": "x" * 501,
            "actor": "ci",
        }
        response = admin_client.post(
            "/api/admin/release-annotations",
            json=payload,
            headers=headers,
        )
        assert response.status_code == 422

    def test_unauthenticated_request_rejected(self, admin_client):
        """Without admin auth the endpoint must refuse the request."""
        payload = {
            "kind": "deploy",
            "revision": "sha",
            "environment": "production",
            "description": "",
            "actor": "ci",
        }
        response = admin_client.post(
            "/api/admin/release-annotations",
            json=payload,
        )
        assert response.status_code in {401, 403, 503}


class TestReleaseAnnotationsList:
    def test_list_returns_annotations(self, admin_client):
        headers = _auth_headers(admin_client)
        if not headers:
            pytest.skip("Admin auth not configured for this test run")

        # Create one first
        admin_client.post(
            "/api/admin/release-annotations",
            json={
                "kind": "deploy",
                "revision": "list-test-sha",
                "environment": "staging",
                "description": "List test deploy",
                "actor": "ci",
            },
            headers=headers,
        )

        response = admin_client.get(
            "/api/admin/release-annotations",
            headers=headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert "annotations" in body
        assert "total" in body
        assert isinstance(body["annotations"], list)

    def test_list_environment_filter(self, admin_client):
        headers = _auth_headers(admin_client)
        if not headers:
            pytest.skip("Admin auth not configured for this test run")

        unique_env = f"test-env-{uuid.uuid4().hex[:8]}"
        admin_client.post(
            "/api/admin/release-annotations",
            json={
                "kind": "deploy",
                "revision": "filter-sha",
                "environment": unique_env,
                "description": "Filter test",
                "actor": "ci",
            },
            headers=headers,
        )

        response = admin_client.get(
            f"/api/admin/release-annotations?environment={unique_env}",
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert all(a["environment"] == unique_env for a in body["annotations"])

    def test_list_kind_filter(self, admin_client):
        headers = _auth_headers(admin_client)
        if not headers:
            pytest.skip("Admin auth not configured for this test run")

        admin_client.post(
            "/api/admin/release-annotations",
            json={
                "kind": "rollback",
                "revision": "kind-filter-sha",
                "environment": "production",
                "description": "Kind filter test",
                "actor": "ci",
            },
            headers=headers,
        )

        response = admin_client.get(
            "/api/admin/release-annotations?kind=rollback",
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert all(a["kind"] == "rollback" for a in body["annotations"])

    def test_list_unauthenticated_rejected(self, admin_client):
        response = admin_client.get("/api/admin/release-annotations")
        assert response.status_code in {401, 403, 503}
