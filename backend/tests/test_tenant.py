"""
Archmorph — Tenant / Multi-Tenancy Unit Tests
Tests for models/tenant.py, services/tenant_service.py (Issue #169)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.tenant import Organization, TeamMember, Invitation, OrgRole, InviteStatus
from services.tenant_service import (
    PLAN_LIMITS,
    ROLE_PERMISSIONS,
)


# ====================================================================
# OrgRole enum
# ====================================================================

class TestOrgRole:
    def test_all_roles(self):
        expected = {"owner", "admin", "editor", "viewer"}
        actual = {r.value for r in OrgRole}
        assert expected == actual

    def test_owner_exists(self):
        assert OrgRole.OWNER.value == "owner"


# ====================================================================
# InviteStatus enum
# ====================================================================

class TestInviteStatus:
    def test_all_statuses(self):
        expected = {"pending", "accepted", "expired", "revoked"}
        actual = {s.value for s in InviteStatus}
        assert expected == actual


# ====================================================================
# PLAN_LIMITS
# ====================================================================

class TestPlanLimits:
    def test_plans_defined(self):
        assert "free" in PLAN_LIMITS
        assert "team" in PLAN_LIMITS
        assert "enterprise" in PLAN_LIMITS

    def test_free_limits(self):
        free = PLAN_LIMITS["free"]
        assert free["max_members"] >= 1
        assert free["max_analyses_per_month"] >= 1

    def test_enterprise_higher_than_free(self):
        assert PLAN_LIMITS["enterprise"]["max_members"] > PLAN_LIMITS["free"]["max_members"]
        assert PLAN_LIMITS["enterprise"]["max_analyses_per_month"] > PLAN_LIMITS["free"]["max_analyses_per_month"]


# ====================================================================
# ROLE_PERMISSIONS
# ====================================================================

class TestRolePermissions:
    def test_all_roles_have_permissions(self):
        for role in OrgRole:
            assert role.value in ROLE_PERMISSIONS, f"Missing permissions for {role.value}"

    def test_owner_has_all_permissions(self):
        owner_perms = ROLE_PERMISSIONS["owner"]
        admin_perms = ROLE_PERMISSIONS["admin"]
        assert len(owner_perms) >= len(admin_perms)

    def test_viewer_has_limited(self):
        viewer_perms = ROLE_PERMISSIONS["viewer"]
        owner_perms = ROLE_PERMISSIONS["owner"]
        assert len(viewer_perms) < len(owner_perms)


# ====================================================================
# check_permission
# ====================================================================

class TestCheckPermission:
    """Test RBAC by checking ROLE_PERMISSIONS directly (check_permission needs DB)."""

    def test_owner_can_invite(self):
        assert "member:invite" in ROLE_PERMISSIONS["owner"]

    def test_viewer_cannot_invite(self):
        assert "member:invite" not in ROLE_PERMISSIONS["viewer"]

    def test_unknown_role_returns_empty(self):
        perms = ROLE_PERMISSIONS.get("unknown_role", set())
        assert len(perms) == 0

    def test_editor_permissions_exist(self):
        assert len(ROLE_PERMISSIONS["editor"]) > 0


# ====================================================================
# Model to_dict
# ====================================================================

class TestModelToDict:
    def test_organization_has_to_dict(self):
        assert hasattr(Organization, "to_dict")

    def test_team_member_has_to_dict(self):
        assert hasattr(TeamMember, "to_dict")

    def test_invitation_has_to_dict(self):
        assert hasattr(Invitation, "to_dict")


# ====================================================================
# Model table names
# ====================================================================

class TestModelTables:
    def test_organization_table(self):
        assert Organization.__tablename__ is not None

    def test_team_member_table(self):
        assert TeamMember.__tablename__ is not None

    def test_invitation_table(self):
        assert Invitation.__tablename__ is not None
