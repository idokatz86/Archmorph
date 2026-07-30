"""Harden canonical analysis identity and legacy tenant compatibility (#1237).

Revision ID: 014
Revises: 013
Create Date: 2026-07-19

The migration deliberately does not guess a provider tenant. Only explicit
provider-bearing aliases are bulk-rehomed; ambiguous ``default_tenant`` rows
wait for verified exact-owner access. It also merges pre-existing duplicate analysis identities without
losing versions/artifacts/decisions, removes exact duplicate artifacts, and
elects one implicit default workspace per owner/tenant before partial unique
indexes are enforced.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from alembic import context, op
import sqlalchemy as sa


revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None

_TENANT_TABLES = ("workspaces", "source_assets", "analyses", "artifacts", "decisions")

# Every table below is created by revision 014 and dropped by ``downgrade``.
# A non-empty table is therefore a hard rollback blocker unless a future
# migration supplies an explicit reversible conversion. Categories are stable,
# operator-actionable, and deliberately contain no row values or identifiers.
_DOWNGRADE_DATA_CATEGORIES = {
    "credentials": ("api_key_credentials",),
    "project_membership": ("project_members",),
    "diagram_lifecycle": ("diagram_lifecycle",),
    "restore_grants": ("restore_grants",),
    "purge_manifests": ("purge_operations",),
    "mutation_receipts": ("analysis_mutation_receipts",),
    "restore_receipts": ("analysis_restore_receipts",),
    "migration_replays": ("migration_replays", "migration_replay_events"),
    "identity_aliases": ("tenant_rehome_aliases",),
    "identity_audits": ("tenant_rehome_audit",),
    "cost_budgets": ("cost_budgets",),
    "cost_alerts": ("cost_alerts",),
}
# tenant rewrite alias/audit evidence is append-only. The generalized guard
# below now applies the same fix-forward rule to every 014-only data category.

_CANONICAL_STATE_ENVIRONMENTS = frozenset({"dev", "staging", "prod"})
_STATE_ENVIRONMENT_ALIASES = {"production": "prod"}
_DECISION_STATUSES = frozenset({"open", "resolved", "accepted"})


def _legacy_scope(owner_user_id: str) -> str:
    provider = None
    subject = owner_user_id
    for prefix, provider_name in (
        ("aad_", "microsoft"),
        ("microsoft_", "microsoft"),
        ("github_", "github"),
        ("google_", "google"),
        ("azure_ad_b2c_", "azure_ad_b2c"),
    ):
        if owner_user_id.startswith(prefix):
            provider = provider_name
            subject = owner_user_id[len(prefix):]
            break
    if provider:
        material = (
            b"archmorph-provider-tenant-v1"
            + b"\0"
            + provider.encode("utf-8")
            + b"\0"
            + subject.encode("utf-8")
        )
        return f"idp:{hashlib.sha256(material).hexdigest()[:32]}"
    digest = hashlib.sha256(owner_user_id.encode("utf-8")).hexdigest()[:24]
    return f"legacy:{digest}"


def _legacy_tenant_scope(owner_user_id: str, source_tenant_id: str) -> str | None:
    """Map only explicitly recognized legacy tenant aliases to their new scope."""
    if owner_user_id.startswith("github_") and source_tenant_id == f"github:{owner_user_id}":
        return _legacy_scope(owner_user_id)
    return None


def _tenant_predicate(column, tenant_id: str | None):
    return column.is_(None) if tenant_id is None else column == tenant_id


def _normalize_state_environment(environment: object) -> str | None:
    if not isinstance(environment, str):
        return None
    normalized = environment.strip().lower()
    normalized = _STATE_ENVIRONMENT_ALIASES.get(normalized, normalized)
    return normalized if normalized in _CANONICAL_STATE_ENVIRONMENTS else None


def _reconcile_decision_statuses(bind) -> None:
    """Normalize supported legacy spellings and reject unknown nonempty values."""
    metadata = sa.MetaData()
    decisions = sa.Table("decisions", metadata, autoload_with=bind)
    normalized = sa.func.lower(sa.func.trim(decisions.c.status))
    unknown_count = bind.execute(
        sa.select(sa.func.count())
        .select_from(decisions)
        .where(
            decisions.c.status.is_not(None),
            sa.func.trim(decisions.c.status) != "",
            normalized.not_in(_DECISION_STATUSES),
        )
    ).scalar_one()
    if unknown_count:
        raise RuntimeError(
            "Migration refused: decisions contain unsupported nonempty status "
            f"values ({unknown_count} rows); no values or identifiers were emitted"
        )
    bind.execute(
        decisions.update()
        .where(
            sa.or_(
                decisions.c.status.is_(None),
                sa.func.trim(decisions.c.status) == "",
            )
        )
        .values(status="open")
    )
    bind.execute(
        decisions.update()
        .where(normalized.in_(_DECISION_STATUSES))
        .values(status=normalized)
    )


def _deployment_state_row_is_empty(row) -> bool:
    """Return true only when discarding this row cannot discard state/lock data."""
    return bool(
        row.state_json in (None, {})
        and row.previous_state_json in (None, {})
        and row.lock_id is None
        and row.lock_info in (None, {})
        and row.locked_at is None
    )


def _canonicalize_deployment_states(bind) -> None:
    """Normalize 013 rows and fail closed before discarding material conflicts."""
    metadata = sa.MetaData()
    deployment_state = sa.Table("deployment_state", metadata, autoload_with=bind)
    workspaces = sa.Table("workspaces", metadata, autoload_with=bind)
    rows = bind.execute(
        sa.select(
            deployment_state.c.id,
            deployment_state.c.project_id,
            deployment_state.c.environment,
            deployment_state.c.state_json,
            deployment_state.c.previous_state_json,
            deployment_state.c.lock_id,
            deployment_state.c.lock_info,
            deployment_state.c.locked_at,
            workspaces.c.id.label("canonical_project_id"),
            workspaces.c.owner_user_id.label("project_owner_user_id"),
            workspaces.c.tenant_id.label("project_tenant_id"),
        )
        .select_from(
            deployment_state.outerjoin(
                workspaces,
                workspaces.c.id == deployment_state.c.project_id,
            )
        )
        .order_by(deployment_state.c.id.asc())
    ).all()

    orphan_count = sum(row.canonical_project_id is None for row in rows)
    if orphan_count:
        raise RuntimeError(
            "Migration refused: Terraform state contains rows without a canonical "
            f"Project ({orphan_count} rows); no identifiers or state data were emitted"
        )

    normalized_rows = []
    invalid_environment_count = 0
    for row in rows:
        normalized_environment = _normalize_state_environment(row.environment)
        if normalized_environment is None:
            invalid_environment_count += 1
            continue
        normalized_rows.append((row, normalized_environment))
    if invalid_environment_count:
        raise RuntimeError(
            "Migration refused: Terraform state contains unsupported environment "
            f"values ({invalid_environment_count} rows); no values or state data were emitted"
        )

    groups: dict[tuple[str, str], list] = {}
    for row, normalized_environment in normalized_rows:
        groups.setdefault(
            (str(row.canonical_project_id), normalized_environment),
            [],
        ).append(row)

    conflicting_scopes = 0
    conflicting_material_rows = 0
    for group_rows in groups.values():
        material_rows = [
            row for row in group_rows if not _deployment_state_row_is_empty(row)
        ]
        if len(material_rows) > 1:
            conflicting_scopes += 1
            conflicting_material_rows += len(material_rows)
    if conflicting_scopes:
        raise RuntimeError(
            "Migration refused: canonical Terraform state has multiple material rows "
            f"in {conflicting_scopes} scopes ({conflicting_material_rows} rows); "
            "no winner was selected, no row was discarded, and no identifiers or "
            "state data were emitted"
        )

    for (_project_id, normalized_environment), group_rows in sorted(groups.items()):
        ordered_rows = sorted(group_rows, key=lambda row: int(row.id))
        material_rows = [
            row for row in ordered_rows if not _deployment_state_row_is_empty(row)
        ]
        survivor = material_rows[0] if material_rows else ordered_rows[0]
        duplicate_ids = [row.id for row in ordered_rows if row.id != survivor.id]
        if duplicate_ids:
            bind.execute(
                deployment_state.delete().where(
                    deployment_state.c.id.in_(duplicate_ids)
                )
            )
        bind.execute(
            deployment_state.update()
            .where(deployment_state.c.id == survivor.id)
            .values(
                environment=normalized_environment,
                owner_user_id=survivor.project_owner_user_id,
                tenant_id=survivor.project_tenant_id,
            )
        )


def _audit(
    bind,
    audit,
    *,
    owner_user_id: str,
    source_tenant_id: str | None,
    target_tenant_id: str | None,
    status: str,
    details: dict,
) -> None:
    bind.execute(
        audit.insert().values(
            id=str(uuid.uuid4()),
            owner_user_id=owner_user_id,
            source_tenant_id=source_tenant_id or "<tenantless>",
            target_tenant_id=target_tenant_id,
            status=status,
            details=json.dumps(details, sort_keys=True),
        )
    )


def _alias(
    bind,
    aliases,
    *,
    source_owner_user_id: str,
    source_tenant_id: str,
    target_owner_user_id: str | None,
    target_tenant_id: str | None,
    entity_type: str,
    source_entity_id: str,
    target_entity_id: str | None,
    status: str,
    reason: str | None = None,
) -> None:
    existing = bind.execute(
        sa.select(aliases.c.id).where(
            aliases.c.source_owner_user_id == source_owner_user_id,
            aliases.c.source_tenant_id == source_tenant_id,
            aliases.c.entity_type == entity_type,
            aliases.c.source_entity_id == source_entity_id,
        )
    ).first()
    values = {
        "target_owner_user_id": target_owner_user_id,
        "target_tenant_id": target_tenant_id,
        "target_entity_id": target_entity_id,
        "status": status,
        "reason": reason,
    }
    if existing is None:
        bind.execute(
            aliases.insert().values(
                id=str(uuid.uuid4()),
                source_owner_user_id=source_owner_user_id,
                source_tenant_id=source_tenant_id,
                entity_type=entity_type,
                source_entity_id=source_entity_id,
                **values,
            )
        )
    else:
        bind.execute(aliases.update().where(aliases.c.id == existing.id).values(**values))


def _deduplicate_analyses(bind, tables, audit) -> None:
    analyses = tables["analyses"]
    versions = tables["analysis_versions"]
    artifacts = tables["artifacts"]
    decisions = tables["decisions"]
    source_assets = tables["source_assets"]
    workspaces = tables["workspaces"]
    deployment_state = tables["deployment_state"]
    groups = bind.execute(
        sa.select(
            analyses.c.owner_user_id,
            analyses.c.tenant_id,
            analyses.c.diagram_id,
            sa.func.count(analyses.c.id),
        )
        .where(analyses.c.diagram_id.is_not(None))
        .group_by(
            analyses.c.owner_user_id,
            analyses.c.tenant_id,
            analyses.c.diagram_id,
        )
        .having(sa.func.count(analyses.c.id) > 1)
    ).all()
    for owner_user_id, tenant_id, diagram_id, _count in groups:
        rows = bind.execute(
            sa.select(analyses.c.id, analyses.c.created_at)
            .where(
                analyses.c.owner_user_id == owner_user_id,
                _tenant_predicate(analyses.c.tenant_id, tenant_id),
                analyses.c.diagram_id == diagram_id,
            )
            .order_by(analyses.c.created_at.asc(), analyses.c.id.asc())
        ).all()
        survivor_id = str(rows[0].id)
        survivor_source_asset_id = bind.execute(
            sa.select(analyses.c.source_asset_id).where(analyses.c.id == survivor_id)
        ).scalar_one_or_none()
        survivor_workspace_id = str(
            bind.execute(
                sa.select(analyses.c.workspace_id).where(analyses.c.id == survivor_id)
            ).scalar_one()
        )
        duplicate_ids = [str(row.id) for row in rows[1:]]
        next_version = int(
            bind.execute(
                sa.select(sa.func.max(versions.c.version_number)).where(
                    versions.c.analysis_id == survivor_id
                )
            ).scalar()
            or 0
        )
        lineage_remap: list[dict[str, object]] = []
        for duplicate_id in duplicate_ids:
            duplicate_workspace_id = str(
                bind.execute(
                    sa.select(analyses.c.workspace_id).where(analyses.c.id == duplicate_id)
                ).scalar_one()
            )
            duplicate_source_asset_id = bind.execute(
                sa.select(analyses.c.source_asset_id).where(analyses.c.id == duplicate_id)
            ).scalar_one_or_none()
            duplicate_versions = bind.execute(
                sa.select(
                    versions.c.id,
                    versions.c.version_number,
                    versions.c.restored_from,
                )
                .where(versions.c.analysis_id == duplicate_id)
                .order_by(versions.c.version_number.asc(), versions.c.created_at.asc(), versions.c.id.asc())
            ).all()
            version_number_map: dict[int, int] = {}
            for duplicate_version in duplicate_versions:
                next_version += 1
                version_number_map[int(duplicate_version.version_number)] = next_version
                lineage_remap.append(
                    {
                        "version_id": str(duplicate_version.id),
                        "source_analysis_id": duplicate_id,
                        "source_version_number": int(duplicate_version.version_number),
                        "source_restored_from": (
                            int(duplicate_version.restored_from)
                            if duplicate_version.restored_from is not None
                            else None
                        ),
                        "target_analysis_id": survivor_id,
                        "target_version_number": next_version,
                    }
                )
                bind.execute(
                    versions.update()
                    .where(versions.c.id == duplicate_version.id)
                    .values(analysis_id=survivor_id, version_number=next_version)
                )
            for duplicate_version in duplicate_versions:
                if duplicate_version.restored_from is None:
                    continue
                mapped_restored_from = version_number_map.get(int(duplicate_version.restored_from))
                bind.execute(
                    versions.update()
                    .where(versions.c.id == duplicate_version.id)
                    .values(restored_from=mapped_restored_from)
                )
                next(
                    item
                    for item in lineage_remap
                    if item["version_id"] == str(duplicate_version.id)
                )["target_restored_from"] = mapped_restored_from
            bind.execute(
                artifacts.update()
                .where(artifacts.c.analysis_id == duplicate_id)
                .values(analysis_id=survivor_id)
            )
            bind.execute(
                decisions.update()
                .where(decisions.c.analysis_id == duplicate_id)
                .values(analysis_id=survivor_id)
            )
            if survivor_source_asset_id is None and duplicate_source_asset_id is not None:
                bind.execute(
                    analyses.update()
                    .where(analyses.c.id == survivor_id)
                    .values(source_asset_id=duplicate_source_asset_id)
                )
                survivor_source_asset_id = duplicate_source_asset_id
            bind.execute(analyses.delete().where(analyses.c.id == duplicate_id))
            if duplicate_workspace_id != survivor_workspace_id:
                other_analysis = bind.execute(
                    sa.select(analyses.c.id)
                    .where(analyses.c.workspace_id == duplicate_workspace_id)
                    .limit(1)
                ).first()
                if other_analysis is None:
                    bind.execute(
                        source_assets.update()
                        .where(source_assets.c.workspace_id == duplicate_workspace_id)
                        .values(workspace_id=survivor_workspace_id)
                    )
                    project_state = bind.execute(
                        sa.select(deployment_state.c.id)
                        .where(deployment_state.c.project_id == duplicate_workspace_id)
                        .limit(1)
                    ).first()
                    if project_state is None:
                        bind.execute(
                            workspaces.delete().where(
                                workspaces.c.id == duplicate_workspace_id
                            )
                        )
        bind.execute(
            analyses.update()
            .where(analyses.c.id == survivor_id)
            .values(current_version=next_version)
        )
        _audit(
            bind,
            audit,
            owner_user_id=str(owner_user_id),
            source_tenant_id=tenant_id,
            target_tenant_id=tenant_id,
            status="analysis_deduplicated",
            details={
                "diagram_id": str(diagram_id),
                "survivor_analysis_id": survivor_id,
                "merged_analysis_ids": duplicate_ids,
                "lineage_remap": lineage_remap,
            },
        )


def _normalize_version_lineage(bind, tables, audit) -> None:
    """Repair pre-constraint lineage deterministically and retain old evidence.

    A valid restore edge points to an existing, earlier version in the same
    analysis. Missing, self, forward, and cyclic edges are detached only after
    their original values have been written to the migration audit table.
    """
    analyses = tables["analyses"]
    versions = tables["analysis_versions"]
    analysis_rows = bind.execute(
        sa.select(
            analyses.c.id,
            analyses.c.owner_user_id,
            analyses.c.tenant_id,
        )
    ).all()
    for analysis in analysis_rows:
        rows = bind.execute(
            sa.select(
                versions.c.id,
                versions.c.version_number,
                versions.c.restored_from,
            )
            .where(versions.c.analysis_id == analysis.id)
            .order_by(versions.c.version_number.asc(), versions.c.id.asc())
        ).all()
        original = {
            int(row.version_number): (
                int(row.restored_from) if row.restored_from is not None else None
            )
            for row in rows
        }
        if not any(value is not None for value in original.values()):
            continue
        existing = set(original)
        repairs: list[dict[str, object]] = []
        for row in rows:
            version_number = int(row.version_number)
            restored_from = original[version_number]
            if restored_from is None:
                continue
            reason = None
            if restored_from not in existing:
                reason = "missing_ancestor"
            elif restored_from >= version_number:
                cursor = restored_from
                seen: set[int] = set()
                while cursor in original and cursor not in seen:
                    if cursor == version_number:
                        reason = "lineage_cycle"
                        break
                    seen.add(cursor)
                    parent = original[cursor]
                    if parent is None:
                        break
                    cursor = parent
                reason = reason or "non_ancestor_reference"
            if reason is None:
                continue
            bind.execute(
                versions.update()
                .where(versions.c.id == row.id)
                .values(restored_from=None)
            )
            repairs.append(
                {
                    "version_id": str(row.id),
                    "version_number": version_number,
                    "original_restored_from": restored_from,
                    "normalized_restored_from": None,
                    "reason": reason,
                }
            )
        _audit(
            bind,
            audit,
            owner_user_id=str(analysis.owner_user_id),
            source_tenant_id=analysis.tenant_id,
            target_tenant_id=analysis.tenant_id,
            status="version_lineage_normalized" if repairs else "version_lineage_validated",
            details={
                "analysis_id": str(analysis.id),
                "original_lineage": [
                    {
                        "version_number": number,
                        "restored_from": restored_from,
                    }
                    for number, restored_from in sorted(original.items())
                ],
                "repairs": repairs,
            },
        )


def _deduplicate_artifacts(bind, tables, audit) -> None:
    artifacts = tables["artifacts"]
    groups = bind.execute(
        sa.select(
            artifacts.c.analysis_id,
            artifacts.c.version_id,
            artifacts.c.artifact_type,
            artifacts.c.content_hash,
            sa.func.count(artifacts.c.id),
        )
        .where(
            artifacts.c.content_hash.is_not(None),
        )
        .group_by(
            artifacts.c.analysis_id,
            artifacts.c.version_id,
            artifacts.c.artifact_type,
            artifacts.c.content_hash,
        )
        .having(sa.func.count(artifacts.c.id) > 1)
    ).all()
    for analysis_id, version_id, artifact_type, content_hash, _count in groups:
        rows = bind.execute(
            sa.select(
                artifacts.c.id,
                artifacts.c.owner_user_id,
                artifacts.c.tenant_id,
            )
            .where(
                artifacts.c.analysis_id == analysis_id,
                _tenant_predicate(artifacts.c.version_id, version_id),
                artifacts.c.artifact_type == artifact_type,
                artifacts.c.content_hash == content_hash,
            )
            .order_by(artifacts.c.created_at.asc(), artifacts.c.id.asc())
        ).all()
        keeper = rows[0]
        duplicate_ids = [str(row.id) for row in rows[1:]]
        bind.execute(artifacts.delete().where(artifacts.c.id.in_(duplicate_ids)))
        _audit(
            bind,
            audit,
            owner_user_id=str(keeper.owner_user_id),
            source_tenant_id=keeper.tenant_id,
            target_tenant_id=keeper.tenant_id,
            status="artifact_deduplicated",
            details={
                "analysis_id": str(analysis_id),
                "version_id": str(version_id),
                "artifact_type": str(artifact_type),
                "content_hash": str(content_hash),
                "survivor_artifact_id": str(keeper.id),
                "removed_artifact_ids": duplicate_ids,
            },
        )


def _rehome_legacy_identities(bind, tables, audit, aliases) -> None:
    analyses = tables["analyses"]
    identities: set[tuple[str, str]] = set()
    for table_name in _TENANT_TABLES:
        table = tables[table_name]
        rows = bind.execute(
            sa.select(table.c.owner_user_id, table.c.tenant_id)
            .where(table.c.tenant_id.is_not(None))
            .distinct()
        ).all()
        identities.update(
            (str(owner_user_id), str(source_tenant_id))
            for owner_user_id, source_tenant_id in rows
            if _legacy_tenant_scope(str(owner_user_id), str(source_tenant_id)) is not None
        )

    for owner_user_id, source_tenant_id in sorted(identities):
        target_tenant_id = _legacy_tenant_scope(owner_user_id, source_tenant_id)
        assert target_tenant_id is not None
        conflicts = {
            str(value)
            for value in bind.execute(
            sa.select(analyses.c.diagram_id)
            .where(
                analyses.c.owner_user_id == owner_user_id,
                analyses.c.tenant_id.in_((source_tenant_id, target_tenant_id)),
                analyses.c.diagram_id.is_not(None),
            )
            .group_by(analyses.c.diagram_id)
            .having(sa.func.count(sa.distinct(analyses.c.tenant_id)) > 1)
            ).scalars().all()
        }
        if conflicts:
            _audit(
                bind,
                audit,
                owner_user_id=owner_user_id,
                source_tenant_id=source_tenant_id,
                target_tenant_id=target_tenant_id,
                status="conflict_retained",
                details={"diagram_ids": sorted(conflicts)},
            )
        legacy_workspaces = bind.execute(
            sa.select(tables["workspaces"].c.id).where(
                tables["workspaces"].c.owner_user_id == owner_user_id,
                tables["workspaces"].c.tenant_id == source_tenant_id,
            )
        ).scalars().all()
        row_counts = {table_name: 0 for table_name in _TENANT_TABLES}
        quarantined_workspaces: list[str] = []
        for workspace_id_value in legacy_workspaces:
            workspace_id = str(workspace_id_value)
            workspace_analyses = bind.execute(
                sa.select(analyses.c.id, analyses.c.diagram_id).where(
                    analyses.c.workspace_id == workspace_id,
                    analyses.c.owner_user_id == owner_user_id,
                    analyses.c.tenant_id == source_tenant_id,
                )
            ).all()
            workspace_conflicts = [
                str(row.diagram_id)
                for row in workspace_analyses
                if row.diagram_id is not None and str(row.diagram_id) in conflicts
            ]
            if workspace_conflicts:
                quarantined_workspaces.append(workspace_id)
                _alias(
                    bind,
                    aliases,
                    source_owner_user_id=owner_user_id,
                    source_tenant_id=source_tenant_id,
                    target_owner_user_id=owner_user_id,
                    target_tenant_id=target_tenant_id,
                    entity_type="workspace",
                    source_entity_id=workspace_id,
                    target_entity_id=None,
                    status="quarantined",
                    reason="target_diagram_conflict",
                )
                for row in workspace_analyses:
                    _alias(
                        bind,
                        aliases,
                        source_owner_user_id=owner_user_id,
                        source_tenant_id=source_tenant_id,
                        target_owner_user_id=owner_user_id,
                        target_tenant_id=target_tenant_id,
                        entity_type="analysis",
                        source_entity_id=str(row.id),
                        target_entity_id=None,
                        status="quarantined",
                        reason=(
                            "target_diagram_conflict"
                            if row.diagram_id is not None and str(row.diagram_id) in conflicts
                            else "workspace_contains_conflict"
                        ),
                    )
                continue

            analysis_ids = [str(row.id) for row in workspace_analyses]
            for table_name, predicate in (
                ("source_assets", tables["source_assets"].c.workspace_id == workspace_id),
                ("artifacts", tables["artifacts"].c.analysis_id.in_(analysis_ids)),
                ("decisions", tables["decisions"].c.analysis_id.in_(analysis_ids)),
            ):
                table = tables[table_name]
                result = bind.execute(
                    table.update().where(
                        predicate,
                        table.c.owner_user_id == owner_user_id,
                        table.c.tenant_id == source_tenant_id,
                    ).values(tenant_id=target_tenant_id)
                )
                row_counts[table_name] += int(result.rowcount or 0)
            result = bind.execute(
                analyses.update().where(
                    analyses.c.id.in_(analysis_ids),
                    analyses.c.owner_user_id == owner_user_id,
                    analyses.c.tenant_id == source_tenant_id,
                ).values(tenant_id=target_tenant_id)
            )
            row_counts["analyses"] += int(result.rowcount or 0)
            result = bind.execute(
                tables["workspaces"].update().where(
                    tables["workspaces"].c.id == workspace_id,
                    tables["workspaces"].c.owner_user_id == owner_user_id,
                    tables["workspaces"].c.tenant_id == source_tenant_id,
                ).values(tenant_id=target_tenant_id)
            )
            row_counts["workspaces"] += int(result.rowcount or 0)
            _alias(
                bind,
                aliases,
                source_owner_user_id=owner_user_id,
                source_tenant_id=source_tenant_id,
                target_owner_user_id=owner_user_id,
                target_tenant_id=target_tenant_id,
                entity_type="workspace",
                source_entity_id=workspace_id,
                target_entity_id=workspace_id,
                status="rehomed",
            )
            for row in workspace_analyses:
                _alias(
                    bind,
                    aliases,
                    source_owner_user_id=owner_user_id,
                    source_tenant_id=source_tenant_id,
                    target_owner_user_id=owner_user_id,
                    target_tenant_id=target_tenant_id,
                    entity_type="analysis",
                    source_entity_id=str(row.id),
                    target_entity_id=str(row.id),
                    status="rehomed",
                )
        _audit(
            bind,
            audit,
            owner_user_id=owner_user_id,
            source_tenant_id=source_tenant_id,
            target_tenant_id=target_tenant_id,
            status="rehome_completed" if any(row_counts.values()) else "conflict_retained",
            details={
                "row_counts": row_counts,
                "quarantined_workspace_ids": quarantined_workspaces,
            },
        )


def _elect_default_workspaces(bind, workspaces, audit) -> None:
    bind.execute(workspaces.update().values(is_default=False))
    active_rows = bind.execute(
        sa.select(
            workspaces.c.id,
            workspaces.c.owner_user_id,
            workspaces.c.tenant_id,
            workspaces.c.name,
        )
        .where(
            workspaces.c.status == "active",
        )
        .order_by(workspaces.c.created_at.asc(), workspaces.c.id.asc())
    ).all()
    grouped: dict[tuple[str, str | None], list] = {}
    for row in active_rows:
        grouped.setdefault((str(row.owner_user_id), row.tenant_id), []).append(row)
    for (owner_user_id, tenant_id), rows in grouped.items():
        named_defaults = [row for row in rows if row.name == "Default Workspace"]
        candidates = named_defaults or rows
        workspace_ids = [str(row.id) for row in candidates]
        bind.execute(
            workspaces.update()
            .where(workspaces.c.id == workspace_ids[0])
            .values(is_default=True)
        )
        if len(workspace_ids) > 1:
            _audit(
                bind,
                audit,
                owner_user_id=owner_user_id,
                source_tenant_id=tenant_id,
                target_tenant_id=tenant_id,
                status="default_workspace_deduplicated",
                details={
                    "default_workspace_id": workspace_ids[0],
                    "non_default_workspace_ids": workspace_ids[1:],
                },
            )


def upgrade() -> None:
    op.alter_column(
        "analyses",
        "diagram_id",
        existing_type=sa.String(50),
        type_=sa.String(100),
        existing_nullable=True,
    )
    op.alter_column(
        "source_assets",
        "diagram_id",
        existing_type=sa.String(50),
        type_=sa.String(100),
        existing_nullable=True,
    )
    for table_name in _TENANT_TABLES:
        op.alter_column(
            table_name,
            "tenant_id",
            existing_type=sa.String(36),
            type_=sa.String(100),
            existing_nullable=True,
        )

    for table_name in ("usage_counters", "funnel_steps"):
        op.add_column(table_name, sa.Column("owner_user_id", sa.String(100), nullable=True))
        op.add_column(table_name, sa.Column("tenant_id", sa.String(100), nullable=True))
        op.create_index(f"ix_{table_name}_owner_user_id", table_name, ["owner_user_id"])
        op.create_index(f"ix_{table_name}_tenant_id", table_name, ["tenant_id"])

    op.create_table(
        "tenant_rehome_audit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.String(100), nullable=False),
        sa.Column("source_tenant_id", sa.String(100), nullable=False),
        sa.Column("target_tenant_id", sa.String(100), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_tenant_rehome_audit_owner", "tenant_rehome_audit", ["owner_user_id"])
    op.create_index("ix_tenant_rehome_audit_status", "tenant_rehome_audit", ["status"])

    op.create_table(
        "tenant_rehome_aliases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_owner_user_id", sa.String(100), nullable=False),
        sa.Column("source_tenant_id", sa.String(100), nullable=False),
        sa.Column("target_owner_user_id", sa.String(100), nullable=True),
        sa.Column("target_tenant_id", sa.String(100), nullable=True),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("source_entity_id", sa.String(100), nullable=False),
        sa.Column("target_entity_id", sa.String(100), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "entity_type IN ('workspace', 'analysis')",
            name="ck_tenant_rehome_aliases_entity_type",
        ),
        sa.CheckConstraint(
            "status IN ('rehomed', 'quarantined', 'resolved')",
            name="ck_tenant_rehome_aliases_status",
        ),
    )
    op.create_index(
        "ux_tenant_rehome_aliases_source",
        "tenant_rehome_aliases",
        ["source_owner_user_id", "source_tenant_id", "entity_type", "source_entity_id"],
        unique=True,
    )
    op.create_index(
        "ix_tenant_rehome_aliases_target",
        "tenant_rehome_aliases",
        ["target_owner_user_id", "target_tenant_id"],
    )

    op.add_column(
        "workspaces",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "api_key_credentials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("principal_id", sa.String(100), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("key_prefix", sa.String(12), nullable=False),
        sa.Column("scopes", sa.Text(), nullable=False),
        sa.Column("rate_limit", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ux_api_key_credentials_key_hash", "api_key_credentials", ["key_hash"], unique=True)
    op.create_index("ix_api_key_credentials_principal_id", "api_key_credentials", ["principal_id"])
    op.create_index(
        "ix_api_key_credentials_active",
        "api_key_credentials",
        ["principal_id", "revoked"],
    )

    op.add_column("cost_records", sa.Column("owner_user_id", sa.String(100), nullable=True))
    op.add_column("cost_records", sa.Column("tenant_id", sa.String(100), nullable=True))
    op.add_column("cost_records", sa.Column("actor_kind", sa.String(20), nullable=True))
    op.add_column("cost_records", sa.Column("key_id", sa.String(64), nullable=True))
    op.create_index("ix_cost_records_owner_user_id", "cost_records", ["owner_user_id"])
    op.create_index("ix_cost_records_tenant_id", "cost_records", ["tenant_id"])
    op.create_index(
        "ix_cost_records_scope_created",
        "cost_records",
        ["owner_user_id", "tenant_id", "created_at"],
    )
    op.create_table(
        "cost_budgets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.String(100), nullable=False),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("actor_kind", sa.String(20), nullable=False),
        sa.Column("key_id", sa.String(64), nullable=True),
        sa.Column("agent_id", sa.String(100), nullable=False),
        sa.Column("amount_usd", sa.Float(), nullable=False),
        sa.Column("period", sa.String(20), nullable=False),
        sa.Column("alert_thresholds", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "period IN ('daily', 'weekly', 'monthly')",
            name="ck_cost_budgets_period",
        ),
    )
    op.create_index(
        "ix_cost_budgets_scope",
        "cost_budgets",
        ["owner_user_id", "tenant_id"],
    )
    op.create_table(
        "cost_alerts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.String(100), nullable=False),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("actor_kind", sa.String(20), nullable=False),
        sa.Column("key_id", sa.String(64), nullable=True),
        sa.Column("agent_id", sa.String(100), nullable=False),
        sa.Column("budget_id", sa.String(36), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("threshold_pct", sa.Float(), nullable=False),
        sa.Column("current_spend", sa.Float(), nullable=False),
        sa.Column("budget_amount", sa.Float(), nullable=False),
        sa.Column("period", sa.String(20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("acknowledged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "severity IN ('warning', 'critical', 'exceeded')",
            name="ck_cost_alerts_severity",
        ),
        sa.CheckConstraint(
            "period IN ('daily', 'weekly', 'monthly')",
            name="ck_cost_alerts_period",
        ),
    )
    op.create_index(
        "ix_cost_alerts_scope_created",
        "cost_alerts",
        ["owner_user_id", "tenant_id", "created_at"],
    )
    op.create_index(
        "ux_cost_alerts_budget_threshold",
        "cost_alerts",
        ["budget_id", "threshold_pct"],
        unique=True,
    )

    op.create_table(
        "project_members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("project_owner_user_id", sa.String(100), nullable=False),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("member_user_id", sa.String(100), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="viewer"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "role IN ('viewer', 'editor')",
            name="ck_project_members_role",
        ),
    )
    op.create_index("ix_project_members_project_id", "project_members", ["project_id"])
    op.create_index("ix_project_members_tenant_id", "project_members", ["tenant_id"])
    op.create_index("ix_project_members_member_user_id", "project_members", ["member_user_id"])
    op.create_index(
        "ix_project_members_scope",
        "project_members",
        ["project_owner_user_id", "tenant_id"],
    )
    op.create_index(
        "ux_project_members_project_member",
        "project_members",
        ["project_id", "member_user_id"],
        unique=True,
    )

    op.create_table(
        "diagram_lifecycle",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("diagram_id", sa.String(100), nullable=False),
        sa.Column("owner_user_id", sa.String(100), nullable=False),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("state", sa.String(20), nullable=False, server_default="active"),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "state IN ('active', 'purging', 'purged')",
            name="ck_diagram_lifecycle_state",
        ),
    )
    op.create_index("ix_diagram_lifecycle_workspace_id", "diagram_lifecycle", ["workspace_id"])
    op.create_index("ix_diagram_lifecycle_diagram", "diagram_lifecycle", ["diagram_id"])
    op.create_index(
        "ux_diagram_lifecycle_scope",
        "diagram_lifecycle",
        ["owner_user_id", "tenant_id", "diagram_id"],
        unique=True,
    )

    op.create_table(
        "restore_grants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("nonce_digest", sa.String(64), nullable=False),
        sa.Column("owner_user_id", sa.String(100), nullable=False),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("diagram_id", sa.String(100), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_hash", sa.String(64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cleanup_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ux_restore_grants_nonce", "restore_grants", ["nonce_digest"], unique=True
    )
    op.create_index(
        "ix_restore_grants_cleanup",
        "restore_grants",
        ["cleanup_at", "id"],
    )
    op.create_index(
        "ix_restore_grants_scope",
        "restore_grants",
        ["owner_user_id", "tenant_id", "diagram_id", "generation"],
    )

    op.create_table(
        "purge_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_id", sa.String(100), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=True),
        sa.Column("owner_user_id", sa.String(100), nullable=False),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("generation", sa.Integer(), nullable=True),
        sa.Column("manifest", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("stages", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("last_error_stage", sa.String(100), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "scope_type IN ('diagram', 'workspace')",
            name="ck_purge_operations_scope",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'in_progress', 'failed', 'completed')",
            name="ck_purge_operations_status",
        ),
    )
    op.create_index("ix_purge_operations_workspace_id", "purge_operations", ["workspace_id"])
    op.create_index("ix_purge_operations_status", "purge_operations", ["status"])
    op.create_index(
        "ix_purge_operations_scope_lookup",
        "purge_operations",
        ["scope_type", "scope_id"],
    )
    op.create_index(
        "ix_purge_operations_status_id",
        "purge_operations",
        ["status", "id"],
    )
    op.create_index(
        "ux_purge_operations_scope",
        "purge_operations",
        ["owner_user_id", "tenant_id", "scope_type", "scope_id"],
        unique=True,
    )

    op.create_table(
        "analysis_mutation_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.String(100), nullable=False),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("diagram_id", sa.String(100), nullable=False),
        sa.Column("operation", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column(
            "analysis_id",
            sa.String(36),
            sa.ForeignKey("analyses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "version_id",
            sa.String(36),
            sa.ForeignKey("analysis_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ux_analysis_mutation_receipts_scope",
        "analysis_mutation_receipts",
        ["owner_user_id", "tenant_id", "diagram_id", "operation", "request_hash"],
        unique=True,
    )
    op.create_index(
        "ix_analysis_mutation_receipts_analysis",
        "analysis_mutation_receipts",
        ["analysis_id"],
    )

    op.create_table(
        "analysis_restore_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.String(100), nullable=False),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column(
            "analysis_id",
            sa.String(36),
            sa.ForeignKey("analyses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idempotency_key_hash", sa.String(64), nullable=False),
        sa.Column("intent_hash", sa.String(64), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column(
            "restored_version_id",
            sa.String(36),
            sa.ForeignKey("analysis_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("restored_version_number", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ux_analysis_restore_receipts_scope",
        "analysis_restore_receipts",
        ["owner_user_id", "tenant_id", "analysis_id", "idempotency_key_hash"],
        unique=True,
    )
    op.create_index(
        "ix_analysis_restore_receipts_analysis",
        "analysis_restore_receipts",
        ["analysis_id"],
    )

    if not context.is_offline_mode():
        _reconcile_decision_statuses(op.get_bind())

    dialect_name = context.get_context().dialect.name
    if dialect_name == "postgresql":
        op.create_unique_constraint(
            "uq_analysis_versions_analysis_id_id",
            "analysis_versions",
            ["analysis_id", "id"],
        )
        op.create_check_constraint(
            "ck_workspaces_status",
            "workspaces",
            "status IN ('active', 'archived', 'deleting')",
        )
        op.create_check_constraint(
            "ck_decisions_type",
            "decisions",
            "decision_type IN ('risk', 'decision', 'note')",
        )
        op.create_check_constraint(
            "ck_decisions_severity",
            "decisions",
            "severity IS NULL OR severity IN ('low', 'medium', 'high', 'critical')",
        )
        op.create_check_constraint(
            "ck_decisions_status",
            "decisions",
            "status IN ('open', 'resolved', 'accepted')",
        )

    op.create_table(
        "migration_replays",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("analysis_id", sa.String(36), nullable=False),
        sa.Column("version_id", sa.String(36), nullable=False),
        sa.Column("diagram_id", sa.String(100), nullable=False),
        sa.Column("owner_user_id", sa.String(100), nullable=False),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["analysis_id", "version_id"],
            ["analysis_versions.analysis_id", "analysis_versions.id"],
            name="fk_migration_replays_analysis_version",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_migration_replays_analysis_id", "migration_replays", ["analysis_id"])
    op.create_index("ix_migration_replays_diagram_id", "migration_replays", ["diagram_id"])
    op.create_index(
        "ix_migration_replays_scope_created",
        "migration_replays",
        ["owner_user_id", "tenant_id", "created_at"],
    )
    op.create_table(
        "migration_replay_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "replay_id",
            sa.String(36),
            sa.ForeignKey("migration_replays.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("data", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_migration_replay_events_replay_id", "migration_replay_events", ["replay_id"])
    op.create_index(
        "ux_migration_replay_events_sequence",
        "migration_replay_events",
        ["replay_id", "sequence"],
        unique=True,
    )

    if not context.is_offline_mode():
        bind = op.get_bind()
        metadata = sa.MetaData()
        metadata.reflect(
            bind=bind,
            only=[
                *list(_TENANT_TABLES),
                "analysis_versions",
                "deployment_state",
                "tenant_rehome_audit",
                "tenant_rehome_aliases",
            ],
        )
        audit = metadata.tables["tenant_rehome_audit"]
        aliases = metadata.tables["tenant_rehome_aliases"]
        _rehome_legacy_identities(bind, metadata.tables, audit, aliases)
        _deduplicate_analyses(bind, metadata.tables, audit)
        _normalize_version_lineage(bind, metadata.tables, audit)
        _deduplicate_artifacts(bind, metadata.tables, audit)
        _elect_default_workspaces(bind, metadata.tables["workspaces"], audit)
        _canonicalize_deployment_states(bind)

    op.alter_column(
        "deployment_state",
        "project_id",
        existing_type=sa.String(),
        type_=sa.String(36),
        existing_nullable=False,
    )
    op.alter_column(
        "deployment_state",
        "environment",
        existing_type=sa.String(),
        type_=sa.String(20),
        existing_nullable=False,
    )
    op.alter_column(
        "deployment_state",
        "owner_user_id",
        existing_type=sa.String(),
        type_=sa.String(100),
        existing_nullable=True,
        nullable=False,
    )
    op.alter_column(
        "deployment_state",
        "tenant_id",
        existing_type=sa.String(),
        type_=sa.String(100),
        existing_nullable=True,
    )
    if dialect_name == "postgresql":
        op.create_check_constraint(
            "ck_deployment_state_environment",
            "deployment_state",
            "environment IN ('dev', 'staging', 'prod')",
        )
        op.create_foreign_key(
            "fk_deployment_state_project",
            "deployment_state",
            "workspaces",
            ["project_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.create_unique_constraint(
        "uq_deployment_state_project_environment",
        "deployment_state",
        ["project_id", "environment"],
    )

    op.create_index(
        "ux_analyses_owner_tenant_diagram",
        "analyses",
        ["owner_user_id", "tenant_id", "diagram_id"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NOT NULL AND diagram_id IS NOT NULL"),
        sqlite_where=sa.text("tenant_id IS NOT NULL AND diagram_id IS NOT NULL"),
    )
    op.create_index(
        "ux_analyses_owner_no_tenant_diagram",
        "analyses",
        ["owner_user_id", "diagram_id"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NULL AND diagram_id IS NOT NULL"),
        sqlite_where=sa.text("tenant_id IS NULL AND diagram_id IS NOT NULL"),
    )
    op.create_index(
        "ux_artifacts_version_type_hash",
        "artifacts",
        ["version_id", "artifact_type", "content_hash"],
        unique=True,
        postgresql_where=sa.text("version_id IS NOT NULL AND content_hash IS NOT NULL"),
        sqlite_where=sa.text("version_id IS NOT NULL AND content_hash IS NOT NULL"),
    )
    op.create_index(
        "ux_workspaces_default_owner_tenant",
        "workspaces",
        ["owner_user_id", "tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default AND tenant_id IS NOT NULL"),
        sqlite_where=sa.text("is_default = 1 AND tenant_id IS NOT NULL"),
    )
    op.create_index(
        "ux_workspaces_default_owner_no_tenant",
        "workspaces",
        ["owner_user_id"],
        unique=True,
        postgresql_where=sa.text("is_default AND tenant_id IS NULL"),
        sqlite_where=sa.text("is_default = 1 AND tenant_id IS NULL"),
    )
    if dialect_name == "postgresql":
        # Install cross-row constraints only after every seeded row has been
        # remapped and normalized. This ordering is required for real 013 data.
        op.drop_constraint("decisions_version_id_fkey", "decisions", type_="foreignkey")
        op.create_foreign_key(
            "fk_decisions_analysis_version",
            "decisions",
            "analysis_versions",
            ["analysis_id", "version_id"],
            ["analysis_id", "id"],
            ondelete="RESTRICT",
        )
        op.create_foreign_key(
            "fk_analysis_versions_restored_from",
            "analysis_versions",
            "analysis_versions",
            ["analysis_id", "restored_from"],
            ["analysis_id", "version_number"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    if not context.is_offline_mode():
        bind = op.get_bind()
        populated_categories = []
        for category, table_names in _DOWNGRADE_DATA_CATEGORIES.items():
            if any(
                bind.execute(
                    sa.text(f'SELECT EXISTS (SELECT 1 FROM "{table_name}" LIMIT 1)')
                ).scalar_one()
                for table_name in table_names
            ):
                populated_categories.append(category)
        legacy_scoped_costs = bind.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM cost_records "
                "WHERE owner_user_id IS NOT NULL OR tenant_id IS NOT NULL LIMIT 1)"
            )
        ).scalar_one()
        if legacy_scoped_costs:
            populated_categories.append("cost_records")
        scoped_telemetry = any(
            bind.execute(
                sa.text(
                    f"SELECT EXISTS (SELECT 1 FROM {table_name} "
                    "WHERE owner_user_id IS NOT NULL OR tenant_id IS NOT NULL LIMIT 1)"
                )
            ).scalar_one()
            for table_name in ("usage_counters", "funnel_steps")
        )
        if scoped_telemetry:
            populated_categories.append("telemetry")
        if populated_categories:
            raise RuntimeError(
                "Downgrade refused: revision 014 contains non-empty durable data "
                "that revision 013 cannot represent. Blocking categories: "
                f"{', '.join(populated_categories)}. Deploy a schema-compatible "
                "revision, export and reversibly convert the affected categories, "
                "or fix forward; no rows were changed."
            )
    op.drop_constraint(
        "uq_deployment_state_project_environment",
        "deployment_state",
        type_="unique",
    )
    dialect_name = context.get_context().dialect.name
    if dialect_name == "postgresql":
        op.drop_constraint(
            "fk_deployment_state_project",
            "deployment_state",
            type_="foreignkey",
        )
        op.drop_constraint(
            "ck_deployment_state_environment",
            "deployment_state",
            type_="check",
        )
    op.alter_column(
        "deployment_state",
        "tenant_id",
        existing_type=sa.String(100),
        type_=sa.String(),
        existing_nullable=True,
    )
    op.alter_column(
        "deployment_state",
        "owner_user_id",
        existing_type=sa.String(100),
        type_=sa.String(),
        existing_nullable=False,
        nullable=True,
    )
    op.alter_column(
        "deployment_state",
        "environment",
        existing_type=sa.String(20),
        type_=sa.String(),
        existing_nullable=False,
    )
    op.alter_column(
        "deployment_state",
        "project_id",
        existing_type=sa.String(36),
        type_=sa.String(),
        existing_nullable=False,
    )
    for table_name in ("funnel_steps", "usage_counters"):
        op.drop_index(f"ix_{table_name}_tenant_id", table_name=table_name)
        op.drop_index(f"ix_{table_name}_owner_user_id", table_name=table_name)
        op.drop_column(table_name, "tenant_id")
        op.drop_column(table_name, "owner_user_id")
    op.drop_index("ux_migration_replay_events_sequence", table_name="migration_replay_events")
    op.drop_index("ix_migration_replay_events_replay_id", table_name="migration_replay_events")
    op.drop_table("migration_replay_events")
    op.drop_index("ix_migration_replays_scope_created", table_name="migration_replays")
    op.drop_index("ix_migration_replays_diagram_id", table_name="migration_replays")
    op.drop_index("ix_migration_replays_analysis_id", table_name="migration_replays")
    op.drop_table("migration_replays")
    if dialect_name == "postgresql":
        op.drop_constraint("ck_workspaces_status", "workspaces", type_="check")
        op.drop_constraint("ck_decisions_status", "decisions", type_="check")
        op.drop_constraint("ck_decisions_severity", "decisions", type_="check")
        op.drop_constraint("ck_decisions_type", "decisions", type_="check")
        op.drop_constraint("fk_decisions_analysis_version", "decisions", type_="foreignkey")
        op.create_foreign_key(
            "decisions_version_id_fkey",
            "decisions",
            "analysis_versions",
            ["version_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.drop_constraint("fk_analysis_versions_restored_from", "analysis_versions", type_="foreignkey")
        op.drop_constraint("uq_analysis_versions_analysis_id_id", "analysis_versions", type_="unique")
    op.drop_index("ix_analysis_restore_receipts_analysis", table_name="analysis_restore_receipts")
    op.drop_index("ux_analysis_restore_receipts_scope", table_name="analysis_restore_receipts")
    op.drop_table("analysis_restore_receipts")
    op.drop_index("ix_analysis_mutation_receipts_analysis", table_name="analysis_mutation_receipts")
    op.drop_index("ux_analysis_mutation_receipts_scope", table_name="analysis_mutation_receipts")
    op.drop_table("analysis_mutation_receipts")
    op.drop_index("ix_api_key_credentials_active", table_name="api_key_credentials")
    op.drop_index("ix_api_key_credentials_principal_id", table_name="api_key_credentials")
    op.drop_index("ux_api_key_credentials_key_hash", table_name="api_key_credentials")
    op.drop_table("api_key_credentials")
    op.drop_index("ux_cost_alerts_budget_threshold", table_name="cost_alerts")
    op.drop_index("ix_cost_alerts_scope_created", table_name="cost_alerts")
    op.drop_table("cost_alerts")
    op.drop_index("ix_cost_budgets_scope", table_name="cost_budgets")
    op.drop_table("cost_budgets")
    op.drop_index("ix_cost_records_scope_created", table_name="cost_records")
    op.drop_index("ix_cost_records_tenant_id", table_name="cost_records")
    op.drop_index("ix_cost_records_owner_user_id", table_name="cost_records")
    op.drop_column("cost_records", "key_id")
    op.drop_column("cost_records", "actor_kind")
    op.drop_column("cost_records", "tenant_id")
    op.drop_column("cost_records", "owner_user_id")
    op.drop_index("ux_purge_operations_scope", table_name="purge_operations")
    op.drop_index("ix_purge_operations_status_id", table_name="purge_operations")
    op.drop_index("ix_purge_operations_scope_lookup", table_name="purge_operations")
    op.drop_index("ix_purge_operations_status", table_name="purge_operations")
    op.drop_index("ix_purge_operations_workspace_id", table_name="purge_operations")
    op.drop_table("purge_operations")
    op.drop_index("ix_restore_grants_scope", table_name="restore_grants")
    op.drop_index("ix_restore_grants_cleanup", table_name="restore_grants")
    op.drop_index("ux_restore_grants_nonce", table_name="restore_grants")
    op.drop_table("restore_grants")
    op.drop_index("ux_diagram_lifecycle_scope", table_name="diagram_lifecycle")
    op.drop_index("ix_diagram_lifecycle_diagram", table_name="diagram_lifecycle")
    op.drop_index("ix_diagram_lifecycle_workspace_id", table_name="diagram_lifecycle")
    op.drop_table("diagram_lifecycle")
    op.drop_index("ux_project_members_project_member", table_name="project_members")
    op.drop_index("ix_project_members_scope", table_name="project_members")
    op.drop_index("ix_project_members_member_user_id", table_name="project_members")
    op.drop_index("ix_project_members_tenant_id", table_name="project_members")
    op.drop_index("ix_project_members_project_id", table_name="project_members")
    op.drop_table("project_members")
    op.drop_index("ux_workspaces_default_owner_no_tenant", table_name="workspaces")
    op.drop_index("ux_workspaces_default_owner_tenant", table_name="workspaces")
    op.drop_index("ux_artifacts_version_type_hash", table_name="artifacts")
    op.drop_index("ux_analyses_owner_no_tenant_diagram", table_name="analyses")
    op.drop_index("ux_analyses_owner_tenant_diagram", table_name="analyses")
    op.drop_column("workspaces", "is_default")
    op.drop_index("ix_tenant_rehome_aliases_target", table_name="tenant_rehome_aliases")
    op.drop_index("ux_tenant_rehome_aliases_source", table_name="tenant_rehome_aliases")
    op.drop_table("tenant_rehome_aliases")
    op.drop_index("ix_tenant_rehome_audit_status", table_name="tenant_rehome_audit")
    op.drop_index("ix_tenant_rehome_audit_owner", table_name="tenant_rehome_audit")
    op.drop_table("tenant_rehome_audit")
    # Intentionally retain VARCHAR(100). A 014-era opaque/conflict scope can be
    # longer than 36 characters; narrowing on downgrade would truncate or make
    # rollback fail. Revision 013 code is compatible with the wider columns.
