"""
Role-Based Access Control (RBAC) and Multi-Tenant Isolation (#238).

Provides:
- In-memory org / membership / quota stores (thread-safe)
- Role hierarchy: owner > admin > member > viewer
- FastAPI dependencies: require_role, require_org_access, require_analysis_access
- Org-scoped quota enforcement
"""

import logging
import threading
import uuid
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any, Dict, List, Optional

from fastapi import Depends, Request
from error_envelope import ArchmorphException
from auth import get_user_from_request_headers, User

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Role hierarchy (higher value = more privilege)
# ─────────────────────────────────────────────────────────────

class OrgRole(IntEnum):
    VIEWER = 0
    MEMBER = 1
    ADMIN = 2
    OWNER = 3


ROLE_NAMES = {r.name.lower(): r for r in OrgRole}


def _parse_role(role: str) -> OrgRole:
    """Convert a role string to OrgRole, raising on unknown."""
    r = ROLE_NAMES.get(role.lower())
    if r is None:
        raise ArchmorphException(400, f"Unknown role: {role}")
    return r


# ─────────────────────────────────────────────────────────────
# In-memory stores (thread-safe)
# ─────────────────────────────────────────────────────────────

_store_lock = threading.Lock()

# org_id -> org dict
ORG_STORE: Dict[str, Dict[str, Any]] = {}

# org_id -> {user_id -> membership dict}
MEMBERSHIP_STORE: Dict[str, Dict[str, Dict[str, Any]]] = {}

# org_id -> quota tracking dict  {month_key -> count}
QUOTA_STORE: Dict[str, Dict[str, int]] = {}

# diagram_id -> {org_id, owner_user_id}
ANALYSIS_OWNER: Dict[str, Dict[str, str]] = {}


# Plan-based quota limits (analyses/month)
PLAN_QUOTAS: Dict[str, int] = {
    "free": 5,
    "pro": 100,
    "enterprise": -1,  # unlimited
}


def _month_key() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year}-{now.month:02d}"


# ─────────────────────────────────────────────────────────────
# Org helpers
# ─────────────────────────────────────────────────────────────

def create_org(name: str, plan: str, owner_user_id: str, owner_email: str) -> Dict[str, Any]:
    """Create an org and add the creator as owner."""
    org_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    org = {
        "org_id": org_id,
        "name": name,
        "plan": plan if plan in PLAN_QUOTAS else "free",
        "created_at": now,
        "updated_at": now,
        "is_active": True,
    }
    membership = {
        "user_id": owner_user_id,
        "email": owner_email,
        "role": OrgRole.OWNER.name.lower(),
        "joined_at": now,
    }
    with _store_lock:
        ORG_STORE[org_id] = org
        MEMBERSHIP_STORE[org_id] = {owner_user_id: membership}
        QUOTA_STORE[org_id] = {}
    return org


def get_org(org_id: str) -> Optional[Dict[str, Any]]:
    with _store_lock:
        return ORG_STORE.get(org_id)


def list_user_orgs(user_id: str) -> List[Dict[str, Any]]:
    with _store_lock:
        result = []
        for oid, members in MEMBERSHIP_STORE.items():
            if user_id in members:
                org = ORG_STORE.get(oid)
                if org:
                    result.append({**org, "role": members[user_id]["role"]})
        return result


def update_org(org_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    allowed = {"name", "plan"}
    with _store_lock:
        org = ORG_STORE.get(org_id)
        if not org:
            return None
        for k, v in updates.items():
            if k in allowed:
                org[k] = v
        org["updated_at"] = datetime.now(timezone.utc).isoformat()
        return dict(org)


def delete_org(org_id: str) -> bool:
    with _store_lock:
        if org_id not in ORG_STORE:
            return False
        del ORG_STORE[org_id]
        MEMBERSHIP_STORE.pop(org_id, None)
        QUOTA_STORE.pop(org_id, None)
        return True


# ─────────────────────────────────────────────────────────────
# Membership helpers
# ─────────────────────────────────────────────────────────────

def add_member(org_id: str, user_id: str, email: str, role: str) -> Dict[str, Any]:
    _parse_role(role)  # validate
    now = datetime.now(timezone.utc).isoformat()
    membership = {"user_id": user_id, "email": email, "role": role, "joined_at": now}
    with _store_lock:
        if org_id not in MEMBERSHIP_STORE:
            raise ArchmorphException(404, "Organization not found")
        MEMBERSHIP_STORE[org_id][user_id] = membership
    return membership


def list_members(org_id: str) -> List[Dict[str, Any]]:
    with _store_lock:
        members = MEMBERSHIP_STORE.get(org_id)
        if members is None:
            raise ArchmorphException(404, "Organization not found")
        return list(members.values())


def change_role(org_id: str, target_user_id: str, new_role: str) -> Dict[str, Any]:
    _parse_role(new_role)
    with _store_lock:
        members = MEMBERSHIP_STORE.get(org_id)
        if not members or target_user_id not in members:
            raise ArchmorphException(404, "Member not found")
        members[target_user_id]["role"] = new_role
        return dict(members[target_user_id])


def remove_member(org_id: str, target_user_id: str) -> bool:
    with _store_lock:
        members = MEMBERSHIP_STORE.get(org_id)
        if not members or target_user_id not in members:
            raise ArchmorphException(404, "Member not found")
        if members[target_user_id]["role"] == OrgRole.OWNER.name.lower():
            raise ArchmorphException(400, "Cannot remove the organization owner")
        del members[target_user_id]
        return True


def get_user_role_in_org(org_id: str, user_id: str) -> Optional[str]:
    with _store_lock:
        members = MEMBERSHIP_STORE.get(org_id, {})
        m = members.get(user_id)
        return m["role"] if m else None


# ─────────────────────────────────────────────────────────────
# Analysis ownership tracking
# ─────────────────────────────────────────────────────────────

def register_analysis(diagram_id: str, org_id: str, owner_user_id: str) -> None:
    with _store_lock:
        ANALYSIS_OWNER[diagram_id] = {"org_id": org_id, "owner_user_id": owner_user_id}


def get_analysis_owner(diagram_id: str) -> Optional[Dict[str, str]]:
    with _store_lock:
        return ANALYSIS_OWNER.get(diagram_id)


# ─────────────────────────────────────────────────────────────
# Quota helpers
# ─────────────────────────────────────────────────────────────

def check_org_quota(org_id: str) -> Dict[str, Any]:
    """Return quota status for the org's current month."""
    with _store_lock:
        org = ORG_STORE.get(org_id)
        if not org:
            raise ArchmorphException(404, "Organization not found")
        plan = org.get("plan", "free")
        limit = PLAN_QUOTAS.get(plan, 5)
        mk = _month_key()
        used = QUOTA_STORE.get(org_id, {}).get(mk, 0)
        unlimited = limit < 0
        return {
            "plan": plan,
            "limit": "unlimited" if unlimited else limit,
            "used": used,
            "remaining": "unlimited" if unlimited else max(0, limit - used),
            "allowed": unlimited or used < limit,
        }


def consume_org_quota(org_id: str) -> Dict[str, Any]:
    """Atomically check and increment quota. Returns quota status."""
    with _store_lock:
        org = ORG_STORE.get(org_id)
        if not org:
            raise ArchmorphException(404, "Organization not found")
        plan = org.get("plan", "free")
        limit = PLAN_QUOTAS.get(plan, 5)
        mk = _month_key()
        bucket = QUOTA_STORE.setdefault(org_id, {})
        used = bucket.get(mk, 0)
        unlimited = limit < 0
        if not unlimited and used >= limit:
            return {
                "plan": plan, "limit": limit, "used": used,
                "remaining": 0, "allowed": False,
            }
        bucket[mk] = used + 1
        new_used = used + 1
        return {
            "plan": plan,
            "limit": "unlimited" if unlimited else limit,
            "used": new_used,
            "remaining": "unlimited" if unlimited else max(0, limit - new_used),
            "allowed": True,
        }


# ─────────────────────────────────────────────────────────────
# FastAPI dependency: extract current user (optional auth)
# ─────────────────────────────────────────────────────────────

def get_current_user_optional(request: Request) -> Optional[User]:
    """Return User if authenticated, None otherwise."""
    return get_user_from_request_headers(dict(request.headers))


def get_current_user_required(request: Request) -> User:
    """Return User or 401."""
    user = get_user_from_request_headers(dict(request.headers))
    if not user:
        raise ArchmorphException(401, "Authentication required")
    return user


# ─────────────────────────────────────────────────────────────
# FastAPI dependencies: RBAC enforcement
# ─────────────────────────────────────────────────────────────

class RequireRole:
    """Dependency that checks the caller has at least ``min_role`` in the
    org identified by the ``org_id`` path parameter.

    Usage::

        @router.get("/api/orgs/{org_id}/settings",
                     dependencies=[Depends(RequireRole("admin"))])
    """

    def __init__(self, min_role):
        # Backward-compatible: accept a list of roles (legacy) or a single string.
        if isinstance(min_role, list):
            # Legacy callers pass e.g. ['admin', 'super_admin'] — use the lowest
            # privilege in the list as the minimum threshold.
            levels = [_parse_role(r) for r in min_role if r in ROLE_NAMES]
            self.min_level = min(levels) if levels else OrgRole.ADMIN
            self._legacy_mode = True
            self._legacy_roles = set(min_role)
        else:
            self.min_level = _parse_role(min_role)
            self._legacy_mode = False
            self._legacy_roles = set()

    def __call__(
        self,
        request: Request,
        org_id: str = None,
        user: User = Depends(get_current_user_required),
    ) -> User:
        # Legacy mode: check user.roles list directly (no org_id needed)
        if self._legacy_mode:
            user_roles = set(getattr(user, "roles", []))
            if "super_admin" in user_roles:
                return user
            if not user_roles & self._legacy_roles:
                raise ArchmorphException(
                    403,
                    f"Insufficient permissions. Required one of: {', '.join(self._legacy_roles)}",
                )
            return user

        # New mode: org-scoped RBAC
        if not org_id:
            raise ArchmorphException(400, "org_id path parameter required for role check")
        role_str = get_user_role_in_org(org_id, user.id)
        if role_str is None:
            raise ArchmorphException(403, "You are not a member of this organization")
        user_level = _parse_role(role_str)
        if user_level < self.min_level:
            logger.warning(
                "RBAC denied: user=%s role=%s required=%s org=%s",
                user.id, role_str, self.min_level.name.lower(), org_id,
            )
            raise ArchmorphException(
                403,
                f"Requires at least '{self.min_level.name.lower()}' role",
            )
        return user


def require_org_access(
    org_id: str,
    user: User = Depends(get_current_user_required),
) -> User:
    """Dependency: verify user belongs to the org (any role)."""
    role = get_user_role_in_org(org_id, user.id)
    if role is None:
        raise ArchmorphException(403, "You are not a member of this organization")
    return user


def require_analysis_access(
    diagram_id: str,
    user: User = Depends(get_current_user_required),
) -> User:
    """Dependency: verify user can access this analysis.

    Access is granted if:
    - The analysis has no registered owner (legacy / anonymous), OR
    - The user is a member of the owning org.
    """
    owner = get_analysis_owner(diagram_id)
    if owner is None:
        return user  # unregistered analysis — open access
    role = get_user_role_in_org(owner["org_id"], user.id)
    if role is None:
        raise ArchmorphException(403, "You do not have access to this analysis")
    return user


class RequireQuota:
    """Dependency that checks (and consumes) the org's monthly analysis quota.

    Attach to analysis-creation endpoints::

        @router.post("/api/orgs/{org_id}/analyze",
                      dependencies=[Depends(RequireQuota())])
    """

    def __call__(
        self,
        org_id: str,
        user: User = Depends(get_current_user_required),
    ) -> User:
        role = get_user_role_in_org(org_id, user.id)
        if role is None:
            raise ArchmorphException(403, "You are not a member of this organization")
        status = consume_org_quota(org_id)
        if not status["allowed"]:
            raise ArchmorphException(
                429,
                f"Monthly analysis quota exceeded ({status['used']}/{status['limit']}). "
                "Upgrade your plan for more.",
            )
        return user
