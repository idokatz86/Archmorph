"""
Archmorph Application Analytics  (Issue #71 — consolidated metrics)

Business-level analytics: sessions, events, conversion funnel, feature
tracking, and API performance monitoring for the admin dashboard.

.. deprecated::
    The low-level metric primitives (``increment_counter``,
    ``set_gauge``, ``record_histogram``) in this module are **thin
    wrappers** that also forward to ``observability.py`` for OTel /
    Azure Monitor export.  New code should import those functions
    directly from ``observability`` instead.
"""

import os
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
from cachetools import TTLCache
import statistics

# Forward metric primitives to the consolidated observability module
# so every counter / histogram also reaches OTel + Azure Monitor.
from observability import (
    increment_counter as _obs_increment_counter,
    record_histogram as _obs_record_histogram,
    set_gauge as _obs_set_gauge,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Telemetry Configuration
# ─────────────────────────────────────────────────────────────
ENABLE_TELEMETRY = os.getenv("ENABLE_TELEMETRY", "true").lower() == "true"


class MetricType(str, Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMER = "timer"


class EventCategory(str, Enum):
    USER = "user"
    ANALYSIS = "analysis"
    EXPORT = "export"
    IAC = "iac"
    FEEDBACK = "feedback"
    ERROR = "error"
    PERFORMANCE = "performance"
    CONVERSION = "conversion"


@dataclass
class AnalyticsEvent:
    """Individual analytics event."""
    event_id: str
    event_name: str
    category: EventCategory
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    properties: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_name": self.event_name,
            "category": self.category.value,
            "timestamp": self.timestamp.isoformat(),
            "user_id": self.user_id,
            "session_id": self.session_id,
            "properties": self.properties,
            "metrics": self.metrics,
        }


@dataclass
class UserSession:
    """User session tracking."""
    session_id: str
    user_id: Optional[str] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    events: List[AnalyticsEvent] = field(default_factory=list)
    page_views: List[str] = field(default_factory=list)
    conversion_achieved: bool = False
    
    def duration_seconds(self) -> float:
        return (self.last_activity - self.started_at).total_seconds()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "started_at": self.started_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "duration_seconds": self.duration_seconds(),
            "events_count": len(self.events),
            "page_views": self.page_views,
            "conversion_achieved": self.conversion_achieved,
        }


# ─────────────────────────────────────────────────────────────
# In-Memory Analytics Storage
# ─────────────────────────────────────────────────────────────
# Events buffer (TTL: 24 hours, max 100k events)
EVENTS_BUFFER: TTLCache = TTLCache(maxsize=100000, ttl=86400)

# Sessions (TTL: 4 hours, max 10k)
SESSIONS: TTLCache = TTLCache(maxsize=10000, ttl=14400)

# Metrics counters
COUNTERS: Dict[str, int] = defaultdict(int)
GAUGES: Dict[str, float] = {}
HISTOGRAMS: Dict[str, List[float]] = defaultdict(list)
TIMERS: Dict[str, List[float]] = defaultdict(list)

# Performance tracking
REQUEST_LATENCIES: Dict[str, List[float]] = defaultdict(list)
ERROR_COUNTS: Dict[str, int] = defaultdict(int)


# ─────────────────────────────────────────────────────────────
# Core Analytics Functions
# ─────────────────────────────────────────────────────────────
def track_event(
    event_name: str,
    category: EventCategory,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    properties: Optional[Dict[str, Any]] = None,
    metrics: Optional[Dict[str, float]] = None,
) -> AnalyticsEvent:
    """Track an analytics event."""
    if not ENABLE_TELEMETRY:
        return None
    
    import uuid
    event_id = f"evt-{uuid.uuid4().hex[:12]}"
    
    event = AnalyticsEvent(
        event_id=event_id,
        event_name=event_name,
        category=category,
        user_id=user_id,
        session_id=session_id,
        properties=properties or {},
        metrics=metrics or {},
    )
    
    EVENTS_BUFFER[event_id] = event
    
    # Update session
    if session_id and session_id in SESSIONS:
        session = SESSIONS[session_id]
        session.events.append(event)
        session.last_activity = datetime.now(timezone.utc)
    
    # Increment counters
    COUNTERS[f"events.{event_name}"] += 1
    COUNTERS[f"events.{category.value}"] += 1
    
    logger.debug("Tracked event: %s (%s)", event_name, category.value)
    
    return event


def start_session(
    user_id: Optional[str] = None,
    initial_page: Optional[str] = None,
) -> UserSession:
    """Start a new user session."""
    import uuid
    session_id = f"sess-{uuid.uuid4().hex[:12]}"
    
    session = UserSession(
        session_id=session_id,
        user_id=user_id,
        page_views=[initial_page] if initial_page else [],
    )
    
    SESSIONS[session_id] = session
    COUNTERS["sessions.started"] += 1
    
    track_event(
        "session_started",
        EventCategory.USER,
        user_id=user_id,
        session_id=session_id,
    )
    
    return session


def end_session(session_id: str):
    """End a user session."""
    if session_id not in SESSIONS:
        return
    
    session = SESSIONS[session_id]
    
    track_event(
        "session_ended",
        EventCategory.USER,
        session_id=session_id,
        metrics={
            "duration_seconds": session.duration_seconds(),
            "events_count": len(session.events),
            "pages_viewed": len(session.page_views),
        },
    )
    
    COUNTERS["sessions.ended"] += 1
    
    if session.conversion_achieved:
        COUNTERS["sessions.converted"] += 1


def track_page_view(session_id: str, page: str):
    """Track a page view within a session."""
    if session_id in SESSIONS:
        session = SESSIONS[session_id]
        session.page_views.append(page)
        session.last_activity = datetime.now(timezone.utc)
    
    track_event(
        "page_view",
        EventCategory.USER,
        session_id=session_id,
        properties={"page": page},
    )


def track_conversion(session_id: str, conversion_type: str):
    """Track a conversion event."""
    if session_id in SESSIONS:
        SESSIONS[session_id].conversion_achieved = True
    
    track_event(
        "conversion",
        EventCategory.CONVERSION,
        session_id=session_id,
        properties={"conversion_type": conversion_type},
    )
    
    COUNTERS[f"conversions.{conversion_type}"] += 1


# ─────────────────────────────────────────────────────────────
# Metrics Functions
# ─────────────────────────────────────────────────────────────
def increment_counter(name: str, value: int = 1, tags: Optional[Dict[str, str]] = None):
    """Increment a counter metric.

    .. deprecated:: Use ``observability.increment_counter`` for new code.
    """
    key = name
    if tags:
        key = f"{name}:{','.join(f'{k}={v}' for k, v in sorted(tags.items()))}"
    COUNTERS[key] += value
    # Forward to observability for OTel export
    _obs_increment_counter(name, value, tags)


def set_gauge(name: str, value: float, tags: Optional[Dict[str, str]] = None):
    """Set a gauge metric value.

    .. deprecated:: Use ``observability.set_gauge`` for new code.
    """
    key = name
    if tags:
        key = f"{name}:{','.join(f'{k}={v}' for k, v in sorted(tags.items()))}"
    GAUGES[key] = value
    # Forward to observability for OTel export
    _obs_set_gauge(name, value, tags)


def record_histogram(name: str, value: float, tags: Optional[Dict[str, str]] = None):
    """Record a value in a histogram.

    .. deprecated:: Use ``observability.record_histogram`` for new code.
    """
    key = name
    if tags:
        key = f"{name}:{','.join(f'{k}={v}' for k, v in sorted(tags.items()))}"
    HISTOGRAMS[key].append(value)

    # Keep only last 1000 values
    if len(HISTOGRAMS[key]) > 1000:
        HISTOGRAMS[key] = HISTOGRAMS[key][-1000:]
    # Forward to observability for OTel export
    _obs_record_histogram(name, value, tags)


def record_timing(name: str, duration_ms: float, tags: Optional[Dict[str, str]] = None):
    """Record a timing metric."""
    key = name
    if tags:
        key = f"{name}:{','.join(f'{k}={v}' for k, v in sorted(tags.items()))}"
    TIMERS[key].append(duration_ms)
    
    # Keep only last 1000 values
    if len(TIMERS[key]) > 1000:
        TIMERS[key] = TIMERS[key][-1000:]


class Timer:
    """Context manager for timing operations."""
    
    def __init__(self, name: str, tags: Optional[Dict[str, str]] = None):
        self.name = name
        self.tags = tags
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.perf_counter()
        return self
    
    def __exit__(self, *args):
        duration_ms = (time.perf_counter() - self.start_time) * 1000
        record_timing(self.name, duration_ms, self.tags)


# ─────────────────────────────────────────────────────────────
# Performance Monitoring
# ─────────────────────────────────────────────────────────────
def track_request_latency(endpoint: str, method: str, latency_ms: float, status_code: int):
    """Track API request latency."""
    key = f"{method}:{endpoint}"
    REQUEST_LATENCIES[key].append(latency_ms)
    
    # Keep only last 1000
    if len(REQUEST_LATENCIES[key]) > 1000:
        REQUEST_LATENCIES[key] = REQUEST_LATENCIES[key][-1000:]
    
    if status_code >= 400:
        ERROR_COUNTS[key] += 1
        track_event(
            "api_error",
            EventCategory.ERROR,
            properties={
                "endpoint": endpoint,
                "method": method,
                "status_code": status_code,
            },
        )


def track_error(
    error_type: str,
    error_message: str,
    endpoint: Optional[str] = None,
    user_id: Optional[str] = None,
    stack_trace: Optional[str] = None,
):
    """Track an application error."""
    track_event(
        "error",
        EventCategory.ERROR,
        user_id=user_id,
        properties={
            "error_type": error_type,
            "error_message": error_message[:500],  # Truncate
            "endpoint": endpoint,
            "stack_trace": stack_trace[:2000] if stack_trace else None,
        },
    )
    
    ERROR_COUNTS[f"error:{error_type}"] += 1


# ─────────────────────────────────────────────────────────────
# Feature Analytics
# ─────────────────────────────────────────────────────────────
def track_feature_usage(
    feature_name: str,
    user_id: Optional[str] = None,
    properties: Optional[Dict[str, Any]] = None,
):
    """Track feature usage for product analytics."""
    track_event(
        f"feature.{feature_name}",
        EventCategory.USER,
        user_id=user_id,
        properties=properties or {},
    )
    
    COUNTERS[f"feature.{feature_name}"] += 1


def track_analysis(
    diagram_id: str,
    source_cloud: str,
    services_count: int,
    duration_ms: float,
    user_id: Optional[str] = None,
):
    """Track diagram analysis event."""
    track_event(
        "analysis_completed",
        EventCategory.ANALYSIS,
        user_id=user_id,
        properties={
            "diagram_id": diagram_id,
            "source_cloud": source_cloud,
        },
        metrics={
            "services_count": services_count,
            "duration_ms": duration_ms,
        },
    )
    
    record_histogram("analysis.services_count", services_count, {"cloud": source_cloud})
    record_timing("analysis.duration", duration_ms, {"cloud": source_cloud})


def track_export(
    diagram_id: str,
    export_format: str,
    user_id: Optional[str] = None,
):
    """Track diagram export event."""
    track_event(
        "export_completed",
        EventCategory.EXPORT,
        user_id=user_id,
        properties={
            "diagram_id": diagram_id,
            "format": export_format,
        },
    )
    
    COUNTERS[f"exports.{export_format}"] += 1


def track_iac_generation(
    diagram_id: str,
    format: str,
    resources_count: int,
    user_id: Optional[str] = None,
):
    """Track IaC generation event."""
    track_event(
        "iac_generated",
        EventCategory.IAC,
        user_id=user_id,
        properties={
            "diagram_id": diagram_id,
            "format": format,
        },
        metrics={
            "resources_count": resources_count,
        },
    )
    
    record_histogram("iac.resources_count", resources_count, {"format": format})


# ─────────────────────────────────────────────────────────────
# Analytics Reports
# ─────────────────────────────────────────────────────────────
def get_analytics_summary(hours: int = 24) -> Dict[str, Any]:
    """Get comprehensive analytics summary."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    
    # Filter recent events
    recent_events = [
        e for e in EVENTS_BUFFER.values()
        if e.timestamp >= cutoff
    ]
    
    # Calculate event stats
    events_by_category = defaultdict(int)
    events_by_name = defaultdict(int)
    
    for event in recent_events:
        events_by_category[event.category.value] += 1
        events_by_name[event.event_name] += 1
    
    # Calculate session stats
    active_sessions = [
        s for s in SESSIONS.values()
        if s.last_activity >= cutoff
    ]
    
    session_durations = [s.duration_seconds() for s in active_sessions]
    
    return {
        "period_hours": hours,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events": {
            "total": len(recent_events),
            "by_category": dict(events_by_category),
            "top_events": dict(sorted(events_by_name.items(), key=lambda x: -x[1])[:10]),
        },
        "sessions": {
            "active": len(active_sessions),
            "converted": len([s for s in active_sessions if s.conversion_achieved]),
            "conversion_rate": (
                len([s for s in active_sessions if s.conversion_achieved]) / len(active_sessions) * 100
                if active_sessions else 0
            ),
            "avg_duration_seconds": statistics.mean(session_durations) if session_durations else 0,
            "median_duration_seconds": statistics.median(session_durations) if session_durations else 0,
        },
        "metrics": {
            "counters": dict(COUNTERS),
            "gauges": dict(GAUGES),
        },
        "performance": get_performance_metrics(),
    }


def get_performance_metrics() -> Dict[str, Any]:
    """Get API performance metrics."""
    metrics = {}
    
    for endpoint, latencies in REQUEST_LATENCIES.items():
        if not latencies:
            continue
        
        metrics[endpoint] = {
            "count": len(latencies),
            "avg_ms": round(statistics.mean(latencies), 2),
            "p50_ms": round(statistics.median(latencies), 2),
            "p95_ms": round(statistics.quantiles(latencies, n=20)[18], 2) if len(latencies) >= 20 else round(max(latencies), 2),
            "p99_ms": round(statistics.quantiles(latencies, n=100)[98], 2) if len(latencies) >= 100 else round(max(latencies), 2),
            "min_ms": round(min(latencies), 2),
            "max_ms": round(max(latencies), 2),
            "errors": ERROR_COUNTS.get(endpoint, 0),
        }
    
    return metrics


def get_feature_metrics() -> Dict[str, Any]:
    """Get feature usage metrics."""
    feature_usage = {
        k: v for k, v in COUNTERS.items()
        if k.startswith("feature.")
    }
    
    return {
        "features": feature_usage,
        "total_feature_uses": sum(feature_usage.values()),
        "most_used": max(feature_usage.items(), key=lambda x: x[1])[0] if feature_usage else None,
    }


def get_conversion_funnel() -> Dict[str, Any]:
    """Get conversion funnel metrics."""
    return {
        "upload": COUNTERS.get("events.diagram_upload", 0),
        "analyze": COUNTERS.get("events.analysis_completed", 0),
        "questions": COUNTERS.get("events.questions_completed", 0),
        "export": COUNTERS.get("events.export_completed", 0),
        "iac_download": COUNTERS.get("events.iac_generated", 0),
        "rates": {
            "upload_to_analyze": _calc_rate(
                COUNTERS.get("events.analysis_completed", 0),
                COUNTERS.get("events.diagram_upload", 1)
            ),
            "analyze_to_export": _calc_rate(
                COUNTERS.get("events.export_completed", 0),
                COUNTERS.get("events.analysis_completed", 1)
            ),
            "export_to_iac": _calc_rate(
                COUNTERS.get("events.iac_generated", 0),
                COUNTERS.get("events.export_completed", 1)
            ),
        },
    }


def _calc_rate(numerator: int, denominator: int) -> float:
    """Calculate percentage rate safely."""
    return round(numerator / denominator * 100, 1) if denominator > 0 else 0


def reset_analytics():
    """Reset all analytics data (for testing)."""
    EVENTS_BUFFER.clear()
    SESSIONS.clear()
    COUNTERS.clear()
    GAUGES.clear()
    HISTOGRAMS.clear()
    TIMERS.clear()
    REQUEST_LATENCIES.clear()
    ERROR_COUNTS.clear()
