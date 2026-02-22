"""Architecture versioning database models (Issue #168)."""

from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey, Index
from sqlalchemy.sql import func
from database import Base


class VersionRecord(Base):
    """Persisted architecture version — replaces in-memory VERSION_STORE."""

    __tablename__ = "architecture_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version_id = Column(String(50), unique=True, nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    diagram_id = Column(String(50), nullable=False, index=True)
    snapshot = Column(Text, nullable=False)        # JSON-serialized analysis snapshot
    created_by = Column(String(100), nullable=True)
    message = Column(Text, nullable=True)
    content_hash = Column(String(16), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_versions_diagram_num", "diagram_id", "version_number"),
    )

    def to_dict(self):
        import json as _json
        return {
            "version_id": self.version_id,
            "version_number": self.version_number,
            "diagram_id": self.diagram_id,
            "created_by": self.created_by,
            "message": self.message,
            "content_hash": self.content_hash,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class VersionChangeRecord(Base):
    """Individual change within a version."""

    __tablename__ = "version_changes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version_id = Column(String(50), ForeignKey("architecture_versions.version_id"), nullable=False, index=True)
    change_type = Column(String(50), nullable=False)
    description = Column(Text, nullable=False)
    details = Column(Text, nullable=True)          # JSON-serialized
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self):
        import json as _json
        return {
            "version_id": self.version_id,
            "change_type": self.change_type,
            "description": self.description,
            "details": _json.loads(self.details) if self.details else {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
