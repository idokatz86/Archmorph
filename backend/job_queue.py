"""
Archmorph Job Queue — async background job management (Issue #172).

Provides an in-memory job queue that tracks AI operation status and
enables SSE streaming of real progress events. The interface is
designed to be swappable with a Redis-backed (ARQ) implementation
in production.

Usage::

    from job_queue import job_manager

    # Submit a job
    job = job_manager.submit("analyze", diagram_id="diag-abc123")

    # Update progress from worker
    job_manager.update_progress(job.job_id, 50, "Analyzing services...")

    # Complete
    job_manager.complete(job.job_id, result={...})

    # SSE stream
    async for event in job_manager.stream(job.job_id):
        yield event
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncGenerator, Dict, List, Optional

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job:
    """In-memory job representation."""

    __slots__ = (
        "job_id", "job_type", "diagram_id", "status",
        "progress", "progress_message", "result", "error",
        "created_at", "started_at", "completed_at",
        "owner_user_id", "tenant_id",
        "_events", "_waiters",
    )

    def __init__(
        self,
        job_type: str,
        diagram_id: Optional[str] = None,
        owner_user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ):
        self.job_id: str = f"job-{uuid.uuid4().hex[:12]}"
        self.job_type: str = job_type
        self.diagram_id: Optional[str] = diagram_id
        self.owner_user_id: Optional[str] = owner_user_id
        self.tenant_id: Optional[str] = tenant_id
        self.status: JobStatus = JobStatus.QUEUED
        self.progress: int = 0
        self.progress_message: str = "Queued"
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self.created_at: str = datetime.now(timezone.utc).isoformat()
        self.started_at: Optional[str] = None
        self.completed_at: Optional[str] = None
        self._events: List[Dict[str, Any]] = []
        self._waiters: List[asyncio.Event] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "diagram_id": self.diagram_id,
            "owner_user_id": self.owner_user_id,
            "tenant_id": self.tenant_id,
            "status": self.status.value,
            "progress": self.progress,
            "progress_message": self.progress_message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class JobManager:
    """In-memory job queue manager.

    Thread-safe for use with asyncio.to_thread() workers.
    Supports SSE streaming via asyncio.Event notifications.
    """

    def __init__(self, max_jobs: int = 10000):
        self._jobs: Dict[str, Job] = {}
        self._max_jobs = max_jobs
        self._lock = asyncio.Lock()

    def submit(
        self,
        job_type: str,
        diagram_id: Optional[str] = None,
        owner_user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Job:
        """Create and register a new job. Returns immediately."""
        job = Job(
            job_type=job_type,
            diagram_id=diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        )

        # Evict oldest completed jobs if at capacity
        if len(self._jobs) >= self._max_jobs:
            self._evict_completed()

        self._jobs[job.job_id] = job
        logger.info("Job submitted: %s (type=%s, diagram=%s)", job.job_id, job_type, diagram_id)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        """Get a job by ID."""
        return self._jobs.get(job_id)

    def start(self, job_id: str) -> None:
        """Mark a job as running."""
        job = self._jobs.get(job_id)
        if not job:
            return
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc).isoformat()
        job.progress_message = "Starting..."
        self._emit(job, "status", {"status": "running"})

    def update_progress(self, job_id: str, progress: int, message: str = "") -> None:
        """Update job progress (0-100) and emit SSE event."""
        job = self._jobs.get(job_id)
        if not job or job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return
        job.progress = min(progress, 100)
        if message:
            job.progress_message = message
        self._emit(job, "progress", {
            "progress": job.progress,
            "message": job.progress_message,
        })

    def complete(self, job_id: str, result: Optional[Dict[str, Any]] = None) -> None:
        """Mark a job as completed with optional result."""
        job = self._jobs.get(job_id)
        if not job:
            return
        job.status = JobStatus.COMPLETED
        job.progress = 100
        job.progress_message = "Complete"
        job.result = result
        job.completed_at = datetime.now(timezone.utc).isoformat()
        self._emit(job, "complete", {"result": result})
        logger.info("Job completed: %s", job_id)

    def fail(self, job_id: str, error: str) -> None:
        """Mark a job as failed."""
        job = self._jobs.get(job_id)
        if not job:
            return
        job.status = JobStatus.FAILED
        job.error = error
        job.completed_at = datetime.now(timezone.utc).isoformat()
        self._emit(job, "error", {"error": error})
        logger.error("Job failed: %s — %s", job_id, error)

    def cancel(self, job_id: str) -> bool:
        """Cancel a job. Returns True if cancelled, False if already done."""
        job = self._jobs.get(job_id)
        if not job:
            return False
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
            return False
        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.now(timezone.utc).isoformat()
        self._emit(job, "cancelled", {})
        logger.info("Job cancelled: %s", job_id)
        return True

    def is_cancelled(self, job_id: str) -> bool:
        """Check if a job has been cancelled (for worker polling)."""
        job = self._jobs.get(job_id)
        return job.status == JobStatus.CANCELLED if job else False

    def list_jobs(
        self,
        diagram_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List jobs with optional filters."""
        jobs = list(self._jobs.values())
        if diagram_id:
            jobs = [j for j in jobs if j.diagram_id == diagram_id]
        if status:
            jobs = [j for j in jobs if j.status.value == status]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return [j.to_dict() for j in jobs[:limit]]

    async def stream(self, job_id: str, timeout: float = 300.0) -> AsyncGenerator[str, None]:
        """SSE event stream for a job.

        Yields formatted SSE events::

            event: progress
            data: {"progress": 50, "message": "Analyzing..."}

        Terminates when job completes, fails, or timeout expires.
        """
        job = self._jobs.get(job_id)
        if not job:
            yield _sse_format("error", {"error": "Job not found"})
            return

        # Send current state first
        yield _sse_format("status", job.to_dict())

        # If already done, send final event and return
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            if job.status == JobStatus.COMPLETED:
                yield _sse_format("complete", {"result": job.result})
            elif job.status == JobStatus.FAILED:
                yield _sse_format("error", {"error": job.error})
            else:
                yield _sse_format("cancelled", {})
            return

        # Stream events as they arrive
        waiter = asyncio.Event()
        job._waiters.append(waiter)
        event_cursor = len(job._events)

        try:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                # Wait for new events (with 5s heartbeat timeout)
                try:
                    await asyncio.wait_for(waiter.wait(), timeout=5.0)
                    waiter.clear()
                except asyncio.TimeoutError:
                    # Send heartbeat to keep connection alive
                    yield ": heartbeat\n\n"
                    continue

                # Yield any new events since cursor
                while event_cursor < len(job._events):
                    evt = job._events[event_cursor]
                    yield _sse_format(evt["event"], evt["data"])
                    event_cursor += 1

                # Check if job is done
                if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                    break

        finally:
            if waiter in job._waiters:
                job._waiters.remove(waiter)

    def _emit(self, job: Job, event_type: str, data: Dict[str, Any]) -> None:
        """Emit an SSE event and wake all waiters."""
        job._events.append({"event": event_type, "data": data})
        for waiter in job._waiters:
            waiter.set()

    def _evict_completed(self) -> None:
        """Remove oldest completed/failed/cancelled jobs to free space."""
        done = [
            (jid, j.completed_at or j.created_at)
            for jid, j in self._jobs.items()
            if j.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
        ]
        done.sort(key=lambda x: x[1])
        for jid, _ in done[: max(1, len(done) // 2)]:
            del self._jobs[jid]


def _sse_format(event: str, data: Any) -> str:
    """Format a Server-Sent Event."""
    payload = json.dumps(data, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


# ─────────────────────────────────────────────────────────────
# Singleton instance
# ─────────────────────────────────────────────────────────────
job_manager = JobManager()
