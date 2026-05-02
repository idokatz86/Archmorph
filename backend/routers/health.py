"""
Health, version, and contact routes.

Issue #161 — Health endpoint now performs real dependency checks and returns
``"degraded"`` or ``"unhealthy"`` when critical subsystems fail, so that
Kubernetes liveness/readiness probes can detect genuine failures.

Performance fix: dependency checks are cached for 10 seconds to avoid
blocking Redis/OpenAI connections on every request under high traffic.
"""

import time
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from version import __version__
from services import AWS_SERVICES, AZURE_SERVICES, GCP_SERVICES, CROSS_CLOUD_MAPPINGS
from service_updater import get_update_status, get_freshness
from freshness_registry import get_all as get_scheduled_jobs, is_any_stale
from api_versioning import get_api_versions
from routers.shared import ENVIRONMENT

router = APIRouter()

# ── Cached dependency checks (avoid blocking I/O on every request) ─────
_dep_checks_cache: dict | None = None
_dep_checks_ts: float = 0
_DEP_CACHE_TTL = 10  # seconds


def _run_dependency_checks() -> tuple[dict[str, str], bool, bool]:
    """Run expensive dependency probes and return (checks, degraded, unhealthy)."""
    global _dep_checks_cache, _dep_checks_ts

    now = time.monotonic()
    if _dep_checks_cache is not None and now - _dep_checks_ts < _DEP_CACHE_TTL:
        return _dep_checks_cache

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

    result = (checks, degraded, unhealthy)
    _dep_checks_cache = result
    _dep_checks_ts = now
    return result


@router.get("/api/health")
async def health():
    update_status = get_update_status()
    freshness = get_freshness()
    scheduled_jobs = get_scheduled_jobs()
    checks, degraded, unhealthy = _run_dependency_checks()

    # Issue #571 — surface catalog freshness as a first-class health signal.
    # Stale (no successful run within the budget) marks the system degraded.
    if freshness["stale"]:
        checks["service_catalog_refresh"] = (
            f"stale ({freshness['age_hours']}h > {freshness['budget_hours']}h budget)"
            if freshness["age_hours"] is not None
            else "never_ran"
        )
        degraded = True
    else:
        checks["service_catalog_refresh"] = f"fresh ({freshness['age_hours']}h)"

    if freshness["providers_failed"]:
        checks["service_catalog_providers_failed"] = ",".join(
            freshness["providers_failed"]
        )
        degraded = True
    # Issue #640 — generalised scheduled-job freshness signal. Any registered
    # job stale beyond its budget marks the system degraded; the watchdog
    # workflow polls this block and files an alert issue.
    stale_jobs = [j["name"] for j in scheduled_jobs if j["stale"]]
    if stale_jobs:
        checks["scheduled_jobs_stale"] = ",".join(stale_jobs)
        degraded = True
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
        "service_catalog_refresh": freshness,
        "scheduled_jobs": scheduled_jobs,
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
