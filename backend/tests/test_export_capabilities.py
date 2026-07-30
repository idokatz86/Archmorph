"""Capability-token boundary tests for export endpoints (#671)."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from auth import AuthProvider, User, UserTier, generate_session_token
from error_envelope import ArchmorphException
from export_capabilities import (
    EXPORT_CAPABILITY_SCOPE,
    ExportCapability,
    ExportCapabilityBinding,
    _digest,
    consume_export_capability,
    issue_export_capability,
    issue_export_capability_for_identity,
    issue_export_capability_for_request,
)
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
    from database import SessionLocal
    from workspace_store import persist_analysis_state

    did = "capability-boundary-diagram"
    snapshot = {
        **dict(SAMPLE_ANALYSIS),
        "_owner_user_id": "cap-owner",
        "_tenant_id": "cap-tenant",
    }
    db = SessionLocal()
    try:
        persist_analysis_state(
            db,
            owner_user_id="cap-owner",
            tenant_id="cap-tenant",
            diagram_id=did,
            snapshot=snapshot,
            session_store=SESSION_STORE,
            cache_required=True,
        )
    finally:
        db.close()
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


def _export_package(
    client, did: str, auth_headers: dict[str, str], token: str | None = None
):
    headers = dict(auth_headers)
    if token:
        headers["X-Export-Capability"] = token
    return client.post(
        f"/api/diagrams/{did}/export-architecture-package?format=html",
        headers=headers,
    )


def _bound_token(diagram_id: str, *, ttl_seconds: int | None = None) -> str:
    return issue_export_capability_for_identity(
        diagram_id,
        caller_owner_user_id="cap-owner",
        tenant_id="cap-tenant",
        ttl_seconds=ttl_seconds,
    )


def test_unbound_capability_issuance_marks_usage_audit_transient(monkeypatch):
    audit_calls = []

    def capture_audit(reason, diagram_id, token_digest=None, **kwargs):
        audit_calls.append((reason, diagram_id, bool(token_digest), kwargs))

    monkeypatch.setattr("export_capabilities._audit", capture_audit)

    token = issue_export_capability("sample-public-capability")

    assert token
    assert audit_calls == [
        (
            "issued",
            "sample-public-capability",
            True,
            {"durable_subject": False},
        )
    ]


def test_bound_capability_issuance_keeps_usage_audit_durable(
    diagram_id,
    monkeypatch,
):
    audit_calls = []

    def capture_audit(reason, audited_diagram_id, token_digest=None, **kwargs):
        audit_calls.append(
            (reason, audited_diagram_id, bool(token_digest), kwargs)
        )

    monkeypatch.setattr("export_capabilities._audit", capture_audit)

    token = _bound_token(diagram_id)

    assert token
    assert audit_calls == [
        (
            "issued",
            diagram_id,
            True,
            {"durable_subject": True},
        )
    ]


@pytest.mark.asyncio
async def test_request_issuance_reuses_verified_canonical_write_binding(
    monkeypatch,
):
    binding = ExportCapabilityBinding(
        principal_marker="api:tenant:owner",
        owner_user_id="owner",
        tenant_id="tenant",
        analysis_id="analysis",
        project_id="project",
        analysis_version=3,
    )

    async def unexpected_resolver(*_args, **_kwargs):
        raise AssertionError("canonical binding must not be queried twice")

    monkeypatch.setattr(
        "export_capabilities.export_capability_binding_for_request",
        unexpected_resolver,
    )
    monkeypatch.setattr(
        "export_capabilities._principal_marker",
        lambda _request: binding.principal_marker,
    )
    monkeypatch.setattr(
        "export_capabilities._request_export_contract",
        lambda _request: ("any", "any"),
    )
    monkeypatch.setattr("export_capabilities._audit", lambda *_args, **_kwargs: None)

    token = await issue_export_capability_for_request(
        object(),
        "diagram",
        binding=binding,
    )

    assert token
    record = EXPORT_CAPABILITY_STORE.peek(_digest(token))
    assert record["analysis_id"] == binding.analysis_id
    assert record["analysis_version"] == binding.analysis_version


@pytest.mark.asyncio
async def test_request_issuance_reuses_explicit_public_binding_result(monkeypatch):
    async def unexpected_resolver(*_args, **_kwargs):
        raise AssertionError("explicit public binding must not be queried twice")

    monkeypatch.setattr(
        "export_capabilities.export_capability_binding_for_request",
        unexpected_resolver,
    )
    monkeypatch.setattr(
        "export_capabilities._principal_marker",
        lambda _request: (_ for _ in ()).throw(
            AssertionError("explicit public binding must not reparse principal")
        ),
    )
    monkeypatch.setattr(
        "export_capabilities._request_export_contract",
        lambda _request: ("any", "any"),
    )
    monkeypatch.setattr("export_capabilities._audit", lambda *_args, **_kwargs: None)

    SESSION_STORE.set(
        "sample-public-diagram",
        {"diagram_id": "sample-public-diagram", "is_sample": True},
    )
    try:
        token = await issue_export_capability_for_request(
            object(),
            "sample-public-diagram",
            binding=None,
            binding_resolved=True,
        )

        assert token
        assert EXPORT_CAPABILITY_STORE.peek(_digest(token))["binding_version"] == 0
    finally:
        SESSION_STORE.delete("sample-public-diagram")


def test_export_without_capability_is_unauthorized(
    test_client, diagram_id, auth_headers
):
    response = _export_package(test_client, diagram_id, auth_headers)

    assert response.status_code == 401
    assert "Missing export capability" in response.text


def test_export_with_expired_capability_is_unauthorized(
    test_client, diagram_id, auth_headers
):
    token = _bound_token(diagram_id)
    record = EXPORT_CAPABILITY_STORE.peek(_digest(token))
    EXPORT_CAPABILITY_STORE.set(
        _digest(token), {**record, "expires_at": time.time() - 1}
    )

    response = _export_package(test_client, diagram_id, auth_headers, token)

    assert response.status_code == 401
    assert "Invalid or unavailable export capability" in response.text


def test_export_capability_cannot_cross_diagram_boundary(
    test_client, diagram_id, auth_headers
):
    from database import SessionLocal
    from workspace_store import persist_analysis_state

    other_id = "other-capability-diagram"
    db = SessionLocal()
    try:
        persist_analysis_state(
            db,
            owner_user_id="cap-owner",
            tenant_id="cap-tenant",
            diagram_id=other_id,
            snapshot={**dict(SAMPLE_ANALYSIS), "diagram_id": other_id},
            session_store=SESSION_STORE,
            cache_required=True,
        )
    finally:
        db.close()
    token = _bound_token(other_id)

    response = _export_package(test_client, diagram_id, auth_headers, token)

    assert response.status_code == 401
    assert "Invalid or unavailable export capability" in response.text
    SESSION_STORE.delete(other_id)


def test_export_capability_is_single_use_to_block_replay(
    test_client, diagram_id, auth_headers
):
    token = _bound_token(diagram_id)

    first = _export_package(test_client, diagram_id, auth_headers, token)
    replay = _export_package(test_client, diagram_id, auth_headers, token)

    assert first.status_code == 200, first.text
    assert first.json()["format"] == "architecture-package-html"
    assert first.json()["export_capability"] != token
    assert replay.status_code == 401
    assert "Invalid or unavailable export capability" in replay.text


def test_rotated_capability_allows_next_valid_export(
    test_client, diagram_id, auth_headers
):
    token = _bound_token(diagram_id)

    first = _export_package(test_client, diagram_id, auth_headers, token)
    next_token = first.json()["export_capability"]
    second = _export_package(test_client, diagram_id, auth_headers, next_token)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["export_capability"] != next_token


def test_diagram_export_accepts_bearer_session_with_capability_when_api_key_configured(
    test_client,
    diagram_id,
    auth_headers,
    monkeypatch,
):
    monkeypatch.setattr(shared_router, "API_KEY", "configured-api-key")
    token = _bound_token(diagram_id)
    headers = {**auth_headers, "X-Export-Capability": token}

    response = test_client.post(
        f"/api/diagrams/{diagram_id}/export-diagram?format=drawio",
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["format"] == "drawio"
    assert response.json()["content"]


def test_capability_does_not_rebind_after_analysis_delete_and_recreate(
    test_client,
    diagram_id,
    auth_headers,
):
    from database import SessionLocal
    from models.workspace import Analysis
    from workspace_store import persist_analysis_state

    token = _bound_token(diagram_id)
    SESSION_STORE.delete(diagram_id)
    db = SessionLocal()
    try:
        db.query(Analysis).filter_by(
            diagram_id=diagram_id,
            owner_user_id="cap-owner",
            tenant_id="cap-tenant",
        ).delete()
        db.commit()
    finally:
        db.close()

    failed = _export_package(test_client, diagram_id, auth_headers, token)
    db = SessionLocal()
    try:
        persist_analysis_state(
            db,
            owner_user_id="cap-owner",
            tenant_id="cap-tenant",
            diagram_id=diagram_id,
            snapshot={
                **dict(SAMPLE_ANALYSIS),
                "_owner_user_id": "cap-owner",
                "_tenant_id": "cap-tenant",
            },
            session_store=SESSION_STORE,
            cache_required=True,
        )
    finally:
        db.close()
    retried = _export_package(test_client, diagram_id, auth_headers, token)
    refreshed = _export_package(
        test_client,
        diagram_id,
        auth_headers,
        _bound_token(diagram_id),
    )

    assert failed.status_code == 404
    assert retried.status_code == 401
    assert refreshed.status_code == 200, refreshed.text


def test_query_export_token_rejected_outside_local(
    test_client, diagram_id, monkeypatch, auth_headers
):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(shared_router, "API_KEY", "prod-capability-key")
    token = _bound_token(diagram_id)
    headers = dict(auth_headers)
    headers["X-API-Key"] = "prod-capability-key"

    response = test_client.post(
        f"/api/diagrams/{diagram_id}/export-architecture-package?format=html&export_token={token}",
        headers=headers,
    )

    assert response.status_code == 400
    assert "Export capabilities are not accepted in URLs" in response.text


def test_concurrent_capability_consumers_have_exactly_one_winner(diagram_id):
    token = issue_export_capability(diagram_id)
    token_digest = _digest(token)
    record = EXPORT_CAPABILITY_STORE.peek(token_digest)
    capability = ExportCapability(
        token_digest=token_digest,
        diagram_id=diagram_id,
        scope=EXPORT_CAPABILITY_SCOPE,
        expires_at=record["expires_at"],
        record=dict(record),
    )

    def consume(_index):
        try:
            consume_export_capability(capability)
            return "success"
        except ArchmorphException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(consume, range(12)))

    assert results.count("success") == 1
    assert results.count(401) == 11


def test_capability_consumption_fails_closed_when_atomic_delete_fails(
    diagram_id,
    monkeypatch,
):
    token = issue_export_capability(diagram_id)
    token_digest = _digest(token)
    record = EXPORT_CAPABILITY_STORE.peek(token_digest)
    capability = ExportCapability(
        token_digest=token_digest,
        diagram_id=diagram_id,
        scope=EXPORT_CAPABILITY_SCOPE,
        expires_at=record["expires_at"],
        record=dict(record),
    )
    monkeypatch.setattr(
        EXPORT_CAPABILITY_STORE,
        "pop",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unconfirmed")),
    )

    with pytest.raises(ArchmorphException) as exc_info:
        consume_export_capability(capability)

    assert exc_info.value.status_code == 503
    assert EXPORT_CAPABILITY_STORE.peek(token_digest) == record


def test_capability_issuance_fails_closed_when_store_write_is_unconfirmed(
    diagram_id,
    monkeypatch,
):
    monkeypatch.setattr(EXPORT_CAPABILITY_STORE, "set", lambda *_args, **_kwargs: False)

    with pytest.raises(ArchmorphException) as exc_info:
        _bound_token(diagram_id)

    assert exc_info.value.status_code == 503
    assert "issuance is temporarily unavailable" in str(exc_info.value.detail)
