import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from database import Base

class Agent(Base):
    __tablename__ = "agents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String, ForeignKey("organizations.org_id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    version = Column(String, default="1.0.0")
    status = Column(String, default="draft")  # draft, active, paused, archived
    
    model_config_data = Column(JSON, nullable=True)
    tools = Column(JSON, default=list)
    data_sources = Column(JSON, default=list)
    memory_config = Column(JSON, nullable=True)
    policy_ref = Column(String, nullable=True)
    metadata_json = Column(JSON, default=dict)
    
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization", backref="agents")

class AgentVersion(Base):
    __tablename__ = "agent_versions"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False, index=True)
    version = Column(String, nullable=False)
    config_snapshot = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String, nullable=True)

    agent = relationship("Agent", backref="version_history")
