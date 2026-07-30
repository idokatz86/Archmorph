"""Expand/contract schema activation and tenant-alias compatibility contracts."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from database import Base
import models  # noqa: F401
from models.workspace import Analysis, TenantRehomeAlias
from schema_compatibility import SCHEMA_CONTRACT, schema_is_supported, supported_schema_metadata
from workspace_store import create_workspace, get_analysis_record


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_schema_metadata_declares_bounded_rollback_window():
    metadata = supported_schema_metadata()

    assert metadata == {
        "minimum_revision": "014",
        "maximum_revision": "014",
        "accepted_revisions": ["014"],
        "migration_target_revision": "014",
        "alias_read_through_until": "014",
        "release_role": "final",
    }
    assert SCHEMA_CONTRACT.minimum_revision != "013"


def test_schema_compatibility_rejects_unknown_split_or_missing_heads():
    assert schema_is_supported("014") is True
    assert schema_is_supported("015") is False
    assert schema_is_supported("013") is False
    assert schema_is_supported("014,015") is False
    assert schema_is_supported("014,unknown") is False
    assert schema_is_supported(None) is False
    assert schema_is_supported("") is False


def test_bridge_profile_accepts_013_and_014_without_weakening_final(monkeypatch):
    monkeypatch.setenv("ARCHMORPH_RELEASE_ROLE", "bridge")

    assert schema_is_supported("013") is True
    assert schema_is_supported("014") is True
    assert supported_schema_metadata()["accepted_revisions"] == ["013", "014"]

    monkeypatch.setenv("ARCHMORPH_RELEASE_ROLE", "final")
    assert schema_is_supported("013") is False
    assert schema_is_supported("014") is True


def test_resolved_tenant_alias_read_through_keeps_previous_identity_usable(db):
    workspace = create_workspace(
        db,
        owner_user_id="canonical-owner",
        tenant_id="canonical-tenant",
        name="Canonical",
    )
    analysis = Analysis(
        workspace_id=workspace.id,
        owner_user_id="canonical-owner",
        tenant_id="canonical-tenant",
        diagram_id="alias-window-diagram",
        source_cloud="aws",
        target_cloud="azure",
        status="completed",
        services_detected=0,
        current_version=0,
    )
    db.add(analysis)
    db.flush()
    db.add(
        TenantRehomeAlias(
            source_owner_user_id="legacy-owner",
            source_tenant_id="default_tenant",
            target_owner_user_id="canonical-owner",
            target_tenant_id="canonical-tenant",
            entity_type="analysis",
            source_entity_id="legacy-analysis-id",
            target_entity_id=analysis.id,
            status="resolved",
            reason="operator_reconciled",
        )
    )
    db.commit()

    found = get_analysis_record(
        db,
        "legacy-analysis-id",
        owner_user_id="legacy-owner",
        tenant_id="default_tenant",
    )

    assert found is not None
    assert found.id == analysis.id
    assert found.owner_user_id == "canonical-owner"
    assert found.tenant_id == "canonical-tenant"


def test_quarantined_or_foreign_alias_never_reads_through(db):
    workspace = create_workspace(
        db,
        owner_user_id="canonical-owner",
        tenant_id="canonical-tenant",
        name="Canonical",
    )
    analysis = Analysis(
        workspace_id=workspace.id,
        owner_user_id="canonical-owner",
        tenant_id="canonical-tenant",
        source_cloud="aws",
        target_cloud="azure",
        status="completed",
        services_detected=0,
        current_version=0,
    )
    db.add(analysis)
    db.flush()
    db.add(
        TenantRehomeAlias(
            source_owner_user_id="legacy-owner",
            source_tenant_id="default_tenant",
            target_owner_user_id="canonical-owner",
            target_tenant_id="canonical-tenant",
            entity_type="analysis",
            source_entity_id="legacy-analysis-id",
            target_entity_id=analysis.id,
            status="quarantined",
            reason="target_diagram_conflict",
        )
    )
    db.commit()

    assert get_analysis_record(
        db,
        "legacy-analysis-id",
        owner_user_id="legacy-owner",
        tenant_id="default_tenant",
    ) is None
    assert get_analysis_record(
        db,
        "legacy-analysis-id",
        owner_user_id="foreign-owner",
        tenant_id="default_tenant",
    ) is None
