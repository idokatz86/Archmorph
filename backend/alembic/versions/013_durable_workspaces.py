"""Add durable workspace, analysis-version, and artifact tables (Issue #1129).

Revision ID: 013
Revises: 012
Create Date: 2026-05-25
"""

from alembic import op
import sqlalchemy as sa

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Workspaces ──────────────────────────────────────────────
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.String(100), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_cloud", sa.String(20), nullable=False, server_default="aws"),
        sa.Column("target_cloud", sa.String(20), nullable=False, server_default="azure"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_workspaces_owner_user_id", "workspaces", ["owner_user_id"])
    op.create_index("ix_workspaces_tenant_id", "workspaces", ["tenant_id"])
    op.create_index("ix_workspaces_owner_tenant", "workspaces", ["owner_user_id", "tenant_id"])
    op.create_index("ix_workspaces_created_at", "workspaces", ["created_at"])

    # ── Source Assets ────────────────────────────────────────────
    op.create_table(
        "source_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_user_id", sa.String(100), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("diagram_id", sa.String(50), nullable=True),
        sa.Column("source_cloud", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_source_assets_workspace_id", "source_assets", ["workspace_id"])
    op.create_index("ix_source_assets_owner_user_id", "source_assets", ["owner_user_id"])
    op.create_index("ix_source_assets_content_hash", "source_assets", ["content_hash"])
    op.create_index("ix_source_assets_diagram_id", "source_assets", ["diagram_id"])
    op.create_index("ix_source_assets_workspace_hash", "source_assets", ["workspace_id", "content_hash"])
    op.create_index("ix_source_assets_created_at", "source_assets", ["created_at"])

    # ── Analyses ──────────────────────────────────────────────────
    op.create_table(
        "analyses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_asset_id", sa.String(36),
                  sa.ForeignKey("source_assets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("owner_user_id", sa.String(100), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=True),
        sa.Column("diagram_id", sa.String(50), nullable=True),
        sa.Column("title", sa.String(300), nullable=True),
        sa.Column("source_cloud", sa.String(20), nullable=False, server_default="aws"),
        sa.Column("target_cloud", sa.String(20), nullable=False, server_default="azure"),
        sa.Column("status", sa.String(20), nullable=False, server_default="completed"),
        sa.Column("services_detected", sa.Integer(), server_default="0"),
        sa.Column("confidence_avg", sa.Float(), nullable=True),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_analyses_workspace_id", "analyses", ["workspace_id"])
    op.create_index("ix_analyses_owner_user_id", "analyses", ["owner_user_id"])
    op.create_index("ix_analyses_tenant_id", "analyses", ["tenant_id"])
    op.create_index("ix_analyses_diagram_id", "analyses", ["diagram_id"])
    op.create_index("ix_analyses_created_at", "analyses", ["created_at"])
    op.create_index("ix_analyses_workspace_owner", "analyses", ["workspace_id", "owner_user_id"])

    # ── Analysis Versions ─────────────────────────────────────────
    op.create_table(
        "analysis_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("analysis_id", sa.String(36),
                  sa.ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("snapshot", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(16), nullable=True),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("restored_from", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_analysis_versions_analysis_id", "analysis_versions", ["analysis_id"])
    op.create_index("ix_analysis_versions_content_hash", "analysis_versions", ["content_hash"])
    op.create_index("ix_analysis_versions_created_at", "analysis_versions", ["created_at"])
    op.create_index(
        "ix_analysis_versions_analysis_num",
        "analysis_versions",
        ["analysis_id", "version_number"],
    )

    # ── Artifacts ─────────────────────────────────────────────────
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("analysis_id", sa.String(36),
                  sa.ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_id", sa.String(36),
                  sa.ForeignKey("analysis_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_asset_id", sa.String(36),
                  sa.ForeignKey("source_assets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("owner_user_id", sa.String(100), nullable=False),
        sa.Column("artifact_type", sa.String(50), nullable=False),
        sa.Column("format", sa.String(20), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("storage_url", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_artifacts_analysis_id", "artifacts", ["analysis_id"])
    op.create_index("ix_artifacts_version_id", "artifacts", ["version_id"])
    op.create_index("ix_artifacts_owner_user_id", "artifacts", ["owner_user_id"])
    op.create_index("ix_artifacts_artifact_type", "artifacts", ["artifact_type"])
    op.create_index("ix_artifacts_content_hash", "artifacts", ["content_hash"])
    op.create_index("ix_artifacts_created_at", "artifacts", ["created_at"])
    op.create_index("ix_artifacts_analysis_type", "artifacts", ["analysis_id", "artifact_type"])

    # ── Decisions ─────────────────────────────────────────────────
    op.create_table(
        "decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("analysis_id", sa.String(36),
                  sa.ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_id", sa.String(36),
                  sa.ForeignKey("analysis_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("owner_user_id", sa.String(100), nullable=False),
        sa.Column("decision_type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(20), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("extra_data", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_decisions_analysis_id", "decisions", ["analysis_id"])
    op.create_index("ix_decisions_owner_user_id", "decisions", ["owner_user_id"])
    op.create_index("ix_decisions_created_at", "decisions", ["created_at"])
    op.create_index("ix_decisions_analysis_type", "decisions", ["analysis_id", "decision_type"])


def downgrade() -> None:
    op.drop_table("decisions")
    op.drop_table("artifacts")
    op.drop_table("analysis_versions")
    op.drop_table("analyses")
    op.drop_table("source_assets")
    op.drop_table("workspaces")
