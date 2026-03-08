from error_envelope import ArchmorphException
"""
Roadmap — Version Timeline & Feature Requests.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, EmailStr
from typing import Optional
import asyncio

from routers.shared import limiter
from roadmap import (
    get_roadmap, get_release_by_version, submit_feature_request, submit_bug_report,
)
from usage_metrics import record_event

router = APIRouter()


@router.get("/api/roadmap")
async def roadmap():
    """
    Get the complete Archmorph roadmap with timeline.
    
    Returns all releases from Day 0 to current, plus planned features.
    """
    return get_roadmap()


@router.get("/api/roadmap/release/{version}")
async def roadmap_release(version: str):
    """Get details for a specific release version."""
    release = get_release_by_version(version)
    if not release:
        raise ArchmorphException(404, f"Release {version} not found")
    return release


class FeatureRequestPayload(BaseModel):
    """Feature request submission."""
    title: str = Field(..., min_length=5, max_length=200, description="Feature title")
    description: str = Field(..., min_length=20, max_length=2000, description="Detailed description")
    use_case: Optional[str] = Field(None, max_length=1000, description="Use case or problem solved")
    email: Optional[EmailStr] = Field(None, description="Contact email for follow-up")


@router.post("/api/roadmap/feature-request")
@limiter.limit("3/hour")
async def roadmap_feature_request(request: Request, payload: FeatureRequestPayload):
    """
    Submit a feature request.
    
    Creates a GitHub issue labeled as feature-request.
    """
    record_event("feature_requests", {"title": payload.title})
    result = await asyncio.to_thread(
        submit_feature_request,
        payload.title,
        payload.description,
        payload.use_case or "",
        payload.email,
    )
    if not result["success"]:
        raise ArchmorphException(500, result.get("error", "Failed to create feature request"))
    return result


class BugReportPayload(BaseModel):
    """Bug report submission."""
    title: str = Field(..., min_length=5, max_length=200, description="Bug title")
    description: str = Field(..., min_length=20, max_length=2000, description="Bug description")
    steps_to_reproduce: Optional[str] = Field(None, max_length=2000, description="Steps to reproduce")
    expected_behavior: Optional[str] = Field(None, max_length=500, description="Expected behavior")
    actual_behavior: Optional[str] = Field(None, max_length=500, description="Actual behavior")
    browser: Optional[str] = Field(None, max_length=100, description="Browser info")
    os_info: Optional[str] = Field(None, max_length=100, description="Operating system")
    email: Optional[EmailStr] = Field(None, description="Contact email for follow-up")


@router.post("/api/roadmap/bug-report")
@limiter.limit("5/hour")
async def roadmap_bug_report(request: Request, payload: BugReportPayload):
    """
    Submit a bug report.
    
    Creates a GitHub issue labeled as bug.
    """
    record_event("bug_reports", {"title": payload.title})
    result = await asyncio.to_thread(
        submit_bug_report,
        payload.title,
        payload.description,
        payload.steps_to_reproduce or "",
        payload.expected_behavior or "",
        payload.actual_behavior or "",
        payload.browser or "Unknown",
        payload.os_info or "Unknown",
        payload.email,
    )
    if not result["success"]:
        raise ArchmorphException(500, result.get("error", "Failed to create bug report"))
    return result
