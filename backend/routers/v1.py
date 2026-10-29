"""Explicit API v1 router aggregation.

Only routers listed by the application are mirrored.  Core public routers are
stable v1 APIs; legacy, admin, beta, and scaffold routers are temporary
compatibility aliases and emit deprecation/sunset headers.
"""

import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Callable, List, Literal, Protocol, Tuple, Union

from fastapi import APIRouter, Request, routing as fastapi_routing
from fastapi.routing import APIRoute
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import BaseRoute

logger = logging.getLogger(__name__)

V1_COMPATIBILITY_SUNSET = "Thu, 15 Oct 2026 00:00:00 GMT"


class APIRouteView(Protocol):
    """Route attributes exposed by both APIRoute and FastAPI RouteContext."""

    path: str
    path_format: str
    path_regex: Any
    methods: set[str] | None
    endpoint: Callable[..., Any] | None
    name: str | None
    tags: list[Any] | None
    summary: str | None
    description: str
    deprecated: bool | None
    response_model: Any
    status_code: int | None
    dependencies: list[Any]
    response_description: str
    responses: dict[int | str, dict[str, Any]]
    response_class: Any
    callbacks: list[Any] | None
    include_in_schema: bool
    openapi_extra: dict[str, Any] | None
    dependant: Any


def iter_api_route_contexts(routes: Sequence[BaseRoute]) -> Iterator[APIRouteView]:
    """Iterate effective API routes across eager and lazy FastAPI routers."""
    route_context_iterator = getattr(fastapi_routing, "iter_route_contexts", None)
    if route_context_iterator is None:
        for route in routes:
            if isinstance(route, APIRoute):
                yield route
            elif getattr(route, "original_router", None) is not None:
                raise RuntimeError(
                    "FastAPI lazy router contexts are unavailable; update "
                    "iter_api_route_contexts for this FastAPI version"
                )
        return

    for route_context in route_context_iterator(routes):
        if isinstance(getattr(route_context, "original_route", None), APIRoute):
            yield route_context


@dataclass(frozen=True)
class V1RouterSpec:
    """Declare whether a router belongs to stable v1 or compatibility v1."""

    router: APIRouter
    prefix: str = ""
    stability: Literal["public", "compatibility"] = "public"
    rationale: str = ""

    def __post_init__(self) -> None:
        if self.stability == "compatibility" and not self.rationale.strip():
            raise ValueError("Compatibility v1 routers require a rationale")


class V1CompatibilityHeadersMiddleware(BaseHTTPMiddleware):
    """Advertise compatibility status on regular and streaming responses."""

    def __init__(self, app, *, compatibility_routes: tuple[APIRoute, ...]):
        super().__init__(app)
        self._compatibility_routes = compatibility_routes

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api/v1/"):
            return await call_next(request)

        response = await call_next(request)
        is_compatibility = any(
            request.method in (route.methods or ())
            and route.path_regex.fullmatch(request.url.path)
            for route in self._compatibility_routes
        )
        if is_compatibility:
            response.headers["Deprecation"] = "true"
            response.headers["Sunset"] = V1_COMPATIBILITY_SUNSET
        return response


def build_v1_router(
    route_specs: List[Union[V1RouterSpec, Tuple[APIRouter, str]]],
) -> APIRouter:
    """Build v1 routes from an explicit, classified router specification."""
    v1_router = APIRouter()
    mirrored = 0
    compatibility = 0
    seen_method_paths: dict[tuple[str, str], str] = {}

    for raw_spec in route_specs:
        # Preserve the small builder's historical tuple API for isolated tests
        # and external callers; the application itself must pass classified specs.
        spec = raw_spec if isinstance(raw_spec, V1RouterSpec) else V1RouterSpec(*raw_spec)
        for route in iter_api_route_contexts(spec.router.routes):
            # Compute the effective path (router prefix + decorator path)
            effective_path = spec.prefix + route.path

            # Only mirror /api/* routes; skip anything already under /api/v1/
            if not effective_path.startswith("/api/"):
                continue
            if effective_path.startswith("/api/v1/"):
                continue

            if route.endpoint is None:
                raise RuntimeError(f"API route {route.path} has no endpoint")
            endpoint_module = getattr(
                route.endpoint,
                "__module__",
                type(route.endpoint).__name__,
            )

            # /api/foo → /api/v1/foo
            v1_path = "/api/v1" + effective_path[4:]
            methods = set(route.methods or ()) - {"HEAD", "OPTIONS"}
            for method in methods:
                key = (v1_path, method)
                if key in seen_method_paths:
                    raise RuntimeError(
                        f"Duplicate v1 route {method} {v1_path} from "
                        f"{seen_method_paths[key]} and {endpoint_module}"
                    )
                seen_method_paths[key] = endpoint_module

            is_compatibility = spec.stability == "compatibility"
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
                responses=route.responses,
                response_class=route.response_class,
                callbacks=route.callbacks,
                include_in_schema=route.include_in_schema,
                openapi_extra=route.openapi_extra,
            )
            mirrored_route = v1_router.routes[-1]
            setattr(mirrored_route, "_archmorph_v1_compatibility", is_compatibility)
            mirrored += 1
            compatibility += int(is_compatibility)

    logger.info(
        "Mirrored %d explicit routes under /api/v1/ (%d compatibility)",
        mirrored,
        compatibility,
    )
    return v1_router
