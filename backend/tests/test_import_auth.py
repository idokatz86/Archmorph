import json
import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["RATE_LIMIT_ENABLED"] = "false"

from main import app  # noqa: E402
from routers import shared as shared_router  # noqa: E402
from routers.shared import verify_api_key  # noqa: E402


API_KEY = "test-import-key"
AUTH_HEADERS = {"X-API-Key": API_KEY}


def _client(monkeypatch):
    monkeypatch.setattr(shared_router, "API_KEY", API_KEY)
    return TestClient(app, raise_server_exceptions=False)


def _upload_payload(payload: dict) -> dict:
    return {"file": ("template.json", json.dumps(payload), "application/json")}


def test_all_import_mutations_require_api_key(monkeypatch):
    client = _client(monkeypatch)
    terraform_state = {"version": 4, "resources": []}
    cloudformation = {"Resources": {}}
    arm_template = {"resources": []}

    for path, payload in (
        ("/api/import/terraform", terraform_state),
        ("/api/import/cloudformation", cloudformation),
        ("/api/import/arm", arm_template),
    ):
        response = client.post(path, files=_upload_payload(payload))
        assert response.status_code == 401, path

    response = client.post(
        "/api/import/infrastructure",
        json={"content": json.dumps(terraform_state), "format": "terraform_state", "filename": "terraform.tfstate"},
    )
    assert response.status_code == 401


def test_legacy_import_routes_parse_with_valid_api_key(monkeypatch):
    client = _client(monkeypatch)
    cases = (
        ("/api/import/terraform", {"version": 4, "resources": []}, "terraform"),
        ("/api/import/cloudformation", {"Resources": {}}, "cloudformation"),
        ("/api/import/arm", {"resources": []}, "arm"),
    )

    for path, payload, source in cases:
        response = client.post(path, headers=AUTH_HEADERS, files=_upload_payload(payload))
        assert response.status_code == 200, response.text
        assert response.json()["source"] == source
        assert response.json()["total_resources"] == 0


def test_import_routes_share_auth_dependency_and_limits():
    import routers.infra_import as infra_import

    assert infra_import._MAX_IMPORT_CONTENT_CHARS == 10 * 1024 * 1024

    protected_paths = {
        "/api/import/terraform",
        "/api/import/cloudformation",
        "/api/import/arm",
        "/api/import/infrastructure",
    }
    matched = {route.path: route for route in app.routes if getattr(route, "path", None) in protected_paths}

    assert matched.keys() == protected_paths
    for route in matched.values():
        dependency_callables = {dep.call for dep in route.dependant.dependencies}
        assert verify_api_key in dependency_callables