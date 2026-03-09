"""
Role-Based Access Control (RBAC) and Multi-Tenant Isolation (#238).

Provides FastAPI dependencies for enforcing tenant boundaries and role levels
across all Archmorph API routes.
"""
from fastapi import Depends, HTTPException
from typing import List
from routers.auth import get_current_user
import logging

logger = logging.getLogger(__name__)

class RequireRole:
    """
    FastAPI Dependency to ensure the current authenticated user has at least one of the required roles.
    Super Admins ('super_admin') bypass this check automatically.
    """
    def __init__(self, required_roles: List[str]):
        self.required_roles = required_roles

    def __call__(self, current_user: dict = Depends(get_current_user)) -> dict:
        if current_user.get("authenticated") is False:
            raise HTTPException(status_code=401, detail="Authentication required for RBAC actions")
        
        user_roles = current_user.get("roles", ["user"])
        
        # Super admin always passes
        if "super_admin" in user_roles:
            return current_user
            
        if not any(role in self.required_roles for role in user_roles):
            logger.warning(f"RBAC Violation: User missing roles {self.required_roles}. Has: {user_roles}")
            raise HTTPException(
                status_code=403, 
                detail=f"Insufficient permissions. Required one of: {', '.join(self.required_roles)}"
            )
        return current_user


def get_tenant_id(current_user: dict = Depends(get_current_user)) -> str:
    """Extracts the tenant ID from the current user token default to 'default_tenant'."""
    return current_user.get("tenant_id", "default_tenant")


def enforce_tenant_isolation(target_tenant_id: str, current_user: dict):
    """
    Validates that the given user object belongs to the requested tenant.
    Should be called inside route handlers.
    """
    if current_user.get("authenticated") is False:
        raise HTTPException(status_code=401, detail="Authentication required for tenant isolation check")
        
    user_tenant = current_user.get("tenant_id", "default_tenant")
    user_roles = current_user.get("roles", [])
    
    # Super admins can explore cross-tenant
    if "super_admin" in user_roles:
        return True
        
    if user_tenant != target_tenant_id:
        logger.error(f"Tenant isolation breach attempted! User tenant: {user_tenant}, Target: {target_tenant_id}")
        raise HTTPException(
            status_code=403, 
            detail="Tenant isolation violation. You cannot access resources belonging to another organization."
        )
    return True
