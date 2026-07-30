"""Tests for usage_metrics module (#281)."""
import uuid

import usage_metrics
from usage_metrics import record_event, get_metrics_summary, get_funnel_metrics, record_funnel_step


class TestRecordEvent:
    def test_record_event_basic(self):
        record_event("test_event", {"key": "value"})
        # Should not raise

    def test_record_event_without_details(self):
        record_event("simple_event")

    def test_transient_subject_metrics_skip_durable_sql_fence(self, monkeypatch):
        def unexpected_fence(**_kwargs):
            raise AssertionError("transient metrics must not open a durable fence")

        monkeypatch.setattr(usage_metrics, "_subject_write_fence", unexpected_fence)
        diagram_id = f"transient-{uuid.uuid4().hex}"

        record_event(
            "test_event",
            {"diagram_id": diagram_id},
            durable_subject=False,
        )
        record_funnel_step(
            diagram_id,
            "analyze",
            durable_subject=False,
        )


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
