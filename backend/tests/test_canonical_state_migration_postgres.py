"""Seeded PostgreSQL 013 -> 014 -> 013 -> 014 migration contracts (#1237)."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


POSTGRES_URL = os.getenv("ARCHMORPH_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="isolated PostgreSQL URL not configured")


def _alembic_config() -> Config:
    config = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    config.set_main_option("sqlalchemy.url", POSTGRES_URL)
    return config


def _idp_scope(provider: str, subject: str) -> str:
    material = b"archmorph-provider-tenant-v1" + b"\0" + provider.encode() + b"\0" + subject.encode()
    return f"idp:{hashlib.sha256(material).hexdigest()[:32]}"


def _reset_database(engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))


def _seed_013(engine) -> dict[str, str]:
    owner = "github_42"
    legacy_tenant = "github:github_42"
    long_target_tenant = _idp_scope("github", "42")
    ids = {name: str(uuid.uuid4()) for name in (
        "workspace_a", "workspace_b", "analysis_a", "analysis_b",
        "source_asset", "version_a", "version_b", "version_b_restore",
        "artifact_a", "artifact_b", "artifact_null_a", "artifact_null_b", "decision",
    )}
    snapshot_a = json.dumps({"source": "a", "mappings": []}, sort_keys=True)
    snapshot_b = json.dumps({"source": "b", "mappings": []}, sort_keys=True)
    artifact_content = "same artifact"
    artifact_hash = hashlib.sha256(artifact_content.encode()).hexdigest()
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO workspaces
                (id, owner_user_id, tenant_id, name, source_cloud, target_cloud, status, is_public)
            VALUES
                (:workspace_a, :owner, :tenant, 'Default Workspace', 'aws', 'azure', 'active', false),
                (:workspace_b, :owner, :tenant, 'Default Workspace', 'aws', 'azure', 'active', false)
        """), {**ids, "owner": owner, "tenant": legacy_tenant})
        connection.execute(text("""
            INSERT INTO source_assets
                (id, workspace_id, owner_user_id, tenant_id, filename)
            VALUES
                (:source_asset, :workspace_b, :owner, :tenant, 'legacy.tfstate')
        """), {**ids, "owner": owner, "tenant": legacy_tenant})
        connection.execute(text("""
            INSERT INTO analyses
                (id, workspace_id, source_asset_id, owner_user_id, tenant_id, diagram_id, source_cloud,
                 target_cloud, status, services_detected, current_version)
            VALUES
                (:analysis_a, :workspace_a, NULL, :owner, :tenant, 'duplicate-diagram', 'aws', 'azure', 'completed', 0, 1),
                (:analysis_b, :workspace_b, :source_asset, :owner, :tenant, 'duplicate-diagram', 'aws', 'azure', 'completed', 0, 2)
        """), {**ids, "owner": owner, "tenant": legacy_tenant})
        connection.execute(text("""
            INSERT INTO analysis_versions
                (id, analysis_id, version_number, snapshot, content_hash, created_by, restored_from)
            VALUES
                (:version_a, :analysis_a, 1, :snapshot_a, 'hash-a', :owner, NULL),
                (:version_b, :analysis_b, 1, :snapshot_b, 'hash-b', :owner, NULL),
                (:version_b_restore, :analysis_b, 2, :snapshot_b, 'hash-b-restore', :owner, 1)
        """), {**ids, "owner": owner, "snapshot_a": snapshot_a, "snapshot_b": snapshot_b})
        connection.execute(text("""
            INSERT INTO artifacts
                (id, analysis_id, version_id, owner_user_id, tenant_id, artifact_type,
                 format, content, content_hash, size_bytes)
            VALUES
                (:artifact_a, :analysis_a, :version_a, :owner, :tenant, 'terraform', 'terraform', :content, :hash, :size),
                (:artifact_b, :analysis_a, :version_a, :owner, :tenant, 'terraform', 'terraform', :content, :hash, :size),
                (:artifact_null_a, :analysis_b, NULL, :owner, :tenant, 'legacy-report', 'json', :content, :legacy_hash, :size),
                (:artifact_null_b, :analysis_b, NULL, :owner, :tenant, 'legacy-report', 'json', :content, :legacy_hash, :size)
        """), {
            **ids,
            "owner": owner,
            "tenant": legacy_tenant,
            "content": artifact_content,
            "hash": artifact_hash,
            "legacy_hash": hashlib.sha256(b"legacy-unversioned-artifact").hexdigest(),
            "size": len(artifact_content),
        })
        connection.execute(text("""
            INSERT INTO decisions
                (id, analysis_id, version_id, owner_user_id, tenant_id, decision_type, title, status)
            VALUES
                (:decision, :analysis_b, :version_b, :owner, :tenant, 'risk', 'preserve me', 'open')
        """), {**ids, "owner": owner, "tenant": legacy_tenant})
    return {**ids, "owner": owner, "target_tenant": long_target_tenant}


def _assert_014_state(engine, seeded: dict[str, str], *, expect_seed_audits: bool) -> None:
    with engine.connect() as connection:
        analyses = connection.execute(text("""
            SELECT id, tenant_id, current_version
            FROM analyses
            WHERE owner_user_id = :owner AND diagram_id = 'duplicate-diagram'
        """), seeded).mappings().all()
        assert len(analyses) == 1
        assert analyses[0]["tenant_id"] == seeded["target_tenant"]
        assert analyses[0]["current_version"] == 3
        analysis_id = analyses[0]["id"]
        source_asset_id = connection.execute(text(
            "SELECT source_asset_id FROM analyses WHERE id = :analysis_id"
        ), {"analysis_id": analysis_id}).scalar_one()
        assert source_asset_id == seeded["source_asset"]
        versions = connection.execute(text("""
            SELECT version_number, restored_from FROM analysis_versions
            WHERE analysis_id = :analysis_id ORDER BY version_number
        """), {"analysis_id": analysis_id}).all()
        assert [version_number for version_number, _ in versions] == [1, 2, 3]
        restored_versions = [
            (version_number, restored_from)
            for version_number, restored_from in versions
            if restored_from is not None
        ]
        assert len(restored_versions) == 1
        restored_version, restored_from = restored_versions[0]
        assert restored_from < restored_version
        assert connection.execute(text("SELECT count(*) FROM artifacts")).scalar_one() == 2
        asset_workspace = connection.execute(text("SELECT workspace_id FROM source_assets")).scalar_one()
        assert asset_workspace == connection.execute(text("SELECT workspace_id FROM analyses")).scalar_one()
        decision = connection.execute(text("SELECT analysis_id, tenant_id FROM decisions")).mappings().one()
        assert decision["analysis_id"] == analysis_id
        assert decision["tenant_id"] == seeded["target_tenant"]
        defaults = connection.execute(text("""
            SELECT count(*) FROM workspaces
            WHERE owner_user_id = :owner AND tenant_id = :target_tenant AND is_default
        """), seeded).scalar_one()
        assert defaults == 1
        statuses = set(connection.execute(text("SELECT status FROM tenant_rehome_audit")).scalars())
        if expect_seed_audits:
            assert {
                "rehome_completed",
                "analysis_deduplicated",
                "artifact_deduplicated",
            } <= statuses
        else:
            assert statuses <= {
                "default_workspace_deduplicated",
                "version_lineage_validated",
            }


def test_seeded_013_014_013_014_roundtrip_preserves_all_rows_and_long_tenants():
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    config = _alembic_config()
    try:
        _reset_database(engine)
        command.upgrade(config, "013")
        seeded = _seed_013(engine)
        command.upgrade(config, "014")
        _assert_014_state(engine, seeded, expect_seed_audits=True)

        command.downgrade(config, "013")
        columns = {column["name"]: column for column in inspect(engine).get_columns("workspaces")}
        assert columns["tenant_id"]["type"].length == 100
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM analyses")).scalar_one() == 1
            assert connection.execute(text("SELECT count(*) FROM analysis_versions")).scalar_one() == 3
            assert connection.execute(text("SELECT count(*) FROM artifacts")).scalar_one() == 2
            assert connection.execute(text("SELECT count(*) FROM decisions")).scalar_one() == 1
            assert connection.execute(text("SELECT count(*) FROM source_assets")).scalar_one() == 1
            assert connection.execute(text("SELECT tenant_id FROM analyses")).scalar_one() == seeded["target_tenant"]

        command.upgrade(config, "014")
        _assert_014_state(engine, seeded, expect_seed_audits=False)
    finally:
        _reset_database(engine)
        engine.dispose()


def test_migration_rehomes_clean_workspaces_and_quarantines_only_conflict():
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    config = _alembic_config()
    owner = "github_conflict-owner"
    source_tenant = f"github:{owner}"
    target_tenant = _idp_scope("github", "conflict-owner")
    ids = {
        name: str(uuid.uuid4())
        for name in (
            "target_workspace",
            "target_analysis",
            "clean_workspace_one",
            "clean_analysis_one",
            "clean_workspace_two",
            "clean_analysis_two",
            "conflict_workspace",
            "conflict_analysis",
        )
    }
    try:
        _reset_database(engine)
        command.upgrade(config, "013")
        with engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO workspaces
                    (id, owner_user_id, tenant_id, name, source_cloud, target_cloud, status, is_public)
                VALUES
                    (:target_workspace, :owner, :target_tenant, 'Target', 'aws', 'azure', 'active', false),
                    (:clean_workspace_one, :owner, :source_tenant, 'Clean one', 'aws', 'azure', 'active', false),
                    (:clean_workspace_two, :owner, :source_tenant, 'Clean two', 'aws', 'azure', 'active', false),
                    (:conflict_workspace, :owner, :source_tenant, 'Conflict', 'aws', 'azure', 'active', false)
            """), {**ids, "owner": owner, "source_tenant": source_tenant, "target_tenant": target_tenant})
            connection.execute(text("""
                INSERT INTO analyses
                    (id, workspace_id, owner_user_id, tenant_id, diagram_id, source_cloud,
                     target_cloud, status, services_detected, current_version)
                VALUES
                    (:target_analysis, :target_workspace, :owner, :target_tenant, 'same-diagram', 'aws', 'azure', 'completed', 0, 0),
                    (:clean_analysis_one, :clean_workspace_one, :owner, :source_tenant, 'clean-one', 'aws', 'azure', 'completed', 0, 0),
                    (:clean_analysis_two, :clean_workspace_two, :owner, :source_tenant, 'clean-two', 'aws', 'azure', 'completed', 0, 0),
                    (:conflict_analysis, :conflict_workspace, :owner, :source_tenant, 'same-diagram', 'aws', 'azure', 'completed', 0, 0)
            """), {**ids, "owner": owner, "source_tenant": source_tenant, "target_tenant": target_tenant})

        command.upgrade(config, "014")
        with engine.connect() as connection:
            migrated = connection.execute(text("""
                SELECT diagram_id FROM analyses
                WHERE owner_user_id = :owner AND tenant_id = :target_tenant
                ORDER BY diagram_id
            """), {"owner": owner, "target_tenant": target_tenant}).scalars().all()
            assert migrated == ["clean-one", "clean-two", "same-diagram"]
            retained = connection.execute(text("""
                SELECT diagram_id FROM analyses
                WHERE owner_user_id = :owner AND tenant_id = :source_tenant
            """), {"owner": owner, "source_tenant": source_tenant}).scalars().all()
            assert retained == ["same-diagram"]
            alias_statuses = connection.execute(text("""
                SELECT source_entity_id, status FROM tenant_rehome_aliases
                WHERE entity_type = 'analysis'
            """)).all()
            assert (ids["clean_analysis_one"], "rehomed") in alias_statuses
            assert (ids["clean_analysis_two"], "rehomed") in alias_statuses
            assert (ids["conflict_analysis"], "quarantined") in alias_statuses

        with pytest.raises(RuntimeError, match="unresolved tenant migration quarantines"):
            command.downgrade(config, "013")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM analyses")).scalar_one() == 4
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "014"
    finally:
        _reset_database(engine)
        engine.dispose()


def test_013_production_init_is_read_only_then_014_migrates_without_partial_schema(
    monkeypatch,
):
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    config = _alembic_config()
    try:
        _reset_database(engine)
        command.upgrade(config, "013")
        inspector = inspect(engine)
        assert "tenant_rehome_audit" not in inspector.get_table_names()
        assert "is_default" not in {
            column["name"] for column in inspector.get_columns("workspaces")
        }

        import database

        monkeypatch.setattr(database, "engine", engine)
        monkeypatch.setattr(database, "_IS_POSTGRES", True)
        monkeypatch.setattr(database, "_IS_SQLITE", False)
        monkeypatch.setattr(database, "_PRODUCTION_LIKE", True)
        monkeypatch.setattr(database, "_ENFORCE_POSTGRES", True)
        with patch.object(
            database.Base.metadata,
            "create_all",
            side_effect=AssertionError("production create_all must not run"),
        ):
            readiness_013 = database.database_readiness()
            assert readiness_013["current_revision"] == "013"
            assert readiness_013["expected_revision"] == "014"
            assert readiness_013["schema_at_head"] is False
            assert readiness_013["required_schema_present"] is False
            assert {
                "table:api_key_credentials",
                "table:analysis_mutation_receipts",
                "table:diagram_lifecycle",
                "table:migration_replay_events",
                "table:migration_replays",
                "table:purge_operations",
                "table:restore_grants",
                "table:tenant_rehome_audit",
                "table:tenant_rehome_aliases",
                "table:project_members",
                "column:workspaces.is_default",
            } <= set(readiness_013["missing_schema_objects"])
            with pytest.raises(
                RuntimeError,
                match="Production database is not at the expected Alembic head",
            ):
                database.init_db()

        inspector.clear_cache()
        assert "tenant_rehome_audit" not in inspector.get_table_names()
        assert "is_default" not in {
            column["name"] for column in inspector.get_columns("workspaces")
        }

        command.upgrade(config, "014")
        readiness_014 = database.database_readiness()
        assert readiness_014["current_revision"] == "014"
        assert readiness_014["expected_revision"] == "014"
        assert readiness_014["schema_at_head"] is True
        assert readiness_014["required_schema_present"] is True
        assert readiness_014["missing_schema_objects"] == []
        assert readiness_014["ready_for_production"] is True
        database.init_db()
    finally:
        _reset_database(engine)
        engine.dispose()


def _seed_duplicate_tenant_scope(engine, *, tenant: str | None, suffix: str) -> None:
    ids = {
        name: str(uuid.uuid4())
        for name in (
            "workspace_a",
            "workspace_b",
            "analysis_a",
            "analysis_b",
            "version_a",
            "version_b",
            "artifact_versioned_a",
            "artifact_versioned_b",
            "artifact_moved",
            "artifact_unversioned_a",
            "artifact_unversioned_b",
        )
    }
    owner = "all-tenant-duplicate-owner"
    diagram_id = "all-tenant-duplicate-diagram"
    content_hash = hashlib.sha256(f"artifact-{suffix}".encode()).hexdigest()
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO workspaces
                (id, owner_user_id, tenant_id, name, source_cloud, target_cloud, status, is_public)
            VALUES
                (:workspace_a, :owner, :tenant, 'Default Workspace', 'aws', 'azure', 'active', false),
                (:workspace_b, :owner, :tenant, 'Default Workspace', 'aws', 'azure', 'active', false)
        """), {**ids, "owner": owner, "tenant": tenant})
        connection.execute(text("""
            INSERT INTO analyses
                (id, workspace_id, owner_user_id, tenant_id, diagram_id, source_cloud,
                 target_cloud, status, services_detected, current_version)
            VALUES
                (:analysis_a, :workspace_a, :owner, :tenant, :diagram_id, 'aws', 'azure', 'completed', 0, 1),
                (:analysis_b, :workspace_b, :owner, :tenant, :diagram_id, 'aws', 'azure', 'completed', 0, 1)
        """), {**ids, "owner": owner, "tenant": tenant, "diagram_id": diagram_id})
        connection.execute(text("""
            INSERT INTO analysis_versions
                (id, analysis_id, version_number, snapshot, content_hash, created_by)
            VALUES
                (:version_a, :analysis_a, 1, :snapshot_a, 'version-a', :owner),
                (:version_b, :analysis_b, 1, :snapshot_b, 'version-b', :owner)
        """), {
            **ids,
            "owner": owner,
            "snapshot_a": json.dumps({"scope": suffix, "copy": "a"}, sort_keys=True),
            "snapshot_b": json.dumps({"scope": suffix, "copy": "b"}, sort_keys=True),
        })
        connection.execute(text("""
            INSERT INTO artifacts
                (id, analysis_id, version_id, owner_user_id, tenant_id, artifact_type,
                 format, content, content_hash, size_bytes)
            VALUES
                (:artifact_versioned_a, :analysis_a, :version_a, :owner, :tenant, 'terraform',
                 'terraform', :content, :content_hash, 8),
                (:artifact_versioned_b, :analysis_a, :version_a, :owner, :tenant, 'terraform',
                 'terraform', :content, :content_hash, 8),
                (:artifact_moved, :analysis_b, :version_b, :owner, :tenant, 'terraform',
                 'terraform', :content, :content_hash, 8),
                (:artifact_unversioned_a, :analysis_a, NULL, :owner, :tenant, 'legacy-report',
                 'json', :content, :content_hash, 8),
                (:artifact_unversioned_b, :analysis_b, NULL, :owner, :tenant, 'legacy-report',
                 'json', :content, :content_hash, 8)
        """), {
            **ids,
            "owner": owner,
            "tenant": tenant,
            "content": f"scope-{suffix}",
            "content_hash": content_hash,
        })


def _assert_all_tenant_duplicate_state(engine) -> None:
    with engine.connect() as connection:
        analyses = connection.execute(text("""
            SELECT tenant_id, count(*) AS row_count, max(current_version) AS current_version
            FROM analyses
            WHERE owner_user_id = 'all-tenant-duplicate-owner'
              AND diagram_id = 'all-tenant-duplicate-diagram'
            GROUP BY tenant_id
        """)).mappings().all()
        assert {(row["tenant_id"], row["row_count"], row["current_version"]) for row in analyses} == {
            (None, 1, 2),
            ("tenant-b", 1, 2),
        }
        assert connection.execute(text("""
            SELECT count(*) FROM analysis_versions
            WHERE analysis_id IN (
                SELECT id FROM analyses
                WHERE owner_user_id = 'all-tenant-duplicate-owner'
            )
        """)).scalar_one() == 4
        assert connection.execute(text("""
            SELECT count(*) FROM artifacts
            WHERE owner_user_id = 'all-tenant-duplicate-owner'
        """)).scalar_one() == 6
        defaults = connection.execute(text("""
            SELECT tenant_id, count(*)
            FROM workspaces
            WHERE owner_user_id = 'all-tenant-duplicate-owner' AND is_default
            GROUP BY tenant_id
        """)).all()
        assert set(defaults) == {(None, 1), ("tenant-b", 1)}


def test_all_tenant_duplicate_groups_and_artifacts_survive_roundtrip():
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    config = _alembic_config()
    try:
        _reset_database(engine)
        command.upgrade(config, "013")
        _seed_duplicate_tenant_scope(engine, tenant=None, suffix="tenantless")
        _seed_duplicate_tenant_scope(engine, tenant="tenant-b", suffix="tenant-b")

        command.upgrade(config, "014")
        _assert_all_tenant_duplicate_state(engine)
        command.downgrade(config, "013")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM analyses")).scalar_one() == 2
            assert connection.execute(text("SELECT count(*) FROM analysis_versions")).scalar_one() == 4
            assert connection.execute(text("SELECT count(*) FROM artifacts")).scalar_one() == 6
        command.upgrade(config, "014")
        _assert_all_tenant_duplicate_state(engine)
    finally:
        _reset_database(engine)
        engine.dispose()


def test_duplicate_analysis_restore_lineage_is_normalized_before_fk_and_survives_roundtrip():
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    config = _alembic_config()
    ids = {
        name: str(uuid.UUID(int=index))
        for index, name in enumerate(
            (
                "workspace_a",
                "workspace_b",
                "analysis_a",
                "analysis_b",
                "a1",
                "a2",
                "a3",
                "b1",
                "b2",
                "b3",
                "b4",
            ),
            start=1,
        )
    }
    owner = "lineage-migration-owner"
    tenant = "lineage-migration-tenant"
    try:
        _reset_database(engine)
        command.upgrade(config, "013")
        with engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO workspaces
                    (id, owner_user_id, tenant_id, name, source_cloud, target_cloud, status, is_public)
                VALUES
                    (:workspace_a, :owner, :tenant, 'A', 'aws', 'azure', 'active', false),
                    (:workspace_b, :owner, :tenant, 'B', 'aws', 'azure', 'active', false)
            """), {**ids, "owner": owner, "tenant": tenant})
            connection.execute(text("""
                INSERT INTO analyses
                    (id, workspace_id, owner_user_id, tenant_id, diagram_id, source_cloud,
                     target_cloud, status, services_detected, current_version)
                VALUES
                    (:analysis_a, :workspace_a, :owner, :tenant, 'lineage-diagram', 'aws', 'azure', 'completed', 0, 3),
                    (:analysis_b, :workspace_b, :owner, :tenant, 'lineage-diagram', 'aws', 'azure', 'completed', 0, 4)
            """), {**ids, "owner": owner, "tenant": tenant})
            connection.execute(text("""
                INSERT INTO analysis_versions
                    (id, analysis_id, version_number, snapshot, content_hash, created_by, restored_from)
                VALUES
                    (:a1, :analysis_a, 1, :snapshot_a1, 'a1', :owner, NULL),
                    (:a2, :analysis_a, 2, :snapshot_a2, 'a2', :owner, 1),
                    (:a3, :analysis_a, 3, :snapshot_a3, 'a3', :owner, 99),
                    (:b1, :analysis_b, 1, :snapshot_b1, 'b1', :owner, NULL),
                    (:b2, :analysis_b, 2, :snapshot_b2, 'b2', :owner, 1),
                    (:b3, :analysis_b, 3, :snapshot_b3, 'b3', :owner, 4),
                    (:b4, :analysis_b, 4, :snapshot_b4, 'b4', :owner, 3)
            """), {
                **ids,
                "owner": owner,
                **{
                    f"snapshot_{prefix}{number}": json.dumps({prefix: number})
                    for prefix, maximum in (("a", 3), ("b", 4))
                    for number in range(1, maximum + 1)
                },
            })

        command.upgrade(config, "014")
        with engine.connect() as connection:
            analysis_id = connection.execute(text("""
                SELECT id FROM analyses
                WHERE owner_user_id = :owner AND tenant_id = :tenant
                  AND diagram_id = 'lineage-diagram'
            """), {"owner": owner, "tenant": tenant}).scalar_one()
            lineage = connection.execute(text("""
                SELECT version_number, restored_from FROM analysis_versions
                WHERE analysis_id = :analysis_id ORDER BY version_number
            """), {"analysis_id": analysis_id}).all()
            assert lineage == [
                (1, None),
                (2, 1),
                (3, None),
                (4, None),
                (5, 4),
                (6, None),
                (7, 6),
            ]
            evidence = [
                json.loads(value)
                for value in connection.execute(text("""
                    SELECT details FROM tenant_rehome_audit
                    WHERE status IN ('analysis_deduplicated', 'version_lineage_normalized')
                    ORDER BY created_at, id
                """)).scalars()
            ]
            assert any(item.get("lineage_remap") for item in evidence)
            repairs = [repair for item in evidence for repair in item.get("repairs", [])]
            assert {repair["reason"] for repair in repairs} == {
                "missing_ancestor",
                "lineage_cycle",
            }

        command.downgrade(config, "013")
        command.upgrade(config, "014")
        with engine.connect() as connection:
            assert connection.execute(text("""
                SELECT count(*) FROM analysis_versions
                WHERE analysis_id = (SELECT id FROM analyses WHERE diagram_id = 'lineage-diagram')
            """)).scalar_one() == 7
    finally:
        _reset_database(engine)
        engine.dispose()


def test_downgrade_refuses_to_discard_unresolved_quarantine_evidence():
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    config = _alembic_config()
    try:
        _reset_database(engine)
        command.upgrade(config, "014")
        with engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO tenant_rehome_aliases
                    (id, source_owner_user_id, source_tenant_id, target_owner_user_id,
                     target_tenant_id, entity_type, source_entity_id, status, reason)
                VALUES
                    (:id, 'legacy', 'default_tenant', 'target', 'target-tenant',
                     'workspace', 'workspace-evidence', 'quarantined', 'target_diagram_conflict')
            """), {"id": str(uuid.uuid4())})
        with pytest.raises(RuntimeError, match="unresolved tenant migration quarantines"):
            command.downgrade(config, "013")
        with engine.connect() as connection:
            assert connection.execute(text("""
                SELECT count(*) FROM tenant_rehome_aliases WHERE status = 'quarantined'
            """)).scalar_one() == 1
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "014"
    finally:
        _reset_database(engine)
        engine.dispose()
