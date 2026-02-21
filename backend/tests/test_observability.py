"""
Tests for Archmorph Observability Module
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from observability import (
    increment_counter, record_histogram, set_gauge, get_metrics,
    trace_span, SpanContext, _metrics,
)


@pytest.fixture(autouse=True)
def clean_metrics():
    """Reset metrics before each test."""
    _metrics["counters"].clear()
    _metrics["histograms"].clear()
    _metrics["gauges"].clear()
    yield
    _metrics["counters"].clear()
    _metrics["histograms"].clear()
    _metrics["gauges"].clear()


class TestCounters:
    """Tests for counter metrics."""
    
    def test_increment_counter_basic(self):
        """Increment a counter by 1."""
        increment_counter("requests.total")
        metrics = get_metrics()
        
        assert "requests.total" in metrics["counters"]
        assert metrics["counters"]["requests.total"]["value"] == 1
    
    def test_increment_counter_multiple(self):
        """Increment counter multiple times."""
        increment_counter("requests.total")
        increment_counter("requests.total")
        increment_counter("requests.total")
        
        metrics = get_metrics()
        assert metrics["counters"]["requests.total"]["value"] == 3
    
    def test_increment_counter_with_value(self):
        """Increment counter by specific value."""
        increment_counter("bytes.sent", value=1024)
        
        metrics = get_metrics()
        assert metrics["counters"]["bytes.sent"]["value"] == 1024
    
    def test_counter_with_tags(self):
        """Counter with tags."""
        increment_counter("requests.total", tags={"method": "GET"})
        increment_counter("requests.total", tags={"method": "POST"})
        
        get_metrics()
        # Both should be tracked separately
        assert len(_metrics["counters"]) == 2


class TestHistograms:
    """Tests for histogram metrics."""
    
    def test_record_histogram_basic(self):
        """Record histogram value."""
        record_histogram("latency_ms", 100.5)
        
        metrics = get_metrics()
        assert "latency_ms" in metrics["histograms"]
        assert metrics["histograms"]["latency_ms"]["count"] == 1
        assert metrics["histograms"]["latency_ms"]["sum"] == 100.5
    
    def test_histogram_statistics(self):
        """Histogram calculates statistics."""
        for val in [10, 20, 30, 40, 50]:
            record_histogram("latency_ms", val)
        
        metrics = get_metrics()
        hist = metrics["histograms"]["latency_ms"]
        
        assert hist["count"] == 5
        assert hist["sum"] == 150
        assert hist["avg"] == 30
        assert hist["min"] == 10
        assert hist["max"] == 50
    
    def test_histogram_percentiles(self):
        """Histogram calculates percentiles."""
        for i in range(100):
            record_histogram("latency_ms", i + 1)
        
        metrics = get_metrics()
        hist = metrics["histograms"]["latency_ms"]
        
        # Percentile calculations may be approximate
        assert 49 <= hist["p50"] <= 51
        assert 94 <= hist["p95"] <= 96
        assert 98 <= hist["p99"] <= 100


class TestGauges:
    """Tests for gauge metrics."""
    
    def test_set_gauge_basic(self):
        """Set a gauge value."""
        set_gauge("memory_usage", 75.5)
        
        metrics = get_metrics()
        assert "memory_usage" in metrics["gauges"]
        assert metrics["gauges"]["memory_usage"]["value"] == 75.5
    
    def test_gauge_overwrites(self):
        """Setting gauge overwrites previous value."""
        set_gauge("memory_usage", 50)
        set_gauge("memory_usage", 80)
        
        metrics = get_metrics()
        assert metrics["gauges"]["memory_usage"]["value"] == 80
    
    def test_gauge_with_tags(self):
        """Gauge with tags."""
        set_gauge("cpu_usage", 45, tags={"core": "0"})
        set_gauge("cpu_usage", 55, tags={"core": "1"})
        
        # Should have two separate gauges
        assert len(_metrics["gauges"]) == 2


class TestTraceSpan:
    """Tests for trace spans."""
    
    def test_span_context_creation(self):
        """Create a span context."""
        span = SpanContext("test_operation")
        
        assert span.name == "test_operation"
        assert span.status == "OK"
        assert span.start_time > 0
    
    def test_span_context_with_attributes(self):
        """Create span with attributes."""
        span = SpanContext("test_operation", {"key": "value"})
        
        assert span.attributes["key"] == "value"
    
    def test_span_add_event(self):
        """Add event to span."""
        span = SpanContext("test_operation")
        span.add_event("checkpoint", {"data": "test"})
        
        assert len(span.events) == 1
        assert span.events[0]["name"] == "checkpoint"
    
    def test_span_set_status(self):
        """Set span status."""
        span = SpanContext("test_operation")
        span.set_status("ERROR", "Something failed")
        
        assert span.status == "ERROR"
        assert span.attributes["status_message"] == "Something failed"
    
    def test_span_end(self):
        """End span records duration."""
        span = SpanContext("test_operation")
        span.end()
        
        assert span.end_time is not None
        assert span.end_time >= span.start_time
    
    def test_trace_span_context_manager(self):
        """Use trace_span as context manager."""
        with trace_span("test_op") as span:
            span.add_event("in_progress")
        
        assert span.end_time is not None
        assert len(span.events) == 1
    
    def test_trace_span_records_histogram(self):
        """trace_span records duration histogram."""
        _metrics["histograms"].clear()
        
        with trace_span("my_operation"):
            pass  # Quick operation
        
        metrics = get_metrics()
        assert "span.my_operation.duration_ms" in metrics["histograms"]
    
    def test_trace_span_on_exception(self):
        """trace_span handles exceptions."""
        with pytest.raises(ValueError):
            with trace_span("failing_op") as span:
                raise ValueError("Test error")
        
        assert span.status == "ERROR"


class TestGetMetrics:
    """Tests for metrics aggregation."""
    
    def test_get_metrics_structure(self):
        """get_metrics returns expected structure."""
        metrics = get_metrics()
        
        assert "counters" in metrics
        assert "histograms" in metrics
        assert "gauges" in metrics
    
    def test_get_metrics_empty(self):
        """get_metrics with no data."""
        metrics = get_metrics()
        
        assert metrics["counters"] == {}
        assert metrics["histograms"] == {}
        assert metrics["gauges"] == {}
    
    def test_get_metrics_combined(self):
        """get_metrics with all metric types."""
        increment_counter("requests")
        record_histogram("latency", 50)
        set_gauge("memory", 70)
        
        metrics = get_metrics()
        
        assert "requests" in metrics["counters"]
        assert "latency" in metrics["histograms"]
        assert "memory" in metrics["gauges"]
