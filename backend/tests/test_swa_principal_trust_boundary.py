import base64
import json
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["RATE_LIMIT_ENABLED"] = "false"

from csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME  # noqa: E402
from main import app  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]


def _swa_header(user_id: str = "trusted-user") -> dict[str, str]:
    principal = {
        "identityProvider": "aad",
        "userId": user_id,
        "userDetails": f"{user_id}@example.com",
        "userRoles": ["authenticated"],
        "claims": [],
    }
    encoded = base64.b64encode(json.dumps(principal).encode("utf-8")).decode("ascii")
    return {"x-ms-client-principal": encoded}


def test_production_rejects_untrusted_swa_principal_header(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("TRUST_SWA_PRINCIPAL_HEADER", raising=False)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/auth/me", headers=_swa_header("forged-user"))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNTRUSTED_SWA_PRINCIPAL"


def test_production_rejects_forged_swa_principal_even_with_matching_csrf(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("TRUST_SWA_PRINCIPAL_HEADER", raising=False)

    token = "csrf-test-token"
    headers = {**_swa_header("forged-user"), CSRF_HEADER_NAME: token}

    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set(CSRF_COOKIE_NAME, token)
        response = client.post("/api/auth/logout", headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNTRUSTED_SWA_PRINCIPAL"


def test_production_rejects_swa_login_with_forged_header_even_with_csrf(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("TRUST_SWA_PRINCIPAL_HEADER", raising=False)

    token = "csrf-login-token"
    headers = {**_swa_header(), CSRF_HEADER_NAME: token}

    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set(CSRF_COOKIE_NAME, token)
        response = client.post("/api/auth/login", json={"provider": "swa"}, headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNTRUSTED_SWA_PRINCIPAL"

def test_production_allows_swa_login_when_trust_boundary_is_enabled_and_csrf_matches(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("TRUST_SWA_PRINCIPAL_HEADER", "true")

    token = "csrf-login-token"
    headers = {**_swa_header(), CSRF_HEADER_NAME: token}

    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set(CSRF_COOKIE_NAME, token)
        response = client.post("/api/auth/login", json={"provider": "swa"}, headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["id"] == "aad_trusted-user"
    assert payload["session_token"]
    assert payload["refresh_token"]


def test_infra_explicitly_disables_swa_principal_trust_by_default():
    infra = (REPO_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")

    assert 'name  = "TRUST_SWA_PRINCIPAL_HEADER"' in infra
    assert 'value = "false"' in infra
    assert 'name     = "BlockForgedSWAPrincipal"' in infra
