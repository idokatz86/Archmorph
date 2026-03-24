"""Add cost_records table for persistent cost metering

Revision ID: 010_cost_records
Revises: 009_suggestion_feedback
Create Date: 2026-03-24 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '010_cost_records'
down_revision = '009_suggestion_feedback'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'cost_records',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('execution_id', sa.String(), nullable=True),
        sa.Column('agent_id', sa.String(), nullable=True, index=True),
        sa.Column('model', sa.String(), nullable=False),
        sa.Column('prompt_tokens', sa.Integer(), default=0),
        sa.Column('completion_tokens', sa.Integer(), default=0),
        sa.Column('total_tokens', sa.Integer(), default=0),
        sa.Column('cost_usd', sa.Float(), default=0.0),
        sa.Column('caller', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_cost_records_created', 'cost_records', ['created_at'])
    op.create_index('ix_cost_records_model', 'cost_records', ['model'])


def downgrade():
    op.drop_index('ix_cost_records_model')
    op.drop_index('ix_cost_records_created')
    op.drop_table('cost_records')
