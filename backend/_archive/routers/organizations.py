"""Organization & Team endpoints for multi-tenancy (Issue #169).

Provides CRUD for organizations, member management, invitations,
and RBAC-checked access patterns.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field

from routers.shared import limiter, verify_api_key
from database import get_db
from services.tenant_service import (
    create_organization,
    get_organization,
    update_organization,
    list_user_organizations,
    list_members,
    change_member_role,
    remove_member,
    create_invitation,
    accept_invitation,
    check_permission,
    get_user_role,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ─────────────────────────────────────────────────────────
# Request / Response schemas
# ─────────────────────────────────────────────────────────
class CreateOrgRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    plan: str = Field("free", pattern="^(free|pro|team|enterprise)$")


class UpdateOrgRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=200)
    plan: Optional[str] = Field(None, pattern="^(free|pro|team|enterprise)$")
    settings: Optional[str] = None


class InviteMemberRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)
    role: str = Field("viewer", pattern="^(admin|editor|viewer)$")


class ChangeRoleRequest(BaseModel):
    role: str = Field(..., pattern="^(owner|admin|editor|viewer)$")


class AcceptInviteRequest(BaseModel):
    token: str = Field(..., min_length=10)


# ─────────────────────────────────────────────────────────
# Helper — extract user from request
# ─────────────────────────────────────────────────────────
def _get_user_id(request: Request) -> str:
    """Extract user_id from request state (set by auth middleware)."""
    user = getattr(request.state, "user", None)
    if user and hasattr(user, "id"):
        return user.id
    # Fallback: header-based for API-key auth
    return request.headers.get("X-User-Id", "anonymous")


def _get_user_email(request: Request) -> str:
    """Extract user email from request state."""
    user = getattr(request.state, "user", None)
    if user and hasattr(user, "email"):
        return user.email or ""
    return request.headers.get("X-User-Email", "")


# ─────────────────────────────────────────────────────────
# Organization CRUD
# ─────────────────────────────────────────────────────────
@router.post("/api/organizations", tags=["organizations"])
@limiter.limit("10/minute")
async def create_org(request: Request, body: CreateOrgRequest, _=Depends(verify_api_key)):
    """Create a new organization. Caller becomes owner."""
    user_id = _get_user_id(request)
    email = _get_user_email(request)
    db = next(get_db())
    try:
        org = create_organization(db, body.name, user_id, email, body.plan)
        return {"status": "created", "organization": org}
    except Exception as e:
        logger.error("Failed to create org: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@router.get("/api/organizations", tags=["organizations"])
@limiter.limit("30/minute")
async def list_orgs(request: Request, _=Depends(verify_api_key)):
    """List all organizations the authenticated user belongs to."""
    user_id = _get_user_id(request)
    db = next(get_db())
    try:
        orgs = list_user_organizations(db, user_id)
        return {"organizations": orgs}
    finally:
        db.close()


@router.get("/api/organizations/{org_id}", tags=["organizations"])
@limiter.limit("30/minute")
async def get_org(request: Request, org_id: str, _=Depends(verify_api_key)):
    """Get organization details. Requires org:read permission."""
    user_id = _get_user_id(request)
    db = next(get_db())
    try:
        if not check_permission(db, org_id, user_id, "org:read"):
            raise HTTPException(status_code=403, detail="Not a member of this organization")
        org = get_organization(db, org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        role = get_user_role(db, org_id, user_id)
        org["your_role"] = role
        return org
    finally:
        db.close()


@router.patch("/api/organizations/{org_id}", tags=["organizations"])
@limiter.limit("10/minute")
async def update_org(
    request: Request, org_id: str, body: UpdateOrgRequest, _=Depends(verify_api_key)
):
    """Update org settings. Requires org:update permission."""
    user_id = _get_user_id(request)
    db = next(get_db())
    try:
        if not check_permission(db, org_id, user_id, "org:update"):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        updates = body.dict(exclude_none=True)
        org = update_organization(db, org_id, updates)
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        return {"status": "updated", "organization": org}
    finally:
        db.close()


# ─────────────────────────────────────────────────────────
# Team Members
# ─────────────────────────────────────────────────────────
@router.get("/api/organizations/{org_id}/members", tags=["organizations"])
@limiter.limit("30/minute")
async def get_members(request: Request, org_id: str, _=Depends(verify_api_key)):
    """List org members. Requires member:read."""
    user_id = _get_user_id(request)
    db = next(get_db())
    try:
        if not check_permission(db, org_id, user_id, "member:read"):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        members = list_members(db, org_id)
        return {"members": members, "count": len(members)}
    finally:
        db.close()


@router.patch("/api/organizations/{org_id}/members/{target_user_id}/role", tags=["organizations"])
@limiter.limit("10/minute")
async def update_member_role(
    request: Request,
    org_id: str,
    target_user_id: str,
    body: ChangeRoleRequest,
    _=Depends(verify_api_key),
):
    """Change a member's role. Requires member:change_role."""
    user_id = _get_user_id(request)
    db = next(get_db())
    try:
        if not check_permission(db, org_id, user_id, "member:change_role"):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        result = change_member_role(db, org_id, target_user_id, body.role)
        if not result:
            raise HTTPException(status_code=404, detail="Member not found")
        return {"status": "updated", "member": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@router.delete("/api/organizations/{org_id}/members/{target_user_id}", tags=["organizations"])
@limiter.limit("10/minute")
async def delete_member(
    request: Request, org_id: str, target_user_id: str, _=Depends(verify_api_key)
):
    """Remove a member. Requires member:remove."""
    user_id = _get_user_id(request)
    db = next(get_db())
    try:
        if not check_permission(db, org_id, user_id, "member:remove"):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        success = remove_member(db, org_id, target_user_id)
        if not success:
            raise HTTPException(status_code=404, detail="Member not found")
        return {"status": "removed"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


# ─────────────────────────────────────────────────────────
# Invitations
# ─────────────────────────────────────────────────────────
@router.post("/api/organizations/{org_id}/invitations", tags=["organizations"])
@limiter.limit("10/minute")
async def invite_member(
    request: Request, org_id: str, body: InviteMemberRequest, _=Depends(verify_api_key)
):
    """Send an invitation. Requires member:invite."""
    user_id = _get_user_id(request)
    db = next(get_db())
    try:
        if not check_permission(db, org_id, user_id, "member:invite"):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        invite = create_invitation(db, org_id, body.email, body.role, user_id)
        return {"status": "invited", "invitation": invite}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@router.post("/api/invitations/accept", tags=["organizations"])
@limiter.limit("10/minute")
async def accept_invite(request: Request, body: AcceptInviteRequest, _=Depends(verify_api_key)):
    """Accept a pending invitation."""
    user_id = _get_user_id(request)
    db = next(get_db())
    try:
        result = accept_invitation(db, body.token, user_id)
        return {"status": "accepted", **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()
