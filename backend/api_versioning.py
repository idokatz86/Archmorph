"""
Archmorph API Versioning Module

Provides API versioning infrastructure with backward compatibility support.
"""

from fastapi import APIRouter
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

# API Version Constants
API_V1 = "v1"
API_V2 = "v2"
CURRENT_VERSION = API_V1
SUPPORTED_VERSIONS = [API_V1]
DEPRECATED_VERSIONS = []

# Version metadata
VERSION_INFO: Dict[str, Dict[str, Any]] = {
    API_V1: {
        "version": "1.0.0",
        "status": "stable",
        "released": "2026-02-21",
        "sunset": None,
        "changes": [
            "Initial versioned API release",
            "All existing endpoints migrated to /api/v1/",
            "Full backward compatibility with /api/ endpoints",
        ],
    },
}


def get_api_versions() -> Dict[str, Any]:
    """
    Get information about all API versions.
    
    Returns:
        Dictionary with version information and deprecation notices.
    """
    return {
        "current_version": CURRENT_VERSION,
        "supported_versions": SUPPORTED_VERSIONS,
        "deprecated_versions": DEPRECATED_VERSIONS,
        "versions": VERSION_INFO,
        "migration_guide": "https://archmorph.io/docs/api-migration",
    }


def create_versioned_router(version: str, prefix: str = "") -> APIRouter:
    """
    Create a versioned API router.
    
    Args:
        version: API version (e.g., "v1", "v2")
        prefix: Additional prefix after version
        
    Returns:
        Configured APIRouter with version prefix.
    """
    full_prefix = f"/api/{version}{prefix}"
    return APIRouter(
        prefix=full_prefix,
        tags=[f"API {version.upper()}"],
    )


class VersionMiddleware:
    """
    ASGI middleware to add API version headers to every response.

    Headers added:
        X-API-Version   – resolved version (e.g., "v1")
        X-API-Deprecated – "true" if the resolved version is deprecated
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")

            # Determine the API version from the URL path
            resolved_version = CURRENT_VERSION  # default for unversioned /api/*
            deprecated = False

            for ver in SUPPORTED_VERSIONS + DEPRECATED_VERSIONS:
                if path.startswith(f"/api/{ver}/") or path == f"/api/{ver}":
                    resolved_version = ver
                    deprecated = ver in DEPRECATED_VERSIONS
                    break

            async def send_wrapper(message):
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.append(
                        (b"x-api-version", resolved_version.encode())
                    )
                    headers.append(
                        (b"x-api-deprecated", b"true" if deprecated else b"false")
                    )
                    message["headers"] = headers
                await send(message)

            await self.app(scope, receive, send_wrapper)
        else:
            await self.app(scope, receive, send)
