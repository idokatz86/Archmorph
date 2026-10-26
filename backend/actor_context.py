"""Authenticated actor and tenant context for tenant-owned boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NewType

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from auth import User
from database import get_db
from error_envelope import ArchmorphException
from models.tenant import Organization, TeamMember
from routers.shared import require_authenticated_user
from services.tenant_service import ROLE_PERMISSIONS


TenantId = NewType("TenantId", str)


@dataclass(frozen=True)
class ActorContext:
    """Authenticated actor with an active, server-validated tenant membership."""

    actor_id: str
    tenant_id: TenantId
    roles: tuple[str, ...]


def require_actor_permission(actor: ActorContext, permission: str) -> None:
    """Require an organization permission from the canonical tenant role matrix."""
    if any(permission in ROLE_PERMISSIONS.get(role, set()) for role in actor.roles):
        return
    raise HTTPException(status_code=403, detail="Insufficient permissions")


def resolve_actor_context(user: User, db: Session) -> ActorContext:
    """Resolve the selected tenant from authenticated identity and active membership."""
    memberships = (
        db.query(TeamMember)
        .join(Organization, Organization.org_id == TeamMember.org_id)
        .filter(
            TeamMember.user_id == user.id,
            TeamMember.org_id == user.tenant_id,
            TeamMember.is_active.is_(True),
            Organization.is_active.is_(True),
        )
        .limit(2)
        .all()
    )
    if len(memberships) != 1:
        raise ArchmorphException(403, "Authenticated user has no active membership in the selected organization")

    membership = memberships[0]
    return ActorContext(
        actor_id=user.id,
        tenant_id=TenantId(membership.org_id),
        roles=(membership.role,),
    )


def require_actor_context(
    user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
) -> ActorContext:
    """FastAPI dependency for authenticated, tenant-owned operations."""
    return resolve_actor_context(user, db)
