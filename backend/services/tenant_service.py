"""Multi-Tenancy Service Layer (Issue #169).

Handles organization CRUD, team member management, invitations,
RBAC enforcement, and tenant-scoped data isolation.
"""


import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models.tenant import OrgRole, InviteStatus
from repositories.tenant import OrganizationRepo, TeamMemberRepo, InvitationRepo

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# Plan limits
# ─────────────────────────────────────────────────────────
PLAN_LIMITS: Dict[str, Dict[str, int]] = {
    "free": {"max_members": 3, "max_analyses_per_month": 5},
    "team": {"max_members": 50, "max_analyses_per_month": 500},
    "enterprise": {"max_members": 10000, "max_analyses_per_month": 100000},
}

# RBAC permission matrix
ROLE_PERMISSIONS: Dict[str, set] = {
    OrgRole.OWNER.value: {
        "org:read", "org:update", "org:delete",
        "member:read", "member:invite", "member:remove", "member:change_role",
        "analysis:read", "analysis:create", "analysis:delete",
        "settings:read", "settings:update",
    },
    OrgRole.ADMIN.value: {
        "org:read", "org:update",
        "member:read", "member:invite", "member:remove",
        "analysis:read", "analysis:create", "analysis:delete",
        "settings:read", "settings:update",
    },
    OrgRole.EDITOR.value: {
        "org:read",
        "member:read",
        "analysis:read", "analysis:create",
        "settings:read",
    },
    OrgRole.VIEWER.value: {
        "org:read",
        "member:read",
        "analysis:read",
        "settings:read",
    },
}


def _slugify(name: str) -> str:
    """Convert org name to URL-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:80]


# ─────────────────────────────────────────────────────────
# Organization management
# ─────────────────────────────────────────────────────────
def create_organization(
    db: Session,
    name: str,
    owner_user_id: str,
    owner_email: str,
    plan: str = "free",
) -> Dict[str, Any]:
    """Create a new organization and add the creator as owner."""
    org_repo = OrganizationRepo(db)
    member_repo = TeamMemberRepo(db)

    org_id = str(uuid.uuid4())
    slug = _slugify(name)

    # Unique slug — append random suffix on collision
    while org_repo.get_by_slug(slug):
        slug = f"{slug}-{secrets.token_hex(3)}"

    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])

    org = org_repo.create(
        org_id=org_id,
        name=name,
        slug=slug,
        plan=plan,
        max_members=limits["max_members"],
        max_analyses_per_month=limits["max_analyses_per_month"],
    )

    member_repo.create(
        org_id=org_id,
        user_id=owner_user_id,
        email=owner_email,
        display_name=None,
        role=OrgRole.OWNER.value,
    )

    db.commit()
    logger.info("Created org %s (%s) with owner %s", str(org_id).replace('\n', '').replace('\r', ''), str(name).replace('\n', '').replace('\r', ''), str(owner_user_id).replace('\n', '').replace('\r', ''))
    return org.to_dict()


def get_organization(db: Session, org_id: str) -> Optional[Dict[str, Any]]:
    """Fetch organization by org_id."""
    org = OrganizationRepo(db).get_by_org_id(org_id)
    return org.to_dict() if org else None


def update_organization(
    db: Session,
    org_id: str,
    updates: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Update organization fields (name, plan, settings)."""
    repo = OrganizationRepo(db)
    org = repo.get_by_org_id(org_id)
    if not org:
        return None

    allowed = {"name", "plan", "settings", "is_active"}
    for key, val in updates.items():
        if key in allowed:
            setattr(org, key, val)

    # If plan changed, update limits
    if "plan" in updates and updates["plan"] in PLAN_LIMITS:
        limits = PLAN_LIMITS[updates["plan"]]
        org.max_members = limits["max_members"]
        org.max_analyses_per_month = limits["max_analyses_per_month"]

    db.commit()
    return org.to_dict()


def list_user_organizations(db: Session, user_id: str) -> List[Dict[str, Any]]:
    """Return all organizations a user belongs to."""
    member_repo = TeamMemberRepo(db)
    org_repo = OrganizationRepo(db)
    memberships = member_repo.get_user_orgs(user_id)
    result = []
    for m in memberships:
        org = org_repo.get_by_org_id(m.org_id)
        if org:
            entry = org.to_dict()
            entry["role"] = m.role
            result.append(entry)
    return result


# ─────────────────────────────────────────────────────────
# Team member management
# ─────────────────────────────────────────────────────────
def list_members(db: Session, org_id: str) -> List[Dict[str, Any]]:
    """List all active members of an organization."""
    members = TeamMemberRepo(db).get_members(org_id)
    return [m.to_dict() for m in members]


def change_member_role(
    db: Session,
    org_id: str,
    target_user_id: str,
    new_role: str,
) -> Optional[Dict[str, Any]]:
    """Change a member's role. Cannot demote last owner."""
    repo = TeamMemberRepo(db)
    member = repo.get_membership(org_id, target_user_id)
    if not member:
        return None

    # Protect last owner
    if member.role == OrgRole.OWNER.value and new_role != OrgRole.OWNER.value:
        owners = [m for m in repo.get_members(org_id) if m.role == OrgRole.OWNER.value]
        if len(owners) <= 1:
            raise ValueError("Cannot demote the last owner")

    member.role = new_role
    db.commit()
    return member.to_dict()


def remove_member(db: Session, org_id: str, target_user_id: str) -> bool:
    """Remove a member from the organization."""
    repo = TeamMemberRepo(db)
    member = repo.get_membership(org_id, target_user_id)
    if not member:
        return False

    if member.role == OrgRole.OWNER.value:
        owners = [m for m in repo.get_members(org_id) if m.role == OrgRole.OWNER.value]
        if len(owners) <= 1:
            raise ValueError("Cannot remove the last owner")

    member.is_active = False
    db.commit()
    return True


# ─────────────────────────────────────────────────────────
# Invitations
# ─────────────────────────────────────────────────────────
def create_invitation(
    db: Session,
    org_id: str,
    email: str,
    role: str,
    invited_by: str,
    ttl_hours: int = 72,
) -> Dict[str, Any]:
    """Create an invitation to join an organization."""
    org_repo = OrganizationRepo(db)
    member_repo = TeamMemberRepo(db)
    invite_repo = InvitationRepo(db)

    org = org_repo.get_by_org_id(org_id)
    if not org:
        raise ValueError("Organization not found")

    # Check member limit
    current = len(member_repo.get_members(org_id))
    pending = len(invite_repo.get_pending(org_id))
    if current + pending >= org.max_members:
        raise ValueError("Organization member limit reached")

    token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)

    invite = invite_repo.create(
        org_id=org_id,
        email=email,
        role=role,
        token=token,
        invited_by=invited_by,
        expires_at=expires_at,
    )
    db.commit()
    logger.info("Invitation created for %s to org %s", str(email).replace('\n', '').replace('\r', ''), str(org_id).replace('\n', '').replace('\r', ''))
    return invite.to_dict()


def accept_invitation(
    db: Session,
    token: str,
    user_id: str,
) -> Dict[str, Any]:
    """Accept a pending invitation and join the organization."""
    invite_repo = InvitationRepo(db)
    member_repo = TeamMemberRepo(db)

    invite = invite_repo.get_by_token(token)
    if not invite:
        raise ValueError("Invalid invitation token")
    if invite.status != InviteStatus.PENDING.value:
        raise ValueError(f"Invitation already {invite.status}")
    if invite.expires_at < datetime.now(timezone.utc):
        invite.status = InviteStatus.EXPIRED.value
        db.commit()
        raise ValueError("Invitation has expired")

    # Check if user already in org
    existing = member_repo.get_membership(invite.org_id, user_id)
    if existing and existing.is_active:
        raise ValueError("User is already a member of this organization")

    if existing:
        existing.is_active = True
        existing.role = invite.role
    else:
        member_repo.create(
            org_id=invite.org_id,
            user_id=user_id,
            email=invite.email,
            role=invite.role,
        )

    invite.status = InviteStatus.ACCEPTED.value
    db.commit()
    logger.info("User %s accepted invite to org %s", str(user_id).replace('\n', '').replace('\r', ''), str(invite.org_id).replace('\n', '').replace('\r', ''))
    return {"org_id": invite.org_id, "role": invite.role}


# ─────────────────────────────────────────────────────────
# RBAC helpers
# ─────────────────────────────────────────────────────────
def check_permission(
    db: Session,
    org_id: str,
    user_id: str,
    permission: str,
) -> bool:
    """Check if a user has a specific permission in an organization."""
    member = TeamMemberRepo(db).get_membership(org_id, user_id)
    if not member or not member.is_active:
        return False
    allowed = ROLE_PERMISSIONS.get(member.role, set())
    return permission in allowed


def get_user_role(db: Session, org_id: str, user_id: str) -> Optional[str]:
    """Get the user's role in an organization."""
    member = TeamMemberRepo(db).get_membership(org_id, user_id)
    if member and member.is_active:
        return member.role
    return None
