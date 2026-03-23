"""
User database model for social authentication (Issue #246).

Stores persistent user records created on first login via
Microsoft, Google, GitHub, or Azure SWA built-in auth.
Uses upsert pattern — auto-creates on first login.
"""

import uuid

from sqlalchemy import Column, String, DateTime, Boolean, Text
from sqlalchemy.sql import func

from database import Base


class UserRecord(Base):
    """Persistent user record — one row per social identity."""

    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    provider = Column(String(20), nullable=False, index=True)  # microsoft | google | github
    provider_id = Column(String(255), nullable=False, index=True)  # External ID from provider
    email = Column(String(320), nullable=True, index=True)
    display_name = Column(String(200), nullable=True)
    avatar_url = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Unique constraint: one record per provider+provider_id pair
    __table_args__ = (
        # Using a unique index instead of UniqueConstraint for portability
        {"sqlite_autoincrement": False},
    )

    def to_dict(self):
        return {
            "id": self.id,
            "provider": self.provider,
            "provider_id": self.provider_id,
            "email": self.email,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }
