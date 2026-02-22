"""Analytics database models (Issue #168)."""

from sqlalchemy import Column, String, Integer, Float, Text, DateTime, Index
from sqlalchemy.sql import func
from database import Base


class AnalyticsEventRecord(Base):
    """Persisted analytics event — replaces in-memory EVENTS_BUFFER."""

    __tablename__ = "analytics_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(50), unique=True, nullable=False, index=True)
    event_name = Column(String(100), nullable=False, index=True)
    category = Column(String(30), nullable=False, index=True)
    user_id = Column(String(100), nullable=True, index=True)
    session_id = Column(String(100), nullable=True, index=True)
    properties = Column(Text, nullable=True)    # JSON-serialized
    metrics = Column(Text, nullable=True)       # JSON-serialized
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_analytics_events_cat_time", "category", "created_at"),
    )

    def to_dict(self):
        import json as _json
        return {
            "event_id": self.event_id,
            "event_name": self.event_name,
            "category": self.category,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "properties": _json.loads(self.properties) if self.properties else {},
            "metrics": _json.loads(self.metrics) if self.metrics else {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AnalyticsSessionRecord(Base):
    """Persisted user session — replaces in-memory SESSIONS cache."""

    __tablename__ = "analytics_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(100), unique=True, nullable=False, index=True)
    user_id = Column(String(100), nullable=True, index=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    last_activity = Column(DateTime(timezone=True), server_default=func.now())
    events_count = Column(Integer, default=0)
    page_views = Column(Text, nullable=True)       # JSON array
    conversion_achieved = Column(Integer, default=0)  # 0=no, 1=yes (SQLite compat)
    duration_seconds = Column(Float, default=0.0)

    def to_dict(self):
        import json as _json
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_activity": self.last_activity.isoformat() if self.last_activity else None,
            "events_count": self.events_count,
            "page_views": _json.loads(self.page_views) if self.page_views else [],
            "conversion_achieved": bool(self.conversion_achieved),
            "duration_seconds": self.duration_seconds,
        }
