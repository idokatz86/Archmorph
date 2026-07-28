"""
Health, version, and contact routes.

Issue #161 — Health endpoint now performs real dependency checks and returns
``"degraded"`` or ``"unhealthy"`` when critical subsystems fail, so that
Kubernetes liveness/readiness probes can detect genuine failures.

Performance fix: dependency checks are cached for 10 seconds to avoid
blocking Redis/OpenAI connections on every request under high traffic.
"""

import asyncio
import logging
import os
import threading
import time
from typing import Literal

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from strict_models import StrictBaseModel

from version import __version__
from services import AWS_SERVICES, AZURE_SERVICES, GCP_SERVICES, CROSS_CLOUD_MAPPINGS
from service_updater import get_update_status, get_freshness
from freshness_registry import get_all as get_scheduled_jobs
from api_versioning import get_api_versions
from routers.shared import ENVIRONMENT, verify_api_key

router = APIRouter()
logger = logging.getLogger(__name__)


class ReadinessChecks(StrictBaseModel):
    database: Literal["ready", "unavailable"]
    database_schema: Literal["ready", "unavailable"]
    redis: Literal["ready", "unavailable"]


class ReadinessResponse(StrictBaseModel):
    status: Literal["ready", "not_ready"]
    checks: ReadinessChecks


class SchemaCompatibilityResponse(StrictBaseModel):
    status: Literal["compatible", "incompatible"]
    current_revision: str | None
    minimum_revision: str
    maximum_revision: str
    accepted_revisions: list[str]
    migration_target_revision: str
    alias_read_through_until: str

# ── Cached dependency checks (avoid blocking I/O on every request) ─────
_dep_checks_cache: dict | None = None
_dep_checks_ts: float = 0
_DEP_CACHE_TTL = 10  # seconds

_CATALOG_HEALTH_BLOB_TIMEOUT_SECONDS = float(
    os.getenv("SERVICE_CATALOG_HEALTH_BLOB_TIMEOUT_SECONDS", "3")
)
_catalog_health_blob_lock = threading.Lock()
_catalog_health_blob_running = False


def _catalog_health_from_state(*, prefer_blob: bool) -> tuple[dict, dict]:
    return get_update_status(prefer_blob=prefer_blob), get_freshness(
        prefer_blob=prefer_blob
    )


def _load_catalog_health_from_blob_once() -> tuple[dict, dict]:
    global _catalog_health_blob_running
    try:
        return _catalog_health_from_state(prefer_blob=True)
    finally:
        with _catalog_health_blob_lock:
            _catalog_health_blob_running = False


async def _catalog_health() -> tuple[dict, dict]:
    """Return durable catalog health with a bounded Blob read and disk fallback."""
    global _catalog_health_blob_running

    with _catalog_health_blob_lock:
        if _catalog_health_blob_running:
            return _catalog_health_from_state(prefer_blob=False)
        _catalog_health_blob_running = True

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_load_catalog_health_from_blob_once),
            timeout=_CATALOG_HEALTH_BLOB_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.warning(
            "Timed out loading service catalog health from blob after %.1fs; falling back to disk",
            _CATALOG_HEALTH_BLOB_TIMEOUT_SECONDS,
        )
        return _catalog_health_from_state(prefer_blob=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to load service catalog health from blob; falling back to disk: %s",
            exc,
        )
        return _catalog_health_from_state(prefer_blob=False)


def _run_dependency_checks() -> tuple[dict[str, str], bool, bool]:
    """Run expensive dependency probes and return (checks, degraded, unhealthy)."""
    global _dep_checks_cache, _dep_checks_ts

    now = time.monotonic()
    if _dep_checks_cache is not None and now - _dep_checks_ts < _DEP_CACHE_TTL:
        return _dep_checks_cache

    checks: dict[str, str] = {}
    degraded = False
    unhealthy = False

    # ── PostgreSQL (canonical durable state) ──────────────
    try:
        from database import database_readiness

        database = database_readiness()
        checks["database_readiness"] = database
        checks["database"] = "ok" if database["ready_for_production"] else "unavailable"
        if database["production_like"] and not database["ready_for_production"]:
            unhealthy = True
    except Exception:
        checks["database"] = "error"
        unhealthy = True

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
        from usage_metrics import (
            AZURE_STORAGE_ACCOUNT_URL,
            AZURE_STORAGE_CONNECTION_STRING,
            AZURE_STORAGE_MANAGED_IDENTITY_CLIENT_ID,
            METRICS_BLOB_CONTAINER,
        )
        if AZURE_STORAGE_ACCOUNT_URL or AZURE_STORAGE_CONNECTION_STRING:
            # Probe the actual container-level data path used by the app.
            # Storage Blob Data Contributor can read/write blobs but may not read
            # account-level service properties, so account-wide probes can fail
            # even when the required runtime path is healthy.
            _bsc = None
            try:
                from azure.storage.blob import BlobServiceClient
                if AZURE_STORAGE_ACCOUNT_URL:
                    from azure.identity import DefaultAzureCredential
                    _cred = DefaultAzureCredential(
                        managed_identity_client_id=(
                            AZURE_STORAGE_MANAGED_IDENTITY_CLIENT_ID or None
                        )
                    )
                    _bsc = BlobServiceClient(
                        AZURE_STORAGE_ACCOUNT_URL,
                        credential=_cred,
                    )
                else:
                    _bsc = BlobServiceClient.from_connection_string(
                        AZURE_STORAGE_CONNECTION_STRING
                    )
                container = _bsc.get_container_client(METRICS_BLOB_CONTAINER)
                container.get_container_properties(timeout=4)
                checks["storage"] = "ok"
            except Exception as exc:
                logger.warning(
                    "Storage health probe unreachable: %s: %s",
                    type(exc).__name__,
                    exc,
                )
                checks["storage"] = "unreachable"
                degraded = True
            finally:
                if _bsc is not None:
                    _bsc.close()
        else:
            checks["storage"] = "local_only"
    except Exception:
        checks["storage"] = "error"
        degraded = True

    # ── Redis (optional unless REQUIRE_REDIS/ENFORCE_REDIS is set) ────────
    try:
        from session_store import (
            redis_configured,
            session_store_readiness,
        )
        redis_readiness = session_store_readiness()
        redis_required = bool(redis_readiness["require_redis"])
        if redis_configured():
            if redis_readiness["redis_reachable"]:
                checks["redis"] = "ok"
            else:
                logger.warning(
                    "Redis health probe unreachable (error_type=%s)",
                    redis_readiness.get("redis_error") or "unknown",
                )
                checks["redis"] = "unreachable"
                if redis_required:
                    unhealthy = True
                else:
                    degraded = True
        else:
            checks["redis"] = "missing_required" if redis_required else "disabled_optional"
            if redis_required:
                unhealthy = True
        checks["redis_readiness"] = redis_readiness
    except Exception:
        checks["redis"] = "error"
        unhealthy = True

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


@router.get("/healthz")
async def healthz():
    """Anonymous minimal liveness probe — returns alive/dead only.

    Safe to call without credentials; used by infrastructure probes (#844).
    Contains no sensitive dependency details.
    """
    return JSONResponse(content={"status": "alive"})


@router.get(
    "/readyz",
    response_model=ReadinessResponse,
    responses={
        200: {
            "description": "Required PostgreSQL and Redis dependencies are ready",
            "content": {
                "application/json": {
                    "example": {
                        "status": "ready",
                        "checks": {
                            "database": "ready",
                            "database_schema": "ready",
                            "redis": "ready",
                        },
                    }
                }
            },
        },
        503: {
            "model": ReadinessResponse,
            "description": "A required dependency is unavailable",
            "content": {
                "application/json": {
                    "example": {
                        "status": "not_ready",
                        "checks": {
                            "database": "unavailable",
                            "database_schema": "unavailable",
                            "redis": "unavailable",
                        },
                    }
                }
            },
        },
    },
)
async def readyz(response: Response) -> ReadinessResponse:
    """Anonymous sanitized readiness for required PostgreSQL and Redis."""
    database_ready = False
    database_schema_ready = False
    redis_ready = False
    try:
        from database import database_readiness

        database = database_readiness()
        database_ready = bool(database["ready_for_production"])
        database_schema_ready = bool(
            database["schema_at_head"] and database["required_schema_present"]
        )
    except Exception:
        database_ready = False
        database_schema_ready = False
    try:
        from session_store import session_store_readiness

        redis = session_store_readiness()
        redis_ready = bool(redis["ready_for_horizontal_scale"])
    except Exception:
        redis_ready = False

    ready = database_ready and redis_ready
    response.status_code = 200 if ready else 503
    return ReadinessResponse(
        status="ready" if ready else "not_ready",
        checks=ReadinessChecks(
            database="ready" if database_ready else "unavailable",
            database_schema="ready" if database_schema_ready else "unavailable",
            redis="ready" if redis_ready else "unavailable",
        ),
    )


@router.get(
    "/api/schema-compatibility",
    response_model=SchemaCompatibilityResponse,
    responses={
        200: {"description": "This application revision supports the current database schema"},
        409: {
            "model": SchemaCompatibilityResponse,
            "description": "This application revision cannot safely serve the current database schema",
        },
    },
)
async def schema_compatibility(response: Response) -> SchemaCompatibilityResponse:
    """Sanitized activation preflight for green and rollback revisions."""
    from database import database_readiness
    from schema_compatibility import schema_is_supported, supported_schema_metadata

    metadata = supported_schema_metadata()
    try:
        readiness = database_readiness()
        current_revision = readiness.get("current_revision")
        compatible = bool(
            readiness.get("postgres_configured")
            and readiness.get("connection_ok")
            and readiness.get("required_schema_present")
            and schema_is_supported(current_revision)
        )
    except Exception:
        current_revision = None
        compatible = False
    response.status_code = 200 if compatible else 409
    return SchemaCompatibilityResponse(
        status="compatible" if compatible else "incompatible",
        current_revision=current_revision if isinstance(current_revision, str) else None,
        minimum_revision=str(metadata["minimum_revision"]),
        maximum_revision=str(metadata["maximum_revision"]),
        accepted_revisions=[str(item) for item in metadata["accepted_revisions"]],
        migration_target_revision=str(metadata["migration_target_revision"]),
        alias_read_through_until=str(metadata["alias_read_through_until"]),
    )


@router.get("/api/health")
async def health(_auth=Depends(verify_api_key)):
    update_status, freshness = await _catalog_health()
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
