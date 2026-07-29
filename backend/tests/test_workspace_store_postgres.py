"""PostgreSQL concurrency contracts for canonical analysis state (#1237).

Set ``ARCHMORPH_TEST_POSTGRES_URL`` to an isolated migrated database to enable.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic import command
from alembic.config import Config
from limits import parse as parse_rate_limit
from limits.storage import RedisStorage
from limits.strategies import FixedWindowRateLimiter
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from error_envelope import ArchmorphException
from models.deployment_state import DeploymentState
from models.workspace import (
    APIKeyCredential,
    Analysis,
    AnalysisMutationReceipt,
    AnalysisRestoreReceipt,
    AnalysisVersion,
    Artifact,
    Decision,
    ProjectMember,
    PurgeOperation,
    RestoreGrant,
    DiagramLifecycle,
    SourceAsset,
    TenantRehomeAudit,
    MigrationReplay,
    MigrationReplayEvent,
    TenantRehomeAlias,
    Workspace,
)
from project_store import PROJECT_EDIT_ROLES
from routers.tf_backend import authorized_deployment_state
from session_store import InMemoryStore, RedisStore
from routers import shared
from routers.api_keys_routes import create_api_key, rotate_api_key
from workspace_store import (
    AnalysisVersionConflictError,
    MAX_VERSIONS_PER_ANALYSIS,
    _trim_old_versions,
    add_migration_replay_event,
    create_decision,
    create_migration_replay,
    create_workspace,
    consume_restore_grant,
    issue_restore_grant,
    list_migration_replays,
    load_analysis_state,
    persist_analysis_state,
    rehome_legacy_analysis_scope,
    restore_analysis_version,
    save_analysis_version,
    snapshot_payload_hash,
    update_workspace,
)


POSTGRES_URL = os.getenv("ARCHMORPH_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="isolated PostgreSQL URL not configured")


@pytest.fixture()
def postgres_factory(request):
    worker = getattr(request.config, "workerinput", {}).get("workerid")
    test_url = POSTGRES_URL
    admin_engine = None
    database_name = None
    if worker:
        from sqlalchemy.engine import make_url

        base_url = make_url(POSTGRES_URL)
        database_name = f"{base_url.database}_{worker}_{uuid.uuid4().hex[:8]}"
        admin_engine = create_engine(base_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        test_url = str(base_url.set(database=database_name))
    engine = create_engine(test_url, pool_pre_ping=True)
    config = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    config.set_main_option("sqlalchemy.url", test_url)
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    config.attributes.pop("connection", None)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    try:
        db.query(APIKeyCredential).delete()
        db.query(MigrationReplayEvent).delete()
        db.query(MigrationReplay).delete()
        db.query(ProjectMember).delete()
        db.query(RestoreGrant).delete()
        db.query(AnalysisRestoreReceipt).delete()
        db.query(AnalysisMutationReceipt).delete()
        db.query(PurgeOperation).delete()
        db.query(DiagramLifecycle).delete()
        db.query(Decision).delete()
        db.query(Artifact).delete()
        db.query(AnalysisVersion).delete()
        db.query(Analysis).delete()
        db.query(Workspace).delete()
        db.query(TenantRehomeAudit).delete()
        db.query(TenantRehomeAlias).delete()
        db.commit()
    finally:
        db.close()
    yield factory
    engine.dispose()
    if admin_engine is not None and database_name is not None:
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
        admin_engine.dispose()


def test_postgres_decision_composite_fk_rejects_cross_analysis_version(postgres_factory):
    db = postgres_factory()
    try:
        first = persist_analysis_state(
            db,
            owner_user_id="pg-decision-owner",
            tenant_id="pg-decision-tenant",
            diagram_id="pg-decision-one",
            snapshot={"mappings": []},
        )
        second = persist_analysis_state(
            db,
            owner_user_id="pg-decision-owner",
            tenant_id="pg-decision-tenant",
            diagram_id="pg-decision-two",
            snapshot={"mappings": []},
        )
        with pytest.raises(ValueError):
            create_decision(
                db,
                analysis_id=first.analysis.id,
                version_id=second.version.id,
                owner_user_id="pg-decision-owner",
                tenant_id="pg-decision-tenant",
                decision_type="risk",
                title="repository rejected",
            )
        db.add(Decision(
            analysis_id=first.analysis.id,
            version_id=second.version.id,
            owner_user_id="pg-decision-owner",
            tenant_id="pg-decision-tenant",
            decision_type="risk",
            title="database rejected",
        ))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_postgres_two_authorized_principals_racing_first_state_create_one_row(
    postgres_factory,
):
    suffix = uuid.uuid4().hex[:12]
    project_id = f"proj-pg-tf-{suffix}"
    tenant_id = f"tenant-pg-tf-{suffix}"
    owner_user_id = f"owner-pg-tf-{suffix}"
    editor_user_id = f"editor-pg-tf-{suffix}"
    db = postgres_factory()
    try:
        db.add(
            Workspace(
                id=project_id,
                owner_user_id=owner_user_id,
                tenant_id=tenant_id,
                name="PostgreSQL Terraform state race",
                status="active",
                is_default=False,
            )
        )
        db.flush()
        db.add(
            ProjectMember(
                project_id=project_id,
                project_owner_user_id=owner_user_id,
                tenant_id=tenant_id,
                member_user_id=editor_user_id,
                role="editor",
            )
        )
        db.commit()
    finally:
        db.close()

    barrier = threading.Barrier(2)

    def create_as(caller_user_id: str) -> int:
        session = postgres_factory()
        try:
            barrier.wait(timeout=10)
            with authorized_deployment_state(
                session,
                project_id=project_id,
                caller_user_id=caller_user_id,
                tenant_id=tenant_id,
                environment=" PRODUCTION ",
                allowed_roles=PROJECT_EDIT_ROLES,
            ) as (state, _canonical_project, environment):
                assert environment == "prod"
                return state.id
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        state_ids = list(executor.map(create_as, [owner_user_id, editor_user_id]))

    assert len(set(state_ids)) == 1
    db = postgres_factory()
    try:
        states = (
            db.query(DeploymentState)
            .filter(
                DeploymentState.project_id == project_id,
                DeploymentState.environment == "prod",
            )
            .all()
        )
        assert len(states) == 1
        assert states[0].owner_user_id == owner_user_id
        assert states[0].tenant_id == tenant_id
    finally:
        db.close()


def test_postgres_member_revocation_cannot_race_authorized_state_commit(
    postgres_factory,
):
    suffix = uuid.uuid4().hex[:12]
    project_id = f"proj-pg-auth-race-{suffix}"
    tenant_id = f"tenant-pg-auth-race-{suffix}"
    owner_user_id = f"owner-pg-auth-race-{suffix}"
    editor_user_id = f"editor-pg-auth-race-{suffix}"
    db = postgres_factory()
    try:
        db.add(
            Workspace(
                id=project_id,
                owner_user_id=owner_user_id,
                tenant_id=tenant_id,
                name="PostgreSQL Terraform authorization race",
                status="active",
                is_default=False,
            )
        )
        db.flush()
        db.add(
            ProjectMember(
                project_id=project_id,
                project_owner_user_id=owner_user_id,
                tenant_id=tenant_id,
                member_user_id=editor_user_id,
                role="editor",
            )
        )
        db.commit()
    finally:
        db.close()

    editor_db = postgres_factory()
    remover_db = postgres_factory()
    try:
        with authorized_deployment_state(
            editor_db,
            project_id=project_id,
            environment="dev",
            caller_user_id=editor_user_id,
            tenant_id=tenant_id,
            allowed_roles=PROJECT_EDIT_ROLES,
        ) as (state, project, environment):
            assert state.project_id == project.id == project_id
            assert environment == "dev"
            remover_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
            with pytest.raises(OperationalError):
                remover_db.query(ProjectMember).filter(
                    ProjectMember.project_id == project_id,
                    ProjectMember.member_user_id == editor_user_id,
                ).delete(synchronize_session=False)
                remover_db.commit()
            remover_db.rollback()

        removed = (
            remover_db.query(ProjectMember)
            .filter(
                ProjectMember.project_id == project_id,
                ProjectMember.member_user_id == editor_user_id,
            )
            .delete(synchronize_session=False)
        )
        assert removed == 1
        remover_db.commit()

        denied_db = postgres_factory()
        try:
            with pytest.raises(ArchmorphException) as denied:
                with authorized_deployment_state(
                    denied_db,
                    project_id=project_id,
                    environment="dev",
                    caller_user_id=editor_user_id,
                    tenant_id=tenant_id,
                    allowed_roles=PROJECT_EDIT_ROLES,
                ):
                    pytest.fail("revoked editor reached Terraform state")
            assert denied.value.status_code == 404
        finally:
            denied_db.close()
    finally:
        editor_db.close()
        remover_db.close()


def test_postgres_api_key_rotation_preserves_canonical_owner(postgres_factory, monkeypatch):
    import database
    import routers.api_keys_routes as key_routes

    monkeypatch.setattr(key_routes, "_use_durable_store", lambda: True)
    monkeypatch.setattr(database, "SessionLocal", postgres_factory)
    monkeypatch.setattr(shared, "API_KEY", "configured-admin-key")
    monkeypatch.setattr(shared, "API_KEY_ROTATED", "")
    record, old_raw = create_api_key("rotating client", ["read", "write"])
    owner = shared.get_api_key_service_principal({"x-api-key": old_raw})
    assert owner is not None
    tenant = f"service:{owner.split(':', 1)[-1]}"
    db = postgres_factory()
    try:
        persist_analysis_state(
            db,
            owner_user_id=owner,
            tenant_id=tenant,
            diagram_id="pg-key-rotation",
            snapshot={"stable": True, "mappings": []},
        )
    finally:
        db.close()

    rotated = rotate_api_key(record.id)
    assert rotated is not None
    _new_record, new_raw = rotated
    assert shared.get_api_key_service_principal({"x-api-key": old_raw}) is None
    assert shared.get_api_key_service_principal({"x-api-key": new_raw}) == owner
    _foreign_record, foreign_raw = create_api_key("foreign client", ["read"])
    foreign_owner = shared.get_api_key_service_principal({"x-api-key": foreign_raw})
    db = postgres_factory()
    try:
        assert load_analysis_state(
            db,
            diagram_id="pg-key-rotation",
            owner_user_id=owner,
            tenant_id=tenant,
        )["stable"] is True
        assert load_analysis_state(
            db,
            diagram_id="pg-key-rotation",
            owner_user_id=foreign_owner,
            tenant_id=f"service:{foreign_owner.split(':', 1)[-1]}",
        ) is None
    finally:
        db.close()


def test_postgres_concurrent_trim_preserves_transitive_lineage(postgres_factory):
    db = postgres_factory()
    try:
        result = persist_analysis_state(
            db,
            owner_user_id="pg-lineage-owner",
            tenant_id="pg-lineage-tenant",
            diagram_id="pg-lineage-diagram",
            snapshot={"value": 1, "mappings": []},
        )
        for value in range(2, MAX_VERSIONS_PER_ANALYSIS + 4):
            save_analysis_version(
                db,
                analysis_id=result.analysis.id,
                owner_user_id="pg-lineage-owner",
                tenant_id="pg-lineage-tenant",
                snapshot={"value": value, "mappings": []},
                restored_from=1 if value == MAX_VERSIONS_PER_ANALYSIS - 1 else (
                    MAX_VERSIONS_PER_ANALYSIS - 1
                    if value == MAX_VERSIONS_PER_ANALYSIS
                    else None
                ),
            )
    finally:
        db.close()
    barrier = threading.Barrier(2)

    def trim():
        session = postgres_factory()
        try:
            barrier.wait(timeout=10)
            _trim_old_versions(session, result.analysis.id)
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _index: trim(), range(2)))
    db = postgres_factory()
    try:
        numbers = {
            row.version_number
            for row in db.query(AnalysisVersion).filter_by(analysis_id=result.analysis.id)
        }
        assert {1, MAX_VERSIONS_PER_ANALYSIS - 1, MAX_VERSIONS_PER_ANALYSIS} <= numbers
    finally:
        db.close()


@pytest.mark.skipif(not os.getenv("ARCHMORPH_TEST_REDIS_URL"), reason="isolated Redis URL not configured")
def test_real_redis_page_and_postgres_replay_survive_cache_loss(postgres_factory, monkeypatch):
    monkeypatch.setenv("REDIS_URL", os.environ["ARCHMORPH_TEST_REDIS_URL"])
    monkeypatch.delenv("REDIS_HOST", raising=False)
    cache = RedisStore(prefix="archmorph-test-replay-page", ttl=120)
    cache.clear()
    db = postgres_factory()
    try:
        persist_analysis_state(
            db,
            owner_user_id="pg-replay-owner",
            tenant_id="pg-replay-tenant",
            diagram_id="pg-replay-diagram",
            snapshot={"mappings": []},
        )
        replay_ids = []
        for index in range(3):
            replay = create_migration_replay(
                db,
                diagram_id="pg-replay-diagram",
                owner_user_id="pg-replay-owner",
                tenant_id="pg-replay-tenant",
                title=f"Replay {index}",
            )
            add_migration_replay_event(
                db,
                replay_id=replay.id,
                owner_user_id="pg-replay-owner",
                tenant_id="pg-replay-tenant",
                event_type="step_entered",
                data={"index": index},
            )
            replay_ids.append(replay.id)
            cache.set(replay.id, {"replay_id": replay.id, "index": index})
        items, total = cache.page(offset=1, limit=1)
        assert total == 3
        assert len(items) == 1
        cache.clear()
        page = list_migration_replays(
            db,
            owner_user_id="pg-replay-owner",
            tenant_id="pg-replay-tenant",
            limit=2,
            offset=1,
        )
        assert page["total"] == 3
        assert len(page["replays"]) == 2
        assert list_migration_replays(
            db,
            owner_user_id="foreign-owner",
            tenant_id="pg-replay-tenant",
            limit=20,
            offset=0,
        )["total"] == 0
    finally:
        db.close()
        cache.clear()


def test_concurrent_first_write_upserts_one_analysis_and_monotonic_versions(postgres_factory):
    barrier = threading.Barrier(8)

    def write(index):
        db = postgres_factory()
        try:
            barrier.wait(timeout=10)
            result = persist_analysis_state(
                db,
                owner_user_id="pg-owner",
                tenant_id="pg-tenant",
                diagram_id="pg-concurrent-first-write",
                snapshot={"writer": index, "mappings": []},
                label=f"writer-{index}",
            )
            return result.analysis.id, result.version.version_number
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(write, range(8)))

    db = postgres_factory()
    try:
        analyses = db.query(Analysis).filter_by(
            owner_user_id="pg-owner",
            tenant_id="pg-tenant",
            diagram_id="pg-concurrent-first-write",
        ).all()
        versions = (
            db.query(AnalysisVersion)
            .filter(AnalysisVersion.analysis_id == analyses[0].id)
            .order_by(AnalysisVersion.version_number)
            .all()
        )
        assert len(analyses) == 1
        assert len({analysis_id for analysis_id, _ in results}) == 1
        assert [version.version_number for version in versions] == list(range(1, 9))
        assert analyses[0].current_version == 8
    finally:
        db.close()


def test_reversed_cache_projection_never_replaces_newer_version(postgres_factory):
    cache = InMemoryStore(maxsize=20, ttl=3600)
    db = postgres_factory()
    try:
        first = persist_analysis_state(
            db,
            owner_user_id="pg-cas-owner",
            tenant_id="pg-cas-tenant",
            diagram_id="pg-cache-cas",
            snapshot={"value": "first", "mappings": []},
            label="first",
        )
        second = persist_analysis_state(
            db,
            owner_user_id="pg-cas-owner",
            tenant_id="pg-cas-tenant",
            diagram_id="pg-cache-cas",
            snapshot={"value": "second", "mappings": []},
            session_store=cache,
            label="second",
            cache_required=True,
        )
    finally:
        db.close()

    from workspace_store import AnalysisCacheWriteError, _write_session_cache

    with pytest.raises(AnalysisCacheWriteError):
        _write_session_cache(
            cache,
            diagram_id="pg-cache-cas",
            owner_user_id="pg-cas-owner",
            tenant_id="pg-cas-tenant",
            snapshot=json.loads(first.version.snapshot),
            version_number=first.version.version_number,
        )
    assert second.version.version_number == 2
    assert cache.peek("pg-cache-cas")["value"] == "second"
    assert cache.peek("pg-cache-cas")["_analysis_version"] == 2


def test_concurrent_same_mutation_receipt_creates_one_version(postgres_factory):
    seeded_db = postgres_factory()
    try:
        seeded = persist_analysis_state(
            seeded_db,
            owner_user_id="pg-receipt-owner",
            tenant_id="pg-receipt-tenant",
            diagram_id="pg-receipt-diagram",
            snapshot={"value": "v1", "mappings": []},
        )
        snapshot = load_analysis_state(
            seeded_db,
            diagram_id="pg-receipt-diagram",
            owner_user_id="pg-receipt-owner",
            tenant_id="pg-receipt-tenant",
        )
        snapshot["value"] = "v2"
    finally:
        seeded_db.close()
    barrier = threading.Barrier(8)

    def write(_index):
        from workspace_store import persist_analysis_mutation

        db = postgres_factory()
        try:
            barrier.wait(timeout=10)
            result = persist_analysis_mutation(
                db,
                owner_user_id="pg-receipt-owner",
                tenant_id="pg-receipt-tenant",
                diagram_id="pg-receipt-diagram",
                snapshot=snapshot,
                expected_version=1,
                operation="same-request",
                request_hash="a" * 64,
            )
            return result.version.version_number
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        versions = list(pool.map(write, range(8)))

    db = postgres_factory()
    try:
        assert set(versions) == {2}
        assert db.query(AnalysisVersion).filter_by(analysis_id=seeded.analysis.id).count() == 2
        assert db.query(AnalysisMutationReceipt).filter_by(
            analysis_id=seeded.analysis.id,
            operation="same-request",
        ).count() == 1
    finally:
        db.close()


def test_concurrent_same_restore_key_creates_one_version(postgres_factory):
    seeded = postgres_factory()
    try:
        original = persist_analysis_state(
            seeded,
            owner_user_id="pg-restore-owner",
            tenant_id="pg-restore-tenant",
            diagram_id="pg-restore-diagram",
            snapshot={"step": "source", "mappings": []},
        )
        persist_analysis_state(
            seeded,
            owner_user_id="pg-restore-owner",
            tenant_id="pg-restore-tenant",
            diagram_id="pg-restore-diagram",
            snapshot={"step": "current", "mappings": [], "_analysis_version": 1},
            expected_version=1,
            operation="prepare-restore-current",
            request_hash="b" * 64,
        )
        analysis_id = original.analysis.id
    finally:
        seeded.close()

    barrier = threading.Barrier(2)

    def restore():
        db = postgres_factory()
        try:
            barrier.wait(timeout=5)
            return restore_analysis_version(
                db,
                analysis_id=analysis_id,
                version_number=1,
                owner_user_id="pg-restore-owner",
                tenant_id="pg-restore-tenant",
                expected_version=2,
                idempotency_key="same-concurrent-restore-key",
            ).version_number
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        versions = list(pool.map(lambda _index: restore(), range(2)))

    assert versions == [3, 3]
    db = postgres_factory()
    try:
        assert db.query(AnalysisVersion).filter_by(analysis_id=analysis_id).count() == 3
        assert db.query(AnalysisRestoreReceipt).filter_by(analysis_id=analysis_id).count() == 1
        replay = restore_analysis_version(
            db,
            analysis_id=analysis_id,
            version_number=1,
            owner_user_id="pg-restore-owner",
            tenant_id="pg-restore-tenant",
            expected_version=2,
            idempotency_key="same-concurrent-restore-key",
        )
        assert replay.version_number == 3
        with pytest.raises(AnalysisVersionConflictError, match="different restore intent"):
            restore_analysis_version(
                db,
                analysis_id=analysis_id,
                version_number=2,
                owner_user_id="pg-restore-owner",
                tenant_id="pg-restore-tenant",
                expected_version=3,
                idempotency_key="same-concurrent-restore-key",
            )
        with pytest.raises(AnalysisVersionConflictError, match="Expected version"):
            restore_analysis_version(
                db,
                analysis_id=analysis_id,
                version_number=1,
                owner_user_id="pg-restore-owner",
                tenant_id="pg-restore-tenant",
                expected_version=2,
                idempotency_key="fresh-but-stale-restore-key",
            )
    finally:
        db.close()


def test_concurrent_restore_grant_consumption_has_one_winner(postgres_factory):
    owner = "pg-grant-race-owner"
    tenant = "pg-grant-race-tenant"
    diagram_id = f"pg-grant-race-{uuid.uuid4().hex}"
    db = postgres_factory()
    try:
        seeded = persist_analysis_state(
            db,
            owner_user_id=owner,
            tenant_id=tenant,
            diagram_id=diagram_id,
            snapshot={"mappings": []},
        )
        payload_hash = snapshot_payload_hash(json.loads(seeded.version.snapshot))
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

    barrier = threading.Barrier(2)

    def consume() -> bool:
        session = postgres_factory()
        try:
            barrier.wait(timeout=5)
            return consume_restore_grant(
                session,
                nonce=nonce,
                owner_user_id=owner,
                tenant_id=tenant,
                diagram_id=diagram_id,
                generation=generation,
                expected_version=expected_version,
                payload_hash=payload_hash,
            )
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: consume(), range(2)))
    assert sorted(results) == [False, True]


def test_concurrent_distinct_diagrams_share_one_default_workspace(postgres_factory):
    barrier = threading.Barrier(12)

    def write(index):
        db = postgres_factory()
        try:
            barrier.wait(timeout=10)
            result = persist_analysis_state(
                db,
                owner_user_id="pg-default-owner",
                tenant_id="pg-default-tenant",
                diagram_id=f"pg-distinct-{index}",
                snapshot={"writer": index, "mappings": []},
            )
            return result.analysis.workspace_id
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=12) as pool:
        workspace_ids = list(pool.map(write, range(12)))

    db = postgres_factory()
    try:
        defaults = db.query(Workspace).filter_by(
            owner_user_id="pg-default-owner",
            tenant_id="pg-default-tenant",
            is_default=True,
        ).all()
        analyses = db.query(Analysis).filter_by(
            owner_user_id="pg-default-owner",
            tenant_id="pg-default-tenant",
        ).all()
        assert len(defaults) == 1
        assert len(set(workspace_ids)) == 1
        assert len(analyses) == 12
        assert {analysis.workspace_id for analysis in analyses} == {defaults[0].id}
    finally:
        db.close()


def test_concurrent_default_workspace_api_returns_one_identity(postgres_factory):
    barrier = threading.Barrier(8)

    def create(index):
        db = postgres_factory()
        try:
            barrier.wait(timeout=10)
            workspace = create_workspace(
                db,
                owner_user_id="pg-create-default-owner",
                tenant_id="pg-create-default-tenant",
                name=f"Default Workspace {index}",
                is_default=True,
            )
            return workspace.id
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        workspace_ids = list(pool.map(create, range(8)))

    db = postgres_factory()
    try:
        defaults = db.query(Workspace).filter_by(
            owner_user_id="pg-create-default-owner",
            tenant_id="pg-create-default-tenant",
            is_default=True,
        ).all()
        assert len(defaults) == 1
        assert set(workspace_ids) == {defaults[0].id}
    finally:
        db.close()


def test_concurrent_workspace_reactivation_elects_one_default(postgres_factory):
    seeded = postgres_factory()
    try:
        workspace_ids = []
        for index in range(4):
            workspace = create_workspace(
                seeded,
                owner_user_id="pg-reactivate-owner",
                tenant_id="pg-reactivate-tenant",
                name=f"Archived {index}",
            )
            workspace.status = "archived"
            workspace_ids.append(workspace.id)
        seeded.commit()
    finally:
        seeded.close()
    barrier = threading.Barrier(len(workspace_ids))

    def reactivate(workspace_id):
        db = postgres_factory()
        try:
            barrier.wait(timeout=10)
            try:
                workspace = update_workspace(
                    db,
                    workspace_id,
                    owner_user_id="pg-reactivate-owner",
                    tenant_id="pg-reactivate-tenant",
                    status="active",
                )
                return workspace.id if workspace and workspace.is_default else None
            except IntegrityError:
                db.rollback()
                return None
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        winners = [value for value in pool.map(reactivate, workspace_ids) if value]
    db = postgres_factory()
    try:
        defaults = db.query(Workspace).filter_by(
            owner_user_id="pg-reactivate-owner",
            tenant_id="pg-reactivate-tenant",
            is_default=True,
        ).all()
        assert len(defaults) == 1
        assert defaults[0].id in winners
    finally:
        db.close()


@pytest.mark.skipif(not os.getenv("ARCHMORPH_TEST_REDIS_URL"), reason="isolated Redis URL not configured")
def test_real_redis_cache_loss_hydrates_from_postgres(postgres_factory, monkeypatch):
    monkeypatch.setenv("REDIS_URL", os.environ["ARCHMORPH_TEST_REDIS_URL"])
    monkeypatch.delenv("REDIS_HOST", raising=False)
    cache = RedisStore(prefix="archmorph-test-canonical", ttl=120)
    cache.clear()
    db = postgres_factory()
    try:
        persist_analysis_state(
            db,
            owner_user_id="pg-redis-owner",
            tenant_id="pg-redis-tenant",
            diagram_id="pg-redis-process-loss",
            snapshot={"durable": True, "mappings": []},
            session_store=cache,
            cache_required=True,
        )
        cache.delete("pg-redis-process-loss")
        hydrated = load_analysis_state(
            db,
            diagram_id="pg-redis-process-loss",
            owner_user_id="pg-redis-owner",
            tenant_id="pg-redis-tenant",
            session_store=cache,
        )
        assert hydrated["durable"] is True
        assert cache.peek("pg-redis-process-loss")["durable"] is True
    finally:
        db.close()
        cache.clear()


@pytest.mark.skipif(not os.getenv("ARCHMORPH_TEST_REDIS_URL"), reason="isolated Redis URL not configured")
def test_real_redis_getdel_has_one_concurrent_winner(monkeypatch):
    monkeypatch.setenv("REDIS_URL", os.environ["ARCHMORPH_TEST_REDIS_URL"])
    monkeypatch.delenv("REDIS_HOST", raising=False)
    store = RedisStore(prefix="archmorph-test-getdel", ttl=120)
    store.clear()
    store.set("capability", {"one_time": True})
    barrier = threading.Barrier(12)

    def consume(_index):
        barrier.wait(timeout=10)
        return store.pop("capability")

    try:
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(consume, range(12)))
        assert results.count({"one_time": True}) == 1
        assert results.count(None) == 11
    finally:
        store.clear()


@pytest.mark.skipif(not os.getenv("ARCHMORPH_TEST_REDIS_URL"), reason="isolated Redis URL not configured")
def test_real_redis_managed_key_rate_limit_is_shared_across_replicas():
    redis_url = os.environ["ARCHMORPH_TEST_REDIS_URL"]
    first = FixedWindowRateLimiter(RedisStorage(redis_url))
    second = FixedWindowRateLimiter(RedisStorage(redis_url))
    rate = parse_rate_limit("2/minute")
    principal = f"api-key:distributed-{uuid.uuid4().hex}"

    assert first.hit(rate, "managed-api-key", principal) is True
    assert second.hit(rate, "managed-api-key", principal) is True
    assert first.hit(rate, "managed-api-key", principal) is False
    assert second.hit(rate, "managed-api-key", f"{principal}-isolated") is True


def test_exact_owner_legacy_graph_rehomes_transactionally_with_audit(postgres_factory):
    db = postgres_factory()
    try:
        first = persist_analysis_state(
            db,
            owner_user_id="pg-rehome-owner",
            tenant_id="default_tenant",
            diagram_id="pg-rehome-first",
            snapshot={"value": "first", "mappings": []},
            artifact_type="migration_timeline",
            artifact_format="json",
            artifact_content='{"phase":1}',
        )
        second = persist_analysis_state(
            db,
            owner_user_id="pg-rehome-owner",
            tenant_id="default_tenant",
            diagram_id="pg-rehome-second",
            workspace_id=first.analysis.workspace_id,
            snapshot={"value": "second", "mappings": []},
        )
        db.add(Decision(
            analysis_id=second.analysis.id,
            version_id=second.version.id,
            owner_user_id="pg-rehome-owner",
            tenant_id="default_tenant",
            decision_type="risk",
            title="preserve",
        ))
        db.commit()

        status = rehome_legacy_analysis_scope(
            db,
            diagram_id="pg-rehome-first",
            owner_user_id="pg-rehome-owner",
            source_tenant_id="default_tenant",
            target_tenant_id="idp:verified-current-provider-scope",
        )

        assert status == "rehomed"
        assert db.query(Workspace).filter_by(
            id=first.analysis.workspace_id,
            tenant_id="idp:verified-current-provider-scope",
        ).count() == 1
        assert db.query(Analysis).filter_by(
            owner_user_id="pg-rehome-owner",
            tenant_id="idp:verified-current-provider-scope",
        ).count() == 2
        assert db.query(Artifact).filter_by(
            analysis_id=first.analysis.id,
            tenant_id="idp:verified-current-provider-scope",
        ).count() == 1
        assert db.query(Decision).filter_by(
            analysis_id=second.analysis.id,
            tenant_id="idp:verified-current-provider-scope",
        ).count() == 1
        audit = db.query(TenantRehomeAudit).filter_by(
            owner_user_id="pg-rehome-owner",
            status="access_rehome_completed",
        ).one()
        assert "pg-rehome-first" in audit.details
    finally:
        db.close()


def test_verified_b2c_alias_rehomes_owner_and_tenant_graph(postgres_factory):
    legacy_owner = "azure_ad_b2c_subject-legacy"
    canonical_owner = "subject-legacy"
    db = postgres_factory()
    try:
        result = persist_analysis_state(
            db,
            owner_user_id=legacy_owner,
            tenant_id="default_tenant",
            diagram_id="pg-b2c-owner-rehome",
            snapshot={"value": "legacy-b2c", "mappings": []},
            artifact_type="migration_timeline",
            artifact_format="json",
            artifact_content='{"phase":1}',
        )
        asset = SourceAsset(
            workspace_id=result.analysis.workspace_id,
            owner_user_id=legacy_owner,
            tenant_id="default_tenant",
            filename="legacy-b2c.tfstate",
            diagram_id="pg-b2c-owner-rehome",
        )
        db.add(asset)
        db.add(Decision(
            analysis_id=result.analysis.id,
            version_id=result.version.id,
            owner_user_id=legacy_owner,
            tenant_id="default_tenant",
            decision_type="risk",
            title="preserve",
        ))
        db.commit()

        status = rehome_legacy_analysis_scope(
            db,
            diagram_id="pg-b2c-owner-rehome",
            owner_user_id=legacy_owner,
            source_tenant_id="default_tenant",
            target_tenant_id="idp:verified-b2c-scope",
            target_owner_user_id=canonical_owner,
        )

        assert status == "rehomed"
        assert db.query(Workspace).filter_by(
            id=result.analysis.workspace_id,
            owner_user_id=canonical_owner,
            tenant_id="idp:verified-b2c-scope",
        ).count() == 1
        assert db.query(Analysis).filter_by(
            id=result.analysis.id,
            owner_user_id=canonical_owner,
            tenant_id="idp:verified-b2c-scope",
        ).count() == 1
        assert db.query(SourceAsset).filter_by(
            id=asset.id,
            owner_user_id=canonical_owner,
            tenant_id="idp:verified-b2c-scope",
        ).count() == 1
        assert db.query(Artifact).filter_by(
            analysis_id=result.analysis.id,
            owner_user_id=canonical_owner,
            tenant_id="idp:verified-b2c-scope",
        ).count() == 1
        assert db.query(Decision).filter_by(
            analysis_id=result.analysis.id,
            owner_user_id=canonical_owner,
            tenant_id="idp:verified-b2c-scope",
        ).count() == 1
        hydrated = load_analysis_state(
            db,
            diagram_id="pg-b2c-owner-rehome",
            owner_user_id=canonical_owner,
            tenant_id="idp:verified-b2c-scope",
        )
        assert hydrated["value"] == "legacy-b2c"
    finally:
        db.close()


def test_verified_rehome_denies_mixed_owner_child_graph(postgres_factory):
    db = postgres_factory()
    try:
        result = persist_analysis_state(
            db,
            owner_user_id="pg-mixed-owner",
            tenant_id="default_tenant",
            diagram_id="pg-mixed-owner-rehome",
            snapshot={"mappings": []},
        )
        foreign_asset = SourceAsset(
            workspace_id=result.analysis.workspace_id,
            owner_user_id="foreign-owner",
            tenant_id="foreign-tenant",
            filename="foreign.tfstate",
        )
        db.add(foreign_asset)
        db.commit()

        status = rehome_legacy_analysis_scope(
            db,
            diagram_id="pg-mixed-owner-rehome",
            owner_user_id="pg-mixed-owner",
            source_tenant_id="default_tenant",
            target_tenant_id="idp:verified-mixed-scope",
        )

        assert status == "conflict"
        assert db.query(Workspace).filter_by(
            id=result.analysis.workspace_id,
            owner_user_id="pg-mixed-owner",
            tenant_id="default_tenant",
        ).count() == 1
        assert db.query(SourceAsset).filter_by(
            id=foreign_asset.id,
            owner_user_id="foreign-owner",
            tenant_id="foreign-tenant",
        ).count() == 1
        audit = db.query(TenantRehomeAudit).filter_by(
            owner_user_id="pg-mixed-owner",
            status="conflict_denied",
        ).one()
        assert "mixed_scope_workspace_graph" in audit.details
    finally:
        db.close()


def test_legacy_target_conflict_is_audited_and_retains_both_scopes(postgres_factory):
    db = postgres_factory()
    try:
        for tenant_id, value in (
            ("default_tenant", "legacy"),
            ("idp:verified-conflict-scope", "target"),
        ):
            persist_analysis_state(
                db,
                owner_user_id="pg-conflict-owner",
                tenant_id=tenant_id,
                diagram_id="pg-conflict-diagram",
                snapshot={"value": value, "mappings": []},
            )

        status = rehome_legacy_analysis_scope(
            db,
            diagram_id="pg-conflict-diagram",
            owner_user_id="pg-conflict-owner",
            source_tenant_id="default_tenant",
            target_tenant_id="idp:verified-conflict-scope",
        )

        assert status == "conflict"
        scopes = {
            row.tenant_id
            for row in db.query(Analysis).filter_by(
                owner_user_id="pg-conflict-owner",
                diagram_id="pg-conflict-diagram",
            )
        }
        assert scopes == {"default_tenant", "idp:verified-conflict-scope"}
        assert db.query(TenantRehomeAudit).filter_by(
            owner_user_id="pg-conflict-owner",
            status="conflict_denied",
        ).count() == 1
    finally:
        db.close()


@pytest.mark.skipif(not os.getenv("ARCHMORPH_TEST_REDIS_URL"), reason="isolated Redis URL not configured")
def test_real_postgres_and_redis_report_ready(monkeypatch, postgres_factory):
    import database
    from session_store import session_store_readiness

    monkeypatch.setenv("REDIS_URL", os.environ["ARCHMORPH_TEST_REDIS_URL"])
    monkeypatch.delenv("REDIS_HOST", raising=False)
    isolated_engine = postgres_factory.kw["bind"]
    monkeypatch.setattr(database, "engine", isolated_engine)
    monkeypatch.setattr(database, "_IS_POSTGRES", True)
    monkeypatch.setattr(database, "_IS_SQLITE", False)
    monkeypatch.setattr(database, "_PRODUCTION_LIKE", True)
    database_status = database.database_readiness()
    assert database_status["schema_at_head"] is True
    assert database_status["required_schema_present"] is True
    assert database_status["ready_for_production"] is True
    readiness = session_store_readiness()
    assert readiness["backend"] == "redis"
    assert readiness["redis_reachable"] is True
    assert readiness["ready_for_horizontal_scale"] is True
