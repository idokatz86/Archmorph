"""
Archmorph Backend API v2.11.1
Cloud Architecture Translator to Azure — Full Services Catalog
Enterprise-ready with Authentication, Analytics, AI Assistant, Roadmap, and Observability
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
import os
import logging
import time

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

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
from icons.routes import router as icon_router  # noqa: E402

# Shared state — re-exported for backward compatibility (tests import these from main)
from routers.shared import limiter, SESSION_STORE, IMAGE_STORE, SHARE_STORE  # noqa: E402

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
# Request Latency Tracking Middleware (v2.9.0)
# ─────────────────────────────────────────────────────────────
class LatencyTrackingMiddleware(BaseHTTPMiddleware):
    """Track request latencies for performance monitoring."""

    async def dispatch(self, request, call_next):
        start_time = time.perf_counter()

        response = await call_next(request)

        duration_ms = (time.perf_counter() - start_time) * 1000

        # Track latency
        try:
            endpoint = request.url.path
            method = request.method
            track_request_latency(endpoint, method, duration_ms, response.status_code)
        except Exception:  # nosec B110 - analytics must never break request handling
            pass

        # Add timing header
        response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"

        return response


app.add_middleware(LatencyTrackingMiddleware)

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)  # nosec B104 - required for Docker container networking
