"""Capability-token boundary tests for export endpoints (#671)."""

from __future__ import annotations

import time

import pytest

from auth import AuthProvider, User, UserTier, generate_session_token
from export_capabilities import EXPORT_CAPABILITY_SCOPE, _digest, issue_export_capability
from routers import shared as shared_router
from routers.shared import EXPORT_CAPABILITY_STORE, SESSION_STORE


SAMPLE_ANALYSIS = {
    "title": "Capability Boundary Test",
    "source_provider": "aws",
    "target_provider": "azure",
    "zones": [{"id": 1, "name": "web-tier", "number": 1, "services": []}],
    "mappings": [
        {"source_service": "ALB", "azure_service": "Application Gateway", "category": "Networking", "confidence": 0.96},
        {"source_service": "EKS", "azure_service": "AKS", "category": "Containers", "confidence": 0.94},
        {"source_service": "RDS", "azure_service": "Azure SQL", "category": "Database", "confidence": 0.88},
    ],
    "guided_answers": {
        "env_target": "Production",
        "arch_deploy_region": "East US",
        "arch_ha": "Zone redundant",
        "sec_compliance": ["SOC 2"],
    },
}


@pytest.fixture(autouse=True)
def require_export_capabilities(monkeypatch):
    monkeypatch.setenv("ARCHMORPH_EXPORT_CAPABILITY_REQUIRED", "true")
    EXPORT_CAPABILITY_STORE.clear()
    yield
    EXPORT_CAPABILITY_STORE.clear()


@pytest.fixture()
def diagram_id():
    did = "capability-boundary-diagram"
    SESSION_STORE[did] = {
        **dict(SAMPLE_ANALYSIS),
        "_owner_user_id": "cap-owner",
        "_tenant_id": "cap-tenant",
    }
    yield did
    try:
        del SESSION_STORE[did]
    except (KeyError, Exception):
        pass


@pytest.fixture()
def auth_headers():
    user = User(
        id="cap-owner",
        email="cap-owner@example.test",
        name="Capability Owner",
        provider=AuthProvider.GITHUB,
        tier=UserTier.TEAM,
        tenant_id="cap-tenant",
    )
    return {"Authorization": f"Bearer {generate_session_token(user)}"}


def _export_package(client, did: str, auth_headers: dict[str, str], token: str | None = None):
    headers = dict(auth_headers)
    if token:
        headers["X-Export-Capability"] = token
    return client.post(
        f"/api/diagrams/{did}/export-architecture-package?format=html",
        headers=headers,
    )


def test_export_without_capability_is_unauthorized(test_client, diagram_id, auth_headers):
    response = _export_package(test_client, diagram_id, auth_headers)

    assert response.status_code == 401
    assert "Missing export capability" in response.text


def test_export_with_expired_capability_is_unauthorized(test_client, diagram_id, auth_headers):
    token = issue_export_capability(diagram_id)
    EXPORT_CAPABILITY_STORE.set(
        _digest(token),
        {
            "diagram_id": diagram_id,
            "scope": EXPORT_CAPABILITY_SCOPE,
            "expires_at": time.time() - 1,
        },
    )

    response = _export_package(test_client, diagram_id, auth_headers, token)

    assert response.status_code == 401
    assert "Expired export capability" in response.text


def test_export_capability_cannot_cross_diagram_boundary(test_client, diagram_id, auth_headers):
    other_id = "other-capability-diagram"
    token = issue_export_capability(other_id)

    response = _export_package(test_client, diagram_id, auth_headers, token)

    assert response.status_code == 403
    assert "not authorized for this diagram" in response.text


def test_export_capability_is_single_use_to_block_replay(test_client, diagram_id, auth_headers):
    token = issue_export_capability(diagram_id)

    first = _export_package(test_client, diagram_id, auth_headers, token)
    replay = _export_package(test_client, diagram_id, auth_headers, token)

    assert first.status_code == 200, first.text
    assert first.json()["format"] == "architecture-package-html"
    assert first.json()["export_capability"] != token
    assert replay.status_code == 401
    assert "Invalid or replayed export capability" in replay.text


def test_rotated_capability_allows_next_valid_export(test_client, diagram_id, auth_headers):
    token = issue_export_capability(diagram_id)

    first = _export_package(test_client, diagram_id, auth_headers, token)
    next_token = first.json()["export_capability"]
    second = _export_package(test_client, diagram_id, auth_headers, next_token)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["export_capability"] != next_token


def test_valid_capability_survives_route_failure_before_export_success(test_client, diagram_id, auth_headers):
    token = issue_export_capability(diagram_id)
    SESSION_STORE.delete(diagram_id)

    failed = _export_package(test_client, diagram_id, auth_headers, token)
    SESSION_STORE[diagram_id] = dict(SAMPLE_ANALYSIS)
    SESSION_STORE[diagram_id]["_owner_user_id"] = "cap-owner"
    SESSION_STORE[diagram_id]["_tenant_id"] = "cap-tenant"
    retried = _export_package(test_client, diagram_id, auth_headers, token)

    assert failed.status_code == 404
    assert retried.status_code == 200, retried.text


def test_query_export_token_rejected_outside_local(test_client, diagram_id, monkeypatch, auth_headers):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(shared_router, "API_KEY", "prod-capability-key")
    token = issue_export_capability(diagram_id)
    headers = dict(auth_headers)
    headers["X-API-Key"] = "prod-capability-key"

    response = test_client.post(
        f"/api/diagrams/{diagram_id}/export-architecture-package?format=html&export_token={token}",
        headers=headers,
    )

    assert response.status_code == 400
    assert "Query-string export capabilities are disabled" in response.text
