"""Persist Terraform state owner and tenant

Revision ID: 012_deployment_state_owner
Revises: 011_hnsw_indexes
Create Date: 2026-05-08 04:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '012_deployment_state_owner'
down_revision = '011_hnsw_indexes'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('deployment_state', sa.Column('owner_user_id', sa.String(), nullable=True))
    op.add_column('deployment_state', sa.Column('tenant_id', sa.String(), nullable=True))
    op.create_index('ix_deployment_state_owner_user_id', 'deployment_state', ['owner_user_id'])
    op.create_index('ix_deployment_state_tenant_id', 'deployment_state', ['tenant_id'])


def downgrade():
    op.drop_index('ix_deployment_state_tenant_id', table_name='deployment_state')
    op.drop_index('ix_deployment_state_owner_user_id', table_name='deployment_state')
    op.drop_column('deployment_state', 'tenant_id')
    op.drop_column('deployment_state', 'owner_user_id')