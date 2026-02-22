"""Multi-Tenancy database models (Issue #169).

Provides Organization, TeamMember, and Invitation models for
tenant isolation, RBAC, and data scoping.
"""

from sqlalchemy import Column, String, Integer, Text, DateTime, Boolean, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

import enum


class OrgRole(str, enum.Enum):
    """Roles within an organization."""
    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class InviteStatus(str, enum.Enum):
    """Invitation status."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    REVOKED = "revoked"


class Organization(Base):
    """Tenant — an isolated organization."""

    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(String(36), unique=True, nullable=False, index=True)  # UUID
    name = Column(String(200), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    plan = Column(String(20), nullable=False, default="free")  # free|pro|team|enterprise
    max_members = Column(Integer, nullable=False, default=5)
    max_analyses_per_month = Column(Integer, nullable=False, default=5)
    storage_prefix = Column(String(100), nullable=True)  # Blob storage container prefix
    settings = Column(Text, nullable=True)  # JSON-serialized org settings
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    members = relationship("TeamMember", back_populates="organization", cascade="all, delete-orphan")
    invitations = relationship("Invitation", back_populates="organization", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "org_id": self.org_id,
            "name": self.name,
            "slug": self.slug,
            "plan": self.plan,
            "max_members": self.max_members,
            "max_analyses_per_month": self.max_analyses_per_month,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TeamMember(Base):
    """User membership in an organization with role."""

    __tablename__ = "team_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(String(36), ForeignKey("organizations.org_id", ondelete="CASCADE"),
                    nullable=False, index=True)
    user_id = Column(String(100), nullable=False, index=True)  # External user ID (JWT sub)
    email = Column(String(255), nullable=False)
    display_name = Column(String(200), nullable=True)
    role = Column(String(20), nullable=False, default=OrgRole.VIEWER.value)
    is_active = Column(Boolean, nullable=False, default=True)
    joined_at = Column(DateTime(timezone=True), server_default=func.now())
    last_active_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    organization = relationship("Organization", back_populates="members")

    def to_dict(self):
        return {
            "id": self.id,
            "org_id": self.org_id,
            "user_id": self.user_id,
            "email": self.email,
            "display_name": self.display_name,
            "role": self.role,
            "is_active": self.is_active,
            "joined_at": self.joined_at.isoformat() if self.joined_at else None,
        }


class Invitation(Base):
    """Pending invitation to join an organization."""

    __tablename__ = "invitations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(String(36), ForeignKey("organizations.org_id", ondelete="CASCADE"),
                    nullable=False, index=True)
    email = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default=OrgRole.VIEWER.value)
    token = Column(String(64), unique=True, nullable=False, index=True)
    invited_by = Column(String(100), nullable=False)  # user_id of inviter
    status = Column(String(20), nullable=False, default=InviteStatus.PENDING.value)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    organization = relationship("Organization", back_populates="invitations")

    def to_dict(self):
        return {
            "id": self.id,
            "org_id": self.org_id,
            "email": self.email,
            "role": self.role,
            "status": self.status,
            "invited_by": self.invited_by,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
