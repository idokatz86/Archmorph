import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, JSON, ForeignKey, Float, Integer
from sqlalchemy.orm import relationship
from database import Base

class Execution(Base):
    __tablename__ = "executions"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id = Column(String, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(String, ForeignKey("organizations.org_id", ondelete="CASCADE"), nullable=False, index=True)
    thread_id = Column(String, nullable=True, index=True)
    status = Column(String, default="queued") # queued, running, completed, failed, cancelled, timeout
    
    input_data = Column(JSON, nullable=True)
    output_data = Column(JSON, nullable=True)
    steps = Column(JSON, default=list) # [{type, input, output, tokens, duration}]
    
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    total_cost = Column(Float, default=0.0)
    duration_ms = Column(Integer, default=0)
    
    error_message = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    agent = relationship("Agent", backref="executions")
