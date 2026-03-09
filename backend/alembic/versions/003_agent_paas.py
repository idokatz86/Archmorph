"""Add AI Agent PaaS tables

Revision ID: 003
Revises: 002
Create Date: 2026-03-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.types import String, DateTime

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", String(length=36), primary_key=True),
        sa.Column("organization_id", String(length=36), sa.ForeignKey("organizations.org_id"), nullable=False, index=True),
        sa.Column("name", String(), nullable=False),
        sa.Column("description", String(), nullable=True),
        sa.Column("version", String(), nullable=True, server_default="1.0.0"),
        sa.Column("status", String(), nullable=True, server_default="draft"),
        sa.Column("model_config_data", JSON(), nullable=True),
        sa.Column("tools", JSON(), nullable=True),
        sa.Column("data_sources", JSON(), nullable=True),
        sa.Column("memory_config", JSON(), nullable=True),
        sa.Column("policy_ref", String(), nullable=True),
        sa.Column("metadata_json", JSON(), nullable=True),
        sa.Column("created_by", String(), nullable=True),
        sa.Column("created_at", DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", DateTime(), server_default=sa.func.now())
    )

    op.create_table(
        "agent_versions",
        sa.Column("id", String(length=36), primary_key=True),
        sa.Column("agent_id", String(length=36), sa.ForeignKey("agents.id"), nullable=False, index=True),
        sa.Column("version", String(), nullable=False),
        sa.Column("config_snapshot", JSON(), nullable=False),
        sa.Column("created_at", DateTime(), server_default=sa.func.now()),
        sa.Column("created_by", String(), nullable=True)
    )

def downgrade() -> None:
    op.drop_table("agent_versions")
    op.drop_table("agents")
