"""Tests for admin_auth module — JWT-based admin session management."""

import pytest


class TestAdminAuth:
    """Unit tests for admin_auth functions."""

    def test_is_configured_false(self, monkeypatch):
        import admin_auth
        monkeypatch.setattr(admin_auth, "ADMIN_SECRET", "")
        assert admin_auth.is_configured() is False

    def test_is_configured_true(self, monkeypatch):
        import admin_auth
        monkeypatch.setattr(admin_auth, "ADMIN_SECRET", "some-key")
        assert admin_auth.is_configured() is True

    def test_verify_admin_secret_correct(self, monkeypatch):
        import admin_auth
        monkeypatch.setattr(admin_auth, "ADMIN_SECRET", "my-secret")
        assert admin_auth.verify_admin_secret("my-secret") is True

    def test_verify_admin_secret_wrong(self, monkeypatch):
        import admin_auth
        monkeypatch.setattr(admin_auth, "ADMIN_SECRET", "my-secret")
        assert admin_auth.verify_admin_secret("wrong") is False

    def test_verify_admin_secret_empty_config(self, monkeypatch):
        import admin_auth
        monkeypatch.setattr(admin_auth, "ADMIN_SECRET", "")
        assert admin_auth.verify_admin_secret("anything") is False

    def test_create_and_validate_token(self, monkeypatch):
        import admin_auth
        monkeypatch.setattr(admin_auth, "ADMIN_SECRET", "test-key")
        monkeypatch.setattr(admin_auth, "JWT_SECRET", "test-key:salt")

        token = admin_auth.create_session_token()
        assert isinstance(token, str)
        assert len(token) > 10

        payload = admin_auth.validate_session_token(token)
        assert payload is not None
        assert payload["sub"] == "admin"
        assert "jti" in payload

    def test_validate_invalid_token(self, monkeypatch):
        import admin_auth
        monkeypatch.setattr(admin_auth, "ADMIN_SECRET", "test-key")
        monkeypatch.setattr(admin_auth, "JWT_SECRET", "test-key:salt")

        result = admin_auth.validate_session_token("garbage.token.here")
        assert result is None

    def test_validate_empty_secret(self, monkeypatch):
        import admin_auth
        monkeypatch.setattr(admin_auth, "JWT_SECRET", "")

        result = admin_auth.validate_session_token("any-token")
        assert result is None

    def test_revoke_token(self, monkeypatch):
        import admin_auth
        monkeypatch.setattr(admin_auth, "ADMIN_SECRET", "test-key")
        monkeypatch.setattr(admin_auth, "JWT_SECRET", "test-key:salt")
        # Reset revocation set
        admin_auth._revoked_tokens.clear()

        token = admin_auth.create_session_token()
        # Token should be valid
        assert admin_auth.validate_session_token(token) is not None

        # Revoke it
        assert admin_auth.revoke_token(token) is True

        # Token should now be invalid
        assert admin_auth.validate_session_token(token) is None

    def test_revoke_invalid_token(self, monkeypatch):
        import admin_auth
        monkeypatch.setattr(admin_auth, "ADMIN_SECRET", "test-key")
        monkeypatch.setattr(admin_auth, "JWT_SECRET", "test-key:salt")

        result = admin_auth.revoke_token("not-a-valid-jwt")
        assert result is False

    def test_expired_token(self, monkeypatch):
        import admin_auth
        from datetime import datetime, timezone, timedelta
        import jwt

        monkeypatch.setattr(admin_auth, "ADMIN_SECRET", "test-key")
        monkeypatch.setattr(admin_auth, "JWT_SECRET", "test-key:salt")

        # Create a token that expired 10 minutes ago
        now = datetime.now(timezone.utc)
        payload = {
            "sub": "admin",
            "iat": now - timedelta(minutes=70),
            "exp": now - timedelta(minutes=10),
            "jti": "expired-jti",
        }
        token = jwt.encode(payload, "test-key:salt", algorithm="HS256")
        result = admin_auth.validate_session_token(token)
        assert result is None


class TestAdminLoginEndpoint:
    """Integration tests for admin login/logout endpoints via FastAPI TestClient."""

    @pytest.fixture
    def client(self):
        from main import app
        from starlette.testclient import TestClient
        return TestClient(app, raise_server_exceptions=False)

    def test_login_success(self, client, monkeypatch):
        monkeypatch.setattr("admin_auth.ADMIN_SECRET", "test-admin-key")
        monkeypatch.setattr("admin_auth.JWT_SECRET", "test-admin-key:test-salt")
        resp = client.post("/api/admin/login", json={"key": "test-admin-key"})
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["expires_in_minutes"] == 60

    def test_login_wrong_key(self, client, monkeypatch):
        monkeypatch.setattr("admin_auth.ADMIN_SECRET", "test-admin-key")
        resp = client.post("/api/admin/login", json={"key": "wrong"})
        assert resp.status_code == 403

    def test_login_not_configured(self, client, monkeypatch):
        monkeypatch.setattr("admin_auth.ADMIN_SECRET", "")
        resp = client.post("/api/admin/login", json={"key": "anything"})
        assert resp.status_code == 503

    def test_login_empty_key(self, client):
        resp = client.post("/api/admin/login", json={"key": ""})
        assert resp.status_code == 422  # Pydantic validation (min_length=1)

    def test_full_session_lifecycle(self, client, monkeypatch):
        """Login → use token → logout → token rejected."""
        import admin_auth
        monkeypatch.setattr("admin_auth.ADMIN_SECRET", "test-admin-key")
        monkeypatch.setattr("admin_auth.JWT_SECRET", "test-admin-key:test-salt")
        admin_auth._revoked_tokens.clear()

        # Login
        resp = client.post("/api/admin/login", json={"key": "test-admin-key"})
        assert resp.status_code == 200
        token = resp.json()["token"]
        auth_header = {"Authorization": f"Bearer {token}"}

        # Use token
        resp = client.get("/api/admin/metrics", headers=auth_header)
        assert resp.status_code == 200

        # Logout
        resp = client.post("/api/admin/logout", headers=auth_header)
        assert resp.status_code == 200
        assert resp.json()["status"] == "logged_out"

        # Token should be revoked
        resp = client.get("/api/admin/metrics", headers=auth_header)
        assert resp.status_code == 401

    def test_monitoring_endpoint_with_token(self, client, monkeypatch):
        monkeypatch.setattr("admin_auth.ADMIN_SECRET", "test-admin-key")
        monkeypatch.setattr("admin_auth.JWT_SECRET", "test-admin-key:test-salt")

        # Login
        resp = client.post("/api/admin/login", json={"key": "test-admin-key"})
        token = resp.json()["token"]

        # Access monitoring
        resp = client.get("/api/admin/monitoring", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
