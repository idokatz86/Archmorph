"""
Architect Review Queue routes — Issue #1137.

Provides per-diagram review queue endpoints:
  GET  /api/diagrams/{id}/review-queue            — queue items + summary
  POST /api/diagrams/{id}/review-queue/{item_id}/disposition — set disposition
  GET  /api/diagrams/{id}/review-queue/summary     — summary only (for gating)

Dispositions are persisted in the diagram session under the key
``review_queue_dispositions`` as a dict mapping item_id → action payload.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from strict_models import StrictBaseModel
from pydantic import Field

from routers.shared import (
    SESSION_STORE,
    authorize_diagram_access,
    limiter,
    require_diagram_access,
    verify_api_key_or_user_session,
)
from error_envelope import ArchmorphException
from review_queue_builder import build_review_queue, queue_summary, apply_risk_annotations
from log_sanitizer import safe as _safe

logger = logging.getLogger(__name__)

router = APIRouter()

# Valid disposition actions
_VALID_ACTIONS = frozenset({"accept", "edit", "mark_risk", "exclude"})


class DispositionRequest(StrictBaseModel):
    """Body for a disposition decision on one review item."""

    action: str = Field(
        ...,
        max_length=20,
        description="One of: accept | edit | mark_risk | exclude",
    )
    edited_text: Optional[str] = Field(
        None,
        max_length=2000,
        description="Replacement text used when action is 'edit'.",
    )

# ─────────────────────────────────────────────────────────────────────────────
# GET /api/diagrams/{diagram_id}/review-queue
# ─────────────────────────────────────────────────────────────────────────────
@router.get(
    "/api/diagrams/{diagram_id}/review-queue",
    dependencies=[Depends(require_diagram_access)],
    tags=["review-queue"],
)
@limiter.limit("30/minute")
async def get_review_queue(
    request: Request,
    diagram_id: str,
    _auth: Any = Depends(verify_api_key_or_user_session),
) -> dict[str, Any]:
    """Return the architect review queue for a diagram.

    Items are built from the analysis result (low-confidence mappings,
    warnings, assumptions, compliance flags).  Saved dispositions are
    merged in so the client can restore UI state.
    """
    session = authorize_diagram_access(request, diagram_id, purpose="view review queue")
    items = build_review_queue(session)
    dispositions: dict[str, Any] = session.get("review_queue_dispositions") or {}
    summary = queue_summary(items, dispositions)

    # Attach disposition state to each item for the client
    hydrated = []
    for item in items:
        hydrated.append({
            **item,
            "disposition": dispositions.get(item["id"]),
        })

    return {
        "diagram_id": diagram_id,
        "items": hydrated,
        "summary": summary,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/diagrams/{diagram_id}/review-queue/summary
# ─────────────────────────────────────────────────────────────────────────────
@router.get(
    "/api/diagrams/{diagram_id}/review-queue/summary",
    dependencies=[Depends(require_diagram_access)],
    tags=["review-queue"],
)
@limiter.limit("60/minute")
async def get_review_queue_summary(
    request: Request,
    diagram_id: str,
    _auth: Any = Depends(verify_api_key_or_user_session),
) -> dict[str, Any]:
    """Lightweight gate-check endpoint.

    Returns the queue summary only (no item details) so the UI can decide
    whether to show a deliverables gate without fetching the full queue.
    """
    session = authorize_diagram_access(request, diagram_id, purpose="view review queue summary")
    items = build_review_queue(session)
    dispositions: dict[str, Any] = session.get("review_queue_dispositions") or {}
    summary = queue_summary(items, dispositions)
    return {"diagram_id": diagram_id, "summary": summary}


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/diagrams/{diagram_id}/review-queue/{item_id}/disposition
# ─────────────────────────────────────────────────────────────────────────────
@router.post(
    "/api/diagrams/{diagram_id}/review-queue/{item_id}/disposition",
    dependencies=[Depends(require_diagram_access)],
    tags=["review-queue"],
)
@limiter.limit("60/minute")
async def set_item_disposition(
    request: Request,
    diagram_id: str,
    item_id: str,
    body: DispositionRequest,
    _auth: Any = Depends(verify_api_key_or_user_session),
) -> dict[str, Any]:
    """Record an architect disposition on one review queue item.

    Persists the decision to the session store and returns the updated summary
    so the client can immediately refresh gate state.
    """
    if body.action not in _VALID_ACTIONS:
        raise ArchmorphException(
            status_code=422,
            detail=f"action must be one of {', '.join(sorted(_VALID_ACTIONS))}",
        )

    session = authorize_diagram_access(request, diagram_id, purpose="review queue disposition")

    items = build_review_queue(session)
    item_ids = {i["id"] for i in items}
    if item_id not in item_ids:
        raise ArchmorphException(status_code=404, detail="Review item not found")

    dispositions: dict[str, Any] = dict(session.get("review_queue_dispositions") or {})
    dispositions[item_id] = {
        "action": body.action,
        "edited_text": body.edited_text,
    }

    # Persist dispositions and, for mark_risk, inject risk annotations
    updated_session = dict(session)
    updated_session["review_queue_dispositions"] = dispositions
    if body.action == "mark_risk":
        updated_session = apply_risk_annotations(updated_session, dispositions)

    SESSION_STORE[diagram_id] = updated_session

    logger.info(
        "Review disposition set: diagram=%s item=%s action=%s",
        _safe(diagram_id),
        _safe(item_id),
        _safe(body.action),
    )

    summary = queue_summary(items, dispositions)
    return {
        "diagram_id": diagram_id,
        "item_id": item_id,
        "action": body.action,
        "summary": summary,
    }
