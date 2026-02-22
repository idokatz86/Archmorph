"""Job queue database model (Issues #168 + #172)."""

from sqlalchemy import Column, String, Integer, Float, Text, DateTime, Index
from sqlalchemy.sql import func
from database import Base


class JobRecord(Base):
    """Persisted async job state — background AI operations."""

    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(50), unique=True, nullable=False, index=True)
    job_type = Column(String(50), nullable=False, index=True)   # analyze | generate_iac | generate_hld
    diagram_id = Column(String(50), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="queued", index=True)  # queued | running | completed | failed | cancelled
    progress = Column(Integer, default=0)           # 0-100
    progress_message = Column(String(255), nullable=True)
    result = Column(Text, nullable=True)            # JSON-serialized result
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Float, nullable=True)

    __table_args__ = (
        Index("ix_jobs_diagram_type", "diagram_id", "job_type"),
        Index("ix_jobs_status_created", "status", "created_at"),
    )

    def to_dict(self):
        import json as _json
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "diagram_id": self.diagram_id,
            "status": self.status,
            "progress": self.progress,
            "progress_message": self.progress_message,
            "result": _json.loads(self.result) if self.result else None,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": self.duration_ms,
        }
