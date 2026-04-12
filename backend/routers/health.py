"""
Health, version, and contact routes.

Issue #161 — Health endpoint now performs real dependency checks and returns
``"degraded"`` or ``"unhealthy"`` when critical subsystems fail, so that
Kubernetes liveness/readiness probes can detect genuine failures.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from version import __version__
from services import AWS_SERVICES, AZURE_SERVICES, GCP_SERVICES, CROSS_CLOUD_MAPPINGS
from service_updater import get_update_status
from api_versioning import get_api_versions
from routers.shared import ENVIRONMENT

router = APIRouter()


@router.get("/api/health")
async def health():
    update_status = get_update_status()

    # Track dependency health — each check sets ("ok"|"degraded"|"error", detail)
    checks: dict[str, str] = {}
    degraded = False
    unhealthy = False

    # ── OpenAI client ─────────────────────────────────────
    try:
        from openai_client import AZURE_OPENAI_ENDPOINT, get_openai_client
        if not AZURE_OPENAI_ENDPOINT:
            checks["openai"] = "not_configured"
            degraded = True
        else:
            # Verify client can be instantiated (catches bad creds at startup)
            client = get_openai_client()
            checks["openai"] = "ok" if client else "error"
            if not client:
                degraded = True
    except Exception:
        checks["openai"] = "error"
        degraded = True

    # ── Blob storage ──────────────────────────────────────
    try:
        from usage_metrics import AZURE_STORAGE_ACCOUNT_URL, AZURE_STORAGE_CONNECTION_STRING
        if AZURE_STORAGE_ACCOUNT_URL:
            checks["storage"] = "ok"
        elif AZURE_STORAGE_CONNECTION_STRING:
            checks["storage"] = "ok"
        else:
            checks["storage"] = "local_only"
    except Exception:
        checks["storage"] = "error"
        degraded = True

    # ── Redis (if configured) ─────────────────────────────
    try:
        from session_store import redis_configured, _create_redis_client
        if redis_configured():
            _create_redis_client(socket_connect_timeout=2)
            checks["redis"] = "ok"
        else:
            checks["redis"] = "not_configured"
    except Exception:
        checks["redis"] = "error"
        # Redis failure degrades session persistence but app still works with in-memory store
        degraded = True

    # ── Service catalog sanity ────────────────────────────
    catalog_ok = len(AWS_SERVICES) > 0 and len(AZURE_SERVICES) > 0 and len(CROSS_CLOUD_MAPPINGS) > 0
    checks["service_catalog"] = "ok" if catalog_ok else "empty"
    if not catalog_ok:
        unhealthy = True

    # ── Circuit breakers (#506) ────────────────────────────
    try:
        from circuit_breakers import get_breaker_status, is_healthy as breakers_healthy
        checks["circuit_breakers"] = get_breaker_status()
        if not breakers_healthy():
            unhealthy = True
    except Exception:
        checks["circuit_breakers"] = "import_error"

    # ── Determine overall status ──────────────────────────
    if unhealthy:
        status = "unhealthy"
        http_status = 503
    elif degraded:
        status = "degraded"
        http_status = 200   # degraded is still serving, but k8s readiness can key on body
    else:
        status = "healthy"
        http_status = 200

    body = {
        "status": status,
        "version": __version__,
        "environment": ENVIRONMENT,
        "mode": "production",
        "checks": checks,
        "service_catalog": {
            "aws": len(AWS_SERVICES),
            "azure": len(AZURE_SERVICES),
            "gcp": len(GCP_SERVICES),
            "mappings": len(CROSS_CLOUD_MAPPINGS),
        },
        "last_service_update": update_status.get("last_check"),
        "scheduler_running": update_status.get("scheduler_running", False),
    }

    return JSONResponse(content=body, status_code=http_status)


@router.get("/api/versions")
async def api_versions():
    """Get information about API versions."""
    return get_api_versions()


@router.get("/api/contact")
async def contact_info():
    """Return contact information."""
    return {
        "project": "Archmorph",
        "github": "https://github.com/idokatz86/Archmorph",
        "issues": "https://github.com/idokatz86/Archmorph/issues",
        "documentation": "https://github.com/idokatz86/Archmorph#readme",
    }
