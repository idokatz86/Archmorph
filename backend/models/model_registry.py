import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, JSON, ForeignKey, Boolean, Float
from database import Base

class ModelEndpoint(Base):
    __tablename__ = "model_endpoints"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String, ForeignKey("organizations.org_id", ondelete="CASCADE"), nullable=False, index=True)
    
    name = Column(String, nullable=False)
    provider = Column(String, nullable=False) # azure-openai, openai, anthropic
    model_version = Column(String, nullable=False) # e.g. gpt-4o, claude-3-opus
    is_active = Column(Boolean, default=True)
    
    connection_config = Column(JSON, nullable=False) # url, keys, region
    capabilities = Column(JSON, default=dict) # vision, tools, max_tokens
    pricing = Column(JSON, default=dict) # input_cost, output_cost per 1k
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
