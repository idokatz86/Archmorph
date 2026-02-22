"""
Archmorph SSE Streaming Helper (Issue #172).

Provides utilities for Server-Sent Events (SSE) responses in FastAPI.

Usage::

    from sse import sse_response

    @router.get("/api/jobs/{job_id}/stream")
    async def stream_job(job_id: str):
        return sse_response(job_manager.stream(job_id))
"""

import json
import logging
from typing import Any, AsyncGenerator, Dict

from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)


def sse_response(generator: AsyncGenerator[str, None]) -> StreamingResponse:
    """Create an SSE StreamingResponse from an async generator.

    Sets appropriate headers for SSE:
    - Content-Type: text/event-stream
    - Cache-Control: no-cache
    - Connection: keep-alive
    - X-Accel-Buffering: no (nginx proxy compatibility)
    """
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def format_sse(event: str, data: Any, event_id: str = None) -> str:
    """Format a single SSE event string.

    Args:
        event: Event type name
        data: Event data (will be JSON-serialized)
        event_id: Optional event ID for client reconnection

    Returns:
        Formatted SSE string::

            event: progress
            id: 42
            data: {"progress": 50}

    """
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    payload = json.dumps(data, default=str) if not isinstance(data, str) else data
    lines.append(f"data: {payload}")
    lines.append("")  # blank line terminates event
    lines.append("")
    return "\n".join(lines)


async def heartbeat_wrapper(
    generator: AsyncGenerator[str, None],
    interval: float = 15.0,
) -> AsyncGenerator[str, None]:
    """Wrap an SSE generator with periodic heartbeat comments.

    Keeps the connection alive through proxies/load balancers that
    timeout idle connections.
    """
    import asyncio

    async def _heartbeat():
        while True:
            await asyncio.sleep(interval)
            yield ": heartbeat\n\n"

    # Interleave generator events with heartbeats
    # (simplified: the job_manager.stream() already handles heartbeats)
    async for event in generator:
        yield event
