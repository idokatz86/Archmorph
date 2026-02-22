"""Usage metrics database models (Issue #168)."""

from sqlalchemy import Column, String, Integer, Text, DateTime, Index
from sqlalchemy.sql import func
from database import Base


class UsageCounterRecord(Base):
    """Persisted usage counter — replaces in-memory _metrics dict."""

    __tablename__ = "usage_counters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    counter_name = Column(String(100), nullable=False, index=True)
    date = Column(String(10), nullable=False, index=True)      # YYYY-MM-DD
    count = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_usage_counters_name_date", "counter_name", "date", unique=True),
    )

    def to_dict(self):
        return {
            "counter_name": self.counter_name,
            "date": self.date,
            "count": self.count,
        }


class FunnelStepRecord(Base):
    """Persisted funnel step — replaces in-memory sessions dict."""

    __tablename__ = "funnel_steps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    diagram_id = Column(String(50), nullable=False, index=True)
    step = Column(String(30), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_funnel_diagram_step", "diagram_id", "step", unique=True),
    )

    def to_dict(self):
        return {
            "diagram_id": self.diagram_id,
            "step": self.step,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
