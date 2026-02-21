"""
Tests for Application Analytics
"""

import pytest
import time
from analytics import (
    AnalyticsEvent, UserSession, EventCategory, MetricType,
    track_event, start_session, end_session, track_page_view,
    track_conversion, increment_counter, set_gauge, record_histogram,
    record_timing, Timer, track_request_latency, track_error,
    track_feature_usage, track_analysis, track_export, track_iac_generation,
    get_analytics_summary, get_performance_metrics, get_feature_metrics,
    get_conversion_funnel, reset_analytics,
    COUNTERS, GAUGES, HISTOGRAMS, SESSIONS,
)


class TestAnalyticsEvent:
    """Tests for AnalyticsEvent class."""
    
    def test_event_creation(self):
        event = AnalyticsEvent(
            event_id="evt-123",
            event_name="test_event",
            category=EventCategory.USER,
        )
        assert event.event_id == "evt-123"
        assert event.category == EventCategory.USER
    
    def test_event_to_dict(self):
        event = AnalyticsEvent(
            event_id="evt-123",
            event_name="test_event",
            category=EventCategory.ANALYSIS,
            properties={"diagram_id": "diag-123"},
            metrics={"duration_ms": 1500},
        )
        data = event.to_dict()
        assert data["event_name"] == "test_event"
        assert data["category"] == "analysis"
        assert data["properties"]["diagram_id"] == "diag-123"


class TestUserSession:
    """Tests for UserSession class."""
    
    def test_session_creation(self):
        session = UserSession(session_id="sess-123")
        assert session.session_id == "sess-123"
        assert session.conversion_achieved is False
    
    def test_session_duration(self):
        session = UserSession(session_id="sess-123")
        time.sleep(0.1)
        session.last_activity = session.started_at
        duration = session.duration_seconds()
        assert duration >= 0
    
    def test_session_to_dict(self):
        session = UserSession(session_id="sess-123", user_id="user-456")
        data = session.to_dict()
        assert data["session_id"] == "sess-123"
        assert data["user_id"] == "user-456"


class TestEventTracking:
    """Tests for event tracking functions."""
    
    def setup_method(self):
        reset_analytics()
    
    def test_track_event(self):
        event = track_event(
            "test_event",
            EventCategory.USER,
            properties={"key": "value"},
        )
        assert event is not None
        assert event.event_name == "test_event"
    
    def test_track_event_increments_counter(self):
        track_event("custom_event", EventCategory.ANALYSIS)
        assert COUNTERS["events.custom_event"] == 1
        
        track_event("custom_event", EventCategory.ANALYSIS)
        assert COUNTERS["events.custom_event"] == 2


class TestSessionManagement:
    """Tests for session management."""
    
    def setup_method(self):
        reset_analytics()
    
    def test_start_session(self):
        session = start_session(user_id="user-123")
        assert session is not None
        assert session.user_id == "user-123"
        assert COUNTERS["sessions.started"] == 1
    
    def test_track_page_view(self):
        session = start_session()
        track_page_view(session.session_id, "/dashboard")
        
        assert "/dashboard" in SESSIONS[session.session_id].page_views
    
    def test_track_conversion(self):
        session = start_session()
        track_conversion(session.session_id, "iac_download")
        
        assert SESSIONS[session.session_id].conversion_achieved is True
        assert COUNTERS["conversions.iac_download"] == 1
    
    def test_end_session(self):
        session = start_session()
        end_session(session.session_id)
        
        assert COUNTERS["sessions.ended"] == 1


class TestMetrics:
    """Tests for metrics functions."""
    
    def setup_method(self):
        reset_analytics()
    
    def test_increment_counter(self):
        increment_counter("test.counter")
        assert COUNTERS["test.counter"] == 1
        
        increment_counter("test.counter", 5)
        assert COUNTERS["test.counter"] == 6
    
    def test_increment_counter_with_tags(self):
        increment_counter("requests", tags={"endpoint": "/api/health"})
        assert COUNTERS["requests:endpoint=/api/health"] == 1
    
    def test_set_gauge(self):
        set_gauge("memory.used", 1024.5)
        assert GAUGES["memory.used"] == 1024.5
        
        set_gauge("memory.used", 2048.0)
        assert GAUGES["memory.used"] == 2048.0
    
    def test_record_histogram(self):
        record_histogram("response.time", 100)
        record_histogram("response.time", 150)
        record_histogram("response.time", 200)
        
        assert len(HISTOGRAMS["response.time"]) == 3
    
    def test_record_timing(self):
        record_timing("db.query", 50.5)
        record_timing("db.query", 75.2)
        
        from analytics import TIMERS
        assert len(TIMERS["db.query"]) == 2


class TestTimerContextManager:
    """Tests for Timer context manager."""
    
    def setup_method(self):
        reset_analytics()
    
    def test_timer_basic(self):
        with Timer("test.operation"):
            time.sleep(0.01)
        
        from analytics import TIMERS
        assert len(TIMERS["test.operation"]) == 1
        assert TIMERS["test.operation"][0] >= 10  # At least 10ms


class TestPerformanceTracking:
    """Tests for performance tracking."""
    
    def setup_method(self):
        reset_analytics()
    
    def test_track_request_latency(self):
        track_request_latency("/api/health", "GET", 50.5, 200)
        track_request_latency("/api/health", "GET", 75.2, 200)
        
        metrics = get_performance_metrics()
        assert "GET:/api/health" in metrics
        assert metrics["GET:/api/health"]["count"] == 2
    
    def test_track_request_error(self):
        track_request_latency("/api/analyze", "POST", 100, 500)
        
        metrics = get_performance_metrics()
        assert metrics["POST:/api/analyze"]["errors"] == 1
    
    def test_track_error(self):
        track_error("ValueError", "Invalid input", endpoint="/api/test")
        
        from analytics import ERROR_COUNTS
        assert ERROR_COUNTS["error:ValueError"] == 1


class TestFeatureTracking:
    """Tests for feature usage tracking."""
    
    def setup_method(self):
        reset_analytics()
    
    def test_track_feature_usage(self):
        track_feature_usage("diagram_export", user_id="user-123")
        assert COUNTERS["feature.diagram_export"] == 1
    
    def test_track_analysis(self):
        track_analysis("diag-123", "AWS", 5, 1500.0)
        
        assert COUNTERS["events.analysis_completed"] == 1
    
    def test_track_export(self):
        track_export("diag-123", "excalidraw")
        assert COUNTERS["exports.excalidraw"] == 1
    
    def test_track_iac_generation(self):
        track_iac_generation("diag-123", "terraform", 10)
        
        assert len(HISTOGRAMS["iac.resources_count:format=terraform"]) == 1


class TestAnalyticsSummary:
    """Tests for analytics summary."""
    
    def setup_method(self):
        reset_analytics()
    
    def test_get_analytics_summary(self):
        track_event("test", EventCategory.USER)
        start_session()
        
        summary = get_analytics_summary(hours=1)
        
        assert "events" in summary
        assert "sessions" in summary
        assert "metrics" in summary
        assert "performance" in summary
    
    def test_get_feature_metrics(self):
        track_feature_usage("feature_a")
        track_feature_usage("feature_b")
        track_feature_usage("feature_a")
        
        metrics = get_feature_metrics()
        
        assert metrics["features"]["feature.feature_a"] == 2
        assert metrics["features"]["feature.feature_b"] == 1
        assert metrics["total_feature_uses"] == 3
    
    def test_get_conversion_funnel(self):
        funnel = get_conversion_funnel()
        
        assert "upload" in funnel
        assert "analyze" in funnel
        assert "export" in funnel
        assert "rates" in funnel


class TestResetAnalytics:
    """Tests for analytics reset."""
    
    def test_reset_clears_all(self):
        track_event("test", EventCategory.USER)
        increment_counter("test")
        start_session()
        
        reset_analytics()
        
        assert len(COUNTERS) == 0
        assert len(GAUGES) == 0
        assert len(SESSIONS) == 0
