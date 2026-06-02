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


OWNER_USER_ID = "aad_bridge-user"
OWNER_TENANT_ID = "default_tenant"


def _owner_headers() -> dict[str, str]:
    user = User(
        id=OWNER_USER_ID,
        email="bridge@example.com",
        provider=AuthProvider.MICROSOFT,
        tenant_id=OWNER_TENANT_ID,
    )
    return {"Authorization": f"Bearer {generate_session_token(user)}"}


def _owned_analysis(diagram_id: str) -> dict:
    return {
        "diagram_id": diagram_id,
        "diagram_type": "AWS Architecture",
        "source_provider": "aws",
        "target_provider": "azure",
        "services_detected": 2,
        "zones": [
            {"id": 1, "number": 1, "name": "Compute", "services": [{"aws": "EC2", "azure": "Azure VM"}]},
        ],
        "mappings": [
            {"source_service": "Amazon EC2", "azure_service": "Azure Virtual Machines", "confidence": 0.95},
            {"source_service": "Amazon S3", "azure_service": "Azure Blob Storage", "confidence": 0.92},
        ],
        "confidence_summary": {"average": 0.94, "high": 2, "medium": 0, "low": 0},
        "hld": {"title": "Bearer Session HLD", "services": [], "executive_summary": "Test HLD"},
        "hld_markdown": "# Bearer Session HLD\n",
        "_owner_user_id": OWNER_USER_ID,
        "_tenant_id": OWNER_TENANT_ID,
    }


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

    headers = _owner_headers()

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/projects/demo-project/diagrams",
            headers=headers,
            files={"file": ("diagram.png", io.BytesIO(_png_bytes()), "image/png")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "uploaded"
    assert payload["diagram_id"].startswith("diag-")
    diagrams.IMAGE_STORE.delete(payload["diagram_id"])
    shared.DIAGRAM_PROJECT_STORE.delete(payload["diagram_id"])
    shared.PROJECT_STORE.delete("demo-project")


def test_project_status_accepts_authenticated_user_bearer_session_when_api_key_configured(monkeypatch):
    monkeypatch.setattr(shared, "API_KEY", "test-api-key")
    headers = _owner_headers()

    with TestClient(app, raise_server_exceptions=False) as client:
        upload = client.post(
            "/api/projects/demo-project/diagrams",
            headers=headers,
            files={"file": ("diagram.png", io.BytesIO(_png_bytes()), "image/png")},
        )
        assert upload.status_code == 200, upload.text
        response = client.get("/api/projects/demo-project", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["project_id"] == "demo-project"
    diagram_id = upload.json()["diagram_id"]
    diagrams.IMAGE_STORE.delete(diagram_id)
    shared.DIAGRAM_PROJECT_STORE.delete(diagram_id)
    shared.PROJECT_STORE.delete("demo-project")


def test_guided_questions_accept_authenticated_user_bearer_session_when_api_key_configured(monkeypatch):
    monkeypatch.setattr(shared, "API_KEY", "test-api-key")
    diagram_id = "diag-bearer-questions"
    shared.SESSION_STORE[diagram_id] = _owned_analysis(diagram_id)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(f"/api/diagrams/{diagram_id}/questions", headers=_owner_headers())

    assert response.status_code == 200, response.text
    assert response.json()["diagram_id"] == diagram_id
    shared.SESSION_STORE.delete(diagram_id)


def test_architecture_package_accepts_authenticated_user_bearer_session_when_api_key_configured(monkeypatch):
    monkeypatch.setattr(shared, "API_KEY", "test-api-key")
    monkeypatch.setenv("ARCHMORPH_EXPORT_CAPABILITY_REQUIRED", "false")
    diagram_id = "diag-bearer-architecture-package"
    shared.SESSION_STORE[diagram_id] = _owned_analysis(diagram_id)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/api/diagrams/{diagram_id}/export-architecture-package?format=html",
            headers=_owner_headers(),
        )

    assert response.status_code == 200, response.text
    assert response.json()["format"] == "architecture-package-html"
    shared.SESSION_STORE.delete(diagram_id)


def test_migration_package_accepts_authenticated_user_bearer_session_when_api_key_configured(monkeypatch):
    monkeypatch.setattr(shared, "API_KEY", "test-api-key")
    monkeypatch.setenv("ARCHMORPH_EXPORT_CAPABILITY_REQUIRED", "false")
    diagram_id = "diag-bearer-migration-package"
    shared.SESSION_STORE[diagram_id] = _owned_analysis(diagram_id)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/api/diagrams/{diagram_id}/export-package",
            headers=_owner_headers(),
            json={"iac_format": "terraform", "include_diagrams": False},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["content_type"] == "application/zip"
    assert payload["content_b64"]
    shared.SESSION_STORE.delete(diagram_id)


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