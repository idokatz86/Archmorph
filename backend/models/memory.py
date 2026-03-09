import os
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, JSON, ForeignKey, Integer, Boolean, Float
from sqlalchemy.orm import relationship
from database import Base

# Conditionally use pgvector for postgres, fallback to JSON/String for sqlite in tests
if os.getenv("TESTING", "false").lower() == "true":
    from sqlalchemy import JSON as VectorType
    def Vector(dim):
        return VectorType
else:
    from pgvector.sqlalchemy import Vector


class AgentMemoryDocument(Base):
    __tablename__ = "agent_memory_documents"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id = Column(String, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    
    filename = Column(String, nullable=False)
    file_type = Column(String, nullable=False) # pdf, txt, etc.
    status = Column(String, default="processing") # processing, ready, error
    
    chunk_count = Column(Integer, default=0)
    embedding_model = Column(String, nullable=True) # e.g., text-embedding-3-small
    metadata_json = Column(JSON, default=dict)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class AgentEpisodicMemory(Base):
    __tablename__ = "agent_episodic_memories"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id = Column(String, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    execution_id = Column(String, ForeignKey("executions.id", ondelete="SET NULL"), nullable=True)
    
    summary = Column(String, nullable=False)
    importance_score = Column(Float, default=1.0) # 1-10 scale of how important this memory is
    tags = Column(JSON, default=list)
    embedding = Column(Vector(1536), nullable=True) # OpenAI text-embedding-3-small dimension
    
    created_at = Column(DateTime, default=datetime.utcnow)

class AgentEntityMemory(Base):
    __tablename__ = "agent_entity_memories"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id = Column(String, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    
    entity_name = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False) # e.g., Person, Project, Preference
    attributes = Column(JSON, default=dict)
    embedding = Column(Vector(1536), nullable=True) # OpenAI text-embedding-3-small dimension
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
