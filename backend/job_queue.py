"""
Archmorph Job Queue — async background job management (Issue #172).

Provides a bounded job/event queue backed by the shared SessionStore
factory (Redis/File/InMemory based on runtime config), enabling
cross-worker job status lookups and SSE progress continuity.

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
import os
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from session_store import get_store, session_store_backend

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job:
    """Job representation persisted in shared store."""

    __slots__ = (
        "job_id", "job_type", "diagram_id", "status",
        "progress", "progress_message", "result", "error",
        "created_at", "started_at", "completed_at",
        "owner_user_id", "tenant_id", "owner_api_key_id",
        "_events", "_waiters",
    )

    def __init__(
        self,
        job_type: str,
        diagram_id: Optional[str] = None,
        owner_user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        owner_api_key_id: Optional[str] = None,
    ):
        self.job_id: str = f"job-{uuid.uuid4().hex[:12]}"
        self.job_type: str = job_type
        self.diagram_id: Optional[str] = diagram_id
        self.owner_user_id: Optional[str] = owner_user_id
        self.tenant_id: Optional[str] = tenant_id
        self.owner_api_key_id: Optional[str] = owner_api_key_id
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
            "owner_api_key_id": self.owner_api_key_id,
            "status": self.status.value,
            "progress": self.progress,
            "progress_message": self.progress_message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "Job":
        job = cls(
            job_type=payload.get("job_type", "unknown"),
            diagram_id=payload.get("diagram_id"),
            owner_user_id=payload.get("owner_user_id"),
            tenant_id=payload.get("tenant_id"),
            owner_api_key_id=payload.get("owner_api_key_id"),
        )
        job.job_id = payload.get("job_id", job.job_id)
        status = payload.get("status", JobStatus.QUEUED.value)
        try:
            job.status = JobStatus(status)
        except ValueError:
            job.status = JobStatus.QUEUED
        job.progress = int(payload.get("progress", 0))
        job.progress_message = payload.get("progress_message", "Queued")
        job.result = payload.get("result")
        job.error = payload.get("error")
        job.created_at = payload.get("created_at", job.created_at)
        job.started_at = payload.get("started_at")
        job.completed_at = payload.get("completed_at")
        return job


class JobManager:
    """Async job queue manager with shared-store persistence and bounded event ring."""

    def __init__(self, max_jobs: int = 10000, max_events_per_job: Optional[int] = None, ttl_seconds: int = 7200):
        self._jobs: Dict[str, Job] = {}
        self._max_jobs = max_jobs
        self._lock = asyncio.Lock()
        self._waiters: Dict[str, List[asyncio.Event]] = {}
        self._ttl_seconds = ttl_seconds
        self._max_events_per_job = max_events_per_job or int(os.getenv("JOB_EVENT_RING_SIZE", "200"))
        self._jobs_store = get_store("jobs", maxsize=max_jobs, ttl=ttl_seconds)
        # One key per job_id: {next_seq, dropped_events, events:[{id,event,data,ts}]}
        self._events_store = get_store("job_events", maxsize=max_jobs, ttl=ttl_seconds)

    def submit(
        self,
        job_type: str,
        diagram_id: Optional[str] = None,
        owner_user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        owner_api_key_id: Optional[str] = None,
    ) -> Job:
        """Create and register a new job. Returns immediately."""
        job = Job(
            job_type=job_type,
            diagram_id=diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            owner_api_key_id=owner_api_key_id,
        )

        # Evict oldest completed jobs if at capacity
        if len(self._jobs) >= self._max_jobs:
            self._evict_completed()

        self._jobs[job.job_id] = job
        self._jobs_store.set(job.job_id, job.to_dict())
        self._events_store.set(job.job_id, {"next_seq": 0, "dropped_events": 0, "events": []})
        logger.info("Job submitted: %s (type=%s, diagram=%s)", job.job_id, job_type, diagram_id)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        """Get a job by ID."""
        payload = self._jobs_store.get(job_id)
        if payload:
            return self._hydrate_from_store(job_id, payload)
        return self._jobs.get(job_id)

    def _hydrate_from_store(self, job_id: str, payload: Dict[str, Any]) -> Job:
        """Refresh the local job object from shared-store state."""
        loaded = Job.from_dict(payload)
        job = self._jobs.get(job_id)
        if not job:
            self._jobs[job_id] = loaded
            return loaded
        for field in loaded.to_dict():
            setattr(job, field, getattr(loaded, field))
        return job

    def start(self, job_id: str) -> None:
        """Mark a job as running."""
        job = self.get(job_id)
        if not job:
            return
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc).isoformat()
        job.progress_message = "Starting..."
        self._jobs_store.set(job.job_id, job.to_dict())
        self._emit(job, "status", {"status": "running"})

    def update_progress(self, job_id: str, progress: int, message: str = "") -> None:
        """Update job progress (0-100) and emit SSE event."""
        job = self.get(job_id)
        if not job or job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return
        job.progress = min(progress, 100)
        if message:
            job.progress_message = message
        self._jobs_store.set(job.job_id, job.to_dict())
        self._emit(job, "progress", {
            "progress": job.progress,
            "message": job.progress_message,
        })

    def complete(self, job_id: str, result: Optional[Dict[str, Any]] = None) -> None:
        """Mark a job as completed with optional result."""
        job = self.get(job_id)
        if not job or job.status == JobStatus.CANCELLED:
            return
        job.status = JobStatus.COMPLETED
        job.progress = 100
        job.progress_message = "Complete"
        job.result = result
        job.completed_at = datetime.now(timezone.utc).isoformat()
        self._jobs_store.set(job.job_id, job.to_dict())
        self._emit(job, "complete", {"result": result})
        logger.info("Job completed: %s", job_id)

    def fail(self, job_id: str, error: str) -> None:
        """Mark a job as failed."""
        job = self.get(job_id)
        if not job or job.status == JobStatus.CANCELLED:
            return
        job.status = JobStatus.FAILED
        job.error = error
        job.completed_at = datetime.now(timezone.utc).isoformat()
        self._jobs_store.set(job.job_id, job.to_dict())
        self._emit(job, "error", {"error": error})
        logger.error("Job failed: %s — %s", job_id, error)

    def cancel(self, job_id: str) -> bool:
        """Cancel a job. Returns True if cancelled, False if already done."""
        job = self.get(job_id)
        if not job:
            return False
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
            return False
        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.now(timezone.utc).isoformat()
        self._jobs_store.set(job.job_id, job.to_dict())
        self._emit(job, "cancelled", {})
        logger.info("Job cancelled: %s", job_id)
        return True

    def is_cancelled(self, job_id: str) -> bool:
        """Check if a job has been cancelled (for worker polling)."""
        job = self.get(job_id)
        return job.status == JobStatus.CANCELLED if job else False

    def list_jobs(
        self,
        diagram_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List jobs with optional filters."""
        jobs: List[Job] = []
        for job_id in self._jobs_store.keys("*"):
            payload = self._jobs_store.get(job_id)
            if not payload:
                continue
            jobs.append(Job.from_dict(payload))
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

        Active jobs stream only new events from connect-time onward.
        Completed/failed/cancelled jobs replay the retained ring-buffer
        events before termination.

        Terminates when job completes, fails, or timeout expires.
        """
        job = self._jobs.get(job_id)
        if not job:
            job = self.get(job_id)
        if not job:
            yield _sse_format("error", {"error": "Job not found"})
            return

        # Send current state first
        yield _sse_format("status", job.to_dict())

        # Stream events as they arrive (shared-store polling + local wakeups)
        waiter = asyncio.Event()
        self._waiters.setdefault(job_id, []).append(waiter)
        stream_start = time.monotonic()
        heartbeat_at = stream_start + 5.0
        initial_done = job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
        initial_state = self._events_store.get(job_id, {"next_seq": 0, "events": []})
        initial_next_seq = int(initial_state.get("next_seq", 0))
        if initial_done:
            # For completed jobs, replay retained buffered events for continuity.
            event_cursor = max(0, initial_next_seq - len(initial_state.get("events", [])))
        else:
            # For active jobs, preserve legacy behavior: only stream new events.
            event_cursor = initial_next_seq

        try:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                # Wait for local wakeups; polling still ensures cross-worker continuity.
                try:
                    await asyncio.wait_for(waiter.wait(), timeout=1.0)
                    waiter.clear()
                except asyncio.TimeoutError:
                    pass

                event_state = self._events_store.get(job_id, {"next_seq": 0, "events": [], "dropped_events": 0})
                events = event_state.get("events", [])
                next_seq = int(event_state.get("next_seq", 0))
                # Ring buffer stores only the newest N events. base_seq is the
                # oldest still-retained event id for this job stream.
                base_seq = max(0, next_seq - len(events))
                if event_cursor < base_seq:
                    event_cursor = base_seq

                terminal_event_seen = False
                for evt in events:
                    evt_id = int(evt.get("id", -1))
                    if evt_id < event_cursor:
                        continue
                    if evt.get("event") in ("complete", "error", "cancelled"):
                        terminal_event_seen = True
                    yield _sse_format(evt["event"], evt["data"])
                    event_cursor = evt_id + 1

                # Send heartbeat every 5s when idle
                if time.monotonic() >= heartbeat_at:
                    yield ": heartbeat\n\n"
                    heartbeat_at = time.monotonic() + 5.0

                # Check if job is done
                latest = self.get(job_id)
                if latest and latest.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED) and event_cursor >= next_seq:
                    # If terminal event wasn't observed from retained ring-buffer events,
                    # emit one terminal event to ensure stream consumers close cleanly.
                    if not terminal_event_seen:
                        if latest.status == JobStatus.COMPLETED:
                            yield _sse_format("complete", {"result": latest.result})
                        elif latest.status == JobStatus.FAILED:
                            yield _sse_format("error", {"error": latest.error})
                        else:
                            yield _sse_format("cancelled", {})
                    break

        finally:
            waiters = self._waiters.get(job_id, [])
            if waiter in waiters:
                waiters.remove(waiter)
            if not waiters and job_id in self._waiters:
                del self._waiters[job_id]

    def _emit(self, job: Job, event_type: str, data: Dict[str, Any]) -> None:
        """Emit an SSE event and wake all waiters."""
        state = self._events_store.get(job.job_id, {"next_seq": 0, "dropped_events": 0, "events": []})
        events = list(state.get("events", []))
        next_seq = int(state.get("next_seq", 0))
        dropped_events = int(state.get("dropped_events", 0))
        events.append(
            {
                "id": next_seq,
                "event": event_type,
                "data": data,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )
        overflow = len(events) - self._max_events_per_job
        if overflow > 0:
            events = events[overflow:]
            dropped_events += overflow
        self._events_store.set(
            job.job_id,
            {"next_seq": next_seq + 1, "dropped_events": dropped_events, "events": events},
        )
        job._events = events
        for waiter in self._waiters.get(job.job_id, []):
            waiter.set()

    def _evict_completed(self) -> None:
        """Remove oldest completed/failed/cancelled jobs to free space."""
        done: List[Tuple[str, str]] = []
        for payload in self.list_jobs(limit=self._max_jobs):
            if payload.get("status") in (
                JobStatus.COMPLETED.value,
                JobStatus.FAILED.value,
                JobStatus.CANCELLED.value,
            ):
                done.append((payload["job_id"], payload.get("completed_at") or payload.get("created_at") or ""))
        done.sort(key=lambda x: x[1])
        for jid, _ in done[: max(1, len(done) // 2)]:
            self._jobs.pop(jid, None)
            self._jobs_store.delete(jid)
            self._events_store.delete(jid)

    def metrics(self) -> Dict[str, Any]:
        """Return queue/event observability metrics."""
        jobs_payload = self.list_jobs(limit=max(1, self._max_jobs))
        by_status: Dict[str, int] = {}
        total_events_buffered = 0
        total_events_dropped = 0
        for item in jobs_payload:
            status = item.get("status", JobStatus.QUEUED.value)
            by_status[status] = by_status.get(status, 0) + 1
            event_state = self._events_store.get(item["job_id"], {"events": [], "dropped_events": 0})
            total_events_buffered += len(event_state.get("events", []))
            total_events_dropped += int(event_state.get("dropped_events", 0))
        return {
            "backend": session_store_backend(),
            "max_jobs": self._max_jobs,
            "ttl_seconds": self._ttl_seconds,
            "max_events_per_job": self._max_events_per_job,
            "jobs_total": len(jobs_payload),
            "jobs_by_status": by_status,
            "events_buffered_total": total_events_buffered,
            "events_dropped_total": total_events_dropped,
        }

    def purge_diagram(self, diagram_id: str) -> int:
        """Delete all jobs and buffered events linked to a diagram."""
        deleted = 0
        for job_id in list(self._jobs_store.keys("*")):
            payload = self._jobs_store.get(job_id) or {}
            if payload.get("diagram_id") != diagram_id:
                continue
            self._jobs.pop(job_id, None)
            self._jobs_store.delete(job_id)
            self._events_store.delete(job_id)
            self._waiters.pop(job_id, None)
            deleted += 1
        return deleted


def _sse_format(event: str, data: Any) -> str:
    """Format a Server-Sent Event."""
    payload = json.dumps(data, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


# ─────────────────────────────────────────────────────────────
# Singleton instance
# ─────────────────────────────────────────────────────────────
job_manager = JobManager()
