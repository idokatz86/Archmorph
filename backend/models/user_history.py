"""User analysis history and saved diagrams — persistent data models (#151)."""

from sqlalchemy import Column, String, Integer, Text, DateTime, Boolean, Float, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class UserAnalysis(Base):
    """A completed analysis tied to a user for dashboard history."""

    __tablename__ = "user_analyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_id = Column(String(50), unique=True, nullable=False, index=True)
    user_id = Column(String(100), nullable=False, index=True)
    org_id = Column(String(36), nullable=True, index=True)
    diagram_id = Column(String(50), nullable=False, index=True)
    title = Column(String(300), nullable=True)
    source_provider = Column(String(20), nullable=False, default="aws")
    target_provider = Column(String(20), nullable=False, default="azure")
    services_detected = Column(Integer, default=0)
    mappings_count = Column(Integer, default=0)
    confidence_avg = Column(Float, nullable=True)
    status = Column(String(20), nullable=False, default="completed")
    thumbnail_url = Column(String(500), nullable=True)
    analysis_snapshot = Column(Text, nullable=True)
    iac_generated = Column(Boolean, default=False)
    hld_generated = Column(Boolean, default=False)
    cost_estimated = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    saved = relationship("SavedDiagram", back_populates="analysis", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "analysis_id": self.analysis_id,
            "user_id": self.user_id,
            "org_id": self.org_id,
            "diagram_id": self.diagram_id,
            "title": self.title,
            "source_provider": self.source_provider,
            "target_provider": self.target_provider,
            "services_detected": self.services_detected,
            "mappings_count": self.mappings_count,
            "confidence_avg": self.confidence_avg,
            "status": self.status,
            "thumbnail_url": self.thumbnail_url,
            "iac_generated": self.iac_generated,
            "hld_generated": self.hld_generated,
            "cost_estimated": self.cost_estimated,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SavedDiagram(Base):
    """Bookmarked / pinned analyses for quick access."""

    __tablename__ = "saved_diagrams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(100), nullable=False, index=True)
    analysis_id = Column(String(50), ForeignKey("user_analyses.analysis_id", ondelete="CASCADE"),
                         nullable=False, index=True)
    label = Column(String(200), nullable=True)
    pinned = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    analysis = relationship("UserAnalysis", back_populates="saved")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "analysis_id": self.analysis_id,
            "label": self.label,
            "pinned": self.pinned,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
