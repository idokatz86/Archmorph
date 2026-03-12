"""
Archmorph Backend API v3.0.0
Cloud Architecture Translator to Azure — Full Services Catalog
Enterprise-ready with Authentication, Analytics, AI Assistant, Roadmap, and Observability
"""

# ── Structured JSON logging (must be configured before any logger is used) ──
from logging_config import configure_logging, correlation_id_var  # noqa: E402

configure_logging()

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from starlette.middleware.gzip import GZipMiddleware  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
import os  # noqa: E402
import logging  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
import concurrent.futures  # noqa: E402
import asyncio  # noqa: E402

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

from database import init_db  # noqa: E402
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
from routers.analysis import router as analysis_router  # noqa: E402
from routers.iac_routes import router as iac_routes_router  # noqa: E402
from routers.hld_routes import router as hld_routes_router
from routers.agents import router as agents_router  # noqa: E402
from routers.executions import router as executions_router  # noqa: E402
from routers.agent_memory import router as agent_memory_router  # noqa: E402
from routers.policies import router as policies_router  # noqa: E402
from routers.models import router as models_router  # noqa: E402
from routers.insights import router as insights_router  # noqa: E402
from routers.sharing import router as sharing_router  # noqa: E402
from routers.infra import router as infra_router  # noqa: E402
from routers.suggestions import router as suggestions_router  # noqa: E402
from routers.services import router as services_router  # noqa: E402
from routers.admin import router as admin_router  # noqa: E402
from routers.chat import router as chat_router  # noqa: E402
from routers.roadmap import router as roadmap_router  # noqa: E402
from routers.samples import router as samples_router  # noqa: E402
from routers.feedback import router as feedback_router  # noqa: E402
from routers.auth import router as auth_router  # noqa: E402
from routers.versioning import router as versioning_router  # noqa: E402
from routers.terraform import router as terraform_router  # noqa: E402
from routers.feature_flags import router as feature_flags_router  # noqa: E402
from routers.privacy import router as privacy_router  # noqa: E402
from routers.jobs import router as jobs_router  # noqa: E402
from routers.credentials import router as credentials_router  # noqa: E402
from routers.tf_backend import router as tf_backend_router  # noqa: E402
from routers.drift import router as drift_router  # noqa: E402
from routers.scanner_routes import router as scanner_router  # noqa: E402
from routers.deploy import router as deploy_router  # noqa: E402
from routers.legal import router as legal_router  # noqa: E402
from routers.v1 import build_v1_router  # noqa: E402
from api_versioning import VersionMiddleware  # noqa: E402
from audit_logging import audit_logger, AuditEventType  # noqa: E402, F401
from error_envelope import register_error_handlers  # noqa: E402

logger = logging.getLogger(__name__)

# Allowed frontend origins (production) — strictly enumerated, no wildcards
env_origins = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if o.strip()
]
default_origins = [
    "https://archmorphai.com",
    "https://www.archmorphai.com",
    "https://agreeable-ground-01012c003.2.azurestaticapps.net"
]
ALLOWED_ORIGINS = list(set(env_origins + default_origins))

# Add local dev origins only when running locally
if os.getenv("ENVIRONMENT", "production") == "dev":
    ALLOWED_ORIGINS.extend(["http://localhost:5173", "http://localhost:3000"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle manager."""
    logger.info("Starting Archmorph API %s — production mode", __version__)
    start_scheduler()

    # ── Parallel startup tasks: DB init + icon loading (#337 cold-start) ──
    async def _init_database():
        try:
            await asyncio.to_thread(init_db)
            logger.info("Database layer initialized")
        except Exception as exc:
            logger.warning("Database init failed (non-fatal, in-memory stores used): %s", exc)

    async def _init_icons():
        try:
            from icons.registry import load_builtin_packs, _load_from_disk
            if not await asyncio.to_thread(_load_from_disk):
                loaded = await asyncio.to_thread(load_builtin_packs)
                logger.info("Auto-loaded %d built-in icon packs", loaded)
            else:
                logger.info("Icon registry restored from disk")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Icon auto-load skipped: %s", exc)

    await asyncio.gather(_init_database(), _init_icons())

    # ── Thread pool sizing (#177) ──
    # GPT vision calls use asyncio.to_thread() which shares the default executor.
    # Default pool is min(32, os.cpu_count()+4) — too low for I/O-bound GPT calls
    # that can block 5-30s each.  Size for 4 workers × ~8 concurrent GPT calls.
    _THREAD_POOL_SIZE = int(os.getenv("THREAD_POOL_SIZE", "40"))
    _executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=_THREAD_POOL_SIZE,
        thread_name_prefix="archmorph-worker",
    )
    asyncio.get_event_loop().set_default_executor(_executor)
    logger.info("Thread pool configured: %d workers", _THREAD_POOL_SIZE)

    yield
    logger.info("Shutting down Archmorph API")
    stop_scheduler()
    flush_metrics()
    _executor.shutdown(wait=False)


app = FastAPI(
    title="Archmorph API",
    description="AI-powered Cloud Architecture Translator to Azure",
    version=__version__,
    lifespan=lifespan,
)

# Issue #174 — Standardized error envelope for all 4xx/5xx responses
register_error_handlers(app)

# Rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — strict origin list, minimal methods/headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
    max_age=3600,  # Cache preflight for 1 hour
)


# ─────────────────────────────────────────────────────────────
# Consolidated Request Middleware (#177 — perf: 4→1 ASGI layers)
# Combines: security headers, correlation ID, latency tracking,
# and audit logging into a single BaseHTTPMiddleware dispatch.
# ─────────────────────────────────────────────────────────────
class ArchmorphMiddleware(BaseHTTPMiddleware):
    """Single middleware layer for cross-cutting concerns.

    Eliminates 4× BaseHTTPMiddleware wrapping overhead by merging
    SecurityHeaders, CorrelationId, LatencyTracking, and Audit into one.
    """

    _AUDIT_SKIP = frozenset({
        "/health", "/api/health", "/favicon.ico",
        "/openapi.json", "/docs", "/redoc",
    })

    async def dispatch(self, request: Request, call_next):
        # ── Correlation ID ──
        cid = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        token = correlation_id_var.set(cid)

        start_time = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            correlation_id_var.reset(token)

        duration_ms = (time.perf_counter() - start_time) * 1000

        # ── Security Headers (#377) ──
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Correlation-ID"] = cid
        response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"

        # ── Latency Tracking ──
        endpoint = request.url.path
        method = request.method
        status = response.status_code

        # ── Cache-Control for read-only endpoints (#376) ──
        if method == "GET" and 200 <= status < 300:
            if "/services" in endpoint or "/roadmap" in endpoint:
                response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=60"
            elif "/health" in endpoint:
                response.headers["Cache-Control"] = "no-cache"
            elif "/cost-estimate" in endpoint or "/cost-breakdown" in endpoint:
                response.headers["Cache-Control"] = "private, max-age=120"
            elif "/best-practices" in endpoint or "/compliance" in endpoint:
                response.headers["Cache-Control"] = "private, max-age=600"

        logger.info(
            "request completed",
            extra={
                "http_method": method,
                "http_path": endpoint,
                "http_status": status,
                "duration_ms": round(duration_ms, 2),
            },
        )

        try:
            track_request_latency(endpoint, method, duration_ms, status)
            obs_increment_counter(
                "http.requests.total", tags={"method": method, "path": endpoint}
            )
            obs_record_histogram(
                "http.request.duration_ms",
                duration_ms,
                tags={"method": method, "path": endpoint, "status": str(status)},
            )
            if status >= 400:
                obs_increment_counter(
                    "http.errors.total",
                    tags={"method": method, "path": endpoint, "status": str(status)},
                )
        except Exception as exc:  # nosec B110 - analytics must never break request handling
            logger.debug("middleware error: %s", exc)

        # ── Audit Logging ──
        if endpoint not in self._AUDIT_SKIP:
            try:
                ip = request.client.host if request.client else None
                audit_logger.log_api_access(
                    endpoint=endpoint,
                    method=method,
                    status_code=status,
                    latency_ms=duration_ms,
                    ip_address=ip,
                )
            except Exception as exc:  # nosec B110 - audit must never break request handling
                logger.debug("audit error: %s", exc)

        return response


app.add_middleware(ArchmorphMiddleware)


# ─────────────────────────────────────────────────────────────
# API Version Header Middleware
# ─────────────────────────────────────────────────────────────
app.add_middleware(VersionMiddleware)

# ─────────────────────────────────────────────────────────────
# GZip Response Compression (Issue #181)
# Compress JSON responses > 1 KB — ~80-90% payload reduction
# ─────────────────────────────────────────────────────────────
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ─────────────────────────────────────────────────────────────
# Include Routers
# ─────────────────────────────────────────────────────────────
app.include_router(icon_router)
app.include_router(health_router)
app.include_router(diagrams_router)
app.include_router(analysis_router)
app.include_router(iac_routes_router)
app.include_router(hld_routes_router)
app.include_router(agents_router)
app.include_router(executions_router)
app.include_router(agent_memory_router)
app.include_router(policies_router)
app.include_router(models_router)
app.include_router(insights_router)
app.include_router(sharing_router)
app.include_router(infra_router)
app.include_router(suggestions_router)
app.include_router(services_router)
app.include_router(admin_router)
app.include_router(chat_router)
app.include_router(roadmap_router)
app.include_router(samples_router)
app.include_router(feedback_router)
app.include_router(auth_router)
app.include_router(versioning_router)
app.include_router(terraform_router)
app.include_router(feature_flags_router)
app.include_router(privacy_router)
app.include_router(jobs_router)
app.include_router(credentials_router)
app.include_router(tf_backend_router)
app.include_router(drift_router)
app.include_router(scanner_router)
app.include_router(deploy_router)
app.include_router(legal_router)

# ─────────────────────────────────────────────────────────────
# API v1 Versioned Routes (/api/v1/* mirrors /api/*)
# ─────────────────────────────────────────────────────────────
_all_routers = [
    (icon_router, "/api"),       # icon_router has prefix="/api"
    (health_router, ""),         # routes define /api/... in decorators
    (diagrams_router, ""),
    (analysis_router, ""),
    (iac_routes_router, ""),
    (hld_routes_router, ""),
    (agents_router, ""),
    (executions_router, ""),
    (agent_memory_router, ""),
    (policies_router, ""),
    (models_router, ""),
    (insights_router, ""),
    (sharing_router, ""),
    (infra_router, ""),
    (suggestions_router, ""),
    (services_router, ""),
    (admin_router, ""),
    (chat_router, ""),
    (roadmap_router, ""),
    (samples_router, ""),
    (feedback_router, ""),
    (auth_router, ""),
    (versioning_router, ""),
    (terraform_router, ""),
    (feature_flags_router, ""),
    (privacy_router, ""),
    (jobs_router, ""),
    (credentials_router, ""), 
    (scanner_router, ""), 
    (deploy_router, ""),
    (credentials_router, ""),
]
v1_router = build_v1_router(_all_routers)
app.include_router(v1_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)  # nosec B104 # noqa: S104 - required for Docker container networking
