"""
ORM model for AI Suggestion feedback persistence (Issue #153).

Stores approved/rejected mapping decisions from the admin review queue,
enabling the few-shot learning loop to survive restarts.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, DateTime, Index
from database import Base


class SuggestionFeedback(Base):
    __tablename__ = "suggestion_feedback"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    source_service = Column(String, nullable=False, index=True)
    source_provider = Column(String, nullable=False)
    azure_service = Column(String, nullable=False)
    confidence = Column(Float, nullable=False)
    category = Column(String, nullable=True)
    decision = Column(String, nullable=False)  # "approved" | "rejected"
    reviewer = Column(String, nullable=True)
    recorded_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_suggestion_feedback_provider", "source_provider"),
        Index("ix_suggestion_feedback_decision", "decision"),
    )
