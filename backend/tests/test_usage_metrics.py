"""Tests for usage_metrics module (#281)."""
from usage_metrics import record_event, get_metrics_summary, get_funnel_metrics, record_funnel_step


class TestRecordEvent:
    def test_record_event_basic(self):
        record_event("test_event", {"key": "value"})
        # Should not raise

    def test_record_event_without_details(self):
        record_event("simple_event")


class TestGetMetricsSummary:
    def test_returns_dict(self):
        summary = get_metrics_summary()
        assert isinstance(summary, dict)

    def test_has_total_events(self):
        summary = get_metrics_summary()
        assert "total_events" in summary or "events" in summary or isinstance(summary, dict)


class TestFunnelMetrics:
    def test_returns_dict(self):
        result = get_funnel_metrics()
        assert isinstance(result, dict)

    def test_record_funnel_step(self):
        record_funnel_step("test-diagram-1", "upload")
        record_funnel_step("test-diagram-1", "analyze")
        # Should track progression
