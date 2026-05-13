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

from fastapi import APIRouter, Query, Request

from job_queue import job_manager
from sse import sse_response
from routers.shared import (
    get_api_key_service_principal,
    limiter,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _ensure_job_access(job, user, api_key_principal_id: Optional[str]) -> None:
    if user:
        if not job.owner_user_id or not job.tenant_id:
            raise ArchmorphException(404, "Job not found")
        if job.owner_user_id != user.id:
            raise ArchmorphException(404, "Job not found")
        if job.tenant_id != user.tenant_id:
            raise ArchmorphException(404, "Job not found")
        return

    if api_key_principal_id:
        if getattr(job, "owner_api_key_id", None) != api_key_principal_id:
            raise ArchmorphException(404, "Job not found")
        return

    raise ArchmorphException(401, "Authentication required")


def _stream_user_from_request(request: Request):
    from auth import get_user_from_request_headers

    headers = dict(request.headers)
    stream_token = request.query_params.get("token")
    if stream_token and "authorization" not in headers:
        headers["authorization"] = f"Bearer {stream_token}"
    user = get_user_from_request_headers(headers)
    if not user:
        raise ArchmorphException(401, "Authentication required")
    return user


def _job_principal_from_request(request: Request, *, allow_stream_token: bool = False):
    from auth import get_user_from_request_headers

    headers = dict(request.headers)
    if allow_stream_token:
        stream_token = request.query_params.get("token")
        if stream_token and "authorization" not in headers:
            headers["authorization"] = f"Bearer {stream_token}"
    user = get_user_from_request_headers(headers)
    if user:
        return user, None
    api_key_principal_id = get_api_key_service_principal(headers)
    if api_key_principal_id:
        return None, api_key_principal_id
    raise ArchmorphException(401, "Authentication required")


@router.get("/api/jobs/{job_id}")
@limiter.limit("60/minute")
async def get_job_status(request: Request, job_id: str):
    """Get the current status of an async job."""
    job = job_manager.get(job_id)
    if not job:
        raise ArchmorphException(404, f"Job {job_id} not found")
    user, api_key_principal_id = _job_principal_from_request(request)
    _ensure_job_access(job, user, api_key_principal_id)
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
    user, api_key_principal_id = _job_principal_from_request(request, allow_stream_token=True)
    _ensure_job_access(job, user, api_key_principal_id)
    return sse_response(job_manager.stream(job_id))


@router.post("/api/jobs/{job_id}/cancel")
@limiter.limit("10/minute")
async def cancel_job(request: Request, job_id: str):
    """Cancel a running or queued job."""
    job = job_manager.get(job_id)
    if not job:
        raise ArchmorphException(404, f"Job {job_id} not found")
    user, api_key_principal_id = _job_principal_from_request(request)
    _ensure_job_access(job, user, api_key_principal_id)
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
    user, api_key_principal_id = _job_principal_from_request(request)
    jobs = job_manager.list_jobs(diagram_id=diagram_id, status=status, limit=limit)
    if user:
        jobs = [
            j for j in jobs
            if j.get("owner_user_id") == user.id and j.get("tenant_id") == user.tenant_id
        ]
    else:
        jobs = [j for j in jobs if j.get("owner_api_key_id") == api_key_principal_id]
    return {"jobs": jobs, "total": len(jobs)}


@router.get("/api/jobs/metrics/summary")
@limiter.limit("30/minute")
async def get_queue_metrics(request: Request):
    """Return async queue and event-buffer metrics for observability."""
    _job_principal_from_request(request)
    return job_manager.metrics()
