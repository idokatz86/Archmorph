"""
User Journey Analytics & Conversion Funnel optimization.

Tracks complete user sessions, identifies drop-off points, measures
conversion funnels (free → pro → enterprise), provides user segmentation,
and supports A/B testing experiments.
"""

import hashlib
import json
import logging
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("journey_analytics")

# ---------------------------------------------------------------------------
# Funnel stages
# ---------------------------------------------------------------------------

class FunnelStage(str, Enum):
    LANDING = "landing"
    SIGNUP = "signup"
    FIRST_UPLOAD = "first_upload"
    FIRST_ANALYSIS = "first_analysis"
    EXPLORE_RESULTS = "explore_results"
    GENERATE_IAC = "generate_iac"
    EXPORT = "export"
    RETURN_VISIT = "return_visit"
    UPGRADE_VIEW = "upgrade_view"
    UPGRADE_COMPLETE = "upgrade_complete"


FUNNEL_ORDER: List[str] = [s.value for s in FunnelStage]

# ---------------------------------------------------------------------------
# User segments
# ---------------------------------------------------------------------------

class UserSegment(str, Enum):
    STARTUP = "startup"
    SMB = "smb"
    ENTERPRISE = "enterprise"
    FREELANCER = "freelancer"
    EDUCATION = "education"


class CloudSegment(str, Enum):
    AWS_PRIMARY = "aws_primary"
    GCP_PRIMARY = "gcp_primary"
    MULTI_CLOUD = "multi_cloud"
    UNKNOWN = "unknown"


class UseCaseSegment(str, Enum):
    MIGRATION = "migration"
    MODERNIZATION = "modernization"
    COST_OPTIMIZATION = "cost_optimization"
    COMPLIANCE = "compliance"
    DOCUMENTATION = "documentation"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class JourneyEvent:
    id: str
    session_id: str
    user_id: str
    event_name: str
    stage: str
    timestamp: str
    properties: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class UserJourney:
    session_id: str
    user_id: str
    started_at: str
    last_activity: str
    events: List[JourneyEvent] = field(default_factory=list)
    stages_reached: List[str] = field(default_factory=list)
    furthest_stage: str = "landing"
    converted: bool = False
    dropped_off_at: Optional[str] = None
    segments: Dict[str, str] = field(default_factory=dict)
    total_duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "started_at": self.started_at,
            "last_activity": self.last_activity,
            "event_count": len(self.events),
            "stages_reached": self.stages_reached,
            "furthest_stage": self.furthest_stage,
            "converted": self.converted,
            "dropped_off_at": self.dropped_off_at,
            "segments": self.segments,
            "total_duration_ms": self.total_duration_ms,
        }


@dataclass
class ABExperiment:
    id: str
    name: str
    description: str
    variants: List[str]
    traffic_split: Dict[str, float]
    metric: str
    status: str = "active"
    created_at: str = ""
    results: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# In-memory store (thread-safe)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_journeys: Dict[str, UserJourney] = {}  # session_id → journey
_user_journeys: Dict[str, List[str]] = defaultdict(list)  # user_id → [session_ids]
_experiments: Dict[str, ABExperiment] = {}
_funnel_counts: Dict[str, int] = defaultdict(int)  # stage → count
_drop_off_counts: Dict[str, int] = defaultdict(int)  # stage → drop-off count
_conversion_events: List[Dict[str, Any]] = []
_MAX_JOURNEYS = 50000
_MAX_CONVERSIONS = 10000


# ---------------------------------------------------------------------------
# Journey tracking
# ---------------------------------------------------------------------------

def track_journey_event(
    session_id: str,
    user_id: str,
    event_name: str,
    stage: str,
    properties: Optional[Dict[str, Any]] = None,
    duration_ms: float = 0.0,
) -> JourneyEvent:
    """Track a user journey event."""
    now = datetime.now(timezone.utc).isoformat()

    event = JourneyEvent(
        id=f"je-{uuid.uuid4().hex[:12]}",
        session_id=session_id,
        user_id=user_id,
        event_name=event_name,
        stage=stage,
        timestamp=now,
        properties=properties or {},
        duration_ms=duration_ms,
    )

    with _lock:
        # Get or create journey
        if session_id not in _journeys:
            _journeys[session_id] = UserJourney(
                session_id=session_id,
                user_id=user_id,
                started_at=now,
                last_activity=now,
            )
            _user_journeys[user_id].append(session_id)

            # Evict oldest if over limit
            if len(_journeys) > _MAX_JOURNEYS:
                oldest_key = next(iter(_journeys))
                del _journeys[oldest_key]

        journey = _journeys[session_id]
        journey.events.append(event)
        journey.last_activity = now
        journey.total_duration_ms += duration_ms

        # Update stages
        if stage not in journey.stages_reached:
            journey.stages_reached.append(stage)
            _funnel_counts[stage] = _funnel_counts.get(stage, 0) + 1

        # Update furthest stage
        if stage in FUNNEL_ORDER:
            current_idx = FUNNEL_ORDER.index(journey.furthest_stage) if journey.furthest_stage in FUNNEL_ORDER else -1
            new_idx = FUNNEL_ORDER.index(stage)
            if new_idx > current_idx:
                journey.furthest_stage = stage

        # Check conversion
        if stage == FunnelStage.UPGRADE_COMPLETE:
            journey.converted = True
            _conversion_events.append({
                "user_id": user_id,
                "session_id": session_id,
                "timestamp": now,
                "properties": properties or {},
            })
            if len(_conversion_events) > _MAX_CONVERSIONS:
                _conversion_events.pop(0)

    return event


def set_user_segments(
    session_id: str,
    company_size: Optional[str] = None,
    cloud_provider: Optional[str] = None,
    use_case: Optional[str] = None,
) -> Optional[Dict[str, str]]:
    """Set segmentation data for a user journey."""
    with _lock:
        journey = _journeys.get(session_id)
        if not journey:
            return None

        if company_size:
            journey.segments["company_size"] = company_size
        if cloud_provider:
            journey.segments["cloud_provider"] = cloud_provider
        if use_case:
            journey.segments["use_case"] = use_case

        return journey.segments


def mark_drop_off(session_id: str) -> Optional[str]:
    """Mark a journey as dropped off at its current furthest stage."""
    with _lock:
        journey = _journeys.get(session_id)
        if not journey or journey.converted:
            return None

        journey.dropped_off_at = journey.furthest_stage
        _drop_off_counts[journey.furthest_stage] = _drop_off_counts.get(journey.furthest_stage, 0) + 1
        return journey.furthest_stage


# ---------------------------------------------------------------------------
# Funnel analysis
# ---------------------------------------------------------------------------

def get_funnel_metrics() -> Dict[str, Any]:
    """Get conversion funnel metrics across all journeys."""
    with _lock:
        journeys = list(_journeys.values())
        counts = dict(_funnel_counts)
        drops = dict(_drop_off_counts)

    total = len(journeys)
    if total == 0:
        return {
            "total_journeys": 0,
            "stages": [],
            "overall_conversion_rate": 0.0,
        }

    converted = sum(1 for j in journeys if j.converted)

    stages = []
    for i, stage in enumerate(FUNNEL_ORDER):
        reached = counts.get(stage, 0)
        dropped = drops.get(stage, 0)
        prev_reached = counts.get(FUNNEL_ORDER[i - 1], total) if i > 0 else total

        stages.append({
            "stage": stage,
            "reached": reached,
            "dropped_off": dropped,
            "conversion_from_previous": round(reached / prev_reached * 100, 1) if prev_reached > 0 else 0.0,
            "conversion_from_start": round(reached / total * 100, 1) if total > 0 else 0.0,
        })

    return {
        "total_journeys": total,
        "total_converted": converted,
        "overall_conversion_rate": round(converted / total * 100, 2) if total else 0.0,
        "stages": stages,
        "biggest_drop_off": max(drops, key=drops.get) if drops else None,
    }


def get_time_to_value() -> Dict[str, Any]:
    """Measure time from first visit to key milestones."""
    with _lock:
        journeys = list(_journeys.values())

    if not journeys:
        return {"message": "No journey data available"}

    milestones = {
        "first_analysis": [],
        "generate_iac": [],
        "export": [],
        "upgrade_complete": [],
    }

    for journey in journeys:
        if len(journey.events) < 2:
            continue

        start_time = journey.events[0].timestamp
        for event in journey.events[1:]:
            if event.stage in milestones:
                # Calculate time delta in minutes
                try:
                    t_start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                    t_event = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
                    delta_min = (t_event - t_start).total_seconds() / 60
                    milestones[event.stage].append(delta_min)
                except (ValueError, TypeError):
                    pass

    result = {}
    for milestone, times in milestones.items():
        if times:
            times.sort()
            result[milestone] = {
                "median_minutes": round(times[len(times) // 2], 1),
                "mean_minutes": round(sum(times) / len(times), 1),
                "p90_minutes": round(times[int(len(times) * 0.9)], 1) if len(times) >= 10 else None,
                "sample_size": len(times),
            }
        else:
            result[milestone] = {"median_minutes": None, "sample_size": 0}

    return {"milestones": result}


# ---------------------------------------------------------------------------
# User segmentation analytics
# ---------------------------------------------------------------------------

def get_segment_analytics(segment_key: str = "company_size") -> Dict[str, Any]:
    """Get analytics broken down by user segment."""
    with _lock:
        journeys = list(_journeys.values())

    segments: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "count": 0,
        "converted": 0,
        "stages": defaultdict(int),
        "avg_events": 0,
        "total_events": 0,
    })

    for journey in journeys:
        seg_value = journey.segments.get(segment_key, "unknown")
        seg = segments[seg_value]
        seg["count"] += 1
        seg["total_events"] += len(journey.events)
        if journey.converted:
            seg["converted"] += 1
        for stage in journey.stages_reached:
            seg["stages"][stage] += 1

    result = {}
    for seg_name, data in segments.items():
        count = data["count"]
        result[seg_name] = {
            "total_users": count,
            "converted": data["converted"],
            "conversion_rate": round(data["converted"] / count * 100, 1) if count else 0.0,
            "avg_events_per_session": round(data["total_events"] / count, 1) if count else 0,
            "stage_distribution": dict(data["stages"]),
        }

    return {"segment_key": segment_key, "segments": result}


# ---------------------------------------------------------------------------
# A/B testing
# ---------------------------------------------------------------------------

def create_experiment(
    name: str,
    description: str,
    variants: List[str],
    traffic_split: Dict[str, float],
    metric: str,
) -> ABExperiment:
    """Create a new A/B test experiment."""
    if abs(sum(traffic_split.values()) - 1.0) > 0.01:
        raise ValueError("Traffic split must sum to 1.0")

    if set(variants) != set(traffic_split.keys()):
        raise ValueError("Variants and traffic_split keys must match")

    if len(variants) < 2:
        raise ValueError("At least 2 variants required")

    experiment = ABExperiment(
        id=f"exp-{uuid.uuid4().hex[:12]}",
        name=name,
        description=description,
        variants=variants,
        traffic_split=traffic_split,
        metric=metric,
        created_at=datetime.now(timezone.utc).isoformat(),
        results={v: {"impressions": 0, "conversions": 0} for v in variants},
    )

    with _lock:
        _experiments[experiment.id] = experiment

    logger.info("Created experiment: %s (%s)", name, experiment.id)
    return experiment


def assign_variant(experiment_id: str, user_id: str) -> Optional[str]:
    """Deterministically assign a user to an experiment variant."""
    with _lock:
        exp = _experiments.get(experiment_id)
        if not exp or exp.status != "active":
            return None

    # Deterministic assignment using hash
    hash_val = int(hashlib.md5(f"{experiment_id}:{user_id}".encode()).hexdigest(), 16)
    normalized = (hash_val % 10000) / 10000.0

    cumulative = 0.0
    for variant, weight in exp.traffic_split.items():
        cumulative += weight
        if normalized < cumulative:
            with _lock:
                exp.results[variant]["impressions"] += 1
            return variant

    # Fallback to last variant
    last = exp.variants[-1]
    with _lock:
        exp.results[last]["impressions"] += 1
    return last


def record_experiment_conversion(experiment_id: str, variant: str) -> bool:
    """Record a conversion for an experiment variant."""
    with _lock:
        exp = _experiments.get(experiment_id)
        if not exp:
            return False
        if variant not in exp.results:
            return False
        exp.results[variant]["conversions"] += 1
    return True


def get_experiment_results(experiment_id: str) -> Optional[Dict[str, Any]]:
    """Get results for an A/B experiment."""
    with _lock:
        exp = _experiments.get(experiment_id)
        if not exp:
            return None

        result = exp.to_dict()
        # Calculate conversion rates
        for variant, data in result["results"].items():
            impressions = data["impressions"]
            conversions = data["conversions"]
            data["conversion_rate"] = round(conversions / impressions * 100, 2) if impressions > 0 else 0.0

        # Determine winner (simple — highest conversion rate)
        if result["results"]:
            winner = max(
                result["results"].items(),
                key=lambda x: x[1]["conversion_rate"],
            )
            result["leading_variant"] = winner[0]
            result["leading_rate"] = winner[1]["conversion_rate"]

        return result


def list_experiments(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all experiments."""
    with _lock:
        exps = list(_experiments.values())
    if status:
        exps = [e for e in exps if e.status == status]
    return [e.to_dict() for e in exps]


def stop_experiment(experiment_id: str) -> bool:
    """Stop an active experiment."""
    with _lock:
        exp = _experiments.get(experiment_id)
        if not exp:
            return False
        exp.status = "stopped"
    return True


# ---------------------------------------------------------------------------
# NPS & satisfaction
# ---------------------------------------------------------------------------

_nps_scores: List[Dict[str, Any]] = []


def record_nps(
    user_id: str,
    score: int,
    segment: Optional[str] = None,
    comment: Optional[str] = None,
) -> Dict[str, Any]:
    """Record an NPS score (0-10)."""
    if not 0 <= score <= 10:
        raise ValueError("NPS score must be between 0 and 10")

    entry = {
        "id": f"nps-{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "score": score,
        "segment": segment,
        "comment": comment,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    with _lock:
        _nps_scores.append(entry)

    return entry


def get_nps_summary(segment: Optional[str] = None) -> Dict[str, Any]:
    """Calculate NPS score and breakdown."""
    with _lock:
        scores = list(_nps_scores)

    if segment:
        scores = [s for s in scores if s.get("segment") == segment]

    if not scores:
        return {"nps": None, "total_responses": 0}

    values = [s["score"] for s in scores]
    promoters = sum(1 for v in values if v >= 9)
    passives = sum(1 for v in values if 7 <= v <= 8)
    detractors = sum(1 for v in values if v <= 6)
    total = len(values)

    nps = round((promoters - detractors) / total * 100, 1)

    return {
        "nps": nps,
        "total_responses": total,
        "promoters": promoters,
        "passives": passives,
        "detractors": detractors,
        "promoter_pct": round(promoters / total * 100, 1),
        "detractor_pct": round(detractors / total * 100, 1),
        "avg_score": round(sum(values) / total, 1),
        "segment": segment,
    }


# ---------------------------------------------------------------------------
# Dashboard summary
# ---------------------------------------------------------------------------

def get_journey_dashboard() -> Dict[str, Any]:
    """Get complete journey analytics dashboard."""
    funnel = get_funnel_metrics()
    ttv = get_time_to_value()
    nps = get_nps_summary()
    company_segments = get_segment_analytics("company_size")
    cloud_segments = get_segment_analytics("cloud_provider")

    with _lock:
        total_journeys = len(_journeys)
        active_experiments = sum(1 for e in _experiments.values() if e.status == "active")

    return {
        "total_journeys": total_journeys,
        "funnel": funnel,
        "time_to_value": ttv,
        "nps": nps,
        "segments": {
            "by_company_size": company_segments,
            "by_cloud_provider": cloud_segments,
        },
        "active_experiments": active_experiments,
    }


# ---------------------------------------------------------------------------
# Test / reset helpers
# ---------------------------------------------------------------------------

def clear_all():
    """Clear all data (for testing)."""
    with _lock:
        _journeys.clear()
        _user_journeys.clear()
        _experiments.clear()
        _funnel_counts.clear()
        _drop_off_counts.clear()
        _conversion_events.clear()
        _nps_scores.clear()
