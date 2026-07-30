from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from database import Base
from models.time_utils import utc_now_naive


class DeploymentState(Base):
    __tablename__ = "deployment_state"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    environment = Column(String(20), index=True, nullable=False)
    # Authorization/audit metadata copied from the canonical Project. These
    # columns deliberately do not participate in state identity.
    owner_user_id = Column(String(100), index=True, nullable=False)
    tenant_id = Column(String(100), index=True, nullable=True)
    state_json = Column(JSON, nullable=True)  # The actual raw terraform.tfstate

    # Locking
    lock_id = Column(String, nullable=True)  # UUID of the lock
    lock_info = Column(JSON, nullable=True)  # Terraform sends JSON lock info
    locked_at = Column(DateTime, nullable=True)

    # Rollback tracking
    previous_state_json = Column(JSON, nullable=True)

    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    __table_args__ = (
        CheckConstraint(
            "environment IN ('dev', 'staging', 'prod')",
            name="ck_deployment_state_environment",
        ),
        UniqueConstraint(
            "project_id",
            "environment",
            name="uq_deployment_state_project_environment",
        ),
    )

