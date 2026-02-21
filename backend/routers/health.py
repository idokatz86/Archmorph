"""
Health, version, and contact routes.
"""

from fastapi import APIRouter

from version import __version__
from services import AWS_SERVICES, AZURE_SERVICES, GCP_SERVICES, CROSS_CLOUD_MAPPINGS
from service_updater import get_update_status
from api_versioning import get_api_versions
from routers.shared import ENVIRONMENT

router = APIRouter()


@router.get("/api/health")
async def health():
    update_status = get_update_status()

    # Deeper checks
    checks = {"openai": "unknown", "storage": "unknown"}

    # Check OpenAI client is reachable
    try:
        from openai_client import AZURE_OPENAI_ENDPOINT
        checks["openai"] = "configured" if AZURE_OPENAI_ENDPOINT else "not_configured"
    except Exception:
        checks["openai"] = "error"

    # Check blob storage if configured
    try:
        from usage_metrics import AZURE_STORAGE_ACCOUNT_URL, AZURE_STORAGE_CONNECTION_STRING
        if AZURE_STORAGE_ACCOUNT_URL:
            checks["storage"] = "rbac"
        elif AZURE_STORAGE_CONNECTION_STRING:
            checks["storage"] = "configured"
        else:
            checks["storage"] = "local_only"
    except Exception:
        checks["storage"] = "error"

    return {
        "status": "healthy",
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
