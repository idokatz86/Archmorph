"""Adversarial managed/static API-key authorization and rate-limit contracts."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter

from main import app
from routers import shared
from routers.api_keys_routes import (
    _hash_index,
    _keys,
    create_api_key,
    revoke_api_key,
    rotate_api_key,
)


@pytest.fixture(autouse=True)
def isolated_credentials(monkeypatch):
    _keys.clear()
    _hash_index.clear()
    _keys["__test_in_memory_registry__"] = object()
    monkeypatch.setattr(shared, "API_KEY", "static-administrator-placeholder")
    monkeypatch.setattr(shared, "API_KEY_ROTATED", "")
    monkeypatch.setattr(shared, "API_KEY_PRINCIPAL_ID", "static-service-principal")
    monkeypatch.setattr(shared, "API_KEY_ALLOW_LEGACY_OVERLAP", False)
    monkeypatch.setattr(shared.limiter, "_limiter", FixedWindowRateLimiter(MemoryStorage()))
    yield
    _keys.clear()
    _hash_index.clear()


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _headers(raw_key: str) -> dict[str, str]:
    return {"X-API-Key": raw_key}


def test_typed_credential_context_has_stable_secret_free_fields():
    record, raw = create_api_key("reader", ["read"], rate_limit=7)

    context = shared._authenticate_api_key(raw, required=False)

    assert context.kind is shared.CredentialKind.MANAGED
    assert context.key_id == record.id
    assert context.principal_id == f"api-key:{record.principal_id}"
    assert context.scopes == frozenset({"read"})
    assert context.rate_limit == 7
    assert context.owner_user_id == context.principal_id
    assert context.tenant_id == f"service:{record.principal_id}"
    assert raw not in repr(context)


def test_read_write_admin_scope_matrix_and_v1_aliases():
    _read_record, read_key = create_api_key("read", ["read"])
    _write_record, write_key = create_api_key("write", ["write"])
    _admin_record, admin_key = create_api_key("admin", ["admin"])

    with _client() as client:
        assert client.get("/api/health", headers=_headers(read_key)).status_code == 200
        assert client.get("/api/health", headers=_headers(write_key)).status_code == 403
        assert client.get("/api/v1/health", headers=_headers(write_key)).status_code == 403

        read_mutation = client.post(
            "/api/projects/diagrams",
            headers=_headers(read_key),
            files={"file": ("architecture.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, "image/png")},
        )
        assert read_mutation.status_code == 403

        write_payload = {
            "name": "must-not-be-created",
            "scopes": ["admin"],
            "rate_limit": 10,
        }
        assert client.post("/api/keys", headers=_headers(read_key), json=write_payload).status_code == 403
        assert client.post("/api/v1/keys", headers=_headers(read_key), json=write_payload).status_code == 403
        assert client.post("/api/keys", headers=_headers(write_key), json=write_payload).status_code == 403
        created = client.post("/api/keys", headers=_headers(admin_key), json=write_payload)
        assert created.status_code == 200, created.text
        assert created.json()["scopes"] == ["admin"]

        assert client.get("/api/admin/metrics", headers=_headers(read_key)).status_code == 403
        assert client.get("/api/admin/metrics", headers=_headers(write_key)).status_code == 403
        assert client.get("/api/admin/metrics", headers=_headers(admin_key)).status_code == 200


def test_two_key_rate_limit_isolation_and_alias_cannot_bypass():
    _first, first_key = create_api_key("first", ["read"], rate_limit=2)
    _second, second_key = create_api_key("second", ["read"], rate_limit=2)

    with _client() as client:
        assert client.get("/api/health", headers=_headers(first_key)).status_code == 200
        assert client.get("/api/v1/health", headers=_headers(first_key)).status_code == 200
        limited = client.get("/api/health", headers=_headers(first_key))
        assert limited.status_code == 429
        assert limited.headers["Retry-After"] == "60"
        assert client.get("/api/health", headers=_headers(second_key)).status_code == 200


def test_two_replicas_share_atomic_per_principal_budget(monkeypatch):
    record, raw = create_api_key("distributed", ["read"], rate_limit=2)
    storage = MemoryStorage()
    replica_a = FixedWindowRateLimiter(storage)
    replica_b = FixedWindowRateLimiter(storage)
    context = shared.CredentialContext(
        kind=shared.CredentialKind.MANAGED,
        principal_id=f"api-key:{record.principal_id}",
        key_id=record.id,
        scopes=frozenset({"read"}),
        rate_limit=2,
        tenant_id=f"service:{record.principal_id}",
        owner_user_id=f"api-key:{record.principal_id}",
    )

    monkeypatch.setattr(shared.limiter, "_limiter", replica_a)
    shared._enforce_managed_key_rate_limit(context)
    monkeypatch.setattr(shared.limiter, "_limiter", replica_b)
    shared._enforce_managed_key_rate_limit(context)
    with pytest.raises(Exception) as exc_info:
        shared._enforce_managed_key_rate_limit(context)
    assert getattr(exc_info.value, "status_code", None) == 429
    assert raw not in str(exc_info.value)


def test_revoked_and_rotated_keys_fail_immediately_with_stable_principal():
    record, old_raw = create_api_key("rotate", ["read", "write"])
    old_principal = shared.get_api_key_service_principal({"x-api-key": old_raw})
    rotated = rotate_api_key(record.id)
    assert rotated is not None
    new_record, new_raw = rotated

    assert new_record.principal_id == record.principal_id
    assert shared.get_api_key_service_principal({"x-api-key": old_raw}) is None
    assert shared.get_api_key_service_principal({"x-api-key": new_raw}) == old_principal
    assert revoke_api_key(new_record.id) is True
    assert shared.get_api_key_service_principal({"x-api-key": new_raw}) is None


def test_static_overlap_then_cutover_uses_one_non_secret_principal(monkeypatch):
    monkeypatch.setattr(shared, "API_KEY", "base-static-placeholder")
    monkeypatch.setattr(shared, "API_KEY_ROTATED", "current-static-placeholder")
    monkeypatch.setattr(shared, "API_KEY_ALLOW_LEGACY_OVERLAP", True)

    base = shared._authenticate_api_key("base-static-placeholder", required=True)
    current = shared._authenticate_api_key("current-static-placeholder", required=True)
    assert base.principal_id == current.principal_id == "api-key:static-service-principal"

    monkeypatch.setattr(shared, "API_KEY_ALLOW_LEGACY_OVERLAP", False)
    with pytest.raises(Exception) as exc_info:
        shared._authenticate_api_key("base-static-placeholder", required=True)
    assert getattr(exc_info.value, "status_code", None) == 401
    assert shared._authenticate_api_key("current-static-placeholder", required=True).principal_id == base.principal_id


def test_raw_api_keys_are_not_emitted_to_logs(caplog):
    raw_secret = "arch_raw-secret-that-must-never-be-logged"
    with patch("routers.api_keys_routes._generate_key", return_value=raw_secret):
        with caplog.at_level(logging.INFO):
            create_api_key("safe-name", ["read"])

    assert raw_secret not in caplog.text