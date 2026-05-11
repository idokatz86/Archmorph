"""Persist Terraform state owner and tenant

Revision ID: 012_deployment_state_owner
Revises: 011_hnsw_indexes
Create Date: 2026-05-08 04:20:00.000000

"""
from alembic import context, op
import sqlalchemy as sa


revision = '012_deployment_state_owner'
down_revision = '011_hnsw_indexes'
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    if context.is_offline_mode():
        return False
    bind = op.get_bind()
    return sa.inspect(bind).has_table(table_name)


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    bind = op.get_bind()
    return {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if context.is_offline_mode() or index_name not in _indexes(table_name):
        op.create_index(index_name, table_name, columns)


def upgrade():
    if not _has_table('deployment_state'):
        op.create_table(
            'deployment_state',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('project_id', sa.String(), nullable=False),
            sa.Column('environment', sa.String(), nullable=False),
            sa.Column('owner_user_id', sa.String(), nullable=True),
            sa.Column('tenant_id', sa.String(), nullable=True),
            sa.Column('state_json', sa.JSON(), nullable=True),
            sa.Column('lock_id', sa.String(), nullable=True),
            sa.Column('lock_info', sa.JSON(), nullable=True),
            sa.Column('locked_at', sa.DateTime(), nullable=True),
            sa.Column('previous_state_json', sa.JSON(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
        )
    else:
        existing_columns = _columns('deployment_state')
        if 'owner_user_id' not in existing_columns:
            op.add_column('deployment_state', sa.Column('owner_user_id', sa.String(), nullable=True))
        if 'tenant_id' not in existing_columns:
            op.add_column('deployment_state', sa.Column('tenant_id', sa.String(), nullable=True))

    _create_index_if_missing('ix_deployment_state_project_id', 'deployment_state', ['project_id'])
    _create_index_if_missing('ix_deployment_state_environment', 'deployment_state', ['environment'])
    _create_index_if_missing('ix_deployment_state_owner_user_id', 'deployment_state', ['owner_user_id'])
    _create_index_if_missing('ix_deployment_state_tenant_id', 'deployment_state', ['tenant_id'])


def downgrade():
    if not _has_table('deployment_state'):
        return

    existing_indexes = _indexes('deployment_state')
    for index_name in (
        'ix_deployment_state_tenant_id',
        'ix_deployment_state_owner_user_id',
        'ix_deployment_state_environment',
        'ix_deployment_state_project_id',
    ):
        if index_name in existing_indexes:
            op.drop_index(index_name, table_name='deployment_state')

    existing_columns = _columns('deployment_state')
    if 'tenant_id' in existing_columns:
        op.drop_column('deployment_state', 'tenant_id')
    if 'owner_user_id' in existing_columns:
        op.drop_column('deployment_state', 'owner_user_id')
