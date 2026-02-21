"""
API v1 Router Aggregator

Automatically mirrors all /api/* routes under /api/v1/* to support
versioned API access while maintaining backward compatibility.

Strategy:
  - /api/*    → unversioned (always points to latest = v1)
  - /api/v1/* → explicitly versioned v1 endpoints (same handlers)

All existing /api/* routes continue working unchanged.
"""

from fastapi import APIRouter
from fastapi.routing import APIRoute
from typing import List, Tuple
import logging

logger = logging.getLogger(__name__)


def build_v1_router(
    routers_with_prefixes: List[Tuple[APIRouter, str]],
) -> APIRouter:
    """
    Build a v1 API router that mirrors all /api/* routes under /api/v1/*.

    Args:
        routers_with_prefixes: List of (router, prefix) tuples where prefix
            is the router's own prefix (e.g., "/api" for icon_router, "" for others).

    Returns:
        APIRouter containing all mirrored v1 routes.
    """
    v1_router = APIRouter()
    mirrored = 0

    for router, prefix in routers_with_prefixes:
        for route in router.routes:
            if not isinstance(route, APIRoute):
                continue

            # Compute the effective path (router prefix + decorator path)
            effective_path = prefix + route.path

            # Only mirror /api/* routes; skip anything already under /api/v1/
            if not effective_path.startswith("/api/"):
                continue
            if effective_path.startswith("/api/v1/"):
                continue

            # /api/foo → /api/v1/foo
            v1_path = "/api/v1" + effective_path[4:]

            v1_router.add_api_route(
                path=v1_path,
                endpoint=route.endpoint,
                methods=route.methods,
                name=f"{route.name}_v1" if route.name else None,
                tags=list(route.tags or []) + ["v1"],
                summary=route.summary,
                description=route.description,
                deprecated=route.deprecated,
                response_model=route.response_model,
                status_code=route.status_code,
                dependencies=route.dependencies,
                response_description=route.response_description,
            )
            mirrored += 1

    logger.info("Mirrored %d routes under /api/v1/", mirrored)
    return v1_router
