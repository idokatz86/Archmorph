"""Feedback & NPS database models (Issue #168)."""

from sqlalchemy import Column, String, Integer, Text, DateTime, Boolean
from sqlalchemy.sql import func
from database import Base


class FeedbackRecord(Base):
    """Persisted NPS / feature feedback record."""

    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    feedback_type = Column(String(20), nullable=False, index=True)  # nps | feature | general
    score = Column(Integer, nullable=True)          # NPS 0-10
    category = Column(String(20), nullable=True)    # promoter | passive | detractor
    feature = Column(String(100), nullable=True)    # feature name for feature feedback
    helpful = Column(Boolean, nullable=True)        # thumbs up/down
    comment = Column(Text, nullable=True)
    session_id = Column(String(100), nullable=True, index=True)
    feature_context = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "feedback_type": self.feedback_type,
            "score": self.score,
            "category": self.category,
            "feature": self.feature,
            "helpful": self.helpful,
            "comment": self.comment,
            "session_id": self.session_id,
            "feature_context": self.feature_context,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class BugReportRecord(Base):
    """Persisted bug report."""

    __tablename__ = "bug_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    description = Column(Text, nullable=False)
    severity = Column(String(20), nullable=False, default="medium")
    context = Column(Text, nullable=True)           # JSON-serialized context dict
    session_id = Column(String(100), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="open")  # open | acknowledged | resolved
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def to_dict(self):
        import json as _json
        return {
            "id": self.id,
            "description": self.description,
            "severity": self.severity,
            "context": _json.loads(self.context) if self.context else {},
            "session_id": self.session_id,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
