"""Policy Management

Revision ID: 006_policy
Revises: 005_memory
Create Date: 2024-02-28 02:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '006_policy'
down_revision = '005_memory'
branch_labels = None
depends_on = None


def upgrade():
    # policies
    op.create_table('agent_policies',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('organization_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('policy_type', sa.String(), nullable=False),
        sa.Column('rules', sa.JSON(), nullable=True),
        sa.Column('enforcement_level', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.org_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_policies_organization_id'), 'agent_policies', ['organization_id'], unique=False)

    # policy bindings
    op.create_table('agent_policy_bindings',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('agent_id', sa.String(), nullable=False),
        sa.Column('policy_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['policy_id'], ['agent_policies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_policy_bindings_agent_id'), 'agent_policy_bindings', ['agent_id'], unique=False)
    op.create_index(op.f('ix_agent_policy_bindings_policy_id'), 'agent_policy_bindings', ['policy_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_agent_policy_bindings_policy_id'), table_name='agent_policy_bindings')
    op.drop_index(op.f('ix_agent_policy_bindings_agent_id'), table_name='agent_policy_bindings')
    op.drop_table('agent_policy_bindings')
    
    op.drop_index(op.f('ix_agent_policies_organization_id'), table_name='agent_policies')
    op.drop_table('agent_policies')
