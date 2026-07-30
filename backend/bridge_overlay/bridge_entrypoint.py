"""Wrap the pre-014 application with a bounded schema bridge contract."""

from __future__ import annotations

import job_queue


async def _bridge_worker_start() -> dict[str, list]:
    """Do not claim/recover durable jobs while the bridge spans two schemas."""
    return {"recovered": [], "failed": []}


async def _bridge_worker_stop() -> None:
    return None


job_queue.durable_job_worker.start = _bridge_worker_start
job_queue.durable_job_worker.stop = _bridge_worker_stop

from main import ArchmorphMiddleware, app  # noqa: E402
from bridge_readonly import BridgeReadOnlyMiddleware  # noqa: E402


ArchmorphMiddleware._ORIGIN_LOCK_SKIP = frozenset(
    {*ArchmorphMiddleware._ORIGIN_LOCK_SKIP, "/readyz", "/api/schema-compatibility"}
)
app.add_middleware(BridgeReadOnlyMiddleware)
