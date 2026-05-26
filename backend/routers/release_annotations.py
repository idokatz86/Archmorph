"""
Release annotation routes — enterprise readiness track.

Records deploy, traffic-shift, and rollback events as telemetry annotations so
that observability dashboards (Azure Monitor Workbooks, Application Insights)
can overlay deployment events on latency and error-rate charts.

Annotations are:
- Emitted as OpenTelemetry span events and in-memory observability counters
  (visible in the admin monitoring dashboard without a live App Insights instance).
- Stored in-process with a bounded TTL ring so recent annotations are queryable
  via GET /api/admin/release-annotations without external dependencies.
- Protected by the admin API key so only CI/CD pipelines can write them.
"""

import logging
import threading
import time
import uuid
from collections import deque
from typing import Any, Deque, Dict, Literal, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import Field

from log_sanitizer import safe
from observability import increment_counter, trace_span
from routers.shared import verify_admin_key
from strict_models import StrictBaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/release-annotations", tags=["release-annotations"])

# ── In-process annotation ring buffer (max 200 entries, ~30 days of daily deploys) ──
_ANNOTATION_MAXLEN = 200
_annotations: Deque[Dict[str, Any]] = deque(maxlen=_ANNOTATION_MAXLEN)
_annotations_lock = threading.Lock()

AnnotationKind = Literal["deploy", "traffic_shift", "rollback", "config_change"]


# ─────────────────────────────────────────────────────────────
# Request / response models
# ─────────────────────────────────────────────────────────────

class ReleaseAnnotationRequest(StrictBaseModel):
    """Body for POST /api/admin/release-annotations.

    Strict validation:
    - ``kind`` — constrained to known annotation types.
    - ``revision``   — commit SHA or image tag; 1-200 chars.
    - ``environment`` — target environment label; 1-64 chars.
    - ``description`` — human-readable note; max 500 chars.
    - ``actor``       — CI principal or GitHub actor; max 200 chars.
    - ``run_url``     — GitHub Actions run URL for traceability (optional).
    """

    kind: AnnotationKind = Field(..., description="Annotation kind")
    revision: str = Field(..., min_length=1, max_length=200, description="Commit SHA or image tag")
    environment: str = Field(..., min_length=1, max_length=64, description="Target environment")
    description: str = Field("", max_length=500, description="Human-readable annotation note")
    actor: str = Field("ci", min_length=1, max_length=200, description="CI principal or GitHub actor")
    run_url: Optional[str] = Field(None, max_length=500, description="GitHub Actions run URL")


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_release_annotation(
    body: ReleaseAnnotationRequest,
    _auth=Depends(verify_admin_key),
):
    """Record a release annotation in telemetry and the in-process ring buffer.

    Emits an OTel span event (surfaced in Azure Monitor Application Map and
    workbook timelines when ``APPLICATIONINSIGHTS_CONNECTION_STRING`` is set)
    and increments a counter metric so dashboards show deploy frequency.

    Returns the created annotation record with its generated ``annotation_id``.
    """
    annotation_id = f"ann-{uuid.uuid4().hex[:16]}"
    ts = time.time()

    record: Dict[str, Any] = {
        "annotation_id": annotation_id,
        "kind": body.kind,
        "revision": body.revision,
        "environment": body.environment,
        "description": body.description,
        "actor": body.actor,
        "run_url": body.run_url,
        "recorded_at": ts,
    }

    # ── Persist to ring buffer ───────────────────────────────
    with _annotations_lock:
        _annotations.append(record)

    # ── Emit OTel span event ─────────────────────────────────
    try:
        with trace_span(
            "release.annotation",
            attributes={
                "annotation.kind": body.kind,
                "annotation.environment": body.environment,
                "annotation.revision": body.revision,
                "annotation.actor": body.actor,
            },
        ):
            pass  # The span is the event; duration is intentionally near-zero.
    except Exception:
        pass  # Never let telemetry failures block the response.

    # ── Emit counter metric ──────────────────────────────────
    increment_counter(
        "release.annotation",
        tags={"kind": body.kind, "environment": body.environment},
    )

    logger.info(
        "Release annotation recorded: kind=%s rev=%s env=%s actor=%s id=%s",
        safe(body.kind),
        safe(body.revision),
        safe(body.environment),
        safe(body.actor),
        safe(annotation_id),
    )

    return JSONResponse(content=record, status_code=201)


@router.get("")
async def list_release_annotations(
    _auth=Depends(verify_admin_key),
    environment: Optional[str] = None,
    kind: Optional[AnnotationKind] = None,
    limit: int = 50,
):
    """List recent release annotations from the in-process ring buffer.

    Supports optional ``environment`` and ``kind`` filters.  Returns the most
    recent ``limit`` annotations (max 200) in reverse-chronological order.
    """
    limit = min(max(1, limit), _ANNOTATION_MAXLEN)

    with _annotations_lock:
        items = list(_annotations)

    # Apply filters
    if environment:
        items = [a for a in items if a["environment"] == environment]
    if kind:
        items = [a for a in items if a["kind"] == kind]

    # Most recent first
    items.sort(key=lambda a: a["recorded_at"], reverse=True)
    items = items[:limit]

    return JSONResponse(content={"annotations": items, "total": len(items)})
