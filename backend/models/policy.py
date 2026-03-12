import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, JSON, ForeignKey, Boolean
from database import Base

class AgentPolicy(Base):
    __tablename__ = "agent_policies"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String, ForeignKey("organizations.org_id", ondelete="CASCADE"), nullable=False, index=True)
    
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    
    # Types: input, output, tool, data, operational
    policy_type = Column(String, nullable=False)
    
    rules = Column(JSON, default=dict)
    enforcement_level = Column(String, default="block") # block, flag, audit, ignore
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class AgentPolicyBinding(Base):
    """Maps agents to specific policies"""
    __tablename__ = "agent_policy_bindings"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id = Column(String, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    policy_id = Column(String, ForeignKey("agent_policies.id", ondelete="CASCADE"), nullable=False, index=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
