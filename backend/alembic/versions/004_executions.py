"""Execution Engine

Revision ID: 004_executions
Revises: 003_agent_paas
Create Date: 2024-02-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '004_executions'
down_revision = '003_agent_paas'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('executions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('agent_id', sa.String(), nullable=False),
        sa.Column('organization_id', sa.String(), nullable=False),
        sa.Column('thread_id', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('input_data', sa.JSON(), nullable=True),
        sa.Column('output_data', sa.JSON(), nullable=True),
        sa.Column('steps', sa.JSON(), nullable=True),
        
        sa.Column('prompt_tokens', sa.Integer(), nullable=True),
        sa.Column('completion_tokens', sa.Integer(), nullable=True),
        sa.Column('total_tokens', sa.Integer(), nullable=True),
        sa.Column('total_cost', sa.Float(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        
        sa.Column('error_message', sa.String(), nullable=True),
        
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.org_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_executions_agent_id'), 'executions', ['agent_id'], unique=False)
    op.create_index(op.f('ix_executions_organization_id'), 'executions', ['organization_id'], unique=False)
    op.create_index(op.f('ix_executions_thread_id'), 'executions', ['thread_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_executions_thread_id'), table_name='executions')
    op.drop_index(op.f('ix_executions_organization_id'), table_name='executions')
    op.drop_index(op.f('ix_executions_agent_id'), table_name='executions')
    op.drop_table('executions')
