from error_envelope import ArchmorphException
"""
AI cross-cloud mapping suggestion routes.

Split from diagrams.py for maintainability (#284).
"""

from fastapi import APIRouter, Request, Depends
from pydantic import Field, field_validator
from strict_models import StrictBaseModel
from typing import Optional
import asyncio
import logging

from routers.shared import limiter, verify_admin_key, verify_api_key
from routers.samples import get_or_recreate_session
from source_provider import normalize_source_provider
from usage_metrics import record_event
from ai_suggestion import (
    suggest_mapping,
    suggest_batch,
    build_dependency_graph,
    get_review_queue,
    review_suggestion,
    get_review_stats,
    get_suggestion_history,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class SourceProviderRequest(StrictBaseModel):
    source_provider: str = Field("aws", pattern="^(aws|gcp)$")

    @field_validator("source_provider", mode="before")
    @classmethod
    def normalize_provider(cls, value):
        return normalize_source_provider(value)


class SuggestMappingRequest(SourceProviderRequest):
    """Request body for single AI mapping suggestion."""
    source_service: str = Field(..., min_length=1, max_length=200)
    context_services: Optional[list] = None


class SuggestBatchRequest(SourceProviderRequest):
    """Request body for batch AI mapping suggestions."""
    services: list = Field(..., min_length=1, max_length=50)


class ReviewRequest(StrictBaseModel):
    """Request body for reviewing an AI mapping suggestion."""
    decision: str = Field(..., pattern="^(approved|rejected)$")
    reviewer: str = Field(..., min_length=1)
    override_azure_service: Optional[str] = None
    override_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    notes: Optional[str] = None


class GenerateRequest(SourceProviderRequest):
    """Request body for triggering AI suggestion generation."""
    source_service: str = Field(..., min_length=1, max_length=200)
    context_services: Optional[list] = None


class GenerateBatchRequest(SourceProviderRequest):
    """Request body for batch AI suggestion generation."""
    services: list = Field(..., min_length=1, max_length=50)


@router.post("/api/suggest/mapping", tags=["ai-suggestion"])
@limiter.limit("20/minute")
async def api_suggest_mapping(
    request: Request, body: SuggestMappingRequest, _=Depends(verify_api_key)
):
    """AI-powered Azure mapping suggestion for a single source service."""
    result = await asyncio.to_thread(
        suggest_mapping,
        body.source_service,
        body.source_provider,
        body.context_services,
    )
    record_event("ai_suggestion", {
        "source": body.source_service,
        "provider": body.source_provider,
        "confidence": result.get("confidence", 0),
    })
    return result


@router.post("/api/suggest/batch", tags=["ai-suggestion"])
@limiter.limit("5/minute")
async def api_suggest_batch(
    request: Request, body: SuggestBatchRequest, _=Depends(verify_api_key)
):
    """AI-powered batch mapping suggestion for multiple services."""
    results = await asyncio.to_thread(
        suggest_batch, body.services, body.source_provider
    )
    record_event("ai_suggestion_batch", {"count": len(results)})
    return {"suggestions": results, "count": len(results)}


@router.get("/api/diagrams/{diagram_id}/dependency-graph", tags=["ai-suggestion"])
@limiter.limit("20/minute")
async def api_dependency_graph(
    request: Request, diagram_id: str, _=Depends(verify_api_key)
):
    """Build a dependency graph from an existing analysis."""
    session = get_or_recreate_session(diagram_id)
    if not session:
        raise ArchmorphException(status_code=404, detail="Analysis not found")
    mappings = session.get("mappings", [])
    graph = build_dependency_graph(mappings)
    return {"diagram_id": diagram_id, **graph}


@router.get("/api/admin/suggestions/queue", tags=["ai-suggestion"])
@limiter.limit("30/minute")
async def api_review_queue(
    request: Request, status: Optional[str] = None, _=Depends(verify_admin_key)
):
    """Get the admin review queue for AI mapping suggestions."""
    items = get_review_queue(status=status)
    stats = get_review_stats()
    return {"queue": items, "stats": stats}


@router.post("/api/admin/suggestions/{suggestion_id}/review", tags=["ai-suggestion"])
@limiter.limit("20/minute")
async def api_review_suggestion(
    request: Request,
    suggestion_id: str,
    body: ReviewRequest,
    _=Depends(verify_admin_key),
):
    """Approve or reject an AI mapping suggestion."""
    result = review_suggestion(
        suggestion_id=suggestion_id,
        decision=body.decision,
        reviewer=body.reviewer,
        override_azure_service=body.override_azure_service,
        override_confidence=body.override_confidence,
        notes=body.notes,
    )
    if not result:
        raise ArchmorphException(status_code=404, detail="Suggestion not found")
    return {"status": body.decision, "suggestion": result}


# ─────────────────────────────────────────────────────────
# Issue #230 — Admin suggestion management routes
# ─────────────────────────────────────────────────────────


@router.post("/api/admin/suggestions/generate", tags=["ai-suggestion"])
@limiter.limit("10/minute")
async def api_generate_suggestion(
    request: Request, body: GenerateRequest, _=Depends(verify_admin_key)
):
    """Trigger AI suggestion generation for a single service or with context."""
    result = await asyncio.to_thread(
        suggest_mapping,
        body.source_service,
        body.source_provider,
        body.context_services,
    )
    record_event("ai_suggestion_generate", {
        "source": body.source_service,
        "provider": body.source_provider,
        "confidence": result.get("confidence", 0),
        "review_status": result.get("review_status", ""),
    })
    return result


@router.post("/api/admin/suggestions/generate/batch", tags=["ai-suggestion"])
@limiter.limit("3/minute")
async def api_generate_batch(
    request: Request, body: GenerateBatchRequest, _=Depends(verify_admin_key)
):
    """Trigger AI suggestion generation for multiple services."""
    results = await asyncio.to_thread(
        suggest_batch, body.services, body.source_provider
    )
    record_event("ai_suggestion_generate_batch", {"count": len(results)})
    return {"suggestions": results, "count": len(results)}


@router.get("/api/admin/suggestions/pending", tags=["ai-suggestion"])
@limiter.limit("30/minute")
async def api_pending_suggestions(
    request: Request, _=Depends(verify_admin_key)
):
    """List pending suggestions awaiting admin review."""
    items = get_review_queue(status="pending")
    return {"pending": items, "count": len(items)}


@router.get("/api/admin/suggestions/history", tags=["ai-suggestion"])
@limiter.limit("30/minute")
async def api_suggestion_history(
    request: Request,
    decision: Optional[str] = None,
    limit: int = 100,
    _=Depends(verify_admin_key),
):
    """History of all suggestions with their review decisions."""
    items = get_suggestion_history(limit=limit, decision_filter=decision)
    return {"history": items, "count": len(items)}


@router.get("/api/admin/suggestions/stats", tags=["ai-suggestion"])
@limiter.limit("30/minute")
async def api_suggestion_stats(
    request: Request, _=Depends(verify_admin_key)
):
    """Accuracy statistics: approved vs rejected ratio, avg confidence."""
    stats = get_review_stats()
    return stats
