"""Memory Management

Revision ID: 005_memory
Revises: 004_executions
Create Date: 2024-02-28 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '005_memory'
down_revision = '004_executions'
branch_labels = None
depends_on = None


def upgrade():
    # documents
    op.create_table('agent_memory_documents',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('agent_id', sa.String(), nullable=False),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('file_type', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('chunk_count', sa.Integer(), nullable=True),
        sa.Column('embedding_model', sa.String(), nullable=True),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_memory_documents_agent_id'), 'agent_memory_documents', ['agent_id'], unique=False)

    # episodic memories
    op.create_table('agent_episodic_memories',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('agent_id', sa.String(), nullable=False),
        sa.Column('execution_id', sa.String(), nullable=True),
        sa.Column('summary', sa.String(), nullable=False),
        sa.Column('importance_score', sa.Float(), nullable=True),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['execution_id'], ['executions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_episodic_memories_agent_id'), 'agent_episodic_memories', ['agent_id'], unique=False)

    # entity memories
    op.create_table('agent_entity_memories',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('agent_id', sa.String(), nullable=False),
        sa.Column('entity_name', sa.String(), nullable=False),
        sa.Column('entity_type', sa.String(), nullable=False),
        sa.Column('attributes', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_entity_memories_agent_id'), 'agent_entity_memories', ['agent_id'], unique=False)
    op.create_index(op.f('ix_agent_entity_memories_entity_name'), 'agent_entity_memories', ['entity_name'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_agent_entity_memories_entity_name'), table_name='agent_entity_memories')
    op.drop_index(op.f('ix_agent_entity_memories_agent_id'), table_name='agent_entity_memories')
    op.drop_table('agent_entity_memories')
    
    op.drop_index(op.f('ix_agent_episodic_memories_agent_id'), table_name='agent_episodic_memories')
    op.drop_table('agent_episodic_memories')
    
    op.drop_index(op.f('ix_agent_memory_documents_agent_id'), table_name='agent_memory_documents')
    op.drop_table('agent_memory_documents')
