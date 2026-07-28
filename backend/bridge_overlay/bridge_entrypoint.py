"""Wrap the pre-014 application with a bounded schema bridge contract."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from fastapi.responses import JSONResponse

import job_queue


async def _bridge_worker_start() -> dict[str, list]:
    """Do not claim/recover durable jobs while the bridge spans two schemas."""
    return {"recovered": [], "failed": []}


async def _bridge_worker_stop() -> None:
    return None


job_queue.durable_job_worker.start = _bridge_worker_start
job_queue.durable_job_worker.stop = _bridge_worker_stop

from main import ArchmorphMiddleware, app  # noqa: E402


ArchmorphMiddleware._ORIGIN_LOCK_SKIP = frozenset(
    {*ArchmorphMiddleware._ORIGIN_LOCK_SKIP, "/readyz", "/api/schema-compatibility"}
)
_BRIDGE_PATHS = frozenset({"/healthz", "/readyz", "/api/schema-compatibility"})


class BridgeReadOnlyMiddleware(BaseHTTPMiddleware):
    """Prevent feature/data mutation while the compatibility bridge is routed."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path not in _BRIDGE_PATHS:
            return JSONResponse(
                {"status": "bridge_read_only", "retryable": True},
                status_code=503,
                headers={"Retry-After": "30"},
            )
        return await call_next(request)


app.add_middleware(BridgeReadOnlyMiddleware)