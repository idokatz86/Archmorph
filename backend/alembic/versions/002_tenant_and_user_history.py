"""Add tenant tables (organizations, team_members, invitations) and user_analyses

Revision ID: 002
Revises: 001
Create Date: 2026-02-24
"""

from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Organizations (multi-tenancy) ──
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.String(36), unique=True, nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(100), unique=True, nullable=False, index=True),
        sa.Column("plan", sa.String(20), nullable=False, server_default="free"),
        sa.Column("max_members", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("max_analyses_per_month", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("storage_prefix", sa.String(100), nullable=True),
        sa.Column("settings", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── Team Members (RBAC within orgs) ──
    op.create_table(
        "team_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("user_id", sa.String(100), nullable=False, index=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column("role", sa.String(20), nullable=False, server_default="viewer"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_team_members_org_user", "team_members", ["org_id", "user_id"], unique=True)

    # ── Invitations ──
    op.create_table(
        "invitations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="viewer"),
        sa.Column("token", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("invited_by", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── User Analyses (persistent history for user dashboard — #151) ──
    op.create_table(
        "user_analyses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("analysis_id", sa.String(50), unique=True, nullable=False, index=True),
        sa.Column("user_id", sa.String(100), nullable=False, index=True),
        sa.Column("org_id", sa.String(36), nullable=True, index=True),
        sa.Column("diagram_id", sa.String(50), nullable=False, index=True),
        sa.Column("title", sa.String(300), nullable=True),
        sa.Column("source_provider", sa.String(20), nullable=False, server_default="aws"),
        sa.Column("target_provider", sa.String(20), nullable=False, server_default="azure"),
        sa.Column("services_detected", sa.Integer(), server_default="0"),
        sa.Column("mappings_count", sa.Integer(), server_default="0"),
        sa.Column("confidence_avg", sa.Float(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="completed"),
        sa.Column("thumbnail_url", sa.String(500), nullable=True),
        sa.Column("analysis_snapshot", sa.Text(), nullable=True),  # JSON snapshot
        sa.Column("iac_generated", sa.Boolean(), server_default=sa.false()),
        sa.Column("hld_generated", sa.Boolean(), server_default=sa.false()),
        sa.Column("cost_estimated", sa.Boolean(), server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_user_analyses_user_created", "user_analyses", ["user_id", "created_at"])

    # ── User Saved Diagrams (bookmarks / favourites) ──
    op.create_table(
        "saved_diagrams",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(100), nullable=False, index=True),
        sa.Column("analysis_id", sa.String(50), sa.ForeignKey("user_analyses.analysis_id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column("pinned", sa.Boolean(), server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_saved_diagrams_user_analysis", "saved_diagrams", ["user_id", "analysis_id"], unique=True)


def downgrade() -> None:
    op.drop_table("saved_diagrams")
    op.drop_table("user_analyses")
    op.drop_table("invitations")
    op.drop_table("team_members")
    op.drop_table("organizations")
