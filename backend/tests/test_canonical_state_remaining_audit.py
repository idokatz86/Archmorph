"""Deterministic regressions for the remaining #1237 canonical-state audit."""

from __future__ import annotations

import asyncio
import hashlib
import threading

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from database import Base
from models.workspace import (
    AnalysisVersion,
    Artifact,
    TenantRehomeAlias,
    Workspace,
)
from routers import shared
from routers.api_keys_routes import _hash_index, _keys, create_api_key, rotate_api_key
from routers.workspaces import _db_call
from session_store import FileStore, InMemoryStore
from workspace_store import (
    MAX_VERSIONS_PER_ANALYSIS,
    _trim_old_versions,
    add_migration_replay_event,
    create_decision,
    create_export_artifact,
    create_migration_replay,
    create_workspace,
    list_migration_replays,
    list_quarantined_legacy_graphs,
    list_workspaces,
    owner_migration_conflict_status,
    persist_analysis_state,
    rehome_legacy_owner_scope,
    resolve_quarantined_legacy_graph,
    save_analysis_version,
    serialize_migration_replay,
    update_workspace,
)


def _bearer_headers(owner: str, tenant: str) -> dict[str, str]:
    from auth import AuthProvider, User, generate_session_token

    user = User(
        id=owner,
        provider=AuthProvider.GITHUB,
        provider_subject=owner,
        tenant_id=tenant,
    )
    return {"Authorization": f"Bearer {generate_session_token(user)}"}


@pytest.fixture(autouse=True)
def clear_managed_keys():
    _keys.clear()
    _hash_index.clear()
    yield
    _keys.clear()
    _hash_index.clear()


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_managed_api_key_rotation_preserves_principal_and_invalidates_old(monkeypatch):
    monkeypatch.setattr(shared, "API_KEY", "configured-admin-key")
    monkeypatch.setattr(shared, "API_KEY_ROTATED", "")
    record, old_raw = create_api_key("client", ["read", "write"])
    old_principal = shared.get_api_key_service_principal({"x-api-key": old_raw})

    rotated = rotate_api_key(record.id)
    assert rotated is not None
    new_record, new_raw = rotated

    assert new_record.principal_id == record.principal_id
    assert shared.get_api_key_service_principal({"x-api-key": old_raw}) is None
    assert shared.get_api_key_service_principal({"x-api-key": new_raw}) == old_principal


def test_static_api_key_rotation_uses_explicit_stable_principal(monkeypatch):
    monkeypatch.setattr(shared, "API_KEY", "old-static-key")
    monkeypatch.setattr(shared, "API_KEY_ROTATED", "new-static-key")
    monkeypatch.setattr(shared, "API_KEY_PRINCIPAL_ID", "stable-client-principal")
    monkeypatch.setattr(shared, "API_KEY_ALLOW_LEGACY_OVERLAP", False)

    assert shared.get_api_key_service_principal({"x-api-key": "old-static-key"}) is None
    assert shared.get_api_key_service_principal({"x-api-key": "new-static-key"}) == (
        "api-key:stable-client-principal"
    )


def test_static_principal_default_is_stable_and_not_secret_derived(monkeypatch):
    monkeypatch.setattr(shared, "API_KEY", "legacy-static-key")
    monkeypatch.setattr(shared, "API_KEY_ROTATED", "")
    monkeypatch.setattr(shared, "API_KEY_PRINCIPAL_ID", "")
    assert shared.get_api_key_service_principal({"x-api-key": "legacy-static-key"}) == (
        "api-key:static-service"
    )


def test_transitive_restore_ancestors_survive_retention_cap(db):
    workspace = create_workspace(
        db,
        owner_user_id="lineage-owner",
        tenant_id="lineage-tenant",
        name="lineage",
    )
    result = persist_analysis_state(
        db,
        owner_user_id="lineage-owner",
        tenant_id="lineage-tenant",
        diagram_id="lineage-diagram",
        workspace_id=workspace.id,
        snapshot={"value": 1, "mappings": []},
    )
    for value in range(2, MAX_VERSIONS_PER_ANALYSIS + 3):
        save_analysis_version(
            db,
            analysis_id=result.analysis.id,
            owner_user_id="lineage-owner",
            tenant_id="lineage-tenant",
            snapshot={"value": value, "mappings": []},
            restored_from=1 if value == MAX_VERSIONS_PER_ANALYSIS + 1 else (
                MAX_VERSIONS_PER_ANALYSIS + 1
                if value == MAX_VERSIONS_PER_ANALYSIS + 2
                else None
            ),
        )

    _trim_old_versions(db, result.analysis.id)
    numbers = {
        row.version_number
        for row in db.query(AnalysisVersion).filter_by(analysis_id=result.analysis.id)
    }
    assert {1, MAX_VERSIONS_PER_ANALYSIS + 1, MAX_VERSIONS_PER_ANALYSIS + 2} <= numbers


def test_lineage_cycle_is_defensively_preserved(db, caplog):
    result = persist_analysis_state(
        db,
        owner_user_id="cycle-owner",
        tenant_id="cycle-tenant",
        diagram_id="cycle-diagram",
        snapshot={"mappings": []},
    )
    first = result.version
    second = save_analysis_version(
        db,
        analysis_id=result.analysis.id,
        owner_user_id="cycle-owner",
        tenant_id="cycle-tenant",
        snapshot={"value": 2, "mappings": []},
        restored_from=1,
    )
    first.restored_from = 2
    db.commit()
    for value in range(3, MAX_VERSIONS_PER_ANALYSIS + 4):
        save_analysis_version(
            db,
            analysis_id=result.analysis.id,
            owner_user_id="cycle-owner",
            tenant_id="cycle-tenant",
            snapshot={"value": value, "mappings": []},
        )
    _trim_old_versions(db, result.analysis.id)
    assert db.get(AnalysisVersion, first.id) is not None
    assert db.get(AnalysisVersion, second.id) is not None
    assert "analysis_version_lineage_cycle" in caplog.text


def test_decision_rejects_version_from_another_analysis(db):
    first = persist_analysis_state(
        db,
        owner_user_id="decision-owner",
        tenant_id="decision-tenant",
        diagram_id="decision-one",
        snapshot={"mappings": []},
    )
    second = persist_analysis_state(
        db,
        owner_user_id="decision-owner",
        tenant_id="decision-tenant",
        diagram_id="decision-two",
        snapshot={"mappings": []},
    )
    with pytest.raises(ValueError, match="not found for analysis"):
        create_decision(
            db,
            analysis_id=first.analysis.id,
            version_id=second.version.id,
            owner_user_id="decision-owner",
            tenant_id="decision-tenant",
            decision_type="risk",
            title="invalid",
        )


def test_decision_api_rejects_cross_analysis_version(test_client):
    from database import SessionLocal

    owner = "decision-api-owner"
    tenant = "decision-api-tenant"
    db = SessionLocal()
    try:
        first = persist_analysis_state(
            db,
            owner_user_id=owner,
            tenant_id=tenant,
            diagram_id="decision-api-one",
            snapshot={"mappings": []},
        )
        second = persist_analysis_state(
            db,
            owner_user_id=owner,
            tenant_id=tenant,
            diagram_id="decision-api-two",
            snapshot={"mappings": []},
        )
        analysis_id = first.analysis.id
        foreign_version_id = second.version.id
    finally:
        db.close()

    response = test_client.post(
        f"/api/analyses/{analysis_id}/decisions",
        headers=_bearer_headers(owner, tenant),
        json={
            "decision_type": "risk",
            "title": "cross-analysis",
            "version_id": foreign_version_id,
        },
    )
    assert response.status_code == 422


def test_workspace_api_rejects_invalid_status_with_typed_contract(test_client):
    owner = "status-api-owner"
    tenant = "status-api-tenant"
    response = test_client.post(
        "/api/workspaces",
        headers=_bearer_headers(owner, tenant),
        json={"name": "Typed workspace"},
    )
    assert response.status_code == 200
    workspace_id = response.json()["id"]
    invalid = test_client.patch(
        f"/api/workspaces/{workspace_id}",
        headers=_bearer_headers(owner, tenant),
        json={"status": "arbitrary"},
    )
    assert invalid.status_code == 422


@pytest.mark.parametrize("store_kind", ["memory", "file"])
def test_store_page_contract_is_deterministic_and_bounded(tmp_path, monkeypatch, store_kind):
    if store_kind == "memory":
        store = InMemoryStore(maxsize=20, ttl=3600)
    else:
        monkeypatch.setenv("SESSION_FILE_DIR", str(tmp_path))
        store = FileStore("page-contract", maxsize=20, ttl=3600)
    for key in ("c", "a", "b", "foreign"):
        store.set(key, {"key": key})
    items, total = store.page(pattern="[abc]", offset=1, limit=1)
    assert total == 3
    assert items == [("b", {"key": "b"})]


def test_bulk_legacy_migration_moves_clean_workspaces_and_quarantines_conflict(db):
    legacy_owner = "legacy-owner"
    target_owner = "canonical-owner"
    target_tenant = "idp:canonical"
    conflict_target = persist_analysis_state(
        db,
        owner_user_id=target_owner,
        tenant_id=target_tenant,
        diagram_id="conflict-diagram",
        snapshot={"scope": "target", "mappings": []},
    )
    clean_one = persist_analysis_state(
        db,
        owner_user_id=legacy_owner,
        tenant_id="default_tenant",
        diagram_id="clean-one",
        snapshot={"scope": "clean-one", "mappings": []},
    )
    clean_two_workspace = create_workspace(
        db,
        owner_user_id=legacy_owner,
        tenant_id="default_tenant",
        name="second clean",
    )
    clean_two = persist_analysis_state(
        db,
        owner_user_id=legacy_owner,
        tenant_id="default_tenant",
        diagram_id="clean-two",
        workspace_id=clean_two_workspace.id,
        snapshot={"scope": "clean-two", "mappings": []},
    )
    conflict_workspace = create_workspace(
        db,
        owner_user_id=legacy_owner,
        tenant_id="default_tenant",
        name="conflicting",
    )
    legacy_conflict = persist_analysis_state(
        db,
        owner_user_id=legacy_owner,
        tenant_id="default_tenant",
        diagram_id="conflict-diagram",
        workspace_id=conflict_workspace.id,
        snapshot={"scope": "legacy", "mappings": []},
    )

    summary = rehome_legacy_owner_scope(
        db,
        owner_user_ids=[legacy_owner],
        source_tenant_id="default_tenant",
        target_tenant_id=target_tenant,
        target_owner_user_id=target_owner,
    )
    repeated = rehome_legacy_owner_scope(
        db,
        owner_user_ids=[legacy_owner],
        source_tenant_id="default_tenant",
        target_tenant_id=target_tenant,
        target_owner_user_id=target_owner,
    )

    assert summary == {"rehomed": 2, "quarantined": 1, "already_processed": 0}
    assert repeated["rehomed"] == 0
    assert list_workspaces(db, owner_user_id=target_owner, tenant_id=target_tenant)["total"] == 3
    assert db.query(Workspace).filter_by(id=conflict_workspace.id, owner_user_id=legacy_owner).one()
    assert db.query(TenantRehomeAlias).filter_by(
        source_entity_id=legacy_conflict.analysis.id,
        status="quarantined",
    ).one()
    assert db.query(TenantRehomeAlias).filter_by(
        source_entity_id=clean_one.analysis.id,
        status="rehomed",
    ).one()
    assert db.query(TenantRehomeAlias).filter_by(
        source_entity_id=clean_two.analysis.id,
        status="rehomed",
    ).one()
    assert conflict_target.analysis.owner_user_id == target_owner


def test_bulk_legacy_migration_never_moves_another_owner(db):
    foreign = persist_analysis_state(
        db,
        owner_user_id="foreign-owner",
        tenant_id="default_tenant",
        diagram_id="foreign-diagram",
        snapshot={"mappings": []},
    )
    rehome_legacy_owner_scope(
        db,
        owner_user_ids=["requested-owner"],
        source_tenant_id="default_tenant",
        target_tenant_id="idp:requested",
        target_owner_user_id="requested-owner",
    )
    db.refresh(foreign.analysis)
    assert foreign.analysis.owner_user_id == "foreign-owner"
    assert foreign.analysis.tenant_id == "default_tenant"


def test_workspace_list_discovers_clean_legacy_graphs_before_known_id_access(
    test_client,
    tmp_path,
    monkeypatch,
):
    import database

    engine = create_engine(
        f"sqlite:///{tmp_path / 'legacy-list.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(database, "SessionLocal", factory)
    owner = "legacy-list-owner"
    target_tenant = "idp:legacy-list-target"
    db = factory()
    try:
        first = persist_analysis_state(
            db,
            owner_user_id=owner,
            tenant_id="default_tenant",
            diagram_id="legacy-list-one",
            snapshot={"mappings": []},
        )
        second_workspace = create_workspace(
            db,
            owner_user_id=owner,
            tenant_id="default_tenant",
            name="Second legacy workspace",
        )
        persist_analysis_state(
            db,
            owner_user_id=owner,
            tenant_id="default_tenant",
            diagram_id="legacy-list-two",
            workspace_id=second_workspace.id,
            snapshot={"mappings": []},
        )
        first_workspace_id = first.analysis.workspace_id
    finally:
        db.close()

    try:
        response = test_client.get(
            "/api/workspaces",
            headers=_bearer_headers(owner, target_tenant),
        )
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 2
        assert {item["id"] for item in response.json()["workspaces"]} == {
            first_workspace_id,
            second_workspace.id,
        }
        db = factory()
        try:
            assert list_workspaces(
                db,
                owner_user_id=owner,
                tenant_id="default_tenant",
            )["total"] == 0
        finally:
            db.close()
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_export_artifact_is_version_bound_idempotent_and_changes_with_version(db):
    first = persist_analysis_state(
        db,
        owner_user_id="export-owner",
        tenant_id="export-tenant",
        diagram_id="export-diagram",
        snapshot={"value": 1, "mappings": []},
    )
    payload = b"exact generated bytes"
    artifact = create_export_artifact(
        db,
        diagram_id="export-diagram",
        owner_user_id="export-owner",
        tenant_id="export-tenant",
        artifact_type="report",
        format="txt",
        content=payload,
    )
    retry = create_export_artifact(
        db,
        diagram_id="export-diagram",
        owner_user_id="export-owner",
        tenant_id="export-tenant",
        artifact_type="report",
        format="txt",
        content=payload,
    )
    assert retry.id == artifact.id
    assert artifact.version_id == first.version.id
    assert artifact.content_hash == hashlib.sha256(payload).hexdigest()
    assert artifact.content.encode() == payload

    persist_analysis_state(
        db,
        owner_user_id="export-owner",
        tenant_id="export-tenant",
        diagram_id="export-diagram",
        snapshot={"value": 2, "mappings": []},
        label="second",
    )
    second_artifact = create_export_artifact(
        db,
        diagram_id="export-diagram",
        owner_user_id="export-owner",
        tenant_id="export-tenant",
        artifact_type="report",
        format="txt",
        content=payload,
    )
    assert second_artifact.id != artifact.id
    assert second_artifact.version_id != artifact.version_id
    assert db.query(Artifact).filter_by(owner_user_id="foreign-owner").count() == 0


def test_report_export_route_binds_exact_bytes_and_survives_cache_loss(test_client, monkeypatch):
    from database import SessionLocal
    from routers.shared import SESSION_STORE

    owner = "export-api-owner"
    tenant = "export-api-tenant"
    diagram_id = "export-api-diagram"
    monkeypatch.setattr(
        "export_artifacts._upload_blob",
        lambda **kwargs: f"testblob://{kwargs['content_hash']}",
    )
    db = SessionLocal()
    try:
        first = persist_analysis_state(
            db,
            owner_user_id=owner,
            tenant_id=tenant,
            diagram_id=diagram_id,
            snapshot={
                "title": "Version-bound report",
                "mappings": [{
                    "source_service": "Lambda",
                    "azure_service": "Azure Functions",
                    "confidence": 0.95,
                    "category": "Compute",
                }],
                "zones": [],
                "warnings": [],
            },
            session_store=SESSION_STORE,
            cache_required=True,
        )
    finally:
        db.close()
    headers = _bearer_headers(owner, tenant)
    first_response = test_client.get(f"/api/diagrams/{diagram_id}/report", headers=headers)
    retry_response = test_client.get(f"/api/diagrams/{diagram_id}/report", headers=headers)
    assert first_response.status_code == retry_response.status_code == 200
    assert first_response.content == retry_response.content
    assert first_response.headers["x-artifact-id"] == retry_response.headers["x-artifact-id"]
    assert first_response.headers["x-analysis-version-id"] == first.version.id
    assert first_response.headers["x-artifact-sha256"] == hashlib.sha256(first_response.content).hexdigest()

    SESSION_STORE.delete(diagram_id)
    cache_loss_response = test_client.get(f"/api/diagrams/{diagram_id}/report", headers=headers)
    assert cache_loss_response.status_code == 200
    assert cache_loss_response.headers["x-artifact-id"] == first_response.headers["x-artifact-id"]

    db = SessionLocal()
    try:
        current = SESSION_STORE.peek(diagram_id)
        second = persist_analysis_state(
            db,
            owner_user_id=owner,
            tenant_id=tenant,
            diagram_id=diagram_id,
            snapshot={**current, "title": "Version two"},
            label="report-version-two",
            expected_version=first.version.version_number,
        )
    finally:
        db.close()
    second_response = test_client.get(f"/api/diagrams/{diagram_id}/report", headers=headers)
    assert second_response.status_code == 200
    assert second_response.headers["x-analysis-version-id"] == second.version.id
    assert second_response.headers["x-artifact-id"] != first_response.headers["x-artifact-id"]


def test_replay_is_version_bound_paged_and_survives_projection_loss(db):
    result = persist_analysis_state(
        db,
        owner_user_id="replay-owner",
        tenant_id="replay-tenant",
        diagram_id="replay-diagram",
        snapshot={"mappings": []},
    )
    replay = create_migration_replay(
        db,
        diagram_id="replay-diagram",
        owner_user_id="replay-owner",
        tenant_id="replay-tenant",
        title="Replay",
    )
    add_migration_replay_event(
        db,
        replay_id=replay.id,
        owner_user_id="replay-owner",
        tenant_id="replay-tenant",
        event_type="step_entered",
        data={"step": 1},
    )
    payload = serialize_migration_replay(db, replay)
    listed = list_migration_replays(
        db,
        owner_user_id="replay-owner",
        tenant_id="replay-tenant",
        limit=1,
        offset=0,
    )
    assert replay.version_id == result.version.id
    assert payload["events"][0]["data"] == {"step": 1}
    assert listed["total"] == 1
    assert listed["replays"][0]["event_count"] == 1
    assert list_migration_replays(
        db,
        owner_user_id="foreign-owner",
        tenant_id="replay-tenant",
        limit=20,
        offset=0,
    )["total"] == 0


def test_workspace_status_and_default_reactivation_invariants(db):
    default = create_workspace(
        db,
        owner_user_id="status-owner",
        tenant_id="status-tenant",
        name="Default",
        is_default=True,
    )
    replacement = create_workspace(
        db,
        owner_user_id="status-owner",
        tenant_id="status-tenant",
        name="Replacement",
    )
    archived = update_workspace(
        db,
        default.id,
        owner_user_id="status-owner",
        tenant_id="status-tenant",
        status="archived",
    )
    assert archived.is_default is False
    reactivated = update_workspace(
        db,
        replacement.id,
        owner_user_id="status-owner",
        tenant_id="status-tenant",
        status="active",
    )
    assert reactivated.is_default is True
    with pytest.raises(ValueError, match="Unsupported workspace status"):
        update_workspace(
            db,
            replacement.id,
            owner_user_id="status-owner",
            tenant_id="status-tenant",
            status="arbitrary",
        )


@pytest.mark.asyncio
async def test_db_call_keeps_event_loop_responsive_and_propagates_exceptions(monkeypatch):
    class FakeSession:
        def close(self):
            return None

    monkeypatch.setattr("database.SessionLocal", FakeSession)
    started = threading.Event()
    release = threading.Event()

    def blocked(_db):
        started.set()
        release.wait(timeout=2)
        return "done"

    task = asyncio.create_task(_db_call(blocked))
    await asyncio.to_thread(started.wait, 1)
    ticked = False

    async def tick():
        nonlocal ticked
        await asyncio.sleep(0)
        ticked = True

    await tick()
    assert ticked is True
    release.set()
    assert await task == "done"

    def fail(_db):
        raise RuntimeError("database failed")

    with pytest.raises(RuntimeError, match="database failed"):
        await _db_call(fail)


def test_quarantine_operator_listing_owner_indicator_resolution_and_repeat(db):
    legacy_owner = "quarantine-legacy-owner"
    target_owner = "quarantine-target-owner"
    target_tenant = "quarantine-target-tenant"
    target = persist_analysis_state(
        db,
        owner_user_id=target_owner,
        tenant_id=target_tenant,
        diagram_id="quarantine-conflict",
        snapshot={"scope": "target", "mappings": []},
    )
    legacy = persist_analysis_state(
        db,
        owner_user_id=legacy_owner,
        tenant_id="default_tenant",
        diagram_id="quarantine-conflict",
        snapshot={"scope": "legacy", "mappings": []},
    )
    summary = rehome_legacy_owner_scope(
        db,
        owner_user_ids=[legacy_owner],
        source_tenant_id="default_tenant",
        target_tenant_id=target_tenant,
        target_owner_user_id=target_owner,
    )
    assert summary["quarantined"] == 1

    listed = list_quarantined_legacy_graphs(db)
    assert listed["total"] == 1
    quarantine = listed["quarantines"][0]
    assert quarantine["workspace_id"] == legacy.analysis.workspace_id
    assert "snapshot" not in quarantine
    assert owner_migration_conflict_status(
        db,
        target_owner_user_id=target_owner,
        target_tenant_id=target_tenant,
    ) == {
        "has_conflicts": True,
        "conflict_count": 1,
        "status": "action_required",
    }
    assert owner_migration_conflict_status(
        db,
        target_owner_user_id="foreign-owner",
        target_tenant_id=target_tenant,
    ) == {
        "has_conflicts": False,
        "conflict_count": 0,
        "status": "ready",
    }

    db.delete(target.analysis)
    db.commit()
    resolved = resolve_quarantined_legacy_graph(db, alias_id=quarantine["alias_id"])
    repeated = resolve_quarantined_legacy_graph(db, alias_id=quarantine["alias_id"])
    assert resolved == {
        "alias_id": quarantine["alias_id"],
        "status": "resolved",
        "idempotent": False,
    }
    assert repeated["idempotent"] is True
    db.refresh(legacy.analysis)
    assert legacy.analysis.owner_user_id == target_owner
    assert legacy.analysis.tenant_id == target_tenant
    assert list_quarantined_legacy_graphs(db)["total"] == 0


def test_quarantine_admin_api_is_protected_lists_and_resolves(
    test_client,
    tmp_path,
    monkeypatch,
):
    import admin_auth
    import database

    engine = create_engine(
        f"sqlite:///{tmp_path / 'quarantine-admin.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(database, "SessionLocal", factory)
    monkeypatch.setattr(admin_auth, "ADMIN_SECRET", "configured-admin-secret")
    monkeypatch.setattr(
        admin_auth,
        "JWT_SECRET",
        "configured-admin-jwt-secret-with-safe-test-length",
    )
    db = factory()
    try:
        workspace = create_workspace(
            db,
            owner_user_id="legacy-admin-owner",
            tenant_id="default_tenant",
            name="Quarantined",
        )
        alias = TenantRehomeAlias(
            source_owner_user_id="legacy-admin-owner",
            source_tenant_id="default_tenant",
            target_owner_user_id="target-admin-owner",
            target_tenant_id="target-admin-tenant",
            entity_type="workspace",
            source_entity_id=workspace.id,
            status="quarantined",
            reason="target_diagram_conflict",
        )
        db.add(alias)
        db.commit()
        alias_id = alias.id
    finally:
        db.close()
    try:
        denied = test_client.get("/api/admin/migration-quarantines")
        assert denied.status_code == 401
        headers = {"Authorization": f"Bearer {admin_auth.create_session_token()}"}
        listed = test_client.get("/api/admin/migration-quarantines", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        resolved = test_client.post(
            f"/api/admin/migration-quarantines/{alias_id}/resolve",
            headers=headers,
        )
        repeated = test_client.post(
            f"/api/admin/migration-quarantines/{alias_id}/resolve",
            headers=headers,
        )
        assert resolved.status_code == repeated.status_code == 200
        assert repeated.json()["idempotent"] is True
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()