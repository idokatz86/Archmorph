"""
Archmorph Observability Module

Provides OpenTelemetry integration for distributed tracing and metrics.
"""

import os
import logging
import time
from typing import Dict, Any, Optional, Callable
from functools import wraps
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Configuration
OTEL_ENABLED = os.getenv("OTEL_ENABLED", "false").lower() == "true"
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "archmorph-api")
OTEL_EXPORTER_ENDPOINT = os.getenv("OTEL_EXPORTER_ENDPOINT", "")

# Metrics storage (in-memory for now, can be exported to Prometheus/Azure Monitor)
_metrics: Dict[str, Any] = {
    "counters": {},
    "histograms": {},
    "gauges": {},
}


class MetricType:
    """Metric type constants."""
    COUNTER = "counter"
    HISTOGRAM = "histogram"
    GAUGE = "gauge"


class SpanContext:
    """Simple span context for tracing."""
    
    def __init__(self, name: str, attributes: Optional[Dict[str, str]] = None):
        self.name = name
        self.attributes = attributes or {}
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.status = "OK"
        self.events: list = []
    
    def add_event(self, name: str, attributes: Optional[Dict[str, str]] = None):
        """Add an event to the span."""
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes or {},
        })
    
    def set_status(self, status: str, message: str = ""):
        """Set span status."""
        self.status = status
        if message:
            self.attributes["status_message"] = message
    
    def end(self):
        """End the span."""
        self.end_time = time.time()
        duration_ms = (self.end_time - self.start_time) * 1000
        
        # Record as histogram
        record_histogram(f"span.{self.name}.duration_ms", duration_ms)
        
        # Log span completion
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Span completed: %s (%.2fms) status=%s",
                self.name, duration_ms, self.status
            )


@contextmanager
def trace_span(name: str, attributes: Optional[Dict[str, str]] = None):
    """
    Context manager for creating a trace span.
    
    Args:
        name: Span name
        attributes: Optional span attributes
        
    Yields:
        SpanContext object
    """
    span = SpanContext(name, attributes)
    try:
        yield span
    except Exception as e:
        span.set_status("ERROR", str(e))
        raise
    finally:
        span.end()


def traced(name: Optional[str] = None):
    """
    Decorator to trace a function.
    
    Args:
        name: Optional span name (defaults to function name)
    """
    def decorator(func: Callable):
        span_name = name or func.__name__
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            with trace_span(span_name) as span:
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    span.set_status("ERROR", str(e))
                    raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            with trace_span(span_name) as span:
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    span.set_status("ERROR", str(e))
                    raise
        
        if asyncio_iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def asyncio_iscoroutinefunction(func) -> bool:
    """Check if function is async."""
    import asyncio
    return asyncio.iscoroutinefunction(func)


# ─────────────────────────────────────────────────────────────
# Metrics Functions
# ─────────────────────────────────────────────────────────────

def increment_counter(name: str, value: int = 1, tags: Optional[Dict[str, str]] = None):
    """
    Increment a counter metric.
    
    Args:
        name: Metric name
        value: Value to add (default 1)
        tags: Optional metric tags
    """
    key = _make_metric_key(name, tags)
    if key not in _metrics["counters"]:
        _metrics["counters"][key] = {"name": name, "tags": tags or {}, "value": 0}
    _metrics["counters"][key]["value"] += value


def record_histogram(name: str, value: float, tags: Optional[Dict[str, str]] = None):
    """
    Record a value in a histogram metric.
    
    Args:
        name: Metric name
        value: Value to record
        tags: Optional metric tags
    """
    key = _make_metric_key(name, tags)
    if key not in _metrics["histograms"]:
        _metrics["histograms"][key] = {
            "name": name,
            "tags": tags or {},
            "values": [],
            "count": 0,
            "sum": 0,
            "min": float("inf"),
            "max": float("-inf"),
        }
    
    h = _metrics["histograms"][key]
    h["values"].append(value)
    h["count"] += 1
    h["sum"] += value
    h["min"] = min(h["min"], value)
    h["max"] = max(h["max"], value)
    
    # Keep only last 1000 values for percentile calculation
    if len(h["values"]) > 1000:
        h["values"] = h["values"][-1000:]


def set_gauge(name: str, value: float, tags: Optional[Dict[str, str]] = None):
    """
    Set a gauge metric value.
    
    Args:
        name: Metric name
        value: Current value
        tags: Optional metric tags
    """
    key = _make_metric_key(name, tags)
    _metrics["gauges"][key] = {
        "name": name,
        "tags": tags or {},
        "value": value,
        "timestamp": time.time(),
    }


def get_metrics() -> Dict[str, Any]:
    """
    Get all metrics.
    
    Returns:
        Dictionary with all metric types and values.
    """
    result = {
        "counters": {},
        "histograms": {},
        "gauges": {},
    }
    
    for key, counter in _metrics["counters"].items():
        result["counters"][counter["name"]] = {
            "value": counter["value"],
            "tags": counter["tags"],
        }
    
    for key, hist in _metrics["histograms"].items():
        avg = hist["sum"] / hist["count"] if hist["count"] > 0 else 0
        p50 = _percentile(hist["values"], 50)
        p95 = _percentile(hist["values"], 95)
        p99 = _percentile(hist["values"], 99)
        
        result["histograms"][hist["name"]] = {
            "count": hist["count"],
            "sum": hist["sum"],
            "avg": avg,
            "min": hist["min"] if hist["min"] != float("inf") else 0,
            "max": hist["max"] if hist["max"] != float("-inf") else 0,
            "p50": p50,
            "p95": p95,
            "p99": p99,
            "tags": hist["tags"],
        }
    
    for key, gauge in _metrics["gauges"].items():
        result["gauges"][gauge["name"]] = {
            "value": gauge["value"],
            "tags": gauge["tags"],
        }
    
    return result


def _make_metric_key(name: str, tags: Optional[Dict[str, str]]) -> str:
    """Create a unique key for a metric with tags."""
    if not tags:
        return name
    tag_str = ",".join(f"{k}={v}" for k, v in sorted(tags.items()))
    return f"{name}[{tag_str}]"


def _percentile(values: list, percentile: float) -> float:
    """Calculate percentile of a list of values."""
    if not values:
        return 0
    sorted_values = sorted(values)
    index = int(len(sorted_values) * percentile / 100)
    index = min(index, len(sorted_values) - 1)
    return sorted_values[index]


# ─────────────────────────────────────────────────────────────
# Request Metrics Middleware
# ─────────────────────────────────────────────────────────────

class ObservabilityMiddleware:
    """
    Middleware to collect request metrics.
    """
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        start_time = time.time()
        path = scope.get("path", "unknown")
        method = scope.get("method", "unknown")
        
        # Track request
        increment_counter("http.requests.total", tags={"method": method, "path": path})
        
        status_code = 200
        
        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
            await send(message)
        
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (time.time() - start_time) * 1000
            record_histogram(
                "http.request.duration_ms",
                duration_ms,
                tags={"method": method, "path": path, "status": str(status_code)}
            )
            
            if status_code >= 400:
                increment_counter(
                    "http.errors.total",
                    tags={"method": method, "path": path, "status": str(status_code)}
                )
