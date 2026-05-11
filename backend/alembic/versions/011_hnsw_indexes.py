"""Add HNSW indexes for pgvector embedding columns (#501)

Indexes agent_episodic_memories, agent_entity_memories, and
rag_document_chunks embedding columns with HNSW for O(log n)
approximate nearest neighbor search instead of O(n) sequential scan.

Revision ID: 011_hnsw_indexes
Revises: 010_cost_records
Create Date: 2026-04-12 16:00:00.000000

"""
from alembic import context, op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '011_hnsw_indexes'
down_revision = '010_cost_records'
branch_labels = None
depends_on = None

# HNSW parameters:
#   m=16       — max connections per layer (default 16, good balance)
#   ef_construction=64 — build-time quality (higher=slower build, better recall)
# Operator class: vector_cosine_ops for cosine similarity


def _has_table(table_name: str) -> bool:
    if context.is_offline_mode():
        return True
    bind = op.get_bind()
    return sa.inspect(bind).has_table(table_name)


def upgrade():
    # Episodic memories — agent conversation memories
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_episodic_memories_embedding_hnsw
        ON agent_episodic_memories
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64);
    """)

    # Entity memories — agent knowledge about entities
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_entity_memories_embedding_hnsw
        ON agent_entity_memories
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64);
    """)

    # RAG document chunks — optional retired RAG surface. Older deployments may
    # still have this table; fresh databases after RAG retirement do not.
    if _has_table('rag_document_chunks'):
        op.execute("""
            CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw
            ON rag_document_chunks
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64);
        """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_episodic_memories_embedding_hnsw;")
    op.execute("DROP INDEX IF EXISTS ix_entity_memories_embedding_hnsw;")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw;")
