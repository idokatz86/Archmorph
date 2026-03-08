from error_envelope import ArchmorphException
"""
Jobs router — async job management + SSE streaming (Issue #172).

Provides endpoints for:
  - GET  /api/jobs/{job_id}        — Get job status
  - GET  /api/jobs/{job_id}/stream — SSE event stream
  - POST /api/jobs/{job_id}/cancel — Cancel a running job
  - GET  /api/jobs                 — List jobs (with filters)
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from job_queue import job_manager
from sse import sse_response
from routers.shared import limiter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/jobs/{job_id}")
@limiter.limit("60/minute")
async def get_job_status(request: Request, job_id: str):
    """Get the current status of an async job."""
    job = job_manager.get(job_id)
    if not job:
        raise ArchmorphException(404, f"Job {job_id} not found")
    return job.to_dict()


@router.get("/api/jobs/{job_id}/stream")
async def stream_job(request: Request, job_id: str):
    """Stream real-time progress events via Server-Sent Events.

    Event types:
      - ``status``   — Initial job state
      - ``progress`` — Progress update (0-100 + message)
      - ``complete`` — Job finished with result
      - ``error``    — Job failed with error message
      - ``cancelled`` — Job was cancelled

    Heartbeat comments (``: heartbeat``) are sent every 5s.
    """
    job = job_manager.get(job_id)
    if not job:
        raise ArchmorphException(404, f"Job {job_id} not found")
    return sse_response(job_manager.stream(job_id))


@router.post("/api/jobs/{job_id}/cancel")
@limiter.limit("10/minute")
async def cancel_job(request: Request, job_id: str):
    """Cancel a running or queued job."""
    job = job_manager.get(job_id)
    if not job:
        raise ArchmorphException(404, f"Job {job_id} not found")
    cancelled = job_manager.cancel(job_id)
    if not cancelled:
        raise ArchmorphException(
            409,
            f"Job {job_id} cannot be cancelled (status: {job.status.value})",
        )
    return {"job_id": job_id, "status": "cancelled"}


@router.get("/api/jobs")
@limiter.limit("30/minute")
async def list_jobs(
    request: Request,
    diagram_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List jobs with optional filters."""
    jobs = job_manager.list_jobs(diagram_id=diagram_id, status=status, limit=limit)
    return {"jobs": jobs, "total": len(jobs)}
