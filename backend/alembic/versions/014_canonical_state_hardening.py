"""Harden canonical analysis identity and legacy tenant compatibility (#1237).

Revision ID: 014
Revises: 013
Create Date: 2026-07-19

The migration deliberately does not guess a provider tenant. Recognized legacy
``default_tenant`` and ``github:github_<subject>`` rows are rehomed to a
deterministic provider-subject scope only when their durable identity is
unambiguous. Conflicting rows are quarantined and recorded for operator review
before uniqueness is enforced.
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
    if source_tenant_id == "default_tenant":
        return _legacy_scope(owner_user_id)
    if owner_user_id.startswith("github_") and source_tenant_id == f"github:{owner_user_id}":
        return _legacy_scope(owner_user_id)
    return None


def _conflict_scope(owner_user_id: str, analysis_id: str) -> str:
    digest = hashlib.sha256(f"{owner_user_id}\0{analysis_id}".encode("utf-8")).hexdigest()[:24]
    return f"legacy-conflict:{digest}"


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
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_tenant_rehome_audit_owner", "tenant_rehome_audit", ["owner_user_id"])
    op.create_index("ix_tenant_rehome_audit_status", "tenant_rehome_audit", ["status"])

    if not context.is_offline_mode():
        bind = op.get_bind()
        metadata = sa.MetaData()
        metadata.reflect(
            bind=bind,
            only=[*list(_TENANT_TABLES), "tenant_rehome_audit"],
        )
        analyses = metadata.tables["analyses"]
        audit = metadata.tables["tenant_rehome_audit"]

        legacy_identities: set[tuple[str, str]] = set()
        for table_name in _TENANT_TABLES:
            table = metadata.tables[table_name]
            rows = bind.execute(
                sa.select(table.c.owner_user_id, table.c.tenant_id)
                .where(table.c.tenant_id.is_not(None))
                .distinct()
            ).all()
            legacy_identities.update(
                (str(owner_user_id), str(source_tenant_id))
                for owner_user_id, source_tenant_id in rows
                if _legacy_tenant_scope(
                    str(owner_user_id),
                    str(source_tenant_id),
                ) is not None
            )

        for owner_user_id, source_tenant_id in sorted(legacy_identities):
            target_tenant_id = _legacy_tenant_scope(
                str(owner_user_id),
                str(source_tenant_id),
            )
            if target_tenant_id is None:
                continue
            duplicate_diagrams = bind.execute(
                sa.select(analyses.c.diagram_id, sa.func.count(analyses.c.id))
                .where(
                    analyses.c.owner_user_id == owner_user_id,
                    analyses.c.tenant_id == source_tenant_id,
                    analyses.c.diagram_id.is_not(None),
                )
                .group_by(analyses.c.diagram_id)
                .having(sa.func.count(analyses.c.id) > 1)
            ).all()
            target_conflicts = bind.execute(
                sa.select(analyses.c.diagram_id)
                .where(
                    analyses.c.owner_user_id == owner_user_id,
                    analyses.c.tenant_id.in_((source_tenant_id, target_tenant_id)),
                    analyses.c.diagram_id.is_not(None),
                )
                .group_by(analyses.c.diagram_id)
                .having(sa.func.count(sa.distinct(analyses.c.tenant_id)) > 1)
            ).scalars().all()
            conflicts = sorted(
                {str(row[0]) for row in duplicate_diagrams}
                | {str(value) for value in target_conflicts}
            )
            if conflicts:
                conflict_rows = bind.execute(
                    sa.select(analyses.c.id, analyses.c.diagram_id).where(
                        analyses.c.owner_user_id == owner_user_id,
                        analyses.c.tenant_id == source_tenant_id,
                        analyses.c.diagram_id.in_(conflicts),
                    )
                ).all()
                for analysis_id, diagram_id in conflict_rows:
                    quarantine_tenant_id = _conflict_scope(str(owner_user_id), str(analysis_id))
                    bind.execute(
                        analyses.update()
                        .where(analyses.c.id == analysis_id)
                        .values(tenant_id=quarantine_tenant_id)
                    )
                    for table_name in ("artifacts", "decisions"):
                        table = metadata.tables[table_name]
                        bind.execute(
                            table.update()
                            .where(table.c.analysis_id == analysis_id)
                            .values(tenant_id=quarantine_tenant_id)
                        )
                    bind.execute(
                        audit.insert().values(
                            id=str(uuid.uuid4()),
                            owner_user_id=owner_user_id,
                            source_tenant_id=source_tenant_id,
                            target_tenant_id=quarantine_tenant_id,
                            status="conflict_quarantined",
                            details=json.dumps(
                                {
                                    "analysis_id": str(analysis_id),
                                    "diagram_id": str(diagram_id),
                                    "desired_tenant_id": target_tenant_id,
                                },
                                sort_keys=True,
                            ),
                        )
                    )

            row_counts: dict[str, int] = {}
            for table_name in _TENANT_TABLES:
                table = metadata.tables[table_name]
                result = bind.execute(
                    table.update()
                    .where(
                        table.c.owner_user_id == owner_user_id,
                        table.c.tenant_id == source_tenant_id,
                    )
                    .values(tenant_id=target_tenant_id)
                )
                row_counts[table_name] = int(result.rowcount or 0)

            bind.execute(
                audit.insert().values(
                    id=str(uuid.uuid4()),
                    owner_user_id=owner_user_id,
                    source_tenant_id=source_tenant_id,
                    target_tenant_id=target_tenant_id,
                    status="rehome_completed",
                    details=json.dumps({"row_counts": row_counts}, sort_keys=True),
                )
            )

    op.create_index(
        "ux_analyses_owner_tenant_diagram",
        "analyses",
        ["owner_user_id", "tenant_id", "diagram_id"],
        unique=True,
    )
    op.create_index(
        "ux_artifacts_version_type_hash",
        "artifacts",
        ["version_id", "artifact_type", "content_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ux_artifacts_version_type_hash", table_name="artifacts")
    op.drop_index("ux_analyses_owner_tenant_diagram", table_name="analyses")
    op.drop_index("ix_tenant_rehome_audit_status", table_name="tenant_rehome_audit")
    op.drop_index("ix_tenant_rehome_audit_owner", table_name="tenant_rehome_audit")
    op.drop_table("tenant_rehome_audit")
    for table_name in reversed(_TENANT_TABLES):
        op.alter_column(
            table_name,
            "tenant_id",
            existing_type=sa.String(100),
            type_=sa.String(36),
            existing_nullable=True,
        )