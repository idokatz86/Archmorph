"""Compatibility authorization dependencies for legacy model-registry routes.

Durable organization membership lives in PostgreSQL (``models.tenant`` and
``services.tenant_service``). Diagram ownership lives on tenant-scoped durable
analysis records and is enforced by ``routers.shared.authorize_diagram_access``.

The former in-memory organization, membership, quota, and analysis-owner stores
were not imported by active routes and were removed by issue #1237. This module
keeps only the two dependency symbols still used by the model registry and its
compatibility tests.
"""

from typing import Iterable

from fastapi import Depends, Request

from auth import User, get_user_from_request_headers
from error_envelope import ArchmorphException


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
    """Require one of the legacy token roles used by model-admin routes.

    Organization-scoped authorization must use the durable tenant service; this
    compatibility dependency intentionally does not maintain its own RBAC state.
    """

    def __init__(self, roles: str | Iterable[str]):
        self._roles = {roles} if isinstance(roles, str) else set(roles)

    def __call__(
        self,
        org_id: str = None,
        user: User = Depends(get_current_user_required),
    ) -> User:
        del org_id  # compatibility-only query parameter; no in-memory org state
        user_roles = set(getattr(user, "roles", []))
        if "super_admin" in user_roles or user_roles & self._roles:
            return user
        raise ArchmorphException(
            403,
            f"Insufficient permissions. Required one of: {', '.join(sorted(self._roles))}",
        )
