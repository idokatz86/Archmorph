"""Add suggestion_feedback table for persistent learning loop

Revision ID: 009_suggestion_feedback
Revises: 008_pgvector
Create Date: 2026-03-24 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '009_suggestion_feedback'
down_revision = '008_pgvector'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'suggestion_feedback',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('source_service', sa.String(), nullable=False, index=True),
        sa.Column('source_provider', sa.String(), nullable=False),
        sa.Column('azure_service', sa.String(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('decision', sa.String(), nullable=False),  # "approved" | "rejected"
        sa.Column('reviewer', sa.String(), nullable=True),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_suggestion_feedback_provider', 'suggestion_feedback', ['source_provider'])
    op.create_index('ix_suggestion_feedback_decision', 'suggestion_feedback', ['decision'])


def downgrade():
    op.drop_index('ix_suggestion_feedback_decision')
    op.drop_index('ix_suggestion_feedback_provider')
    op.drop_table('suggestion_feedback')
