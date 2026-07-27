"""PostgreSQL concurrency contracts for canonical analysis state (#1237).

Set ``ARCHMORPH_TEST_POSTGRES_URL`` to an isolated migrated database to enable.
"""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.workspace import (
    Analysis,
    AnalysisVersion,
    Artifact,
    Decision,
    SourceAsset,
    TenantRehomeAudit,
    Workspace,
)
from session_store import InMemoryStore, RedisStore
from workspace_store import (
    create_workspace,
    load_analysis_state,
    persist_analysis_state,
    rehome_legacy_analysis_scope,
)


POSTGRES_URL = os.getenv("ARCHMORPH_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="isolated PostgreSQL URL not configured")


@pytest.fixture()
def postgres_factory():
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    try:
        db.query(Decision).delete()
        db.query(Artifact).delete()
        db.query(AnalysisVersion).delete()
        db.query(Analysis).delete()
        db.query(Workspace).delete()
        db.query(TenantRehomeAudit).delete()
        db.commit()
    finally:
        db.close()
    yield factory
    engine.dispose()


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
def test_real_postgres_and_redis_report_ready(monkeypatch):
    import database
    from session_store import session_store_readiness

    monkeypatch.setenv("REDIS_URL", os.environ["ARCHMORPH_TEST_REDIS_URL"])
    monkeypatch.delenv("REDIS_HOST", raising=False)
    assert database.database_readiness()["ready_for_production"] is True
    readiness = session_store_readiness()
    assert readiness["backend"] == "redis"
    assert readiness["redis_reachable"] is True
    assert readiness["ready_for_horizontal_scale"] is True
