from sqlalchemy import Column, String, JSON, DateTime, Integer
from database import Base
from models.time_utils import utc_now_naive

class DeploymentState(Base):
    __tablename__ = "deployment_state"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(String, index=True, nullable=False)
    environment = Column(String, index=True, nullable=False)  # e.g., 'dev', 'prod'
    owner_user_id = Column(String, index=True, nullable=True)
    tenant_id = Column(String, index=True, nullable=True)
    state_json = Column(JSON, nullable=True)  # The actual raw terraform.tfstate
    
    # Locking
    lock_id = Column(String, nullable=True)     # UUID of the lock
    lock_info = Column(JSON, nullable=True)     # Terraform sends JSON lock info
    locked_at = Column(DateTime, nullable=True)

    # Rollback tracking
    previous_state_json = Column(JSON, nullable=True) 

    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

