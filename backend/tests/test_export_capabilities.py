"""Capability-token boundary tests for export endpoints (#671)."""

from __future__ import annotations

import time

import pytest

from export_capabilities import EXPORT_CAPABILITY_SCOPE, _digest, issue_export_capability
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
    SESSION_STORE[did] = dict(SAMPLE_ANALYSIS)
    yield did
    try:
        del SESSION_STORE[did]
    except (KeyError, Exception):
        pass


def _export_package(client, did: str, token: str | None = None):
    headers = {"X-Export-Capability": token} if token else {}
    return client.post(
        f"/api/diagrams/{did}/export-architecture-package?format=html",
        headers=headers,
    )


def test_export_without_capability_is_unauthorized(test_client, diagram_id):
    response = _export_package(test_client, diagram_id)

    assert response.status_code == 401
    assert "Missing export capability" in response.text


def test_export_with_expired_capability_is_unauthorized(test_client, diagram_id):
    token = issue_export_capability(diagram_id)
    EXPORT_CAPABILITY_STORE.set(
        _digest(token),
        {
            "diagram_id": diagram_id,
            "scope": EXPORT_CAPABILITY_SCOPE,
            "expires_at": time.time() - 1,
        },
    )

    response = _export_package(test_client, diagram_id, token)

    assert response.status_code == 401
    assert "Expired export capability" in response.text


def test_export_capability_cannot_cross_diagram_boundary(test_client, diagram_id):
    other_id = "other-capability-diagram"
    token = issue_export_capability(other_id)

    response = _export_package(test_client, diagram_id, token)

    assert response.status_code == 403
    assert "not authorized for this diagram" in response.text


def test_export_capability_is_single_use_to_block_replay(test_client, diagram_id):
    token = issue_export_capability(diagram_id)

    first = _export_package(test_client, diagram_id, token)
    replay = _export_package(test_client, diagram_id, token)

    assert first.status_code == 200, first.text
    assert first.json()["format"] == "architecture-package-html"
    assert first.json()["export_capability"] != token
    assert replay.status_code == 401
    assert "Invalid or replayed export capability" in replay.text


def test_rotated_capability_allows_next_valid_export(test_client, diagram_id):
    token = issue_export_capability(diagram_id)

    first = _export_package(test_client, diagram_id, token)
    next_token = first.json()["export_capability"]
    second = _export_package(test_client, diagram_id, next_token)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["export_capability"] != next_token
