"""
Feedback & NPS routes.
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from typing import Literal, Optional, Dict, Any

from routers.shared import limiter
from feedback import (
    submit_nps, submit_feature_feedback,
    submit_bug_report as submit_feedback_bug_report,
)

router = APIRouter()


# Issue #167 — Strict input validation on all feedback models
class NPSRequest(BaseModel):
    score: int = Field(..., ge=0, le=10, description="NPS score 0-10")
    follow_up: Optional[str] = Field(None, max_length=2000)
    session_id: Optional[str] = Field(None, max_length=128)
    feature_context: Optional[str] = Field(None, max_length=256)


class FeatureFeedbackRequest(BaseModel):
    feature: str = Field(..., min_length=1, max_length=128, pattern=r"^[\w\-. ]+$")
    helpful: bool
    comment: Optional[str] = Field(None, max_length=2000)
    session_id: Optional[str] = Field(None, max_length=128)


class BugReportRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=5000)
    context: Optional[Dict[str, Any]] = None
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    session_id: Optional[str] = Field(None, max_length=128)


@router.post("/api/feedback/nps")
@limiter.limit("10/minute")
async def submit_nps_feedback(request: Request, data: NPSRequest):
    """Submit NPS score (0-10) with optional follow-up."""
    return submit_nps(
        score=data.score,
        follow_up=data.follow_up,
        session_id=data.session_id,
        feature_context=data.feature_context
    )


@router.post("/api/feedback/feature")
@limiter.limit("20/minute")
async def submit_feature_feedback_endpoint(request: Request, data: FeatureFeedbackRequest):
    """Submit feature feedback (thumbs up/down)."""
    return submit_feature_feedback(
        feature=data.feature,
        helpful=data.helpful,
        comment=data.comment,
        session_id=data.session_id
    )


@router.post("/api/feedback/bug")
@limiter.limit("5/minute")
async def submit_bug_report_endpoint(request: Request, data: BugReportRequest):
    """Submit bug report with context."""
    return submit_feedback_bug_report(
        description=data.description,
        context=data.context,
        severity=data.severity,
        session_id=data.session_id
    )
