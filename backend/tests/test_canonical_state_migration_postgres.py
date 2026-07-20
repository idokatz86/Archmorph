"""Seeded PostgreSQL 013 -> 014 -> 013 -> 014 migration contracts (#1237)."""

from __future__ import annotations

import hashlib
import json
import os
import uuid

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
            assert statuses <= {"default_workspace_deduplicated"}


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
