"""
Tests for workspace_store.py — durable workspaces, analyses, versions,
artifacts, and decisions (Issue #1129).

Covers:
- Workspace CRUD and ownership enforcement
- SourceAsset creation and listing
- Analysis creation, listing within workspace
- AnalysisVersion append-only semantics, trim cap, restore
- Artifact linkage to analysis and version
- Decision recording
- Tenant boundary enforcement
- maybe_link_session bridge helper
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import Base
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401 — register all ORM models with Base.metadata
from workspace_store import (
    MAX_VERSIONS_PER_ANALYSIS,
    create_analysis,
    create_artifact,
    create_decision,
    create_source_asset,
    create_workspace,
    delete_workspace,
    get_analysis_record,
    get_analysis_version,
    get_artifact,
    get_workspace,
    list_analyses_in_workspace,
    list_analysis_versions,
    list_artifacts,
    list_decisions,
    list_source_assets,
    list_workspaces,
    maybe_link_session,
    restore_analysis_version,
    save_analysis_version,
    update_workspace,
)


# ─────────────────────────────────────────────────────────────
# In-memory SQLite fixture
# ─────────────────────────────────────────────────────────────

@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


# ─────────────────────────────────────────────────────────────
# Workspace CRUD
# ─────────────────────────────────────────────────────────────

class TestWorkspaceCRUD:
    def test_create_returns_workspace(self, db):
        ws = create_workspace(db, owner_user_id="u1", name="My WS")
        assert ws.id is not None
        assert ws.owner_user_id == "u1"
        assert ws.name == "My WS"
        assert ws.status == "active"

    def test_get_own_workspace(self, db):
        ws = create_workspace(db, owner_user_id="u1", name="WS-A")
        found = get_workspace(db, ws.id, owner_user_id="u1")
        assert found is not None
        assert found.id == ws.id

    def test_get_other_user_returns_none(self, db):
        ws = create_workspace(db, owner_user_id="u1", name="WS-B")
        found = get_workspace(db, ws.id, owner_user_id="u2")
        assert found is None

    def test_list_workspaces(self, db):
        create_workspace(db, owner_user_id="u3", name="A")
        create_workspace(db, owner_user_id="u3", name="B")
        result = list_workspaces(db, owner_user_id="u3")
        assert result["total"] == 2
        assert len(result["workspaces"]) == 2

    def test_list_workspaces_empty(self, db):
        result = list_workspaces(db, owner_user_id="nobody")
        assert result["total"] == 0

    def test_list_workspaces_tenant_isolation(self, db):
        create_workspace(db, owner_user_id="u4", tenant_id="t1", name="WS-T1")
        create_workspace(db, owner_user_id="u4", tenant_id="t2", name="WS-T2")
        result = list_workspaces(db, owner_user_id="u4", tenant_id="t1")
        assert result["total"] == 1
        assert result["workspaces"][0]["name"] == "WS-T1"

    def test_update_workspace(self, db):
        ws = create_workspace(db, owner_user_id="u5", name="Old Name")
        updated = update_workspace(db, ws.id, owner_user_id="u5", name="New Name")
        assert updated.name == "New Name"

    def test_update_workspace_wrong_user(self, db):
        ws = create_workspace(db, owner_user_id="u5", name="WS")
        result = update_workspace(db, ws.id, owner_user_id="attacker", name="hacked")
        assert result is None

    def test_delete_workspace(self, db):
        ws = create_workspace(db, owner_user_id="u6", name="Delete Me")
        assert delete_workspace(db, ws.id, owner_user_id="u6") is True
        assert get_workspace(db, ws.id, owner_user_id="u6") is None

    def test_delete_workspace_wrong_user(self, db):
        ws = create_workspace(db, owner_user_id="u6", name="WS")
        assert delete_workspace(db, ws.id, owner_user_id="attacker") is False

    def test_to_dict_fields(self, db):
        ws = create_workspace(db, owner_user_id="u7", name="Dict WS", description="desc")
        d = ws.to_dict()
        assert d["id"] == ws.id
        assert d["owner_user_id"] == "u7"
        assert d["name"] == "Dict WS"
        assert d["description"] == "desc"
        assert "created_at" in d


# ─────────────────────────────────────────────────────────────
# SourceAsset CRUD
# ─────────────────────────────────────────────────────────────

class TestSourceAsset:
    def test_create_source_asset(self, db):
        ws = create_workspace(db, owner_user_id="u1", name="WS")
        asset = create_source_asset(
            db,
            workspace_id=ws.id,
            owner_user_id="u1",
            filename="diagram.png",
            content_type="image/png",
            file_size_bytes=1024,
            content_hash="abc123",
            diagram_id="diag-001",
        )
        assert asset.id is not None
        assert asset.workspace_id == ws.id
        assert asset.filename == "diagram.png"

    def test_create_source_asset_rejects_foreign_workspace(self, db):
        ws = create_workspace(db, owner_user_id="u1", tenant_id="t1", name="WS")
        with pytest.raises(ValueError):
            create_source_asset(
                db,
                workspace_id=ws.id,
                owner_user_id="u2",
                tenant_id="t2",
                filename="diagram.png",
            )

    def test_list_source_assets(self, db):
        ws = create_workspace(db, owner_user_id="u1", name="WS")
        create_source_asset(db, workspace_id=ws.id, owner_user_id="u1", filename="a.png")
        create_source_asset(db, workspace_id=ws.id, owner_user_id="u1", filename="b.png")
        result = list_source_assets(db, workspace_id=ws.id, owner_user_id="u1")
        assert result["total"] == 2

    def test_source_asset_to_dict(self, db):
        ws = create_workspace(db, owner_user_id="u1", name="WS")
        asset = create_source_asset(
            db,
            workspace_id=ws.id,
            owner_user_id="u1",
            filename="f.vsdx",
        )
        d = asset.to_dict()
        assert d["filename"] == "f.vsdx"
        assert "created_at" in d


# ─────────────────────────────────────────────────────────────
# Analysis CRUD
# ─────────────────────────────────────────────────────────────

class TestAnalysisCRUD:
    def test_create_analysis(self, db):
        ws = create_workspace(db, owner_user_id="u1", name="WS")
        analysis = create_analysis(
            db,
            workspace_id=ws.id,
            owner_user_id="u1",
            diagram_id="diag-001",
            source_cloud="aws",
            target_cloud="azure",
        )
        assert analysis.id is not None
        assert analysis.workspace_id == ws.id
        assert analysis.diagram_id == "diag-001"

    def test_create_analysis_rejects_foreign_workspace(self, db):
        ws = create_workspace(db, owner_user_id="u1", tenant_id="t1", name="WS")
        with pytest.raises(ValueError):
            create_analysis(db, workspace_id=ws.id, owner_user_id="u2", tenant_id="t2", diagram_id="d1")

    def test_create_analysis_rejects_asset_from_other_workspace(self, db):
        ws_a = create_workspace(db, owner_user_id="u1", name="WS-A")
        ws_b = create_workspace(db, owner_user_id="u1", name="WS-B")
        asset = create_source_asset(db, workspace_id=ws_a.id, owner_user_id="u1", filename="diagram.png")
        with pytest.raises(ValueError):
            create_analysis(
                db,
                workspace_id=ws_b.id,
                owner_user_id="u1",
                source_asset_id=asset.id,
                diagram_id="d1",
            )

    def test_get_analysis_ownership(self, db):
        ws = create_workspace(db, owner_user_id="u1", name="WS")
        a = create_analysis(db, workspace_id=ws.id, owner_user_id="u1", diagram_id="d1")
        # owner can read
        assert get_analysis_record(db, a.id, owner_user_id="u1") is not None
        # other user cannot
        assert get_analysis_record(db, a.id, owner_user_id="attacker") is None

    def test_list_analyses_in_workspace(self, db):
        ws = create_workspace(db, owner_user_id="u2", name="WS")
        create_analysis(db, workspace_id=ws.id, owner_user_id="u2", diagram_id="d1")
        create_analysis(db, workspace_id=ws.id, owner_user_id="u2", diagram_id="d2")
        result = list_analyses_in_workspace(db, workspace_id=ws.id, owner_user_id="u2")
        assert result["total"] == 2

    def test_list_analyses_tenant_boundary(self, db):
        ws_a = create_workspace(db, owner_user_id="u1", tenant_id="t1", name="WS-A")
        ws_b = create_workspace(db, owner_user_id="u2", tenant_id="t2", name="WS-B")
        create_analysis(db, workspace_id=ws_a.id, owner_user_id="u1", tenant_id="t1", diagram_id="da")
        create_analysis(db, workspace_id=ws_b.id, owner_user_id="u2", tenant_id="t2", diagram_id="db")
        result_a = list_analyses_in_workspace(db, workspace_id=ws_a.id, owner_user_id="u1", tenant_id="t1")
        result_b = list_analyses_in_workspace(db, workspace_id=ws_b.id, owner_user_id="u1", tenant_id="t1")
        assert result_a["total"] == 1
        # u1 cannot list ws_b's analyses
        assert result_b["total"] == 0


# ─────────────────────────────────────────────────────────────
# AnalysisVersion
# ─────────────────────────────────────────────────────────────

class TestAnalysisVersions:
    def _make_analysis(self, db, owner="u1"):
        ws = create_workspace(db, owner_user_id=owner, name="WS")
        return create_analysis(
            db,
            workspace_id=ws.id,
            owner_user_id=owner,
            diagram_id="diag-v",
            source_cloud="gcp",
            target_cloud="azure",
        )

    def test_save_version_increments(self, db):
        a = self._make_analysis(db)
        v1 = save_analysis_version(db, analysis_id=a.id, owner_user_id="u1", snapshot={"x": 1})
        v2 = save_analysis_version(db, analysis_id=a.id, owner_user_id="u1", snapshot={"x": 2})
        assert v1.version_number == 1
        assert v2.version_number == 2

    def test_save_version_updates_analysis_current(self, db):
        a = self._make_analysis(db)
        save_analysis_version(db, analysis_id=a.id, owner_user_id="u1", snapshot={"x": 1})
        db.refresh(a)
        assert a.current_version == 1

    def test_save_version_wrong_user(self, db):
        a = self._make_analysis(db)
        with pytest.raises(ValueError):
            save_analysis_version(
                db, analysis_id=a.id, owner_user_id="attacker", snapshot={}
            )

    def test_list_versions_metadata_only(self, db):
        a = self._make_analysis(db)
        save_analysis_version(db, analysis_id=a.id, owner_user_id="u1", snapshot={"a": 1})
        save_analysis_version(db, analysis_id=a.id, owner_user_id="u1", snapshot={"b": 2})
        versions = list_analysis_versions(db, analysis_id=a.id, owner_user_id="u1")
        assert len(versions) == 2
        # Snapshot not included in listing
        for v in versions:
            assert "snapshot" not in v

    def test_list_versions_wrong_user(self, db):
        a = self._make_analysis(db)
        save_analysis_version(db, analysis_id=a.id, owner_user_id="u1", snapshot={})
        result = list_analysis_versions(db, analysis_id=a.id, owner_user_id="attacker")
        assert result == []

    def test_get_version_includes_snapshot(self, db):
        a = self._make_analysis(db)
        save_analysis_version(db, analysis_id=a.id, owner_user_id="u1", snapshot={"key": "val"})
        v = get_analysis_version(db, analysis_id=a.id, version_number=1, owner_user_id="u1")
        assert v is not None
        d = v.to_dict(include_snapshot=True)
        assert d["snapshot"]["key"] == "val"

    def test_save_version_redacts_internal_session_metadata(self, db):
        a = self._make_analysis(db)
        save_analysis_version(
            db,
            analysis_id=a.id,
            owner_user_id="u1",
            snapshot={
                "services_detected": 1,
                "_owner_user_id": "u1",
                "_tenant_id": "t1",
                "export_capability": {"token": "opaque"},
            },
        )
        v = get_analysis_version(db, analysis_id=a.id, version_number=1, owner_user_id="u1")
        snap = json.loads(v.snapshot)
        assert "_owner_user_id" not in snap
        assert "_tenant_id" not in snap
        assert "export_capability" not in snap

    def test_get_version_not_found(self, db):
        a = self._make_analysis(db)
        v = get_analysis_version(db, analysis_id=a.id, version_number=99, owner_user_id="u1")
        assert v is None

    def test_version_cap_trims_oldest(self, db):
        a = self._make_analysis(db)
        for i in range(MAX_VERSIONS_PER_ANALYSIS + 5):
            save_analysis_version(db, analysis_id=a.id, owner_user_id="u1", snapshot={"i": i})
        versions = list_analysis_versions(db, analysis_id=a.id, owner_user_id="u1")
        assert len(versions) <= MAX_VERSIONS_PER_ANALYSIS

    def test_restore_version_creates_new(self, db):
        a = self._make_analysis(db)
        save_analysis_version(db, analysis_id=a.id, owner_user_id="u1", snapshot={"step": "original"})
        save_analysis_version(db, analysis_id=a.id, owner_user_id="u1", snapshot={"step": "updated"})
        new_v = restore_analysis_version(
            db, analysis_id=a.id, version_number=1, owner_user_id="u1"
        )
        assert new_v is not None
        assert new_v.restored_from == 1
        assert new_v.version_number == 3
        # Snapshot matches original
        snap = json.loads(new_v.snapshot)
        assert snap["step"] == "original"

    def test_restore_nonexistent_version(self, db):
        a = self._make_analysis(db)
        result = restore_analysis_version(
            db, analysis_id=a.id, version_number=99, owner_user_id="u1"
        )
        assert result is None

    def test_restore_updates_session_store(self, db):
        a = self._make_analysis(db)
        save_analysis_version(db, analysis_id=a.id, owner_user_id="u1", snapshot={"v": 1})

        class _FakeStore:
            def __init__(self):
                self.data = {}

            def set(self, key, value):
                self.data[key] = value

        store = _FakeStore()
        restore_analysis_version(
            db, analysis_id=a.id, version_number=1, owner_user_id="u1",
            session_store=store,
        )
        assert "diag-v" in store.data
        assert store.data["diag-v"]["v"] == 1

    def test_restore_does_not_overwrite_foreign_session_owner(self, db):
        a = self._make_analysis(db)
        save_analysis_version(db, analysis_id=a.id, owner_user_id="u1", snapshot={"v": 1})

        class _FakeStore:
            def __init__(self):
                self.data = {"diag-v": {"_owner_user_id": "attacker", "_tenant_id": None}}

            def get(self, key):
                return self.data.get(key)

            def set(self, key, value):
                self.data[key] = value

        store = _FakeStore()
        new_v = restore_analysis_version(
            db,
            analysis_id=a.id,
            version_number=1,
            owner_user_id="u1",
            session_store=store,
        )
        assert new_v is not None
        assert store.data["diag-v"]["_owner_user_id"] == "attacker"


# ─────────────────────────────────────────────────────────────
# Artifact linkage
# ─────────────────────────────────────────────────────────────

class TestArtifactLinkage:
    def _make_analysis(self, db, owner="u1"):
        ws = create_workspace(db, owner_user_id=owner, name="WS")
        return create_analysis(
            db,
            workspace_id=ws.id,
            owner_user_id=owner,
            diagram_id="diag-art",
        )

    def test_create_artifact(self, db):
        a = self._make_analysis(db)
        artifact = create_artifact(
            db,
            analysis_id=a.id,
            owner_user_id="u1",
            artifact_type="terraform",
            format="terraform",
            content="resource {}",
        )
        assert artifact.id is not None
        assert artifact.analysis_id == a.id
        assert artifact.content_hash is not None
        assert artifact.size_bytes > 0

    def test_artifact_links_to_version(self, db):
        a = self._make_analysis(db)
        version = save_analysis_version(db, analysis_id=a.id, owner_user_id="u1", snapshot={})
        artifact = create_artifact(
            db,
            analysis_id=a.id,
            version_id=version.id,
            owner_user_id="u1",
            artifact_type="bicep",
        )
        assert artifact.version_id == version.id

    def test_list_artifacts(self, db):
        a = self._make_analysis(db)
        create_artifact(db, analysis_id=a.id, owner_user_id="u1", artifact_type="terraform")
        create_artifact(db, analysis_id=a.id, owner_user_id="u1", artifact_type="hld")
        result = list_artifacts(db, analysis_id=a.id, owner_user_id="u1")
        assert result["total"] == 2

    def test_list_artifacts_by_type(self, db):
        a = self._make_analysis(db)
        create_artifact(db, analysis_id=a.id, owner_user_id="u1", artifact_type="terraform")
        create_artifact(db, analysis_id=a.id, owner_user_id="u1", artifact_type="hld")
        result = list_artifacts(db, analysis_id=a.id, owner_user_id="u1", artifact_type="terraform")
        assert result["total"] == 1

    def test_get_artifact_ownership(self, db):
        a = self._make_analysis(db)
        art = create_artifact(db, analysis_id=a.id, owner_user_id="u1", artifact_type="bicep")
        assert get_artifact(db, art.id, owner_user_id="u1") is not None
        assert get_artifact(db, art.id, owner_user_id="attacker") is None

    def test_artifact_to_dict_no_content_by_default(self, db):
        a = self._make_analysis(db)
        art = create_artifact(
            db,
            analysis_id=a.id,
            owner_user_id="u1",
            artifact_type="cost_report",
            content="$1234",
        )
        d = art.to_dict()
        assert "content" not in d

    def test_artifact_to_dict_with_content(self, db):
        a = self._make_analysis(db)
        art = create_artifact(
            db,
            analysis_id=a.id,
            owner_user_id="u1",
            artifact_type="cost_report",
            content="$1234",
        )
        d = art.to_dict(include_content=True)
        assert d["content"] == "$1234"

    def test_list_artifacts_wrong_user_returns_empty(self, db):
        a = self._make_analysis(db)
        create_artifact(db, analysis_id=a.id, owner_user_id="u1", artifact_type="terraform")
        result = list_artifacts(db, analysis_id=a.id, owner_user_id="attacker")
        assert result["total"] == 0


# ─────────────────────────────────────────────────────────────
# Decisions
# ─────────────────────────────────────────────────────────────

class TestDecisions:
    def _make_analysis(self, db, owner="u1"):
        ws = create_workspace(db, owner_user_id=owner, name="WS")
        return create_analysis(db, workspace_id=ws.id, owner_user_id=owner, diagram_id="diag-d")

    def test_create_decision(self, db):
        a = self._make_analysis(db)
        d = create_decision(
            db,
            analysis_id=a.id,
            owner_user_id="u1",
            decision_type="risk",
            title="High cost",
            severity="high",
        )
        assert d.id is not None
        assert d.decision_type == "risk"

    def test_list_decisions(self, db):
        a = self._make_analysis(db)
        create_decision(db, analysis_id=a.id, owner_user_id="u1", decision_type="risk", title="R1")
        create_decision(db, analysis_id=a.id, owner_user_id="u1", decision_type="decision", title="D1")
        all_decisions = list_decisions(db, analysis_id=a.id, owner_user_id="u1")
        assert len(all_decisions) == 2

    def test_list_decisions_by_type(self, db):
        a = self._make_analysis(db)
        create_decision(db, analysis_id=a.id, owner_user_id="u1", decision_type="risk", title="R1")
        create_decision(db, analysis_id=a.id, owner_user_id="u1", decision_type="decision", title="D1")
        risks = list_decisions(db, analysis_id=a.id, owner_user_id="u1", decision_type="risk")
        assert len(risks) == 1
        assert risks[0]["decision_type"] == "risk"

    def test_list_decisions_wrong_user(self, db):
        a = self._make_analysis(db)
        create_decision(db, analysis_id=a.id, owner_user_id="u1", decision_type="risk", title="R")
        result = list_decisions(db, analysis_id=a.id, owner_user_id="attacker")
        assert result == []

    def test_decision_to_dict(self, db):
        a = self._make_analysis(db)
        d = create_decision(
            db,
            analysis_id=a.id,
            owner_user_id="u1",
            decision_type="decision",
            title="Switch to Bicep",
            metadata={"reason": "cost"},
        )
        data = d.to_dict()
        assert data["title"] == "Switch to Bicep"
        assert data["metadata"]["reason"] == "cost"
        assert "created_at" in data


# ─────────────────────────────────────────────────────────────
# maybe_link_session bridge
# ─────────────────────────────────────────────────────────────

class TestMaybeLinkSession:
    _sample_session = {
        "source_provider": "aws",
        "target_provider": "azure",
        "services_detected": 3,
        "mappings": [
            {"source_service": "S3", "azure_service": "Blob Storage", "confidence": 0.9},
            {"source_service": "EC2", "azure_service": "VM", "confidence": 0.85},
        ],
    }

    def test_creates_workspace_and_analysis_if_missing(self, db):
        version = maybe_link_session(
            db,
            owner_user_id="u1",
            diagram_id="new-diag",
            session=self._sample_session,
        )
        assert version is not None
        assert version.version_number == 1
        # Analysis was auto-created
        analysis = (
            db.query(__import__("models.workspace", fromlist=["Analysis"]).Analysis)
            .filter_by(diagram_id="new-diag", owner_user_id="u1")
            .first()
        )
        assert analysis is not None

    def test_uses_existing_analysis_for_same_diagram(self, db):
        # First call creates workspace + analysis + v1
        v1 = maybe_link_session(
            db, owner_user_id="u1", diagram_id="diag-dup", session=self._sample_session
        )
        # Second call with updated session → v2 on same analysis
        updated = dict(self._sample_session, services_detected=5)
        v2 = maybe_link_session(
            db, owner_user_id="u1", diagram_id="diag-dup", session=updated
        )
        assert v1 is not None
        assert v2 is not None
        assert v2.analysis_id == v1.analysis_id
        assert v2.version_number == 2

    def test_swallows_errors_gracefully(self, db):
        # Passing None db should not raise
        result = maybe_link_session(
            db=None,  # type: ignore[arg-type]
            owner_user_id="u1",
            diagram_id="diag-err",
            session={},
        )
        assert result is None

    def test_uses_provided_workspace_id(self, db):
        ws = create_workspace(db, owner_user_id="u2", name="My WS")
        v = maybe_link_session(
            db,
            owner_user_id="u2",
            diagram_id="diag-linked",
            session=self._sample_session,
            workspace_id=ws.id,
        )
        assert v is not None
        from models.workspace import Analysis as _Analysis
        analysis = db.query(_Analysis).filter_by(diagram_id="diag-linked").first()
        assert analysis.workspace_id == ws.id

    def test_rejects_foreign_workspace_id(self, db):
        ws = create_workspace(db, owner_user_id="owner", tenant_id="t1", name="Private WS")
        result = maybe_link_session(
            db,
            owner_user_id="other",
            tenant_id="t2",
            diagram_id="diag-foreign",
            session=self._sample_session,
            workspace_id=ws.id,
        )
        assert result is None

    def test_maybe_link_session_is_tenant_scoped(self, db):
        v1 = maybe_link_session(
            db,
            owner_user_id="u1",
            tenant_id="tenant-a",
            diagram_id="diag-shared",
            session={"mappings": []},
        )
        v2 = maybe_link_session(
            db,
            owner_user_id="u1",
            tenant_id="tenant-b",
            diagram_id="diag-shared",
            session={"mappings": []},
        )

        assert v1 is not None
        assert v2 is not None
        assert v1.analysis_id != v2.analysis_id
        assert list_workspaces(db, owner_user_id="u1", tenant_id="tenant-a")["total"] == 1
        assert list_workspaces(db, owner_user_id="u1", tenant_id="tenant-b")["total"] == 1
