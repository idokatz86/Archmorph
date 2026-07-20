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


def _deduplicate_analyses(bind, tables, audit) -> None:
    analyses = tables["analyses"]
    versions = tables["analysis_versions"]
    artifacts = tables["artifacts"]
    decisions = tables["decisions"]
    source_assets = tables["source_assets"]
    workspaces = tables["workspaces"]
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
                    bind.execute(
                        workspaces.delete().where(workspaces.c.id == duplicate_workspace_id)
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


def _rehome_legacy_identities(bind, tables, audit) -> None:
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
        conflicts = bind.execute(
            sa.select(analyses.c.diagram_id)
            .where(
                analyses.c.owner_user_id == owner_user_id,
                analyses.c.tenant_id.in_((source_tenant_id, target_tenant_id)),
                analyses.c.diagram_id.is_not(None),
            )
            .group_by(analyses.c.diagram_id)
            .having(sa.func.count(sa.distinct(analyses.c.tenant_id)) > 1)
        ).scalars().all()
        if conflicts:
            _audit(
                bind,
                audit,
                owner_user_id=owner_user_id,
                source_tenant_id=source_tenant_id,
                target_tenant_id=target_tenant_id,
                status="conflict_retained",
                details={"diagram_ids": sorted(str(value) for value in conflicts)},
            )
            continue

        row_counts: dict[str, int] = {}
        for table_name in _TENANT_TABLES:
            table = tables[table_name]
            predicate = sa.and_(
                table.c.owner_user_id == owner_user_id,
                table.c.tenant_id == source_tenant_id,
            )
            result = bind.execute(
                table.update()
                .where(predicate)
                .values(tenant_id=target_tenant_id)
            )
            row_counts[table_name] = int(result.rowcount or 0)
        _audit(
            bind,
            audit,
            owner_user_id=owner_user_id,
            source_tenant_id=source_tenant_id,
            target_tenant_id=target_tenant_id,
            status="rehome_completed",
            details={"row_counts": row_counts},
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
    for table_name in _TENANT_TABLES:
        op.alter_column(
            table_name,
            "tenant_id",
            existing_type=sa.String(36),
            type_=sa.String(100),
            existing_nullable=True,
        )

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

    op.add_column(
        "workspaces",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    if not context.is_offline_mode():
        bind = op.get_bind()
        metadata = sa.MetaData()
        metadata.reflect(
            bind=bind,
            only=[
                *list(_TENANT_TABLES),
                "analysis_versions",
                "tenant_rehome_audit",
            ],
        )
        audit = metadata.tables["tenant_rehome_audit"]
        _rehome_legacy_identities(bind, metadata.tables, audit)
        _deduplicate_analyses(bind, metadata.tables, audit)
        _deduplicate_artifacts(bind, metadata.tables, audit)
        _elect_default_workspaces(bind, metadata.tables["workspaces"], audit)

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


def downgrade() -> None:
    op.drop_index("ux_workspaces_default_owner_no_tenant", table_name="workspaces")
    op.drop_index("ux_workspaces_default_owner_tenant", table_name="workspaces")
    op.drop_index("ux_artifacts_version_type_hash", table_name="artifacts")
    op.drop_index("ux_analyses_owner_no_tenant_diagram", table_name="analyses")
    op.drop_index("ux_analyses_owner_tenant_diagram", table_name="analyses")
    op.drop_column("workspaces", "is_default")
    op.drop_index("ix_tenant_rehome_audit_status", table_name="tenant_rehome_audit")
    op.drop_index("ix_tenant_rehome_audit_owner", table_name="tenant_rehome_audit")
    op.drop_table("tenant_rehome_audit")
    # Intentionally retain VARCHAR(100). A 014-era opaque/conflict scope can be
    # longer than 36 characters; narrowing on downgrade would truncate or make
    # rollback fail. Revision 013 code is compatible with the wider columns.
