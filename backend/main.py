"""
Archmorph Backend API v2.11.1
Cloud Architecture Translator to Azure — Full Services Catalog
Enterprise-ready with Authentication, Analytics, AI Assistant, Roadmap, and Observability
"""

# ── Structured JSON logging (must be configured before any logger is used) ──
from logging_config import configure_logging, correlation_id_var  # noqa: E402

configure_logging()

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
import os  # noqa: E402
import logging  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402

from slowapi import _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402

# ── Azure Monitor / Application Insights ──
APPLICATIONINSIGHTS_CONNECTION_STRING = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
if APPLICATIONINSIGHTS_CONNECTION_STRING:
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        configure_azure_monitor(connection_string=APPLICATIONINSIGHTS_CONNECTION_STRING)
        logging.getLogger(__name__).info("Application Insights telemetry enabled")
    except Exception as exc:
        logging.getLogger(__name__).warning("App Insights init failed: %s", exc)
else:
    logging.getLogger(__name__).info("APPLICATIONINSIGHTS_CONNECTION_STRING not set — telemetry disabled")

from version import __version__  # noqa: E402
from service_updater import start_scheduler, stop_scheduler  # noqa: E402
from usage_metrics import flush_metrics  # noqa: E402
from analytics import track_request_latency  # noqa: E402
from observability import (  # noqa: E402
    increment_counter as obs_increment_counter,
    record_histogram as obs_record_histogram,
)
from icons.routes import router as icon_router  # noqa: E402

# Shared state — re-exported for backward compatibility (tests import these from main)
from routers.shared import limiter, SESSION_STORE, IMAGE_STORE, SHARE_STORE  # noqa: E402, F401

# Routers
from routers.health import router as health_router  # noqa: E402
from routers.diagrams import router as diagrams_router  # noqa: E402
from routers.services import router as services_router  # noqa: E402
from routers.admin import router as admin_router  # noqa: E402
from routers.chat import router as chat_router  # noqa: E402
from routers.roadmap import router as roadmap_router  # noqa: E402
from routers.samples import router as samples_router  # noqa: E402
from routers.feedback import router as feedback_router  # noqa: E402
from routers.auth import router as auth_router  # noqa: E402
from routers.versioning import router as versioning_router  # noqa: E402
from routers.migration import router as migration_router  # noqa: E402
from routers.terraform import router as terraform_router  # noqa: E402
from routers.feature_flags import router as feature_flags_router  # noqa: E402
from routers.v1 import build_v1_router  # noqa: E402
from api_versioning import VersionMiddleware  # noqa: E402
from audit_logging import audit_logger, AuditEventType  # noqa: E402, F401

logger = logging.getLogger(__name__)

# Allowed frontend origins (production) — strictly enumerated, no wildcards
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv(
        "ALLOWED_ORIGINS",
        "https://agreeable-ground-01012c003.2.azurestaticapps.net"
    ).split(",")
    if o.strip()
]
# Add local dev origins only when running locally
if os.getenv("ENVIRONMENT", "production") == "dev":
    ALLOWED_ORIGINS += ["http://localhost:5173", "http://localhost:3000"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle manager."""
    logger.info("Starting Archmorph API %s — production mode", __version__)
    start_scheduler()

    # Auto-load built-in icon packs from samples/
    try:
        from icons.registry import load_builtin_packs, _load_from_disk

        if not _load_from_disk():
            loaded = load_builtin_packs()
            logger.info("Auto-loaded %d built-in icon packs", loaded)
        else:
            logger.info("Icon registry restored from disk")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Icon auto-load skipped: %s", exc)

    yield
    logger.info("Shutting down Archmorph API")
    stop_scheduler()
    flush_metrics()


app = FastAPI(
    title="Archmorph API",
    description="AI-powered Cloud Architecture Translator to Azure",
    version=__version__,
    lifespan=lifespan,
)

# Rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — strict origin list, minimal methods/headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
    max_age=3600,  # Cache preflight for 1 hour
)


# Security headers middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
        # Always set HSTS — behind Container Apps reverse proxy, scheme may report as HTTP
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


app.add_middleware(SecurityHeadersMiddleware)


# ─────────────────────────────────────────────────────────────
# Correlation ID Middleware
# ─────────────────────────────────────────────────────────────
class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Propagate or generate a correlation ID for every request."""

    async def dispatch(self, request: Request, call_next):
        cid = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        token = correlation_id_var.set(cid)
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = cid
            return response
        finally:
            correlation_id_var.reset(token)


app.add_middleware(CorrelationIdMiddleware)


# ─────────────────────────────────────────────────────────────
# Request Latency Tracking Middleware (v2.9.0)
# ─────────────────────────────────────────────────────────────
class LatencyTrackingMiddleware(BaseHTTPMiddleware):
    """Track request latencies for performance monitoring and observability."""

    async def dispatch(self, request, call_next):
        start_time = time.perf_counter()

        response = await call_next(request)

        duration_ms = (time.perf_counter() - start_time) * 1000

        # Structured latency log
        endpoint = request.url.path
        method = request.method
        status = response.status_code
        logger.info(
            "request completed",
            extra={
                "http_method": method,
                "http_path": endpoint,
                "http_status": status,
                "duration_ms": round(duration_ms, 2),
            },
        )

        # Track latency
        try:
            # Analytics tracking (feeds /api/admin/analytics/performance)
            track_request_latency(endpoint, method, duration_ms, status)
            # Observability tracking (feeds /api/admin/monitoring + OTel export)
            obs_increment_counter(
                "http.requests.total", tags={"method": method, "path": endpoint}
            )
            obs_record_histogram(
                "http.request.duration_ms",
                duration_ms,
                tags={
                    "method": method,
                    "path": endpoint,
                    "status": str(status),
                },
            )
            if status >= 400:
                obs_increment_counter(
                    "http.errors.total",
                    tags={
                        "method": method,
                        "path": endpoint,
                        "status": str(status),
                    },
                )
        except Exception as exc:  # nosec B110 - analytics must never break request handling
            logger.debug("middleware error: %s", exc)

        # Add timing header
        response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"

        return response


app.add_middleware(LatencyTrackingMiddleware)


# ─────────────────────────────────────────────────────────────
# Audit Logging Middleware (v2.12.0)
# ─────────────────────────────────────────────────────────────
class AuditMiddleware(BaseHTTPMiddleware):
    """Automatically audit-log every API request with latency and status."""

    # Paths that generate high volume with negligible security value
    _SKIP_PATHS = frozenset({"/health", "/api/health", "/favicon.ico", "/openapi.json", "/docs", "/redoc"})

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self._SKIP_PATHS:
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        latency_ms = (time.perf_counter() - start) * 1000

        try:
            ip = request.client.host if request.client else None
            audit_logger.log_api_access(
                endpoint=request.url.path,
                method=request.method,
                status_code=response.status_code,
                latency_ms=latency_ms,
                ip_address=ip,
            )
        except Exception as exc:  # nosec B110 - audit must never break request handling
            logger.debug("middleware error: %s", exc)

        return response


app.add_middleware(AuditMiddleware)


# ─────────────────────────────────────────────────────────────
# API Version Header Middleware
# ─────────────────────────────────────────────────────────────
app.add_middleware(VersionMiddleware)

# ─────────────────────────────────────────────────────────────
# Include Routers
# ─────────────────────────────────────────────────────────────
app.include_router(icon_router)
app.include_router(health_router)
app.include_router(diagrams_router)
app.include_router(services_router)
app.include_router(admin_router)
app.include_router(chat_router)
app.include_router(roadmap_router)
app.include_router(samples_router)
app.include_router(feedback_router)
app.include_router(auth_router)
app.include_router(versioning_router)
app.include_router(migration_router)
app.include_router(terraform_router)
app.include_router(feature_flags_router)

# ─────────────────────────────────────────────────────────────
# API v1 Versioned Routes (/api/v1/* mirrors /api/*)
# ─────────────────────────────────────────────────────────────
_all_routers = [
    (icon_router, "/api"),       # icon_router has prefix="/api"
    (health_router, ""),         # routes define /api/... in decorators
    (diagrams_router, ""),
    (services_router, ""),
    (admin_router, ""),
    (chat_router, ""),
    (roadmap_router, ""),
    (samples_router, ""),
    (feedback_router, ""),
    (auth_router, ""),
    (versioning_router, ""),
    (migration_router, ""),
    (terraform_router, ""),
    (feature_flags_router, ""),
]
v1_router = build_v1_router(_all_routers)
app.include_router(v1_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)  # nosec B104 - required for Docker container networking
