"""Migration contracts for canonical state hardening (#1237)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from auth import AuthProvider, legacy_owner_tenant_scope, provider_subject_tenant_scope


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "014_canonical_state_hardening.py"
)
SPEC = importlib.util.spec_from_file_location("canonical_state_migration_014", MIGRATION_PATH)
assert SPEC and SPEC.loader
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


def test_legacy_provider_rows_rehome_to_current_opaque_identity_scope():
    assert migration._legacy_scope("github_42") == provider_subject_tenant_scope(
        AuthProvider.GITHUB,
        "42",
    )
    assert migration._legacy_scope("aad_subject-a") == provider_subject_tenant_scope(
        AuthProvider.MICROSOFT,
        "subject-a",
    )


def test_unknown_legacy_owner_uses_deterministic_quarantine_free_scope():
    owner = "historical-owner-without-provider-prefix"
    assert migration._legacy_scope(owner) == legacy_owner_tenant_scope(owner)
    assert migration._legacy_scope(owner).startswith("legacy:")


def test_legacy_github_tenant_alias_targets_current_scope():
    assert migration._legacy_tenant_scope(
        "github_42",
        "github:github_42",
    ) == provider_subject_tenant_scope(AuthProvider.GITHUB, "42")


def test_ambiguous_default_tenant_waits_for_verified_access_rehome():
    assert migration._legacy_tenant_scope("github_42", "default_tenant") is None
    assert migration._legacy_tenant_scope("raw-b2c-subject", "default_tenant") is None


def test_migration_contains_conflict_audit_and_uniqueness_guards():
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    assert 'status="conflict_retained"' in source
    assert "tenant_rehome_audit" in source
    assert "_deduplicate_analyses" in source
    assert "_deduplicate_artifacts" in source
    assert "ux_analyses_owner_tenant_diagram" in source
    assert "ux_artifacts_version_type_hash" in source
    assert "ux_workspaces_default_owner_tenant" in source
    assert "retain VARCHAR(100)" in source
    assert "ix_analysis_versions_analysis_num" in (
        MIGRATION_PATH.parent.joinpath("013_durable_workspaces.py").read_text(encoding="utf-8")
    )
