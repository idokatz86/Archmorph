import io
import os
import sys
import base64
import json

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["RATE_LIMIT_ENABLED"] = "false"

from auth import AuthProvider, User, generate_session_token  # noqa: E402
from main import app  # noqa: E402
from routers import diagrams  # noqa: E402
from routers import shared  # noqa: E402


def _png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _swa_principal(user_id: str = "bridge-user") -> str:
    principal = {
        "identityProvider": "aad",
        "userId": user_id,
        "userDetails": f"{user_id}@example.com",
        "userRoles": ["authenticated"],
        "claims": [],
    }
    return base64.b64encode(json.dumps(principal).encode("utf-8")).decode("ascii")


def test_diagram_upload_accepts_authenticated_user_bearer_session(monkeypatch):
    monkeypatch.setattr(shared, "API_KEY", "test-api-key")

    user = User(id="aad_bridge-user", email="bridge@example.com", provider=AuthProvider.MICROSOFT)
    token = generate_session_token(user)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/projects/demo-project/diagrams",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("diagram.png", io.BytesIO(_png_bytes()), "image/png")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "uploaded"
    assert payload["diagram_id"].startswith("diag-")
    diagrams.IMAGE_STORE.delete(payload["diagram_id"])


def test_swa_session_bridge_requires_configured_api_key(monkeypatch):
    monkeypatch.setattr(shared, "API_KEY", "")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/auth/swa-session",
            headers={"X-API-Key": "anything"},
            json={"client_principal": _swa_principal()},
        )

    assert response.status_code == 500
    assert response.json()["error"]["message"] == "Server misconfiguration: API key not set"


def test_swa_session_bridge_rejects_missing_api_key(monkeypatch):
    monkeypatch.setattr(shared, "API_KEY", "test-api-key")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/auth/swa-session",
            json={"client_principal": _swa_principal()},
        )

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid or missing API key"


def test_swa_session_bridge_mints_backend_session_with_api_key(monkeypatch):
    monkeypatch.setattr(shared, "API_KEY", "test-api-key")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/auth/swa-session",
            headers={"X-API-Key": "test-api-key"},
            json={"client_principal": _swa_principal()},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["id"] == "aad_bridge-user"
    assert payload["session_token"]
    assert payload["refresh_token"]