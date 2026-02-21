"""
Feedback & NPS routes.
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any

from routers.shared import limiter
from feedback import (
    submit_nps, submit_feature_feedback,
    submit_bug_report as submit_feedback_bug_report,
)

router = APIRouter()


class NPSRequest(BaseModel):
    score: int
    follow_up: Optional[str] = None
    session_id: Optional[str] = None
    feature_context: Optional[str] = None


class FeatureFeedbackRequest(BaseModel):
    feature: str
    helpful: bool
    comment: Optional[str] = None
    session_id: Optional[str] = None


class BugReportRequest(BaseModel):
    description: str
    context: Optional[Dict[str, Any]] = None
    severity: str = "medium"
    session_id: Optional[str] = None


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
