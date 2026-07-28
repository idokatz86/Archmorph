"""HTTP contracts for durable version restore concurrency and idempotency."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import database
from database import Base
from routers.shared import SESSION_STORE
from workspace_store import persist_analysis_state


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(database, "SessionLocal", factory)
    monkeypatch.setattr("routers.versioning.SessionLocal", factory)
    SESSION_STORE.clear()
    yield
    SESSION_STORE.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _seed(owner: str, tenant: str, diagram_id: str):
    db = database.SessionLocal()
    try:
        result = persist_analysis_state(
            db,
            owner_user_id=owner,
            tenant_id=tenant,
            diagram_id=diagram_id,
            snapshot={"step": "source", "mappings": []},
        )
        persist_analysis_state(
            db,
            owner_user_id=owner,
            tenant_id=tenant,
            diagram_id=diagram_id,
            snapshot={"step": "current", "mappings": [], "_analysis_version": 1},
            expected_version=1,
            operation=f"prepare-{diagram_id}",
            request_hash="c" * 64,
        )
        return result.analysis.id
    finally:
        db.close()


def test_analysis_restore_requires_headers_and_replays_original(
    test_client,
    tenant_a_auth_headers,
    tenant_a,
):
    analysis_id = _seed(tenant_a["user_id"], tenant_a["tenant_id"], "restore-api-analysis")
    path = f"/api/analyses/{analysis_id}/versions/1/restore"

    assert test_client.post(path, headers=tenant_a_auth_headers).status_code == 422
    headers = {
        **tenant_a_auth_headers,
        "If-Match": 'W/"2"',
        "Idempotency-Key": "analysis-restore-idempotency",
    }
    first = test_client.post(path, headers=headers)
    retry = test_client.post(path, headers=headers)
    assert first.status_code == retry.status_code == 200
    assert first.json()["new_version"]["version_number"] == 3
    assert retry.json() == first.json()

    conflict = test_client.post(
        f"/api/analyses/{analysis_id}/versions/2/restore",
        headers={**headers, "If-Match": '"3"'},
    )
    assert conflict.status_code == 409
    stale = test_client.post(
        path,
        headers={
            **tenant_a_auth_headers,
            "If-Match": '"2"',
            "Idempotency-Key": "different-stale-key",
        },
    )
    assert stale.status_code == 409


def test_diagram_restore_requires_headers_and_v1_alias_matches(
    test_client,
    tenant_a_auth_headers,
    tenant_a,
):
    _seed(tenant_a["user_id"], tenant_a["tenant_id"], "restore-api-diagram")
    path = "/api/diagrams/restore-api-diagram/versions/1/restore"
    alias = "/api/v1/diagrams/restore-api-diagram/versions/1/restore"

    assert test_client.post(path, headers=tenant_a_auth_headers).status_code == 422
    headers = {
        **tenant_a_auth_headers,
        "If-Match": '"2"',
        "Idempotency-Key": "diagram-restore-idempotency",
    }
    first = test_client.post(path, headers=headers)
    retry = test_client.post(alias, headers=headers)
    assert first.status_code == retry.status_code == 200
    assert first.json()["new_version"]["version_number"] == 3
    assert retry.json()["new_version"]["version_number"] == 3