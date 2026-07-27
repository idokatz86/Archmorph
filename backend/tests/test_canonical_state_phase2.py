"""Deterministic regressions for canonical mutation, restore, linking, and purge."""

from __future__ import annotations

import copy
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from auth import AuthProvider, User, UserTier, generate_session_token
from database import Base
from error_envelope import ArchmorphException
from models.workspace import (
    Analysis,
    AnalysisMutationReceipt,
    AnalysisVersion,
    DiagramLifecycle,
    PurgeOperation,
    RestoreGrant,
    Workspace,
)
from purge_service import PurgeIncompleteError, diagram_fixed_point, purge_diagram, purge_workspace
from routers.shared import IMAGE_STORE, PROJECT_STORE, SESSION_STORE
from session_store import InMemoryStore
from starlette.requests import Request
from tests.conftest import SAMPLE_ANALYSIS
from workspace_store import (
    AnalysisCacheWriteError,
    AnalysisVersionConflictError,
    consume_restore_grant,
    get_analysis_by_diagram,
    issue_restore_grant,
    load_analysis_state,
    persist_analysis_mutation,
    persist_analysis_state,
    snapshot_payload_hash,
)


@pytest.fixture()
def phase2_runtime(tmp_path, monkeypatch):
    import database
    from routers import diff_routes, versioning

    engine = create_engine(
        f"sqlite:///{tmp_path / 'canonical-phase2.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(database, "SessionLocal", factory)
    monkeypatch.setattr(diff_routes, "SessionLocal", factory)
    monkeypatch.setattr(versioning, "SessionLocal", factory)
    SESSION_STORE.clear()
    IMAGE_STORE.clear()
    PROJECT_STORE.clear()
    yield factory
    SESSION_STORE.clear()
    IMAGE_STORE.clear()
    PROJECT_STORE.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _identity(prefix: str = "phase2"):
    suffix = uuid.uuid4().hex
    owner = f"{prefix}-{suffix}"
    tenant = f"tenant-{suffix}"
    user = User(
        id=owner,
        provider=AuthProvider.GITHUB,
        tier=UserTier.TEAM,
        tenant_id=tenant,
    )
    token = generate_session_token(user)
    headers = {"Authorization": f"Bearer {token}"}
    request = Request(
        {
            "type": "http",
            "headers": [(b"authorization", headers["Authorization"].encode())],
        }
    )
    return owner, tenant, headers, request


def _seed(factory, owner: str, tenant: str, diagram_id: str, *, workspace_id=None):
    db = factory()
    try:
        snapshot = copy.deepcopy(SAMPLE_ANALYSIS)
        snapshot["diagram_id"] = diagram_id
        return persist_analysis_state(
            db,
            owner_user_id=owner,
            tenant_id=tenant,
            diagram_id=diagram_id,
            workspace_id=workspace_id,
            snapshot=snapshot,
            session_store=SESSION_STORE,
            cache_required=True,
        )
    finally:
        db.close()


def _mutation_hash(operation: str, snapshot: dict) -> str:
    return hashlib.sha256(json.dumps(
        {"operation": operation, "snapshot": snapshot},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()).hexdigest()


def test_stale_cache_v1_cannot_overwrite_durable_v2_and_is_rehydrated(phase2_runtime):
    owner, tenant, _headers, _request = _identity("stale")
    diagram_id = f"diag-{uuid.uuid4().hex}"
    first = _seed(phase2_runtime, owner, tenant, diagram_id)
    db = phase2_runtime()
    try:
        current = load_analysis_state(
            db,
            diagram_id=diagram_id,
            owner_user_id=owner,
            tenant_id=tenant,
        )
        current["durable_value"] = "v2"
        second = persist_analysis_mutation(
            db,
            owner_user_id=owner,
            tenant_id=tenant,
            diagram_id=diagram_id,
            snapshot=current,
            expected_version=1,
            operation="advance",
            request_hash=_mutation_hash("advance", current),
        )
        stale = json.loads(first.version.snapshot)
        stale["_analysis_version"] = 1
        stale["durable_value"] = "stale-overwrite"
        with pytest.raises(AnalysisVersionConflictError):
            persist_analysis_mutation(
                db,
                owner_user_id=owner,
                tenant_id=tenant,
                diagram_id=diagram_id,
                snapshot=stale,
                expected_version=1,
                operation="stale-write",
                request_hash=_mutation_hash("stale-write", stale),
            )
        durable = load_analysis_state(
            db,
            diagram_id=diagram_id,
            owner_user_id=owner,
            tenant_id=tenant,
            session_store=SESSION_STORE,
        )
        assert second.version.version_number == 2
        assert durable["durable_value"] == "v2"
        assert durable["_analysis_version"] == 2
        assert db.query(AnalysisVersion).filter_by(analysis_id=first.analysis.id).count() == 2
    finally:
        db.close()


def test_cache_claiming_newer_version_is_replaced_by_postgres(phase2_runtime):
    owner, tenant, _headers, _request = _identity("false-newer")
    diagram_id = f"diag-{uuid.uuid4().hex}"
    _seed(phase2_runtime, owner, tenant, diagram_id)
    SESSION_STORE.set(
        diagram_id,
        {
            "diagram_id": diagram_id,
            "_owner_user_id": owner,
            "_tenant_id": tenant,
            "_analysis_version": 999,
            "value": "not-durable",
        },
    )
    db = phase2_runtime()
    try:
        hydrated = load_analysis_state(
            db,
            diagram_id=diagram_id,
            owner_user_id=owner,
            tenant_id=tenant,
            session_store=SESSION_STORE,
        )
    finally:
        db.close()

    assert hydrated["_analysis_version"] == 1
    assert SESSION_STORE.peek(diagram_id)["_analysis_version"] == 1
    assert "value" not in SESSION_STORE.peek(diagram_id)


def test_post_commit_cache_failure_retry_returns_same_durable_version(phase2_runtime):
    owner, tenant, _headers, _request = _identity("retry")
    diagram_id = f"diag-{uuid.uuid4().hex}"
    seeded = _seed(phase2_runtime, owner, tenant, diagram_id)
    db = phase2_runtime()
    operation = "post-commit-cache-failure"
    snapshot = load_analysis_state(db, diagram_id=diagram_id, owner_user_id=owner, tenant_id=tenant)
    snapshot["value"] = "committed-once"
    request_hash = _mutation_hash(operation, snapshot)

    class FailingProjection(InMemoryStore):
        def update_if(self, *_args, **_kwargs):
            raise RuntimeError("projection failed")

    try:
        with pytest.raises(AnalysisCacheWriteError):
            persist_analysis_mutation(
                db,
                owner_user_id=owner,
                tenant_id=tenant,
                diagram_id=diagram_id,
                snapshot=snapshot,
                expected_version=1,
                operation=operation,
                request_hash=request_hash,
                session_store=FailingProjection(),
                cache_required=True,
            )
        retry = persist_analysis_mutation(
            db,
            owner_user_id=owner,
            tenant_id=tenant,
            diagram_id=diagram_id,
            snapshot=snapshot,
            expected_version=1,
            operation=operation,
            request_hash=request_hash,
            session_store=SESSION_STORE,
            cache_required=True,
        )
        assert retry.idempotent_replay is True
        assert retry.version.version_number == 2
        assert db.query(AnalysisVersion).filter_by(analysis_id=seeded.analysis.id).count() == 2
        assert db.query(AnalysisMutationReceipt).filter_by(analysis_id=seeded.analysis.id).count() == 1
        assert SESSION_STORE.peek(diagram_id)["_analysis_version"] == 2
    finally:
        db.close()


def test_authenticated_analysis_retry_after_projection_failure_is_idempotent(
    phase2_runtime,
    monkeypatch,
):
    from routers import diagrams

    owner, tenant, _headers, _request = _identity("analysis-retry")
    diagram_id = f"diag-{uuid.uuid4().hex}"
    db = phase2_runtime()
    workspace = Workspace(
        id=f"proj-{uuid.uuid4().hex[:24]}",
        owner_user_id=owner,
        tenant_id=tenant,
        name="Project",
        status="active",
        is_default=False,
    )
    db.add(workspace)
    db.commit()
    from project_store import register_diagram

    register_diagram(
        db,
        project_id=workspace.id,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
        filename="retry.png",
    )
    original_update_if = SESSION_STORE.update_if
    monkeypatch.setattr(
        SESSION_STORE,
        "update_if",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cache failed")),
    )
    snapshot = {"diagram_id": diagram_id, "value": "same-result", "mappings": []}
    with pytest.raises(ArchmorphException) as exc_info:
        diagrams._persist_authenticated_analysis(
            db,
            user_id=owner,
            tenant_id=tenant,
            diagram_id=diagram_id,
            session=copy.deepcopy(snapshot),
            cache_required=True,
            require_project_membership=True,
        )
    assert exc_info.value.status_code == 503
    monkeypatch.setattr(SESSION_STORE, "update_if", original_update_if)
    retry = diagrams._persist_authenticated_analysis(
        db,
        user_id=owner,
        tenant_id=tenant,
        diagram_id=diagram_id,
        session=copy.deepcopy(snapshot),
        cache_required=True,
        require_project_membership=True,
    )
    assert retry.version.version_number == 1
    assert retry.idempotent_replay is True
    assert db.query(AnalysisVersion).filter_by(analysis_id=retry.analysis.id).count() == 1
    db.close()


def test_restore_grant_is_one_time_and_bound_to_scope_hash_version_and_expiry(phase2_runtime):
    owner, tenant, _headers, _request = _identity("grant")
    diagram_id = f"diag-{uuid.uuid4().hex}"
    seeded = _seed(phase2_runtime, owner, tenant, diagram_id)
    payload = json.loads(seeded.version.snapshot)
    payload_hash = snapshot_payload_hash(payload)
    db = phase2_runtime()
    try:
        nonce, generation, expected_version = issue_restore_grant(
            db,
            owner_user_id=owner,
            tenant_id=tenant,
            diagram_id=diagram_id,
            ttl_seconds=60,
            payload_hash=payload_hash,
        )
        assert consume_restore_grant(
            db,
            nonce=nonce,
            owner_user_id=owner,
            tenant_id=tenant,
            diagram_id=diagram_id,
            generation=generation,
            expected_version=expected_version,
            payload_hash=payload_hash,
        ) is True
        assert consume_restore_grant(
            db,
            nonce=nonce,
            owner_user_id=owner,
            tenant_id=tenant,
            diagram_id=diagram_id,
            generation=generation,
            expected_version=expected_version,
            payload_hash=payload_hash,
        ) is False

        for wrong in ("owner", "tenant", "hash", "version"):
            nonce, generation, expected_version = issue_restore_grant(
                db,
                owner_user_id=owner,
                tenant_id=tenant,
                diagram_id=diagram_id,
                ttl_seconds=60,
                payload_hash=payload_hash,
            )
            assert consume_restore_grant(
                db,
                nonce=nonce,
                owner_user_id="wrong" if wrong == "owner" else owner,
                tenant_id="wrong" if wrong == "tenant" else tenant,
                diagram_id=diagram_id,
                generation=generation,
                expected_version=expected_version + (1 if wrong == "version" else 0),
                payload_hash="wrong" if wrong == "hash" else payload_hash,
            ) is False

        nonce, generation, expected_version = issue_restore_grant(
            db,
            owner_user_id=owner,
            tenant_id=tenant,
            diagram_id=diagram_id,
            ttl_seconds=60,
        )
        grant = db.query(RestoreGrant).filter_by(
            nonce_digest=hashlib.sha256(nonce.encode()).hexdigest()
        ).one()
        grant.expires_at = datetime.fromtimestamp(time.time() - 1, tz=timezone.utc)
        db.commit()
        assert consume_restore_grant(
            db,
            nonce=nonce,
            owner_user_id=owner,
            tenant_id=tenant,
            diagram_id=diagram_id,
            generation=generation,
            expected_version=expected_version,
            payload_hash=payload_hash,
        ) is False
    finally:
        db.close()


def test_restore_route_uses_durable_v2_not_stale_browser_v1(test_client, phase2_runtime):
    owner, tenant, headers, _request = _identity("restore-authority")
    diagram_id = f"diag-{uuid.uuid4().hex}"
    first = _seed(phase2_runtime, owner, tenant, diagram_id)
    db = phase2_runtime()
    try:
        current = load_analysis_state(db, diagram_id=diagram_id, owner_user_id=owner, tenant_id=tenant)
        current["server_value"] = "v2"
        persist_analysis_mutation(
            db,
            owner_user_id=owner,
            tenant_id=tenant,
            diagram_id=diagram_id,
            snapshot=current,
            expected_version=1,
            operation="server-v2",
            request_hash=_mutation_hash("server-v2", current),
        )
    finally:
        db.close()
    SESSION_STORE.delete(diagram_id)
    stale = json.loads(first.version.snapshot)
    stale["server_value"] = "v1-browser"

    response = test_client.post(
        f"/api/diagrams/{diagram_id}/restore-session",
        headers=headers,
        json={"analysis": stale},
    )

    assert response.status_code == 200, response.text
    assert response.json()["analysis"]["server_value"] == "v2"
    assert response.json()["analysis"]["_analysis_version"] == 2
    assert SESSION_STORE.peek(diagram_id)["server_value"] == "v2"


def test_existing_durable_restore_ignores_browser_artifacts_and_image(
    test_client,
    phase2_runtime,
):
    owner, tenant, headers, _request = _identity("restore-artifacts")
    diagram_id = f"diag-{uuid.uuid4().hex}"
    _seed(phase2_runtime, owner, tenant, diagram_id)
    SESSION_STORE.delete(diagram_id)

    response = test_client.post(
        f"/api/diagrams/{diagram_id}/restore-session",
        headers=headers,
        json={
            "analysis": {"diagram_id": diagram_id, "mappings": [], "stale": True},
            "hld": {"title": "stale browser HLD"},
            "iac_code": "stale browser IaC",
            "iac_format": "terraform",
        },
    )

    assert response.status_code == 200, response.text
    authoritative = response.json()["analysis"]
    assert "stale" not in authoritative
    assert "hld" not in authoritative
    assert "_cached_iac_code" not in authoritative
    assert IMAGE_STORE.peek(diagram_id) is None


def test_purge_revokes_restore_grant_and_replay_cannot_recreate(phase2_runtime):
    owner, tenant, _headers, _request = _identity("purge-replay")
    diagram_id = f"diag-{uuid.uuid4().hex}"
    seeded = _seed(phase2_runtime, owner, tenant, diagram_id)
    payload = json.loads(seeded.version.snapshot)
    payload_hash = snapshot_payload_hash(payload)
    db = phase2_runtime()
    try:
        nonce, generation, expected_version = issue_restore_grant(
            db,
            owner_user_id=owner,
            tenant_id=tenant,
            diagram_id=diagram_id,
            ttl_seconds=60,
            payload_hash=payload_hash,
        )
    finally:
        db.close()

    result = purge_diagram(diagram_id=diagram_id, owner_user_id=owner, tenant_id=tenant)
    assert result.status == "completed"
    db = phase2_runtime()
    try:
        assert consume_restore_grant(
            db,
            nonce=nonce,
            owner_user_id=owner,
            tenant_id=tenant,
            diagram_id=diagram_id,
            generation=generation,
            expected_version=expected_version,
            payload_hash=payload_hash,
        ) is False
        with pytest.raises(ValueError, match="purged"):
            persist_analysis_state(
                db,
                owner_user_id=owner,
                tenant_id=tenant,
                diagram_id=diagram_id,
                snapshot=payload,
            )
        lifecycle = db.query(DiagramLifecycle).filter_by(
            owner_user_id=owner,
            tenant_id=tenant,
            diagram_id=diagram_id,
        ).one()
        assert lifecycle.state == "purged"
        assert lifecycle.generation > generation
    finally:
        db.close()


def test_diagram_purge_failure_each_stage_retries_to_fixed_point(phase2_runtime, monkeypatch):
    import purge_service as purge_module

    stages = [
        "session",
        "image",
        "vision_cache",
        "export_capabilities",
        "share_store",
        "share_links",
        "jobs",
        "iac_chat",
        "collaboration",
        "replays",
        "history",
        "version_history",
        "durable_graph",
    ]
    for stage in stages:
        owner, tenant, _headers, _request = _identity(f"stage-{stage}")
        diagram_id = f"diag-{uuid.uuid4().hex}"
        _seed(phase2_runtime, owner, tenant, diagram_id)
        IMAGE_STORE.set(diagram_id, ("aW1hZ2U=", "image/png"))
        original = purge_module._run_stage
        failed_once = False

        def injected(operation_id, current_stage, callback):
            nonlocal failed_once
            if current_stage == stage and not failed_once:
                failed_once = True
                db = phase2_runtime()
                try:
                    from workspace_store import record_purge_stage

                    record_purge_stage(
                        db,
                        operation_id,
                        stage=current_stage,
                        result={"confirmed_absent": False, "injected": True},
                        failed=True,
                    )
                finally:
                    db.close()
                raise PurgeIncompleteError(operation_id, current_stage)
            return original(operation_id, current_stage, callback)

        monkeypatch.setattr(purge_module, "_run_stage", injected)
        with pytest.raises(PurgeIncompleteError) as exc_info:
            purge_diagram(diagram_id=diagram_id, owner_user_id=owner, tenant_id=tenant)
        operation_id = exc_info.value.operation_id
        monkeypatch.setattr(purge_module, "_run_stage", original)
        retried = purge_diagram(diagram_id=diagram_id, owner_user_id=owner, tenant_id=tenant)
        assert retried.operation_id == operation_id
        assert retried.status == "completed"
        assert diagram_fixed_point(diagram_id, owner, tenant)


def test_pending_purge_tombstone_blocks_reads_before_cache_cleanup(
    test_client,
    phase2_runtime,
    monkeypatch,
):
    import purge_service as purge_module

    owner, tenant, headers, _request = _identity("pending-read")
    diagram_id = f"diag-{uuid.uuid4().hex}"
    _seed(phase2_runtime, owner, tenant, diagram_id)
    original = purge_module._run_stage

    def fail_session(operation_id, stage, callback):
        if stage == "session":
            raise PurgeIncompleteError(operation_id, stage)
        return original(operation_id, stage, callback)

    monkeypatch.setattr(purge_module, "_run_stage", fail_session)
    with pytest.raises(PurgeIncompleteError):
        purge_diagram(diagram_id=diagram_id, owner_user_id=owner, tenant_id=tenant)
    assert SESSION_STORE.peek(diagram_id) is not None

    response = test_client.get(
        f"/api/diagrams/{diagram_id}/review-queue",
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Diagram not found"


def test_workspace_purge_removes_children_project_cache_and_blocks_resurrection(phase2_runtime):
    from services import credential_manager

    owner, tenant, _headers, _request = _identity("workspace-purge")
    db = phase2_runtime()
    workspace = Workspace(
        id=f"proj-{uuid.uuid4().hex[:24]}",
        owner_user_id=owner,
        tenant_id=tenant,
        name="Delete me",
        status="active",
        is_default=False,
    )
    db.add(workspace)
    db.commit()
    workspace_id = workspace.id
    db.close()
    first = _seed(phase2_runtime, owner, tenant, f"diag-{uuid.uuid4().hex}", workspace_id=workspace_id)
    second = _seed(phase2_runtime, owner, tenant, f"diag-{uuid.uuid4().hex}", workspace_id=workspace_id)
    PROJECT_STORE.set(workspace_id, {"project_id": workspace_id, "project_version": 2})
    credential_manager.store_credentials(
        f"workspace-token-{uuid.uuid4().hex}",
        provider="aws",
        creds={"access_key_id": "ephemeral"},
        owner_user_id=owner,
        tenant_id=tenant,
    )

    result = purge_workspace(workspace_id=workspace_id, owner_user_id=owner, tenant_id=tenant)

    assert result.status == "completed"
    assert set(result.deleted["diagrams"]) == {first.analysis.diagram_id, second.analysis.diagram_id}
    assert PROJECT_STORE.peek(workspace_id) is None
    assert credential_manager.scope_credentials_absent(owner, tenant) is True
    db = phase2_runtime()
    try:
        assert db.query(Workspace).filter_by(id=workspace_id).count() == 0
        assert db.query(Analysis).filter_by(workspace_id=workspace_id).count() == 0
        assert db.query(PurgeOperation).filter_by(
            scope_type="workspace",
            scope_id=workspace_id,
            status="completed",
        ).count() == 1
        with pytest.raises(ValueError):
            persist_analysis_state(
                db,
                owner_user_id=owner,
                tenant_id=tenant,
                diagram_id=first.analysis.diagram_id,
                workspace_id=workspace_id,
                snapshot={"mappings": []},
            )
    finally:
        db.close()


def test_workspace_link_requires_authoritative_snapshot_and_survives_cache_loss(
    test_client,
    phase2_runtime,
):
    owner, tenant, headers, _request = _identity("workspace-link")
    diagram_id = f"diag-{uuid.uuid4().hex}"
    seeded = _seed(phase2_runtime, owner, tenant, diagram_id)
    db = phase2_runtime()
    target = Workspace(
        id=f"proj-{uuid.uuid4().hex[:24]}",
        owner_user_id=owner,
        tenant_id=tenant,
        name="Target",
        status="active",
        is_default=False,
    )
    db.add(target)
    db.commit()
    target_id = target.id
    db.close()

    stale = copy.deepcopy(SESSION_STORE.peek(diagram_id))
    stale.pop("_analysis_version")
    SESSION_STORE.set(diagram_id, stale)
    linked = test_client.post(
        f"/api/workspaces/{target_id}/analyses",
        headers=headers,
        json={"diagram_id": diagram_id},
    )
    assert linked.status_code == 200, linked.text
    assert SESSION_STORE.peek(diagram_id)["_analysis_version"] >= 1
    SESSION_STORE.delete(diagram_id)
    db = phase2_runtime()
    try:
        analysis = get_analysis_by_diagram(
            db,
            diagram_id=diagram_id,
            owner_user_id=owner,
            tenant_id=tenant,
        )
        assert analysis.id == seeded.analysis.id
        assert analysis.workspace_id == target_id
        assert analysis.current_version >= 1
        assert load_analysis_state(
            db,
            diagram_id=diagram_id,
            owner_user_id=owner,
            tenant_id=tenant,
        ) is not None
    finally:
        db.close()
