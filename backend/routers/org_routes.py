"""
Organization management routes (#238).

CRUD for organizations, member management, and org-scoped audit logs.
All routes require authentication; role checks use RBAC dependencies.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from routers.shared import limiter
from error_envelope import ArchmorphException
from auth import User
from audit_logging import audit_logger, get_audit_logs
from rbac import (
    get_current_user_required,
    require_org_access,
    RequireRole,
    create_org,
    get_org,
    list_user_orgs,
    update_org,
    delete_org,
    add_member,
    list_members,
    change_role,
    remove_member,
    get_user_role_in_org,
    check_org_quota,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["organizations"])


# ─────────────────────────────────────────────────────────────
# Request / response models
# ─────────────────────────────────────────────────────────────

class CreateOrgRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    plan: str = Field("free", pattern=r"^(free|pro|enterprise)$")


class UpdateOrgRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    plan: Optional[str] = Field(None, pattern=r"^(free|pro|enterprise)$")


class AddMemberRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    role: str = Field("member", pattern=r"^(viewer|member|admin)$")


class ChangeRoleRequest(BaseModel):
    role: str = Field(..., pattern=r"^(viewer|member|admin)$")


# ─────────────────────────────────────────────────────────────
# Organization CRUD
# ─────────────────────────────────────────────────────────────

@router.post("/api/orgs")
@limiter.limit("10/minute")
async def create_organization(
    request: Request,
    body: CreateOrgRequest,
    user: User = Depends(get_current_user_required),
):
    """Create a new organization (caller becomes owner)."""
    org = create_org(
        name=body.name,
        plan=body.plan,
        owner_user_id=user.id,
        owner_email=user.email or "",
    )
    audit_logger.log_admin_action(
        action="org.create",
        user_id=user.id,
        details={"org_id": org["org_id"], "name": body.name, "plan": body.plan},
    )
    return org


@router.get("/api/orgs")
@limiter.limit("30/minute")
async def list_organizations(
    request: Request,
    user: User = Depends(get_current_user_required),
):
    """List organizations the current user belongs to."""
    return {"organizations": list_user_orgs(user.id)}


@router.get("/api/orgs/{org_id}")
@limiter.limit("30/minute")
async def get_organization(
    request: Request,
    org_id: str,
    user: User = Depends(require_org_access),
):
    """Get org details (requires membership)."""
    org = get_org(org_id)
    if not org:
        raise ArchmorphException(404, "Organization not found")
    role = get_user_role_in_org(org_id, user.id)
    quota = check_org_quota(org_id)
    return {**org, "role": role, "quota": quota}


@router.put("/api/orgs/{org_id}")
@limiter.limit("10/minute")
async def update_organization(
    request: Request,
    org_id: str,
    body: UpdateOrgRequest,
    user: User = Depends(RequireRole("admin")),
):
    """Update org name/plan (admin+ only)."""
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise ArchmorphException(400, "No fields to update")
    org = update_org(org_id, updates)
    if not org:
        raise ArchmorphException(404, "Organization not found")
    audit_logger.log_admin_action(
        action="org.update",
        user_id=user.id,
        details={"org_id": org_id, "updates": updates},
    )
    return org


@router.delete("/api/orgs/{org_id}")
@limiter.limit("5/minute")
async def delete_organization(
    request: Request,
    org_id: str,
    user: User = Depends(RequireRole("owner")),
):
    """Delete an org (owner only)."""
    if not delete_org(org_id):
        raise ArchmorphException(404, "Organization not found")
    audit_logger.log_admin_action(
        action="org.delete",
        user_id=user.id,
        details={"org_id": org_id},
    )
    return {"deleted": True}


# ─────────────────────────────────────────────────────────────
# Member management
# ─────────────────────────────────────────────────────────────

@router.post("/api/orgs/{org_id}/members")
@limiter.limit("20/minute")
async def invite_member(
    request: Request,
    org_id: str,
    body: AddMemberRequest,
    user: User = Depends(RequireRole("admin")),
):
    """Invite/add a member to the org (admin+ only).

    Uses the email as a provisional user_id until the invitee logs in.
    """
    member = add_member(
        org_id=org_id,
        user_id=body.email,  # provisional — replaced on first login
        email=body.email,
        role=body.role,
    )
    audit_logger.log_admin_action(
        action="member.add",
        user_id=user.id,
        details={"org_id": org_id, "email": body.email, "role": body.role},
    )
    return member


@router.get("/api/orgs/{org_id}/members")
@limiter.limit("30/minute")
async def get_members(
    request: Request,
    org_id: str,
    user: User = Depends(require_org_access),
):
    """List all members of the org."""
    return {"members": list_members(org_id)}


@router.put("/api/orgs/{org_id}/members/{user_id}")
@limiter.limit("10/minute")
async def update_member_role(
    request: Request,
    org_id: str,
    user_id: str,
    body: ChangeRoleRequest,
    user: User = Depends(RequireRole("admin")),
):
    """Change a member's role (admin+ only). Cannot promote to owner."""
    member = change_role(org_id, user_id, body.role)
    audit_logger.log_admin_action(
        action="member.role_change",
        user_id=user.id,
        details={"org_id": org_id, "target_user": user_id, "new_role": body.role},
    )
    return member


@router.delete("/api/orgs/{org_id}/members/{user_id}")
@limiter.limit("10/minute")
async def delete_member(
    request: Request,
    org_id: str,
    user_id: str,
    user: User = Depends(RequireRole("admin")),
):
    """Remove a member from the org (admin+ only). Cannot remove owner."""
    remove_member(org_id, user_id)
    audit_logger.log_admin_action(
        action="member.remove",
        user_id=user.id,
        details={"org_id": org_id, "target_user": user_id},
    )
    return {"removed": True}


# ─────────────────────────────────────────────────────────────
# Org audit log
# ─────────────────────────────────────────────────────────────

@router.get("/api/orgs/{org_id}/audit")
@limiter.limit("10/minute")
async def get_org_audit(
    request: Request,
    org_id: str,
    limit: int = 100,
    user: User = Depends(RequireRole("admin")),
):
    """Retrieve audit log entries scoped to this org (admin+ only)."""
    all_logs = get_audit_logs(limit=limit * 3)
    # Filter entries that mention this org_id in their details
    scoped = [
        entry for entry in all_logs
        if entry.get("details", {}).get("org_id") == org_id
    ][:limit]
    return {"audit_entries": scoped, "count": len(scoped)}


# ─────────────────────────────────────────────────────────────
# Quota info
# ─────────────────────────────────────────────────────────────

@router.get("/api/orgs/{org_id}/quota")
@limiter.limit("30/minute")
async def get_quota(
    request: Request,
    org_id: str,
    user: User = Depends(require_org_access),
):
    """Get current quota usage for the org."""
    return check_org_quota(org_id)
