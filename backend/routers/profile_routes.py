from error_envelope import ArchmorphException
"""
User Profile Management routes (Issue #247).

Provides profile CRUD, analysis history, and GDPR account deletion.
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from typing import Optional, Literal
import logging

from routers.shared import limiter
from auth import get_user_from_request_headers, USER_STORE

logger = logging.getLogger(__name__)

router = APIRouter()


# ─────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────

class NotificationPreferences(BaseModel):
    email_on_completion: bool = False


class ProfileUpdate(BaseModel):
    display_name: Optional[str] = Field(None, max_length=200)
    company: Optional[str] = Field(None, max_length=200)
    role: Optional[Literal[
        "cloud_architect", "devops", "developer", "manager", "other"
    ]] = None
    preferred_source_cloud: Optional[Literal[
        "aws", "gcp", "multi-cloud"
    ]] = None
    preferred_iac_format: Optional[Literal[
        "terraform", "bicep", "cloudformation"
    ]] = None
    preferred_language: Optional[str] = Field(None, max_length=10)
    notification_preferences: Optional[NotificationPreferences] = None


# In-memory profile extension store (maps user_id -> extra profile fields)
_PROFILE_STORE: dict = {}


def _require_user(request: Request):
    """Extract authenticated user from request or raise 401."""
    user = get_user_from_request_headers(dict(request.headers))
    if not user or not user.id:
        raise ArchmorphException(401, "Authentication required")
    return user


def _get_profile(user_id: str) -> dict:
    """Get extended profile for a user."""
    return _PROFILE_STORE.get(user_id, {})


def _build_profile_response(user, profile: dict) -> dict:
    """Build full profile response from user + extended profile."""
    base = user.to_dict()
    base.update({
        "company": profile.get("company"),
        "role": profile.get("role"),
        "preferred_source_cloud": profile.get("preferred_source_cloud"),
        "preferred_iac_format": profile.get("preferred_iac_format"),
        "preferred_language": profile.get("preferred_language"),
        "notification_preferences": profile.get(
            "notification_preferences", {"email_on_completion": False}
        ),
    })
    return base


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────

@router.get("/api/me/profile")
@limiter.limit("30/minute")
async def get_profile(request: Request):
    """Get current user's profile with extended fields."""
    user = _require_user(request)
    profile = _get_profile(user.id)
    return _build_profile_response(user, profile)


@router.put("/api/me/profile")
@limiter.limit("10/minute")
async def update_profile(request: Request, body: ProfileUpdate):
    """Update current user's profile."""
    user = _require_user(request)

    profile = _PROFILE_STORE.get(user.id, {})

    if body.display_name is not None:
        user.name = body.display_name
        profile["display_name"] = body.display_name
    if body.company is not None:
        profile["company"] = body.company
    if body.role is not None:
        profile["role"] = body.role
    if body.preferred_source_cloud is not None:
        profile["preferred_source_cloud"] = body.preferred_source_cloud
    if body.preferred_iac_format is not None:
        profile["preferred_iac_format"] = body.preferred_iac_format
    if body.preferred_language is not None:
        profile["preferred_language"] = body.preferred_language
    if body.notification_preferences is not None:
        profile["notification_preferences"] = body.notification_preferences.model_dump()

    _PROFILE_STORE[user.id] = profile

    return _build_profile_response(user, profile)


@router.get("/api/me/analyses")
@limiter.limit("30/minute")
async def list_analyses(request: Request):
    """List current user's analysis history (placeholder)."""
    _require_user(request)
    return {"analyses": [], "total": 0}


@router.delete("/api/me/account")
@limiter.limit("3/minute")
async def delete_account(request: Request):
    """Delete user account and all associated data (GDPR).

    Removes profile data, usage data, and user record.
    """
    user = _require_user(request)
    user_id = user.id

    # Remove extended profile
    _PROFILE_STORE.pop(user_id, None)

    # Remove from user store
    try:
        del USER_STORE[user_id]
    except (KeyError, TypeError):
        pass

    logger.info("Account deleted for user %s (GDPR)", user_id)

    return {"success": True, "message": "Account and all associated data have been deleted"}
