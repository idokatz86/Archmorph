"""
Archmorph Observability Module  (Issue #71 — consolidated metrics)

Single source of truth for distributed tracing and metrics.
Uses the real OpenTelemetry SDK with Azure Monitor exporter when
``APPLICATIONINSIGHTS_CONNECTION_STRING`` is set (configured in main.py
via ``azure-monitor-opentelemetry``).

In-memory ``_metrics`` dict is retained so the admin monitoring dashboard
(``/api/admin/monitoring``, ``/api/admin/observability``) keeps working
without an external telemetry backend.
"""

import logging
import time
from typing import Dict, Any, Optional, Callable
from functools import wraps
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# ── OpenTelemetry SDK integration ─────────────────────────────
# The OTel *API* is always safe to call — if no SDK/exporter is
# configured the calls are silent no-ops.  The SDK is wired up by
# ``configure_azure_monitor()`` in main.py when the connection
# string env-var is present.
try:
    from opentelemetry import trace as _otel_trace
    from opentelemetry import metrics as _otel_metrics

    _tracer = _otel_trace.get_tracer("archmorph", "1.0.0")
    _meter = _otel_metrics.get_meter("archmorph", "1.0.0")
    _OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _otel_trace = None  # type: ignore[assignment]
    _otel_metrics = None  # type: ignore[assignment]
    _tracer = None
    _meter = None
    _OTEL_AVAILABLE = False
    logger.info("OpenTelemetry not installed — in-memory metrics only")


# ── Lazy OTel instrument registries ───────────────────────────
_otel_counters: Dict[str, Any] = {}
_otel_histograms: Dict[str, Any] = {}


def _get_otel_counter(name: str):
    """Get or lazily create an OTel Counter instrument."""
    if not _OTEL_AVAILABLE or _meter is None:
        return None
    if name not in _otel_counters:
        _otel_counters[name] = _meter.create_counter(name, description=f"Counter: {name}")
    return _otel_counters[name]


def _get_otel_histogram(name: str):
    """Get or lazily create an OTel Histogram instrument."""
    if not _OTEL_AVAILABLE or _meter is None:
        return None
    if name not in _otel_histograms:
        _otel_histograms[name] = _meter.create_histogram(name, description=f"Histogram: {name}")
    return _otel_histograms[name]


# ── In-memory metrics (admin dashboard) ──────────────────────
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
    """
    Span context for tracing.

    Wraps a real OpenTelemetry span when the SDK is configured,
    and always records duration in the in-memory histogram.
    """

    def __init__(
        self,
        name: str,
        attributes: Optional[Dict[str, str]] = None,
        _otel_span: Any = None,
    ):
        self.name = name
        self.attributes = attributes or {}
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.status = "OK"
        self.events: list = []
        self._otel_span = _otel_span

    def add_event(self, name: str, attributes: Optional[Dict[str, str]] = None):
        """Add an event to the span."""
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes or {},
        })
        if self._otel_span is not None:
            self._otel_span.add_event(name, attributes=attributes or {})

    def set_status(self, status: str, message: str = ""):
        """Set span status."""
        self.status = status
        if message:
            self.attributes["status_message"] = message
        if self._otel_span is not None and status == "ERROR" and _otel_trace is not None:
            self._otel_span.set_status(_otel_trace.StatusCode.ERROR, message)

    def end(self):
        """End the span."""
        self.end_time = time.time()
        duration_ms = (self.end_time - self.start_time) * 1000

        # Record duration in in-memory histogram (and OTel via record_histogram)
        record_histogram(f"span.{self.name}.duration_ms", duration_ms)

        # Finish the real OTel span
        if self._otel_span is not None:
            self._otel_span.end()

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Span completed: %s (%.2fms) status=%s",
                self.name, duration_ms, self.status,
            )


@contextmanager
def trace_span(name: str, attributes: Optional[Dict[str, str]] = None):
    """
    Context manager for creating a trace span.

    Creates a real OpenTelemetry span when the SDK is available.

    Args:
        name: Span name
        attributes: Optional span attributes

    Yields:
        SpanContext object
    """
    otel_span = None
    if _OTEL_AVAILABLE and _tracer is not None:
        otel_span = _tracer.start_span(name, attributes=attributes or {})

    span = SpanContext(name, attributes, _otel_span=otel_span)
    try:
        yield span
    except Exception as e:
        span.set_status("ERROR", str(e))
        raise
    finally:
        span.end()


def traced(name: Optional[str] = None):
    """
    Decorator to trace a function with OpenTelemetry spans.

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
# Metrics Functions  (dual-write: in-memory + OTel)
# ─────────────────────────────────────────────────────────────

def increment_counter(name: str, value: int = 1, tags: Optional[Dict[str, str]] = None):
    """
    Increment a counter metric.

    Writes to the in-memory store (admin dashboard) **and** to an
    OpenTelemetry Counter instrument (Azure Monitor export).
    """
    # ── in-memory ──
    key = _make_metric_key(name, tags)
    if key not in _metrics["counters"]:
        _metrics["counters"][key] = {"name": name, "tags": tags or {}, "value": 0}
    _metrics["counters"][key]["value"] += value

    # ── OTel ──
    otel_counter = _get_otel_counter(name)
    if otel_counter is not None:
        otel_counter.add(value, attributes=tags or {})


def record_histogram(name: str, value: float, tags: Optional[Dict[str, str]] = None):
    """
    Record a value in a histogram metric.

    Writes to the in-memory store (admin dashboard) **and** to an
    OpenTelemetry Histogram instrument (Azure Monitor export).
    """
    # ── in-memory ──
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

    # ── OTel ──
    otel_hist = _get_otel_histogram(name)
    if otel_hist is not None:
        otel_hist.record(value, attributes=tags or {})


def set_gauge(name: str, value: float, tags: Optional[Dict[str, str]] = None):
    """
    Set a gauge metric value.

    In-memory only — serves the admin monitoring dashboard.
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
    Get all in-memory metrics for the admin dashboard.

    Returns:
        Dictionary with counters, histograms, and gauges.
    """
    result: Dict[str, Any] = {
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
    ASGI middleware for HTTP request tracing and metrics.

    Creates real OpenTelemetry spans when the SDK is configured **and**
    records request count / latency / error counters in the in-memory
    store for the admin monitoring dashboard.
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

        # Track request counter
        increment_counter("http.requests.total", tags={"method": method, "path": path})

        status_code = 200

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
            await send(message)

        # Create an OTel span for the HTTP request
        otel_span = None
        if _OTEL_AVAILABLE and _tracer is not None:
            otel_span = _tracer.start_span(
                f"{method} {path}",
                attributes={"http.method": method, "http.target": path},
            )

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            status_code = 500
            raise
        finally:
            duration_ms = (time.time() - start_time) * 1000
            record_histogram(
                "http.request.duration_ms",
                duration_ms,
                tags={"method": method, "path": path, "status": str(status_code)},
            )

            if status_code >= 400:
                increment_counter(
                    "http.errors.total",
                    tags={"method": method, "path": path, "status": str(status_code)},
                )

            if otel_span is not None:
                otel_span.set_attribute("http.status_code", status_code)
                otel_span.set_attribute("http.response_time_ms", duration_ms)
                if status_code >= 400 and _otel_trace is not None:
                    otel_span.set_status(
                        _otel_trace.StatusCode.ERROR, f"HTTP {status_code}",
                    )
                otel_span.end()
