"""Model Registry

Revision ID: 007_model_registry
Revises: 006_policy
Create Date: 2024-02-28 03:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '007_model_registry'
down_revision = '006_policy'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('model_endpoints',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('organization_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('model_version', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('connection_config', sa.JSON(), nullable=False),
        sa.Column('capabilities', sa.JSON(), nullable=True),
        sa.Column('pricing', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.org_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_model_endpoints_organization_id'), 'model_endpoints', ['organization_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_model_endpoints_organization_id'), table_name='model_endpoints')
    op.drop_table('model_endpoints')
