from error_envelope import ArchmorphException
"""
Feature Flags API routes.

GET  /api/flags           — list all flags (public)
GET  /api/flags/{name}    — get a single flag (public)
PUT  /api/flags/{name}    — update a flag (admin only)
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from typing import List, Optional

from routers.shared import verify_admin_key
from feature_flags import get_feature_flags
from audit_logging import audit_logger, AuditEventType

router = APIRouter()


class FlagUpdateRequest(BaseModel):
    """Request body for updating a feature flag."""
    enabled: Optional[bool] = None
    description: Optional[str] = None
    rollout_percentage: Optional[int] = Field(default=None, ge=0, le=100)
    target_users: Optional[List[str]] = None
    target_environments: Optional[List[str]] = None


@router.get("/api/flags")
async def list_flags():
    """Return all feature flags."""
    ff = get_feature_flags()
    return {"flags": ff.get_all()}


@router.get("/api/flags/{name}")
async def get_flag(name: str):
    """Return a single feature flag by name."""
    ff = get_feature_flags()
    flag = ff.get_flag(name)
    if flag is None:
        raise ArchmorphException(status_code=404, detail=f"Flag '{name}' not found")
    return flag


@router.patch("/api/flags/{name}", dependencies=[Depends(verify_admin_key)])
async def update_flag(request: Request, name: str, data: FlagUpdateRequest):
    """Update a feature flag (admin only)."""
    ff = get_feature_flags()
    before = ff.get_flag(name)
    updates = data.model_dump(exclude_none=True)
    if not updates:
        raise ArchmorphException(status_code=400, detail="No updates provided")
    result = ff.update_flag(name, updates)
    if result is None:
        raise ArchmorphException(status_code=404, detail=f"Flag '{name}' not found")
    audit_logger.log_admin_action(
        endpoint=request.url.path,
        ip_address=request.client.host if request.client else None,
        details={
            "action": "feature_flag_update",
            "flag": name,
            "before": before,
            "after": result,
            "changed_fields": sorted(updates.keys()),
        },
        event_type=AuditEventType.ADMIN_CONFIG_CHANGE,
    )
    return result
