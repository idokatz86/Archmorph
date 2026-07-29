"""Adversarial lifecycle and schema regressions for the remaining #1237 audit."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import io
import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from auth import AuthProvider, User, UserTier, generate_session_token
from database import Base
from main import SESSION_STORE, app
from models.tenant import Organization, TeamMember
from models.usage import FunnelStepRecord, UsageCounterRecord
from models.workspace import (
    AnalysisVersion,
    Decision,
    ProjectMember,
    PurgeOperation,
    RestoreGrant,
    Workspace,
)
from purge_service import PurgeIncompleteError, purge_diagram
import restore_grant_cleanup as cleanup_module
from restore_grant_cleanup import (
    RestoreGrantCleanupLifecycle,
    RestoreGrantCleanupRun,
    restore_grant_cleanup_metrics,
    run_restore_grant_cleanup,
)
from routers import collaboration_routes
from routers.hld_routes import _persist_async_hld
from routers.iac_routes import _persist_async_iac
from tests.conftest import SAMPLE_ANALYSIS
import usage_metrics
from workspace_store import (
    CanonicalWriteDeniedError,
    create_artifact,
    create_analysis,
    create_decision,
    link_analysis_to_workspace,
    load_analysis_state,
    persist_analysis_mutation,
    persist_analysis_state,
    rehome_legacy_analysis_scope,
    restore_analysis_version,
    save_analysis_version,
    update_workspace,
)


@pytest.fixture()
def lifecycle_runtime(tmp_path, monkeypatch):
    import database
    from routers import diagrams

    engine = create_engine(
        f"sqlite:///{tmp_path / 'remaining-lifecycle-audit.db'}",
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
    monkeypatch.setattr(diagrams, "SessionLocal", factory)
    SESSION_STORE.clear()
    collaboration_routes._session_store.clear()
    collaboration_routes._change_store.clear()
    yield factory
    SESSION_STORE.clear()
    collaboration_routes._session_store.clear()
    collaboration_routes._change_store.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def isolated_usage_metrics(tmp_path, monkeypatch):
    original_metrics = usage_metrics._metrics
    original_file = usage_metrics.METRICS_FILE
    usage_metrics._metrics = json.loads(json.dumps(usage_metrics._DEFAULT_METRICS))
    monkeypatch.setattr(usage_metrics, "METRICS_FILE", str(tmp_path / "usage.json"))
    monkeypatch.setattr(usage_metrics, "AZURE_STORAGE_ACCOUNT_URL", "")
    monkeypatch.setattr(usage_metrics, "AZURE_STORAGE_CONNECTION_STRING", "")
    try:
        yield
    finally:
        usage_metrics._metrics = original_metrics
        usage_metrics.METRICS_FILE = original_file


def _headers(user_id: str, tenant_id: str) -> dict[str, str]:
    token = generate_session_token(
        User(
            id=user_id,
            provider=AuthProvider.GITHUB,
            tier=UserTier.TEAM,
            tenant_id=tenant_id,
        )
    )
    return {"Authorization": f"Bearer {token}"}


def _seed_explicit_project(
    factory,
    *,
    owner: str,
    tenant: str,
    diagram_id: str,
):
    db = factory()
    try:
        project = Workspace(
            id=f"proj-{uuid.uuid4().hex[:24]}",
            owner_user_id=owner,
            tenant_id=tenant,
            name="Lifecycle audit project",
            status="active",
            is_default=False,
        )
        db.add(project)
        db.commit()
        snapshot = copy.deepcopy(SAMPLE_ANALYSIS)
        snapshot["diagram_id"] = diagram_id
        result = persist_analysis_state(
            db,
            owner_user_id=owner,
            tenant_id=tenant,
            diagram_id=diagram_id,
            workspace_id=project.id,
            snapshot=snapshot,
            session_store=SESSION_STORE,
            cache_required=True,
        )
        return result
    finally:
        db.close()


def _seed(factory, *, owner: str, tenant: str, diagram_id: str):
    db = factory()
    try:
        snapshot = copy.deepcopy(SAMPLE_ANALYSIS)
        snapshot["diagram_id"] = diagram_id
        return persist_analysis_state(
            db,
            owner_user_id=owner,
            tenant_id=tenant,
            diagram_id=diagram_id,
            snapshot=snapshot,
        )
    finally:
        db.close()


def _archive(factory, workspace_id: str, owner: str, tenant: str) -> None:
    db = factory()
    try:
        assert (
            update_workspace(
                db,
                workspace_id,
                owner_user_id=owner,
                tenant_id=tenant,
                status="archived",
            )
            is not None
        )
    finally:
        db.close()


def test_archived_workspace_rejects_existing_append_new_analysis_and_restore(
    lifecycle_runtime,
):
    suffix = uuid.uuid4().hex
    owner = f"archive-owner-{suffix}"
    tenant = f"archive-tenant-{suffix}"
    diagram_id = f"archive-diagram-{suffix}"
    seeded = _seed(
        lifecycle_runtime,
        owner=owner,
        tenant=tenant,
        diagram_id=diagram_id,
    )
    _archive(lifecycle_runtime, seeded.analysis.workspace_id, owner, tenant)

    db = lifecycle_runtime()
    try:
        with pytest.raises(ValueError):
            save_analysis_version(
                db,
                analysis_id=seeded.analysis.id,
                owner_user_id=owner,
                tenant_id=tenant,
                snapshot={"mappings": [], "attempt": "append"},
            )
        with pytest.raises(ValueError):
            create_analysis(
                db,
                workspace_id=seeded.analysis.workspace_id,
                owner_user_id=owner,
                tenant_id=tenant,
                diagram_id=f"new-{diagram_id}",
            )
        with pytest.raises(ValueError):
            restore_analysis_version(
                db,
                analysis_id=seeded.analysis.id,
                version_number=1,
                owner_user_id=owner,
                tenant_id=tenant,
                expected_version=1,
                idempotency_key=f"restore-{suffix}",
            )
        assert (
            db.query(AnalysisVersion)
            .filter(AnalysisVersion.analysis_id == seeded.analysis.id)
            .count()
            == 1
        )
    finally:
        db.close()


def test_archived_workspace_rejects_existing_canonical_mutation(lifecycle_runtime):
    suffix = uuid.uuid4().hex
    owner = f"mutation-owner-{suffix}"
    tenant = f"mutation-tenant-{suffix}"
    diagram_id = f"mutation-diagram-{suffix}"
    seeded = _seed(
        lifecycle_runtime,
        owner=owner,
        tenant=tenant,
        diagram_id=diagram_id,
    )
    _archive(lifecycle_runtime, seeded.analysis.workspace_id, owner, tenant)

    db = lifecycle_runtime()
    try:
        stale = copy.deepcopy(SAMPLE_ANALYSIS)
        stale["diagram_id"] = diagram_id
        stale["_analysis_version"] = 1
        with pytest.raises(ValueError):
            persist_analysis_mutation(
                db,
                owner_user_id=owner,
                tenant_id=tenant,
                diagram_id=diagram_id,
                snapshot=stale,
                expected_version=1,
                operation="archived-mutation",
                request_hash="a" * 64,
            )
        assert (
            load_analysis_state(
                db,
                diagram_id=diagram_id,
                owner_user_id=owner,
                tenant_id=tenant,
            )
            is None
        )
    finally:
        db.close()


def test_archived_workspace_rejects_legacy_identity_rehome(lifecycle_runtime):
    suffix = uuid.uuid4().hex
    owner = f"rehome-owner-{suffix}"
    diagram_id = f"rehome-diagram-{suffix}"
    seeded = _seed(
        lifecycle_runtime,
        owner=owner,
        tenant="default_tenant",
        diagram_id=diagram_id,
    )
    _archive(
        lifecycle_runtime,
        seeded.analysis.workspace_id,
        owner,
        "default_tenant",
    )

    db = lifecycle_runtime()
    try:
        assert (
            rehome_legacy_analysis_scope(
                db,
                diagram_id=diagram_id,
                owner_user_id=owner,
                source_tenant_id="default_tenant",
                target_tenant_id=f"target-{suffix}",
            )
            == "not_found"
        )
        unchanged = db.query(Workspace).filter_by(id=seeded.analysis.workspace_id).one()
        assert unchanged.owner_user_id == owner
        assert unchanged.tenant_id == "default_tenant"
        assert unchanged.status == "archived"
    finally:
        db.close()


def test_archived_workspace_rejects_artifact_decision_move_and_async_completion(
    lifecycle_runtime,
):
    suffix = uuid.uuid4().hex
    owner = f"surface-owner-{suffix}"
    tenant = f"surface-tenant-{suffix}"
    diagram_id = f"surface-diagram-{suffix}"
    seeded = _seed_explicit_project(
        lifecycle_runtime,
        owner=owner,
        tenant=tenant,
        diagram_id=diagram_id,
    )
    latest = copy.deepcopy(SESSION_STORE.peek(diagram_id))

    db = lifecycle_runtime()
    try:
        target = Workspace(
            owner_user_id=owner,
            tenant_id=tenant,
            name="Archived move target",
            status="archived",
            is_default=False,
        )
        db.add(target)
        db.commit()
        with pytest.raises(CanonicalWriteDeniedError):
            link_analysis_to_workspace(
                db,
                diagram_id=diagram_id,
                workspace_id=target.id,
                owner_user_id=owner,
                tenant_id=tenant,
            )
    finally:
        db.close()

    _archive(lifecycle_runtime, seeded.analysis.workspace_id, owner, tenant)
    db = lifecycle_runtime()
    try:
        with pytest.raises(CanonicalWriteDeniedError):
            create_artifact(
                db,
                analysis_id=seeded.analysis.id,
                owner_user_id=owner,
                tenant_id=tenant,
                artifact_type="hld",
                content="must not persist",
            )
        with pytest.raises(CanonicalWriteDeniedError):
            create_decision(
                db,
                analysis_id=seeded.analysis.id,
                owner_user_id=owner,
                tenant_id=tenant,
                decision_type="risk",
                title="must not persist",
            )
    finally:
        db.close()

    job = SimpleNamespace(
        owner_user_id=owner,
        tenant_id=tenant,
        owner_api_key_id=None,
    )
    updated_hld = {**latest, "hld": {"title": "late"}}
    with pytest.raises(CanonicalWriteDeniedError):
        _persist_async_hld(
            job_id=f"hld-{suffix}",
            payload={"analysis_hash": "hld-input"},
            job_record=job,
            diagram_id=diagram_id,
            latest_session=latest,
            updated_session=updated_hld,
            markdown="# late",
        )
    updated_iac = {**latest, "iac_code": "late"}
    with pytest.raises(CanonicalWriteDeniedError):
        _persist_async_iac(
            job_id=f"iac-{suffix}",
            payload={"analysis_hash": "iac-input"},
            job_record=job,
            diagram_id=diagram_id,
            latest_session=latest,
            updated_session=updated_iac,
            iac_format="terraform",
            code="late",
            code_hash=hashlib.sha256(b"late").hexdigest(),
        )

    db = lifecycle_runtime()
    try:
        assert (
            db.query(AnalysisVersion)
            .filter(AnalysisVersion.analysis_id == seeded.analysis.id)
            .count()
            == 1
        )
        assert db.query(Decision).filter_by(analysis_id=seeded.analysis.id).count() == 0
    finally:
        db.close()


def test_archived_cache_cannot_authorize_hld_or_iac_route(
    test_client,
    lifecycle_runtime,
):
    suffix = uuid.uuid4().hex
    owner = f"route-owner-{suffix}"
    tenant = f"route-tenant-{suffix}"
    diagram_id = f"route-diagram-{suffix}"
    seeded = _seed_explicit_project(
        lifecycle_runtime,
        owner=owner,
        tenant=tenant,
        diagram_id=diagram_id,
    )
    _archive(lifecycle_runtime, seeded.analysis.workspace_id, owner, tenant)

    with (
        patch("routers.hld_routes.diagrams_compat.generate_hld") as hld_generator,
        patch("routers.iac_routes.generate_iac_code") as iac_generator,
    ):
        hld = test_client.post(
            f"/api/diagrams/{diagram_id}/generate-hld",
            headers=_headers(owner, tenant),
        )
        iac = test_client.post(
            f"/api/diagrams/{diagram_id}/generate?format=terraform",
            headers=_headers(owner, tenant),
        )
    assert hld.status_code == 404
    assert iac.status_code == 404
    hld_generator.assert_not_called()
    iac_generator.assert_not_called()


def test_archived_project_upload_route_does_not_allocate_replacement(
    test_client,
    lifecycle_runtime,
):
    suffix = uuid.uuid4().hex
    owner = f"upload-owner-{suffix}"
    tenant = f"upload-tenant-{suffix}"
    diagram_id = f"upload-existing-{suffix}"
    seeded = _seed_explicit_project(
        lifecycle_runtime,
        owner=owner,
        tenant=tenant,
        diagram_id=diagram_id,
    )
    project_id = seeded.analysis.workspace_id
    _archive(lifecycle_runtime, project_id, owner, tenant)

    response = test_client.post(
        f"/api/projects/{project_id}/diagrams",
        headers=_headers(owner, tenant),
        files={
            "file": (
                "archived.png",
                io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100),
                "image/png",
            )
        },
    )

    assert response.status_code == 404
    db = lifecycle_runtime()
    try:
        assert (
            db.query(Workspace).filter_by(owner_user_id=owner, tenant_id=tenant).count()
            == 1
        )
    finally:
        db.close()


def test_archived_analysis_restore_route_is_uniformly_denied(
    test_client,
    lifecycle_runtime,
):
    suffix = uuid.uuid4().hex
    owner = f"restore-route-owner-{suffix}"
    tenant = f"restore-route-tenant-{suffix}"
    diagram_id = f"restore-route-diagram-{suffix}"
    seeded = _seed_explicit_project(
        lifecycle_runtime,
        owner=owner,
        tenant=tenant,
        diagram_id=diagram_id,
    )
    _archive(lifecycle_runtime, seeded.analysis.workspace_id, owner, tenant)

    response = test_client.post(
        f"/api/analyses/{seeded.analysis.id}/versions/1/restore",
        headers={
            **_headers(owner, tenant),
            "If-Match": '"1"',
            "Idempotency-Key": f"restore-route-{suffix}",
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Version not found"


def test_archived_project_editor_collaboration_write_is_uniformly_denied(
    test_client,
    lifecycle_runtime,
):
    suffix = uuid.uuid4().hex
    owner = f"collab-owner-{suffix}"
    editor = f"collab-editor-{suffix}"
    tenant = f"collab-tenant-{suffix}"
    diagram_id = f"collab-diagram-{suffix}"
    seeded = _seed_explicit_project(
        lifecycle_runtime,
        owner=owner,
        tenant=tenant,
        diagram_id=diagram_id,
    )
    db = lifecycle_runtime()
    try:
        db.add(
            Organization(
                org_id=tenant,
                name="Collaboration tenant",
                slug=f"collab-{suffix}",
            )
        )
        db.flush()
        db.add(
            TeamMember(
                org_id=tenant,
                user_id=editor,
                email=f"{editor}@example.test",
                role="editor",
                is_active=True,
            )
        )
        db.add(
            ProjectMember(
                project_id=seeded.analysis.workspace_id,
                project_owner_user_id=owner,
                tenant_id=tenant,
                member_user_id=editor,
                role="editor",
            )
        )
        db.commit()
    finally:
        db.close()

    created = test_client.post(
        "/api/collab/sessions",
        headers=_headers(editor, tenant),
        json={"analysis_id": diagram_id, "owner": editor},
    )
    assert created.status_code == 200, created.text
    session_id = created.json()["session_id"]
    _archive(lifecycle_runtime, seeded.analysis.workspace_id, owner, tenant)

    denied = test_client.post(
        f"/api/collab/sessions/{session_id}/changes",
        headers=_headers(editor, tenant),
        json={
            "user_id": editor,
            "change_type": "comment",
            "payload": {"text": "must not persist"},
        },
    )
    assert denied.status_code == 404
    assert denied.json()["error"]["message"] == "Collaboration session not found"
    assert collaboration_routes._change_store.get(session_id, []) == []


def test_usage_purge_removes_subject_sessions_events_hashes_names_and_sql_scope(
    lifecycle_runtime,
    isolated_usage_metrics,
):
    suffix = uuid.uuid4().hex
    owner = f"usage-owner-{suffix}"
    tenant = f"usage-tenant-{suffix}"
    diagram_id = f"usage-diagram-{suffix}"
    foreign_owner = f"foreign-owner-{suffix}"
    foreign_tenant = f"foreign-tenant-{suffix}"
    foreign_diagram = f"foreign-diagram-{suffix}"
    sibling_diagram = f"sibling-diagram-{suffix}"
    _seed_explicit_project(
        lifecycle_runtime,
        owner=owner,
        tenant=tenant,
        diagram_id=diagram_id,
    )
    usage_metrics.record_event(
        "analyses_run",
        {
            "diagram_id": diagram_id,
            "owner_user_id": owner,
            "tenant_id": tenant,
            "filename": "private-architecture.png",
        },
    )
    usage_metrics.record_funnel_step(diagram_id, "upload")
    usage_metrics.record_event(
        "analyses_run",
        {
            "diagram_id": sibling_diagram,
            "owner_user_id": owner,
            "tenant_id": tenant,
            "filename": "sibling.png",
        },
    )
    usage_metrics.record_funnel_step(sibling_diagram, "upload")
    usage_metrics.record_event(
        "analyses_run",
        {
            "diagram_id": foreign_diagram,
            "owner_user_id": foreign_owner,
            "tenant_id": foreign_tenant,
            "filename": "foreign.png",
        },
    )
    usage_metrics.record_funnel_step(foreign_diagram, "upload")
    aggregate_before = copy.deepcopy(usage_metrics._metrics["counters"])
    funnel_total_before = copy.deepcopy(usage_metrics._metrics["funnel_totals"])

    db = lifecycle_runtime()
    try:
        db.add_all(
            [
                FunnelStepRecord(
                    diagram_id=diagram_id,
                    step="upload",
                    owner_user_id=owner,
                    tenant_id=tenant,
                ),
                FunnelStepRecord(
                    diagram_id=foreign_diagram,
                    step="upload",
                    owner_user_id=foreign_owner,
                    tenant_id=foreign_tenant,
                ),
                UsageCounterRecord(
                    counter_name=f"target-{suffix}",
                    date="2026-07-29",
                    count=7,
                    owner_user_id=owner,
                    tenant_id=tenant,
                ),
                UsageCounterRecord(
                    counter_name=f"foreign-{suffix}",
                    date="2026-07-29",
                    count=11,
                    owner_user_id=foreign_owner,
                    tenant_id=foreign_tenant,
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    removed = usage_metrics.purge_usage_telemetry(
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
    )

    assert removed["sessions"] == 1
    assert removed["events"] == 1
    assert usage_metrics._metrics["counters"] == aggregate_before
    assert usage_metrics._metrics["funnel_totals"] == funnel_total_before
    assert (
        usage_metrics._retained_identifier(diagram_id)
        not in usage_metrics._metrics["sessions"]
    )
    assert (
        usage_metrics._retained_identifier(sibling_diagram)
        in usage_metrics._metrics["sessions"]
    )
    assert (
        usage_metrics._retained_identifier(foreign_diagram)
        in usage_metrics._metrics["sessions"]
    )
    serialized = json.dumps(usage_metrics._metrics, sort_keys=True)
    assert diagram_id not in serialized
    assert usage_metrics._retained_identifier(diagram_id) not in serialized
    assert (
        usage_metrics._retained_identifier("private-architecture.png") not in serialized
    )
    assert usage_metrics._retained_identifier(sibling_diagram) in serialized
    assert foreign_diagram not in serialized
    assert usage_metrics._retained_identifier(foreign_diagram) in serialized

    db = lifecycle_runtime()
    try:
        assert db.query(FunnelStepRecord).filter_by(diagram_id=diagram_id).count() == 0
        assert (
            db.query(FunnelStepRecord).filter_by(diagram_id=foreign_diagram).count()
            == 1
        )
        target_counter = (
            db.query(UsageCounterRecord)
            .filter_by(counter_name=f"target-{suffix}")
            .one()
        )
        foreign_counter = (
            db.query(UsageCounterRecord)
            .filter_by(counter_name=f"foreign-{suffix}")
            .one()
        )
        assert target_counter.count == 7
        assert target_counter.owner_user_id is None
        assert target_counter.tenant_id is None
        assert foreign_counter.count == 11
        assert foreign_counter.owner_user_id == foreign_owner
        assert foreign_counter.tenant_id == foreign_tenant
    finally:
        db.close()
    assert usage_metrics.usage_telemetry_absent(
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
    )


def test_usage_purge_stage_retries_after_persistence_failure_and_survives_restart(
    lifecycle_runtime,
    isolated_usage_metrics,
    monkeypatch,
):
    suffix = uuid.uuid4().hex
    owner = f"retry-usage-owner-{suffix}"
    tenant = f"retry-usage-tenant-{suffix}"
    diagram_id = f"retry-usage-diagram-{suffix}"
    _seed_explicit_project(
        lifecycle_runtime,
        owner=owner,
        tenant=tenant,
        diagram_id=diagram_id,
    )
    usage_metrics.record_event(
        "analyses_run",
        {"diagram_id": diagram_id, "filename": "retry-private.png"},
    )
    usage_metrics.record_funnel_step(diagram_id, "analyze")
    original_save = usage_metrics._save_metrics
    failed = False

    def fail_strict_once(*, require_all=False):
        nonlocal failed
        if require_all and not failed:
            failed = True
            raise RuntimeError("injected telemetry persistence failure")
        return original_save(require_all=require_all)

    monkeypatch.setattr(usage_metrics, "_save_metrics", fail_strict_once)
    with pytest.raises(PurgeIncompleteError) as exc_info:
        purge_diagram(
            diagram_id=diagram_id,
            owner_user_id=owner,
            tenant_id=tenant,
        )
    assert exc_info.value.stage == "usage_telemetry"
    operation_id = exc_info.value.operation_id
    monkeypatch.setattr(usage_metrics, "_save_metrics", original_save)
    retried = purge_diagram(
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
    )
    assert retried.operation_id == operation_id
    assert retried.status == "completed"

    stale_payload = json.loads(json.dumps(usage_metrics._DEFAULT_METRICS))
    retained_id = usage_metrics._retained_identifier(diagram_id)
    stale_payload["sessions"][retained_id] = {
        "steps": ["analyze"],
        "started": "2026-07-29T00:00:00+00:00",
        "last": "2026-07-29T00:00:00+00:00",
    }
    stale_payload["recent_events"].append(
        {
            "type": "analyses_run",
            "timestamp": "2026-07-29T00:00:00+00:00",
            "details": {"diagram_id_hash": retained_id},
        }
    )
    with open(usage_metrics.METRICS_FILE, "w") as file_handle:
        json.dump(stale_payload, file_handle)
    usage_metrics._metrics = copy.deepcopy(stale_payload)

    usage_metrics._load_metrics(prefer_blob=False)
    assert retained_id not in usage_metrics._metrics["sessions"]
    assert usage_metrics.get_recent_events() == []
    usage_metrics.flush_metrics()
    assert usage_metrics.usage_telemetry_absent(
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
    )
    db = lifecycle_runtime()
    try:
        operation = db.query(PurgeOperation).filter_by(id=operation_id).one()
        stages = json.loads(operation.stages)
        assert stages["usage_telemetry"]["confirmed_absent"] is True
    finally:
        db.close()


def test_purged_scope_blocks_stale_event_and_emits_no_purge_identifier(
    test_client,
    lifecycle_runtime,
    isolated_usage_metrics,
):
    suffix = uuid.uuid4().hex
    owner = f"event-owner-{suffix}"
    tenant = f"event-tenant-{suffix}"
    diagram_id = f"event-diagram-{suffix}"
    _seed_explicit_project(
        lifecycle_runtime,
        owner=owner,
        tenant=tenant,
        diagram_id=diagram_id,
    )
    with patch("routers.diagrams.record_event") as purge_event:
        response = test_client.delete(
            f"/api/diagrams/{diagram_id}/purge",
            headers=_headers(owner, tenant),
        )
    assert response.status_code == 200, response.text
    purge_event.assert_called_once_with("diagram_data_purged")

    counter_before = usage_metrics._metrics["counters"].get("analyses_run", 0)
    usage_metrics.record_event(
        "analyses_run",
        {"diagram_id": diagram_id, "filename": "stale-worker.png"},
    )
    usage_metrics.record_funnel_step(diagram_id, "analyze")
    assert usage_metrics._metrics["counters"]["analyses_run"] == counter_before + 1
    assert (
        usage_metrics._retained_identifier(diagram_id)
        not in usage_metrics._metrics["sessions"]
    )
    assert all(
        event["type"] != "analyses_run"
        for event in usage_metrics._metrics["recent_events"]
    )


def _grant(
    index: int,
    *,
    expired: bool,
    owner: str,
    tenant: str,
    diagram_id: str,
) -> RestoreGrant:
    now = datetime.now(timezone.utc)
    cleanup_at = now - timedelta(minutes=5) if expired else now + timedelta(hours=1)
    return RestoreGrant(
        nonce_digest=hashlib.sha256(f"grant-{index}-{diagram_id}".encode()).hexdigest(),
        owner_user_id=owner,
        tenant_id=tenant,
        diagram_id=diagram_id,
        generation=1,
        expected_version=1,
        expires_at=cleanup_at,
        cleanup_at=cleanup_at,
    )


def test_restore_grant_cleanup_drains_250_plus_without_issuance_and_preserves_active(
    lifecycle_runtime,
):
    suffix = uuid.uuid4().hex
    owner = f"cleanup-owner-{suffix}"
    tenant = f"cleanup-tenant-{suffix}"
    diagram_id = f"cleanup-diagram-{suffix}"
    db = lifecycle_runtime()
    try:
        db.add_all(
            [
                _grant(
                    index,
                    expired=True,
                    owner=owner,
                    tenant=tenant,
                    diagram_id=diagram_id,
                )
                for index in range(257)
            ]
        )
        db.add_all(
            [
                _grant(
                    1000 + index,
                    expired=False,
                    owner=owner,
                    tenant=tenant,
                    diagram_id=diagram_id,
                )
                for index in range(5)
            ]
        )
        db.commit()
    finally:
        db.close()
    metrics_before = restore_grant_cleanup_metrics()

    result = run_restore_grant_cleanup(
        session_factory=lifecycle_runtime,
        batch_size=64,
        max_batches=10,
        time_budget_seconds=5,
        backlog_target=0,
    )

    assert result.deleted == 257
    assert result.batches == 5
    assert result.backlog == 0
    assert result.target_reached is True
    db = lifecycle_runtime()
    try:
        assert db.query(RestoreGrant).count() == 5
        assert all(
            grant.cleanup_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)
            for grant in db.query(RestoreGrant)
        )
    finally:
        db.close()
    metrics = restore_grant_cleanup_metrics()
    assert metrics["deleted_total"] - metrics_before["deleted_total"] == 257
    assert metrics["backlog"] == 0
    assert metrics["last_success"] is not None


def test_restore_grant_cleanup_partial_failure_is_metriced_and_retry_safe(
    lifecycle_runtime,
    monkeypatch,
):
    suffix = uuid.uuid4().hex
    owner = f"cleanup-retry-owner-{suffix}"
    tenant = f"cleanup-retry-tenant-{suffix}"
    diagram_id = f"cleanup-retry-diagram-{suffix}"
    db = lifecycle_runtime()
    try:
        db.add_all(
            [
                _grant(
                    index,
                    expired=True,
                    owner=owner,
                    tenant=tenant,
                    diagram_id=diagram_id,
                )
                for index in range(230)
            ]
        )
        db.commit()
    finally:
        db.close()

    original_cleanup = cleanup_module.cleanup_restore_grants
    calls = 0

    def flaky_cleanup(db, *, limit):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected cleanup database failure")
        return original_cleanup(db, limit=limit)

    errors_before = restore_grant_cleanup_metrics()["errors"]
    monkeypatch.setattr(cleanup_module, "cleanup_restore_grants", flaky_cleanup)
    with pytest.raises(RuntimeError, match="injected cleanup"):
        run_restore_grant_cleanup(
            session_factory=lifecycle_runtime,
            batch_size=100,
            max_batches=5,
            time_budget_seconds=5,
        )
    db = lifecycle_runtime()
    try:
        assert db.query(RestoreGrant).count() == 130
    finally:
        db.close()
    failed_metrics = restore_grant_cleanup_metrics()
    assert failed_metrics["errors"] == errors_before + 1
    assert failed_metrics["backlog"] == 130

    monkeypatch.setattr(cleanup_module, "cleanup_restore_grants", original_cleanup)
    retried = run_restore_grant_cleanup(
        session_factory=lifecycle_runtime,
        batch_size=100,
        max_batches=5,
        time_budget_seconds=5,
    )
    assert retried.deleted == 130
    assert retried.backlog == 0


def test_restore_grant_cleanup_runs_on_startup_schedule_and_graceful_shutdown():
    calls: list[int] = []
    scheduled = threading.Event()

    def fake_cleanup(**_kwargs):
        calls.append(len(calls) + 1)
        if len(calls) >= 2:
            scheduled.set()
        return RestoreGrantCleanupRun(
            deleted=0,
            batches=0,
            backlog=0,
            target_reached=True,
            elapsed_ms=0.1,
        )

    lifecycle = RestoreGrantCleanupLifecycle(
        interval_seconds=0.01,
        run_cleanup=fake_cleanup,
    )

    async def exercise() -> None:
        await lifecycle.start()
        assert calls == [1]
        assert await asyncio.to_thread(scheduled.wait, 1.0)
        await lifecycle.stop()

    asyncio.run(exercise())
    assert len(calls) >= 2
    assert lifecycle.status()["task_active"] is False
    assert lifecycle.status()["running"] is False


def test_decision_status_api_accepts_enum_values_and_rejects_invalid_status(
    test_client,
    lifecycle_runtime,
):
    suffix = uuid.uuid4().hex
    owner = f"decision-owner-{suffix}"
    tenant = f"decision-tenant-{suffix}"
    diagram_id = f"decision-diagram-{suffix}"
    seeded = _seed_explicit_project(
        lifecycle_runtime,
        owner=owner,
        tenant=tenant,
        diagram_id=diagram_id,
    )
    for status in ("open", "resolved", "accepted"):
        response = test_client.post(
            f"/api/analyses/{seeded.analysis.id}/decisions",
            headers=_headers(owner, tenant),
            json={
                "decision_type": "decision",
                "title": f"Decision {status}",
                "status": status,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == status

    invalid = test_client.post(
        f"/api/analyses/{seeded.analysis.id}/decisions",
        headers=_headers(owner, tenant),
        json={
            "decision_type": "decision",
            "title": "Invalid decision",
            "status": "pending-review",
        },
    )
    assert invalid.status_code == 422


def test_decision_status_database_constraint_and_openapi_enum_are_stable(
    lifecycle_runtime,
):
    suffix = uuid.uuid4().hex
    owner = f"decision-db-owner-{suffix}"
    tenant = f"decision-db-tenant-{suffix}"
    diagram_id = f"decision-db-diagram-{suffix}"
    seeded = _seed_explicit_project(
        lifecycle_runtime,
        owner=owner,
        tenant=tenant,
        diagram_id=diagram_id,
    )
    db = lifecycle_runtime()
    try:
        db.add(
            Decision(
                analysis_id=seeded.analysis.id,
                owner_user_id=owner,
                tenant_id=tenant,
                decision_type="decision",
                title="Bypass repository validation",
                status="pending-review",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()

    schema = app.openapi()
    assert schema["components"]["schemas"]["DecisionStatus"]["enum"] == [
        "open",
        "resolved",
        "accepted",
    ]
    status_schema = schema["components"]["schemas"]["CreateDecisionRequest"][
        "properties"
    ]["status"]
    assert status_schema["$ref"].endswith("/DecisionStatus")
