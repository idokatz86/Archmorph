"""
RAG (Retrieval-Augmented Generation) database models — Issue #395.

Provides pgvector-backed document collections and chunks for semantic search.
Uses the same TESTING env var pattern as models/memory.py for SQLite fallback.
"""

import os
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, JSON, ForeignKey, Integer, Text
from database import Base

# Conditionally use pgvector for postgres, fallback to JSON/String for sqlite in tests
if os.getenv("TESTING", "false").lower() == "true":
    from sqlalchemy import JSON as VectorType
    def Vector(dim):
        return VectorType
else:
    from pgvector.sqlalchemy import Vector


class DocumentCollection(Base):
    """A named collection of RAG documents scoped to an agent."""
    __tablename__ = "rag_collections"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id = Column(String, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)

    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    chunk_strategy = Column(String, default="fixed")  # fixed, semantic, sliding
    chunk_size = Column(Integer, default=512)  # token count per chunk
    chunk_overlap = Column(Integer, default=64)  # overlap tokens for sliding window
    embedding_model = Column(String, default="text-embedding-3-small")
    metadata_json = Column(JSON, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RAGDocument(Base):
    """A source document ingested into a collection."""
    __tablename__ = "rag_documents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    collection_id = Column(String, ForeignKey("rag_collections.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(String, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)

    filename = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    status = Column(String, default="processing")  # processing, ready, error
    chunk_count = Column(Integer, default=0)
    file_size_bytes = Column(Integer, nullable=True)
    error_message = Column(String, nullable=True)
    metadata_json = Column(JSON, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DocumentChunk(Base):
    """A chunk of text from a source document with its embedding vector."""
    __tablename__ = "rag_document_chunks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String, ForeignKey("rag_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    collection_id = Column(String, ForeignKey("rag_collections.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(String, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)

    content = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)  # position in source document
    token_count = Column(Integer, nullable=True)

    # Source citation metadata
    source_filename = Column(String, nullable=False)
    source_page = Column(Integer, nullable=True)  # page number for PDFs
    source_section = Column(String, nullable=True)  # heading or section name

    embedding = Column(Vector(1536), nullable=True)  # text-embedding-3-small = 1536 dims
    metadata_json = Column(JSON, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow)
