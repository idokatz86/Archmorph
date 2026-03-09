"""Add vector extension and embeddings

Revision ID: 008_pgvector
Revises: 007_model_registry
Create Date: 2024-03-09 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision = '008_pgvector'
down_revision = '007_model_registry'
branch_labels = None
depends_on = None

def upgrade():
    op.execute('CREATE EXTENSION IF NOT EXISTS vector;')
    
    op.add_column('agent_episodic_memories', sa.Column('embedding', Vector(1536), nullable=True))
    op.add_column('agent_entity_memories', sa.Column('embedding', Vector(1536), nullable=True))

def downgrade():
    op.drop_column('agent_entity_memories', 'embedding')
    op.drop_column('agent_episodic_memories', 'embedding')
    op.execute('DROP EXTENSION IF EXISTS vector;')
