from error_envelope import ArchmorphException
"""User Journey Analytics & Conversion Funnel REST endpoints."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Dict, List, Optional

from journey_analytics import (
    track_journey_event,
    set_user_segments,
    mark_drop_off,
    get_funnel_metrics,
    get_time_to_value,
    get_segment_analytics,
    create_experiment,
    assign_variant,
    record_experiment_conversion,
    get_experiment_results,
    list_experiments,
    stop_experiment,
    record_nps,
    get_nps_summary,
    get_journey_dashboard,
    FUNNEL_ORDER,
)

router = APIRouter(prefix="/api/journey", tags=["journey-analytics"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class TrackEventRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)
    event_name: str = Field(..., min_length=1)
    stage: str = Field(..., min_length=1)
    properties: Optional[Dict] = None
    duration_ms: float = 0.0


class SegmentRequest(BaseModel):
    company_size: Optional[str] = None
    cloud_provider: Optional[str] = None
    use_case: Optional[str] = None


class ExperimentCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = ""
    variants: List[str] = Field(..., min_length=2)
    traffic_split: Dict[str, float]
    metric: str = Field(..., min_length=1)


class AssignVariantRequest(BaseModel):
    user_id: str = Field(..., min_length=1)


class ConversionRequest(BaseModel):
    variant: str = Field(..., min_length=1)


class NPSRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    score: int = Field(..., ge=0, le=10)
    segment: Optional[str] = None
    comment: Optional[str] = None


# ---------------------------------------------------------------------------
# Journey tracking
# ---------------------------------------------------------------------------

@router.post("/events", summary="Track a journey event")
async def api_track_event(body: TrackEventRequest):
    """Record a user journey event (page view, action, transition)."""
    try:
        event = track_journey_event(
            session_id=body.session_id,
            user_id=body.user_id,
            event_name=body.event_name,
            stage=body.stage,
            properties=body.properties,
            duration_ms=body.duration_ms,
        )
        return {"status": "tracked", "event_id": event.id}
    except Exception as exc:
        raise ArchmorphException(status_code=400, detail=str(exc))


@router.post("/sessions/{session_id}/segments", summary="Set user segments")
async def api_set_segments(session_id: str, body: SegmentRequest):
    """Assign segmentation data to a journey session."""
    result = set_user_segments(
        session_id=session_id,
        company_size=body.company_size,
        cloud_provider=body.cloud_provider,
        use_case=body.use_case,
    )
    if result is None:
        raise ArchmorphException(status_code=404, detail="Session not found")
    return {"status": "updated", "segments": result}


@router.post("/sessions/{session_id}/drop-off", summary="Mark drop-off")
async def api_mark_drop_off(session_id: str):
    """Mark a session as dropped off at its last known stage."""
    stage = mark_drop_off(session_id)
    if stage is None:
        raise ArchmorphException(status_code=404, detail="Session not found")
    return {"status": "marked", "drop_off_stage": stage}


# ---------------------------------------------------------------------------
# Funnel analytics
# ---------------------------------------------------------------------------

@router.get("/funnel", summary="Funnel metrics")
async def api_funnel_metrics():
    """Get conversion funnel with drop-off rates per stage."""
    return get_funnel_metrics()


@router.get("/funnel/stages", summary="List funnel stages")
async def api_funnel_stages():
    """Return ordered list of funnel stages."""
    return {"stages": FUNNEL_ORDER}


@router.get("/time-to-value", summary="Time-to-value metrics")
async def api_time_to_value():
    """Get time-to-value statistics across user journeys."""
    return get_time_to_value()


@router.get("/segments", summary="Segment analytics")
async def api_segment_analytics(
    key: str = Query("company_size", description="Segment key to group by"),
):
    """Get analytics broken down by user segment."""
    return get_segment_analytics(segment_key=key)


# ---------------------------------------------------------------------------
# A/B experiments
# ---------------------------------------------------------------------------

@router.post("/experiments", summary="Create experiment")
async def api_create_experiment(body: ExperimentCreateRequest):
    """Create a new A/B test experiment."""
    try:
        exp = create_experiment(
            name=body.name,
            description=body.description,
            variants=body.variants,
            traffic_split=body.traffic_split,
            metric=body.metric,
        )
        return {"status": "created", "experiment_id": exp.id, "name": exp.name}
    except ValueError as exc:
        raise ArchmorphException(status_code=400, detail=str(exc))


@router.get("/experiments", summary="List experiments")
async def api_list_experiments(
    status: Optional[str] = Query(None, description="Filter by status"),
):
    """List all experiments, optionally filtered by status."""
    return {"experiments": list_experiments(status=status)}


@router.get("/experiments/{experiment_id}", summary="Experiment results")
async def api_experiment_results(experiment_id: str):
    """Get results for a specific experiment."""
    result = get_experiment_results(experiment_id)
    if result is None:
        raise ArchmorphException(status_code=404, detail="Experiment not found")
    return result


@router.post("/experiments/{experiment_id}/assign", summary="Assign variant")
async def api_assign_variant(experiment_id: str, body: AssignVariantRequest):
    """Assign a user to an experiment variant."""
    variant = assign_variant(experiment_id, body.user_id)
    if variant is None:
        raise ArchmorphException(status_code=404, detail="Experiment not found or inactive")
    return {"variant": variant}


@router.post("/experiments/{experiment_id}/convert", summary="Record conversion")
async def api_record_conversion(experiment_id: str, body: ConversionRequest):
    """Record a conversion for an experiment variant."""
    ok = record_experiment_conversion(experiment_id, body.variant)
    if not ok:
        raise ArchmorphException(status_code=404, detail="Experiment not found")
    return {"status": "recorded"}


@router.post("/experiments/{experiment_id}/stop", summary="Stop experiment")
async def api_stop_experiment(experiment_id: str):
    """Stop a running experiment."""
    ok = stop_experiment(experiment_id)
    if not ok:
        raise ArchmorphException(status_code=404, detail="Experiment not found")
    return {"status": "stopped"}


# ---------------------------------------------------------------------------
# NPS
# ---------------------------------------------------------------------------

@router.post("/nps", summary="Record NPS score")
async def api_record_nps(body: NPSRequest):
    """Record a Net Promoter Score response."""
    try:
        entry = record_nps(
            user_id=body.user_id,
            score=body.score,
            segment=body.segment,
            comment=body.comment,
        )
        return {"status": "recorded", "id": entry["id"]}
    except ValueError as exc:
        raise ArchmorphException(status_code=400, detail=str(exc))


@router.get("/nps", summary="NPS summary")
async def api_nps_summary(
    segment: Optional[str] = Query(None, description="Filter by segment"),
):
    """Get NPS summary with breakdown."""
    return get_nps_summary(segment=segment)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@router.get("/dashboard", summary="Journey dashboard")
async def api_journey_dashboard():
    """Aggregated journey analytics dashboard."""
    return get_journey_dashboard()
