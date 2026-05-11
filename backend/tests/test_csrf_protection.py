import base64
import json
import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["RATE_LIMIT_ENABLED"] = "false"

from csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME  # noqa: E402
from main import app  # noqa: E402


def _swa_header() -> dict[str, str]:
    principal = {
        "identityProvider": "aad",
        "userId": "csrf-user",
        "userDetails": "csrf@example.com",
        "userRoles": ["authenticated"],
        "claims": [],
    }
    encoded = base64.b64encode(json.dumps(principal).encode("utf-8")).decode("ascii")
    return {"x-ms-client-principal": encoded}


def test_csrf_endpoint_sets_strict_samesite_cookie():
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/auth/csrf")

    assert response.status_code == 200
    token = response.json()["csrf_token"]
    set_cookie = response.headers["set-cookie"]
    assert f"{CSRF_COOKIE_NAME}={token}" in set_cookie
    assert "SameSite=strict" in set_cookie


def test_swa_cookie_auth_mutation_requires_csrf_token():
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/auth/logout", headers=_swa_header())

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_TOKEN_MISSING_OR_INVALID"


def test_swa_cookie_auth_mutation_accepts_matching_csrf_token():
    token = "csrf-test-token"
    headers = {**_swa_header(), CSRF_HEADER_NAME: token}

    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set(CSRF_COOKIE_NAME, token)
        response = client.post("/api/auth/logout", headers=headers)

    assert response.status_code == 200
    assert response.json()["success"] is True


def test_bearer_mutation_does_not_require_csrf_token():
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/auth/logout", headers={"Authorization": "Bearer local-token"})

    assert response.status_code == 200
    assert response.json()["success"] is True