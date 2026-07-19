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
import contextvars
import hashlib
import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from session_store import get_store, session_store_backend
from observability import increment_counter as obs_increment_counter, record_histogram as obs_record_histogram

logger = logging.getLogger(__name__)

_CURRENT_LEASE_TOKEN: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "archmorph_job_lease_token",
    default=None,
)
EXECUTION_SCHEMA_VERSION = 1
IDEMPOTENCY_RESERVATION_STALE_SECONDS = 5.0


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
        "phase", "progress", "progress_message", "result", "error",
        "created_at", "started_at", "completed_at", "updated_at",
        "owner_user_id", "tenant_id", "owner_api_key_id",
        "durable", "execution_schema_version", "execution_payload", "input_hash",
        "attempt", "max_attempts", "lease_owner", "lease_token",
        "lease_expires_at", "heartbeat_at", "recovery_count", "retryable",
        "active_counters_released",
        "_events", "_waiters",
    )

    def __init__(
        self,
        job_type: str,
        diagram_id: Optional[str] = None,
        owner_user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        owner_api_key_id: Optional[str] = None,
        durable: bool = False,
        execution_payload: Optional[Dict[str, Any]] = None,
        input_hash: Optional[str] = None,
        max_attempts: int = 3,
        job_id: Optional[str] = None,
    ):
        self.job_id: str = job_id or f"job-{uuid.uuid4().hex[:12]}"
        self.job_type: str = job_type
        self.diagram_id: Optional[str] = diagram_id
        self.owner_user_id: Optional[str] = owner_user_id
        self.tenant_id: Optional[str] = tenant_id
        self.owner_api_key_id: Optional[str] = owner_api_key_id
        self.durable: bool = durable
        self.execution_schema_version: int = EXECUTION_SCHEMA_VERSION
        self.execution_payload: Dict[str, Any] = execution_payload or {}
        self.input_hash: Optional[str] = input_hash
        self.attempt: int = 0
        self.max_attempts: int = max(1, int(max_attempts))
        self.lease_owner: Optional[str] = None
        self.lease_token: Optional[str] = None
        self.lease_expires_at: Optional[str] = None
        self.heartbeat_at: Optional[str] = None
        self.recovery_count: int = 0
        self.retryable: bool = durable
        self.active_counters_released: bool = False
        self.status: JobStatus = JobStatus.QUEUED
        self.phase: str = "queued"
        self.progress: int = 0
        self.progress_message: str = "Queued"
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self.created_at: str = datetime.now(timezone.utc).isoformat()
        self.started_at: Optional[str] = None
        self.completed_at: Optional[str] = None
        self.updated_at: str = self.created_at
        self._events: List[Dict[str, Any]] = []
        self._waiters: List[asyncio.Event] = []

    def to_dict(self) -> Dict[str, Any]:
        timing = _job_timing(self)
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "diagram_id": self.diagram_id,
            "owner_user_id": self.owner_user_id,
            "tenant_id": self.tenant_id,
            "owner_api_key_id": self.owner_api_key_id,
            "durable": self.durable,
            "execution_schema_version": self.execution_schema_version,
            "input_hash": self.input_hash,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "lease_expires_at": self.lease_expires_at,
            "heartbeat_at": self.heartbeat_at,
            "recovery_count": self.recovery_count,
            "retryable": self.retryable,
            "active_counters_released": self.active_counters_released,
            "status": self.status.value,
            "phase": self.phase,
            "progress": self.progress,
            "progress_message": self.progress_message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "updated_at": self.updated_at,
            **timing,
        }

    def to_storage_dict(self) -> Dict[str, Any]:
        """Serialize public state plus the internal durable execution envelope."""
        return {
            **self.to_dict(),
            "execution_payload": self.execution_payload,
            "lease_owner": self.lease_owner,
            "lease_token": self.lease_token,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "Job":
        job = cls(
            job_type=payload.get("job_type", "unknown"),
            diagram_id=payload.get("diagram_id"),
            owner_user_id=payload.get("owner_user_id"),
            tenant_id=payload.get("tenant_id"),
            owner_api_key_id=payload.get("owner_api_key_id"),
            durable=bool(payload.get("durable", False)),
            execution_payload=payload.get("execution_payload") or {},
            input_hash=payload.get("input_hash"),
            max_attempts=int(payload.get("max_attempts", 3) or 3),
        )
        job.job_id = payload.get("job_id", job.job_id)
        status = payload.get("status", JobStatus.QUEUED.value)
        try:
            job.status = JobStatus(status)
        except ValueError:
            job.status = JobStatus.QUEUED
        job.phase = payload.get("phase") or _phase_for_status(job.status)
        job.progress = int(payload.get("progress", 0))
        job.progress_message = payload.get("progress_message", "Queued")
        job.result = payload.get("result")
        job.error = payload.get("error")
        job.created_at = payload.get("created_at", job.created_at)
        job.started_at = payload.get("started_at")
        job.completed_at = payload.get("completed_at")
        job.updated_at = payload.get("updated_at") or job.completed_at or job.started_at or job.created_at
        job.execution_schema_version = int(payload.get("execution_schema_version", EXECUTION_SCHEMA_VERSION))
        job.attempt = max(0, int(payload.get("attempt", 0) or 0))
        job.lease_owner = payload.get("lease_owner")
        job.lease_token = payload.get("lease_token")
        job.lease_expires_at = payload.get("lease_expires_at")
        job.heartbeat_at = payload.get("heartbeat_at")
        job.recovery_count = max(0, int(payload.get("recovery_count", 0) or 0))
        job.retryable = bool(payload.get("retryable", job.durable))
        job.active_counters_released = bool(payload.get("active_counters_released", False))
        return job


class AdmissionRejected(Exception):
    """Raised when per-user or per-tenant active-job limit is exceeded."""

    def __init__(self, message: str, *, scope: str, active: int, limit: int):
        super().__init__(message)
        self.scope = scope
        self.active = active
        self.limit = limit


class AdmissionStoreError(Exception):
    """Raised when the shared admission counter cannot be updated reliably."""


class JobStoreError(Exception):
    """Raised when an accepted durable job cannot be persisted reliably."""


def _env_int_default(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class JobManager:
    """Async job queue manager with shared-store persistence and bounded event ring."""

    def __init__(
        self,
        max_jobs: int = 10000,
        max_events_per_job: Optional[int] = None,
        ttl_seconds: int = 7200,
        max_active_jobs_per_user: Optional[int] = None,
        max_active_jobs_per_tenant: Optional[int] = None,
        lease_seconds: Optional[int] = None,
        max_attempts: Optional[int] = None,
        worker_id: Optional[str] = None,
    ):
        self._jobs: Dict[str, Job] = {}
        self._max_jobs = max_jobs
        self._waiters: Dict[str, List[asyncio.Event]] = {}
        self._submission_listeners: List[Any] = []
        self._ttl_seconds = ttl_seconds
        self._max_events_per_job = max_events_per_job or int(os.getenv("JOB_EVENT_RING_SIZE", "200"))
        self._jobs_store = get_store("jobs", maxsize=max_jobs, ttl=ttl_seconds)
        # One key per job_id: {next_seq, dropped_events, events:[{id,event,data,ts}]}
        self._events_store = get_store("job_events", maxsize=max_jobs, ttl=ttl_seconds)
        # O(1) per-principal active counters for admission checks.
        self._active_counts_store = get_store("job_active_counts", maxsize=max_jobs * 3, ttl=ttl_seconds)
        self._idempotency_store = get_store("job_idempotency", maxsize=max_jobs, ttl=ttl_seconds)
        self._metrics_store = get_store("job_durable_metrics", maxsize=50, ttl=max(ttl_seconds, 86400))
        self._lease_seconds = max(5, lease_seconds or _env_int_default("JOB_LEASE_SECONDS", 90))
        self._default_max_attempts = max(1, max_attempts or _env_int_default("JOB_MAX_ATTEMPTS", 3))
        self._worker_id = worker_id or os.getenv("JOB_WORKER_ID") or f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        # Per-user and per-tenant active-job limits (queued + running).
        # Defaults are read from environment variables so operators can tune them.
        self._max_active_per_user: int = (
            max_active_jobs_per_user
            if max_active_jobs_per_user is not None
            else _env_int_default("MAX_ACTIVE_JOBS_PER_USER", 5)
        )
        self._max_active_per_tenant: int = (
            max_active_jobs_per_tenant
            if max_active_jobs_per_tenant is not None
            else _env_int_default("MAX_ACTIVE_JOBS_PER_TENANT", 20)
        )

    @staticmethod
    def input_hash(job_type: str, diagram_id: Optional[str], execution_payload: Dict[str, Any]) -> str:
        canonical = json.dumps(
            {
                "schema_version": EXECUTION_SCHEMA_VERSION,
                "job_type": job_type,
                "diagram_id": diagram_id,
                "execution_payload": execution_payload,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _idempotency_key(
        input_hash: str,
        *,
        owner_user_id: Optional[str],
        tenant_id: Optional[str],
        owner_api_key_id: Optional[str],
    ) -> str:
        principal = {
            "owner_user_id": owner_user_id,
            "tenant_id": tenant_id,
            "owner_api_key_id": owner_api_key_id,
        }
        canonical = json.dumps(principal, sort_keys=True, separators=(",", ":"))
        principal_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"{principal_hash}:{input_hash}"

    def _increment_durable_metric(self, name: str, amount: int = 1) -> None:
        def updater(current: Any) -> Dict[str, Any]:
            payload = dict(current or {})
            payload[name] = max(0, int(payload.get(name, 0) or 0)) + amount
            payload["updated_at"] = datetime.now(timezone.utc).isoformat()
            return payload

        self._metrics_store.update_if("totals", lambda _current: True, updater, ttl=max(self._ttl_seconds, 86400))
        obs_increment_counter(f"jobs.durable.{name}", amount)

    def _active_counter_specs(
        self,
        *,
        owner_user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        owner_api_key_id: Optional[str] = None,
    ) -> List[Tuple[str, str, int]]:
        specs: List[Tuple[str, str, int]] = []
        if owner_user_id:
            specs.append(("user", f"user:{owner_user_id}", self._max_active_per_user))
        if tenant_id:
            specs.append(("tenant", f"tenant:{tenant_id}", self._max_active_per_tenant))
        if owner_api_key_id:
            specs.append(("api_key", f"api_key:{owner_api_key_id}", self._max_active_per_user))
        return specs

    @staticmethod
    def _counter_record_key(_specs: List[Tuple[str, str, int]]) -> str:
        return "totals"

    @staticmethod
    def _counter_record_counts(value: Any) -> Dict[str, int]:
        if not isinstance(value, dict):
            return {}
        raw_counts = value.get("counts", value)
        if not isinstance(raw_counts, dict):
            return {}
        counts: Dict[str, int] = {}
        for key, active in raw_counts.items():
            try:
                counts[str(key)] = max(0, int(active or 0))
            except (TypeError, ValueError):
                counts[str(key)] = 0
        return counts

    @staticmethod
    def _counter_record_reservations(value: Any) -> Dict[str, Dict[str, Any]]:
        if not isinstance(value, dict) or not isinstance(value.get("reservations"), dict):
            return {}
        return {
            str(job_id): dict(reservation)
            for job_id, reservation in value["reservations"].items()
            if isinstance(reservation, dict)
        }

    def _reserve_active_counters(
        self,
        *,
        owner_user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        owner_api_key_id: Optional[str] = None,
        enforce_limit: bool = False,
        reservation_id: str,
    ) -> List[Tuple[str, str, int]]:
        specs = [
            spec
            for spec in self._active_counter_specs(
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            owner_api_key_id=owner_api_key_id,
            )
            if spec[2] > 0
        ]
        if not specs:
            return []
        record_key = self._counter_record_key(specs)

        def predicate(current: Any) -> bool:
            counts = self._counter_record_counts(current)
            reservations = self._counter_record_reservations(current)
            return reservation_id in reservations or (not enforce_limit) or all(
                counts.get(key, 0) < limit for _scope, key, limit in specs
            )

        def updater(current: Any) -> Dict[str, Any]:
            counts = self._counter_record_counts(current)
            reservations = self._counter_record_reservations(current)
            if reservation_id in reservations:
                return {
                    "counts": counts,
                    "reservations": reservations,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            for _scope, key, _limit in specs:
                counts[key] = counts.get(key, 0) + 1
            reservations[reservation_id] = {
                "keys": [key for _scope, key, _limit in specs],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            return {
                "counts": counts,
                "reservations": reservations,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

        updated, value = self._active_counts_store.update_if(
            record_key,
            predicate,
            updater,
            ttl=self._ttl_seconds,
        )
        if updated:
            return specs
        counts = self._counter_record_counts(value)
        for scope, key, limit in specs:
            active = counts.get(key, 0)
            if enforce_limit and active >= limit:
                label = {
                    "user": "Active analysis job limit",
                    "tenant": "Tenant active analysis job limit",
                    "api_key": "API key active analysis job limit",
                }.get(scope, "Active analysis job limit")
                raise AdmissionRejected(
                    f"{label} reached ({active}/{limit}). Wait for current analysis jobs to finish and try again.",
                    scope=scope,
                    active=active,
                    limit=limit,
                )
        raise AdmissionStoreError("Admission counter update failed")

    def _release_counter_reservation(self, reservation_id: str) -> None:
        record_key = self._counter_record_key([])

        def predicate(current: Any) -> bool:
            return reservation_id in self._counter_record_reservations(current)

        def updater(current: Any) -> Dict[str, Any]:
            counts = self._counter_record_counts(current)
            reservations = self._counter_record_reservations(current)
            reservation = reservations.pop(reservation_id, {})
            for key in reservation.get("keys", []):
                counts[key] = max(0, counts.get(key, 0) - 1)
                if counts[key] == 0:
                    counts.pop(key, None)
            return {
                "counts": counts,
                "reservations": reservations,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

        self._active_counts_store.update_if(
            record_key,
            predicate,
            updater,
            ttl=self._ttl_seconds,
        )

    def _release_active_counters(self, job: Job) -> None:
        if job.active_counters_released:
            return
        self._release_job_counter_reservation(job)
        job.active_counters_released = True

    def _release_job_counter_reservation(self, job: Job) -> None:
        self._release_counter_reservation(job.job_id)

    def count_active_jobs(
        self,
        *,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        api_key_id: Optional[str] = None,
    ) -> int:
        """Count jobs in queued or running state for a given principal.

        Exactly one of ``user_id``, ``tenant_id``, or ``api_key_id`` should
        be provided; the first non-None value is used.
        """
        if user_id:
            specs = self._active_counter_specs(owner_user_id=user_id)
            record = self._active_counts_store.peek(self._counter_record_key(specs))
            return self._counter_record_counts(record).get(f"user:{user_id}", 0)
        if tenant_id:
            specs = self._active_counter_specs(tenant_id=tenant_id)
            record = self._active_counts_store.peek(self._counter_record_key(specs))
            return self._counter_record_counts(record).get(f"tenant:{tenant_id}", 0)
        if api_key_id:
            specs = self._active_counter_specs(owner_api_key_id=api_key_id)
            record = self._active_counts_store.peek(self._counter_record_key(specs))
            return self._counter_record_counts(record).get(f"api_key:{api_key_id}", 0)
        return 0

    def check_admission(
        self,
        *,
        owner_user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        owner_api_key_id: Optional[str] = None,
    ) -> None:
        """Raise :class:`AdmissionRejected` if the caller is over their active-job quota.

        Checks are skipped when the respective limit is <= 0 (disabled).
        """
        if owner_user_id and self._max_active_per_user > 0:
            active = self.count_active_jobs(user_id=owner_user_id)
            if active >= self._max_active_per_user:
                raise AdmissionRejected(
                    f"Active analysis job limit reached ({active}/{self._max_active_per_user}). "
                    "Wait for current analysis jobs to finish and try again.",
                    scope="user",
                    active=active,
                    limit=self._max_active_per_user,
                )
        if tenant_id and self._max_active_per_tenant > 0:
            active = self.count_active_jobs(tenant_id=tenant_id)
            if active >= self._max_active_per_tenant:
                raise AdmissionRejected(
                    f"Tenant active analysis job limit reached ({active}/{self._max_active_per_tenant}). "
                    "Wait for current analysis jobs to finish and try again.",
                    scope="tenant",
                    active=active,
                    limit=self._max_active_per_tenant,
                )
        if owner_api_key_id and self._max_active_per_user > 0:
            active = self.count_active_jobs(api_key_id=owner_api_key_id)
            if active >= self._max_active_per_user:
                raise AdmissionRejected(
                    f"API key active analysis job limit reached ({active}/{self._max_active_per_user}). "
                    "Wait for current analysis jobs to finish and try again.",
                    scope="api_key",
                    active=active,
                    limit=self._max_active_per_user,
                )

    def submit(
        self,
        job_type: str,
        diagram_id: Optional[str] = None,
        owner_user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        owner_api_key_id: Optional[str] = None,
        enforce_admission: bool = False,
        execution_payload: Optional[Dict[str, Any]] = None,
        input_hash: Optional[str] = None,
        max_attempts: Optional[int] = None,
    ) -> Job:
        """Create and register a new job. Returns immediately."""
        durable = execution_payload is not None
        normalized_payload = dict(execution_payload or {})
        normalized_hash = input_hash or (
            self.input_hash(job_type, diagram_id, normalized_payload)
            if durable
            else None
        )
        idempotency_key = (
            self._idempotency_key(
                normalized_hash,
                owner_user_id=owner_user_id,
                tenant_id=tenant_id,
                owner_api_key_id=owner_api_key_id,
            )
            if normalized_hash
            else None
        )
        if normalized_hash and idempotency_key:
            existing = self.find_by_input_hash(
                normalized_hash,
                owner_user_id=owner_user_id,
                tenant_id=tenant_id,
                owner_api_key_id=owner_api_key_id,
            )
            if existing:
                return existing
        job_id = f"job-{uuid.uuid4().hex[:12]}"
        track_active_counters = enforce_admission or job_type == "analyze"
        counter_reserved = bool(track_active_counters)
        self._reserve_active_counters(
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            owner_api_key_id=owner_api_key_id,
            enforce_limit=enforce_admission,
            reservation_id=job_id,
        ) if track_active_counters else []
        job = Job(
            job_type=job_type,
            diagram_id=diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            owner_api_key_id=owner_api_key_id,
            durable=durable,
            execution_payload=normalized_payload,
            input_hash=normalized_hash,
            max_attempts=max_attempts or self._default_max_attempts,
            job_id=job_id,
        )
        job_persisted = False

        try:
            if idempotency_key:
                existing = self._reserve_idempotency(idempotency_key, job.job_id)
                if existing:
                    if counter_reserved:
                        self._release_counter_reservation(job.job_id)
                        counter_reserved = False
                    return existing

            # Evict oldest completed jobs if at capacity
            if len(self._jobs) >= self._max_jobs:
                self._evict_completed()

            self._jobs[job.job_id] = job
            if not self._jobs_store.set(job.job_id, job.to_storage_dict()):
                raise JobStoreError("Durable job state could not be persisted")
            job_persisted = True
            if not self._events_store.set(job.job_id, {"next_seq": 0, "dropped_events": 0, "events": []}):
                logger.warning("Initial event state unavailable for accepted job %s; it will be created lazily", job.job_id)
            self._notify_submission_listeners()
            logger.info("Job submitted: %s (type=%s, diagram=%s)", job.job_id, job_type, diagram_id)
            return job
        except Exception:
            if job_persisted:
                logger.exception("Accepted job persistence completed before a later submission error")
                return job
            if idempotency_key:
                self._release_idempotency(idempotency_key, job.job_id)
            self._jobs.pop(job.job_id, None)
            if counter_reserved:
                self._release_counter_reservation(job.job_id)
            raise

    def add_submission_listener(self, listener: Any) -> None:
        if listener not in self._submission_listeners:
            self._submission_listeners.append(listener)

    def remove_submission_listener(self, listener: Any) -> None:
        if listener in self._submission_listeners:
            self._submission_listeners.remove(listener)

    def _notify_submission_listeners(self) -> None:
        for listener in tuple(self._submission_listeners):
            try:
                listener()
            except Exception:
                logger.debug("Durable worker submission notification failed", exc_info=True)

    def _reserve_idempotency(self, input_hash: str, job_id: str) -> Optional[Job]:
        """Atomically reserve an input hash, returning an existing reusable job."""
        while True:
            reserved, current = self._idempotency_store.update_if(
                input_hash,
                lambda value: value is None or not isinstance(value, dict) or not value.get("job_id"),
                lambda _value: {"job_id": job_id, "created_at": datetime.now(timezone.utc).isoformat()},
                ttl=self._ttl_seconds,
            )
            if reserved:
                return None
            existing_job_id = current.get("job_id") if isinstance(current, dict) else None
            existing = self.get(existing_job_id) if existing_job_id else None
            if existing and existing.status in {JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.COMPLETED}:
                return existing
            if existing_job_id:
                created_at = _parse_iso(current.get("created_at")) if isinstance(current, dict) else None
                stale = created_at is None or (
                    datetime.now(timezone.utc) - created_at
                ).total_seconds() >= IDEMPOTENCY_RESERVATION_STALE_SECONDS
                if not stale:
                    raise JobStoreError("Durable job idempotency reservation is still being persisted")
                self._release_idempotency(input_hash, existing_job_id)
                continue
            raise JobStoreError("Durable job idempotency reservation could not be persisted")

    def _release_idempotency(self, input_hash: str, job_id: str) -> None:
        self._idempotency_store.update_if(
            input_hash,
            lambda current: isinstance(current, dict) and current.get("job_id") == job_id,
            lambda _current: None,
            ttl=self._ttl_seconds,
        )

    def find_by_input_hash(
        self,
        input_hash: str,
        *,
        owner_user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        owner_api_key_id: Optional[str] = None,
    ) -> Optional[Job]:
        """Return an active or successful idempotent job for the same input."""
        idempotency_key = self._idempotency_key(
            input_hash,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            owner_api_key_id=owner_api_key_id,
        )
        reservation = self._idempotency_store.peek(idempotency_key)
        reserved_job_id = reservation.get("job_id") if isinstance(reservation, dict) else None
        if reserved_job_id:
            reserved_job = self.get(reserved_job_id)
            if reserved_job and reserved_job.status in {
                JobStatus.QUEUED,
                JobStatus.RUNNING,
                JobStatus.COMPLETED,
            }:
                return reserved_job
        for job_id in self._jobs_store.keys("*"):
            payload = self._jobs_store.peek(job_id) or {}
            if payload.get("input_hash") != input_hash:
                continue
            if (
                payload.get("owner_user_id") != owner_user_id
                or payload.get("tenant_id") != tenant_id
                or payload.get("owner_api_key_id") != owner_api_key_id
            ):
                continue
            status = payload.get("status")
            if status in {
                JobStatus.QUEUED.value,
                JobStatus.RUNNING.value,
                JobStatus.COMPLETED.value,
            }:
                self._idempotency_store.update_if(
                    idempotency_key,
                    lambda current: current is None,
                    lambda _current: {"job_id": job_id, "created_at": payload.get("created_at")},
                    ttl=self._ttl_seconds,
                )
                return self._hydrate_from_store(job_id, payload)
        return None

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
        for field in Job.__slots__:
            if field.startswith("_"):
                continue
            setattr(job, field, getattr(loaded, field))
        return job

    def start(self, job_id: str, phase: str = "running") -> None:
        """Mark a job as running."""
        job = self.get(job_id)
        if not job:
            return
        if job.durable:
            logger.warning("Ignoring direct start for durable job %s; a worker lease is required", job_id)
            return
        job.status = JobStatus.RUNNING
        job.phase = phase
        job.started_at = datetime.now(timezone.utc).isoformat()
        job.progress_message = "Starting..."
        job.updated_at = job.started_at
        self._jobs_store.set(job.job_id, job.to_storage_dict())
        self._emit(job, "status", job.to_dict())

    def claim(self, job_id: str, *, now: Optional[datetime] = None) -> Optional[str]:
        """Atomically claim a queued or lease-expired durable job."""
        now = now or datetime.now(timezone.utc)
        lease_token = uuid.uuid4().hex
        lease_expires_at = datetime.fromtimestamp(now.timestamp() + self._lease_seconds, timezone.utc).isoformat()

        def predicate(current: Any) -> bool:
            if not isinstance(current, dict) or not current.get("durable"):
                return False
            status = current.get("status")
            lease_expires_at = _parse_iso(current.get("lease_expires_at"))
            expired = lease_expires_at is None or lease_expires_at <= now
            attempts_available = int(current.get("attempt", 0) or 0) < int(current.get("max_attempts", 1) or 1)
            return attempts_available and (
                status == JobStatus.QUEUED.value
                or (status == JobStatus.RUNNING.value and expired)
            )

        def updater(current: Dict[str, Any]) -> Dict[str, Any]:
            updated = dict(current)
            updated.update(
                {
                    "status": JobStatus.RUNNING.value,
                    "phase": "running",
                    "started_at": updated.get("started_at") or now.isoformat(),
                    "updated_at": now.isoformat(),
                    "progress_message": "Starting...",
                    "attempt": int(updated.get("attempt", 0) or 0) + 1,
                    "lease_owner": self._worker_id,
                    "lease_token": lease_token,
                    "lease_expires_at": lease_expires_at,
                    "heartbeat_at": now.isoformat(),
                    "retryable": True,
                }
            )
            return updated

        claimed, payload = self._jobs_store.update_if(job_id, predicate, updater, ttl=self._ttl_seconds)
        if not claimed:
            return None
        job = self._hydrate_from_store(job_id, payload)
        self._emit(job, "status", job.to_dict())
        return lease_token

    def heartbeat(self, job_id: str, lease_token: str) -> bool:
        """Extend a running job lease when the caller still owns it."""
        now = datetime.now(timezone.utc)
        expires_at = datetime.fromtimestamp(now.timestamp() + self._lease_seconds, timezone.utc).isoformat()

        def predicate(current: Any) -> bool:
            return (
                isinstance(current, dict)
                and current.get("status") == JobStatus.RUNNING.value
                and current.get("lease_token") == lease_token
                and (_parse_iso(current.get("lease_expires_at")) or datetime.min.replace(tzinfo=timezone.utc)) > now
            )

        def updater(current: Dict[str, Any]) -> Dict[str, Any]:
            return {
                **current,
                "updated_at": now.isoformat(),
                "heartbeat_at": now.isoformat(),
                "lease_expires_at": expires_at,
            }

        updated, payload = self._jobs_store.update_if(job_id, predicate, updater, ttl=self._ttl_seconds)
        if updated:
            self._hydrate_from_store(job_id, payload)
        return updated

    @contextmanager
    def lease_context(self, lease_token: str):
        token = _CURRENT_LEASE_TOKEN.set(lease_token)
        try:
            yield
        finally:
            _CURRENT_LEASE_TOKEN.reset(token)

    def _owned_terminal_transition(
        self,
        job_id: str,
        status: JobStatus,
        *,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        lease_token: Optional[str] = None,
        allow_unclaimed: bool = False,
        allow_recovery: bool = False,
    ) -> bool:
        token = lease_token or _CURRENT_LEASE_TOKEN.get()
        transition_now = datetime.now(timezone.utc)
        now = transition_now.isoformat()
        release_counters = False

        def predicate(current: Any) -> bool:
            nonlocal release_counters
            release_counters = isinstance(current, dict) and not bool(
                current.get("active_counters_released", False)
            )
            return (
                isinstance(current, dict)
                and current.get("status") not in {
                    JobStatus.COMPLETED.value,
                    JobStatus.FAILED.value,
                    JobStatus.CANCELLED.value,
                }
                and (
                    not current.get("durable")
                    or (
                        token
                        and current.get("lease_token") == token
                        and (_parse_iso(current.get("lease_expires_at")) or datetime.min.replace(tzinfo=timezone.utc))
                        > transition_now
                    )
                    or (allow_unclaimed and current.get("status") == JobStatus.QUEUED.value)
                    or (
                        allow_recovery
                        and (
                            current.get("status") == JobStatus.QUEUED.value
                            or (
                                current.get("status") == JobStatus.RUNNING.value
                                and (_parse_iso(current.get("lease_expires_at")) or datetime.min.replace(tzinfo=timezone.utc))
                                <= transition_now
                            )
                        )
                    )
                )
            )

        def updater(current: Dict[str, Any]) -> Dict[str, Any]:
            updated = dict(current)
            updated.update(
                {
                    "status": status.value,
                    "phase": status.value,
                    "progress": 100 if status == JobStatus.COMPLETED else updated.get("progress", 0),
                    "progress_message": "Complete" if status == JobStatus.COMPLETED else updated.get("progress_message", ""),
                    "result": result if status == JobStatus.COMPLETED else updated.get("result"),
                    "error": error if status == JobStatus.FAILED else updated.get("error"),
                    "completed_at": now,
                    "updated_at": now,
                    "lease_owner": None,
                    "lease_token": None,
                    "lease_expires_at": None,
                    "heartbeat_at": None,
                    "retryable": False,
                    "active_counters_released": True,
                }
            )
            return updated

        transitioned, payload = self._jobs_store.update_if(job_id, predicate, updater, ttl=self._ttl_seconds)
        if not transitioned:
            return False
        job = self._hydrate_from_store(job_id, payload)
        if release_counters:
            self._release_job_counter_reservation(job)
        if status == JobStatus.COMPLETED:
            self._emit(job, "complete", {"result": result})
        elif status == JobStatus.FAILED:
            self._emit(job, "error", {"error": error})
        else:
            self._emit(job, "cancelled", {})
        return True

    def _requeue(self, job_id: str, *, reason: str, now: Optional[datetime] = None) -> bool:
        recovery_now = now or datetime.now(timezone.utc)
        updated_at = recovery_now.isoformat()

        def predicate(current: Any) -> bool:
            if not isinstance(current, dict) or not current.get("durable"):
                return False
            return (
                current.get("status") == JobStatus.RUNNING.value
                and (_parse_iso(current.get("lease_expires_at")) or datetime.min.replace(tzinfo=timezone.utc)) <= recovery_now
            )

        def updater(current: Dict[str, Any]) -> Dict[str, Any]:
            return {
                **current,
                "status": JobStatus.QUEUED.value,
                "phase": "recovered",
                "progress_message": reason,
                "updated_at": updated_at,
                "lease_owner": None,
                "lease_token": None,
                "lease_expires_at": None,
                "heartbeat_at": None,
                "recovery_count": int(current.get("recovery_count", 0) or 0) + 1,
                "retryable": True,
            }

        updated, payload = self._jobs_store.update_if(job_id, predicate, updater, ttl=self._ttl_seconds)
        if updated:
            job = self._hydrate_from_store(job_id, payload)
            self._emit(job, "recovered", {"message": reason, "attempt": job.attempt})
            self._increment_durable_metric("recovered_total")
            if job.attempt > 0:
                self._increment_durable_metric("retried_total")
        return updated

    def rebuild_active_counters(self) -> None:
        """Reconcile analysis admission reservations from persisted active jobs."""
        for job_id in self._jobs_store.keys("*"):
            payload = self._jobs_store.peek(job_id) or {}
            job = Job.from_dict(payload)
            if job.job_type == "analyze" and job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                self._reserve_active_counters(
                    owner_user_id=job.owner_user_id,
                    tenant_id=job.tenant_id,
                    owner_api_key_id=job.owner_api_key_id,
                    enforce_limit=False,
                    reservation_id=job.job_id,
                )
        self.reconcile_active_counter_reservations()

    def reconcile_active_counter_reservations(self) -> List[str]:
        """Release admission reservations whose jobs are missing or terminal."""
        record = self._active_counts_store.peek(self._counter_record_key([]))
        released: List[str] = []
        now = datetime.now(timezone.utc)
        for job_id, reservation in self._counter_record_reservations(record).items():
            payload = self._jobs_store.peek(job_id)
            if isinstance(payload, dict) and payload.get("status") in {
                JobStatus.QUEUED.value,
                JobStatus.RUNNING.value,
            }:
                continue
            created_at = _parse_iso(reservation.get("created_at"))
            if not isinstance(payload, dict) and created_at and (
                now - created_at
            ).total_seconds() < IDEMPOTENCY_RESERVATION_STALE_SECONDS:
                continue
            self._release_counter_reservation(job_id)
            released.append(job_id)
        return released

    def reconcile_abandoned(
        self,
        *,
        now: Optional[datetime] = None,
        rebuild_counters: bool = False,
    ) -> Dict[str, Any]:
        """Recover lease-expired jobs; optionally rebuild admission counters."""
        now = now or datetime.now(timezone.utc)
        recovered: List[str] = []
        failed: List[str] = []
        if rebuild_counters:
            self.rebuild_active_counters()
        else:
            self.reconcile_active_counter_reservations()

        for job_id in self._jobs_store.keys("*"):
            payload = self._jobs_store.peek(job_id) or {}
            job = Job.from_dict(payload)
            if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
                continue
            if not job.durable:
                continue
            if job.status == JobStatus.QUEUED:
                if job.attempt >= job.max_attempts:
                    self._owned_terminal_transition(
                        job_id,
                        JobStatus.FAILED,
                        error="Durable job retry budget exhausted after worker loss",
                        allow_unclaimed=True,
                    )
                    failed.append(job_id)
                continue
            lease_expired = (
                (_parse_iso(job.lease_expires_at) or datetime.min.replace(tzinfo=timezone.utc)) <= now
            )
            if not lease_expired:
                continue
            if job.attempt >= job.max_attempts:
                transitioned = self._owned_terminal_transition(
                    job_id,
                    JobStatus.FAILED,
                    error="Durable job retry budget exhausted after worker loss",
                    lease_token=job.lease_token,
                    allow_recovery=True,
                )
                if transitioned:
                    self._increment_durable_metric("abandoned_total")
                    failed.append(job_id)
            elif self._requeue(job_id, reason="Recovered after worker or revision loss", now=now):
                self._increment_durable_metric("abandoned_total")
                recovered.append(job_id)
        return {"recovered": recovered, "failed": failed}

    def update_progress(self, job_id: str, progress: int, message: str = "", phase: Optional[str] = None) -> None:
        """Update job progress (0-100) and emit SSE event."""
        job = self.get(job_id)
        if not job or job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return
        lease_token = _CURRENT_LEASE_TOKEN.get()
        if job.durable:
            now = datetime.now(timezone.utc)

            def predicate(current: Any) -> bool:
                return (
                    isinstance(current, dict)
                    and current.get("status") == JobStatus.RUNNING.value
                    and bool(lease_token)
                    and current.get("lease_token") == lease_token
                    and (_parse_iso(current.get("lease_expires_at")) or datetime.min.replace(tzinfo=timezone.utc)) > now
                )

            def updater(current: Dict[str, Any]) -> Dict[str, Any]:
                updated = dict(current)
                updated["progress"] = max(0, min(progress, 100))
                updated["updated_at"] = now.isoformat()
                if phase:
                    updated["phase"] = phase
                if message:
                    updated["progress_message"] = message
                return updated

            updated, payload = self._jobs_store.update_if(
                job_id,
                predicate,
                updater,
                ttl=self._ttl_seconds,
            )
            if not updated:
                return
            job = self._hydrate_from_store(job_id, payload)
        else:
            if phase:
                job.phase = phase
            job.progress = max(0, min(progress, 100))
            if message:
                job.progress_message = message
            job.updated_at = datetime.now(timezone.utc).isoformat()
            self._jobs_store.set(job.job_id, job.to_storage_dict())
        self._emit(job, "progress", _progress_payload(job))

    def complete(self, job_id: str, result: Optional[Dict[str, Any]] = None) -> None:
        """Mark a job as completed with optional result."""
        job = self.get(job_id)
        if not job or job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return
        if job.durable:
            if self._owned_terminal_transition(job_id, JobStatus.COMPLETED, result=result):
                logger.info("Job completed: %s", job_id)
            return
        job.status = JobStatus.COMPLETED
        self._release_active_counters(job)
        job.phase = "completed"
        job.progress = 100
        job.progress_message = "Complete"
        job.result = result
        job.completed_at = datetime.now(timezone.utc).isoformat()
        job.updated_at = job.completed_at
        self._jobs_store.set(job.job_id, job.to_storage_dict())
        self._emit(job, "complete", {"result": result})
        logger.info("Job completed: %s", job_id)

    def fail(self, job_id: str, error: str) -> None:
        """Mark a job as failed."""
        job = self.get(job_id)
        if not job or job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return
        if job.durable:
            if self._owned_terminal_transition(job_id, JobStatus.FAILED, error=error):
                logger.error("Job failed: %s — %s", job_id, error)
            return
        job.status = JobStatus.FAILED
        self._release_active_counters(job)
        job.phase = "failed"
        job.error = error
        job.completed_at = datetime.now(timezone.utc).isoformat()
        job.updated_at = job.completed_at
        self._jobs_store.set(job.job_id, job.to_storage_dict())
        self._emit(job, "error", {"error": error})
        logger.error("Job failed: %s — %s", job_id, error)

    def cancel(self, job_id: str) -> bool:
        """Cancel a job. Returns True if cancelled, False if already done."""
        job = self.get(job_id)
        if not job:
            return False
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return False
        if job.durable:
            cancel_now = datetime.now(timezone.utc).isoformat()
            release_counters = False

            def predicate(current: Any) -> bool:
                nonlocal release_counters
                release_counters = isinstance(current, dict) and not bool(
                    current.get("active_counters_released", False)
                )
                return (
                    isinstance(current, dict)
                    and current.get("status") in {JobStatus.QUEUED.value, JobStatus.RUNNING.value}
                )

            def updater(current: Dict[str, Any]) -> Dict[str, Any]:
                return {
                    **current,
                    "status": JobStatus.CANCELLED.value,
                    "phase": JobStatus.CANCELLED.value,
                    "completed_at": cancel_now,
                    "updated_at": cancel_now,
                    "lease_owner": None,
                    "lease_token": None,
                    "lease_expires_at": None,
                    "heartbeat_at": None,
                    "retryable": False,
                    "active_counters_released": True,
                }

            cancelled, payload = self._jobs_store.update_if(
                job_id,
                predicate,
                updater,
                ttl=self._ttl_seconds,
            )
            if not cancelled:
                return False
            job = self._hydrate_from_store(job_id, payload)
            if release_counters:
                self._release_job_counter_reservation(job)
            self._emit(job, "cancelled", {})
            logger.info("Job cancelled: %s", job_id)
            return True
        job.status = JobStatus.CANCELLED
        self._release_active_counters(job)
        job.phase = "cancelled"
        job.completed_at = datetime.now(timezone.utc).isoformat()
        job.updated_at = job.completed_at
        self._jobs_store.set(job.job_id, job.to_storage_dict())
        self._emit(job, "cancelled", {})
        logger.info("Job cancelled: %s", job_id)
        return True

    def is_cancelled(self, job_id: str) -> bool:
        """Check if a job has been cancelled (for worker polling)."""
        job = self.get(job_id)
        return job.status == JobStatus.CANCELLED if job else False

    def owns_current_lease(self, job_id: str) -> bool:
        """Return True when the current worker context still owns a live lease."""
        lease_token = _CURRENT_LEASE_TOKEN.get()
        job = self.get(job_id)
        if not job:
            return False
        if not job.durable:
            return job.status not in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
        lease_expires_at = _parse_iso(job.lease_expires_at)
        return (
            job.status == JobStatus.RUNNING
            and bool(lease_token)
            and job.lease_token == lease_token
            and lease_expires_at is not None
            and lease_expires_at > datetime.now(timezone.utc)
        )

    def list_jobs(
        self,
        diagram_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List jobs with optional filters."""
        jobs: List[Job] = []
        for job_id in self._jobs_store.keys("*"):
            payload = self._jobs_store.peek(job_id)
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
                    latest = self.get(job_id)
                    if latest and latest.status not in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                        heartbeat_payload = {**_progress_payload(latest), "heartbeat": True}
                        heartbeat_payload["message"] = ""
                        yield _sse_format("progress", heartbeat_payload)
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
        def updater(current: Any) -> Dict[str, Any]:
            state = dict(current or {})
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
            return {
                "next_seq": next_seq + 1,
                "dropped_events": dropped_events,
                "events": events,
            }

        updated, state = self._events_store.update_if(
            job.job_id,
            lambda _current: True,
            updater,
            ttl=self._ttl_seconds,
        )
        if not updated:
            logger.warning("Failed to persist job event (job_id=%s, event=%s)", job.job_id, event_type)
            return
        job._events = list(state.get("events", []))
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
            job = self._jobs.get(jid) or self.get(jid)
            if job and job.input_hash:
                self._release_idempotency(
                    self._idempotency_key(
                        job.input_hash,
                        owner_user_id=job.owner_user_id,
                        tenant_id=job.tenant_id,
                        owner_api_key_id=job.owner_api_key_id,
                    ),
                    jid,
                )
            self._jobs.pop(jid, None)
            self._jobs_store.delete(jid)
            self._events_store.delete(jid)

    def metrics(self) -> Dict[str, Any]:
        """Return queue/event observability metrics."""
        jobs_payload = self.list_jobs(limit=max(1, self._max_jobs))
        by_status: Dict[str, int] = {}
        queue_ages: List[int] = []
        total_events_buffered = 0
        total_events_dropped = 0
        for item in jobs_payload:
            status = item.get("status", JobStatus.QUEUED.value)
            by_status[status] = by_status.get(status, 0) + 1
            if status == JobStatus.QUEUED.value:
                queue_ages.append(int(item.get("queue_wait_seconds") or 0))
            event_state = self._events_store.peek(item["job_id"], {"events": [], "dropped_events": 0})
            total_events_buffered += len(event_state.get("events", []))
            total_events_dropped += int(event_state.get("dropped_events", 0))
        durable_totals = self._metrics_store.peek("totals", {}) or {}
        retryable_jobs = sum(
            1
            for item in jobs_payload
            if item.get("durable")
            and item.get("retryable")
            and item.get("status") in {JobStatus.QUEUED.value, JobStatus.RUNNING.value}
        )
        obs_record_histogram("jobs.durable.retryable_jobs", retryable_jobs)
        return {
            "backend": session_store_backend(),
            "max_jobs": self._max_jobs,
            "ttl_seconds": self._ttl_seconds,
            "max_events_per_job": self._max_events_per_job,
            "jobs_total": len(jobs_payload),
            "jobs_by_status": by_status,
            "queued_jobs": by_status.get(JobStatus.QUEUED.value, 0),
            "active_workers": by_status.get(JobStatus.RUNNING.value, 0),
            "oldest_queued_age_seconds": max(queue_ages) if queue_ages else 0,
            "queued_age_p95_seconds": _percentile(queue_ages, 95),
            "events_buffered_total": total_events_buffered,
            "events_dropped_total": total_events_dropped,
            "durability": {
                "lease_seconds": self._lease_seconds,
                "max_attempts": self._default_max_attempts,
                "retryable_jobs": retryable_jobs,
                "abandoned_total": int(durable_totals.get("abandoned_total", 0) or 0),
                "recovered_total": int(durable_totals.get("recovered_total", 0) or 0),
                "retried_total": int(durable_totals.get("retried_total", 0) or 0),
            },
        }

    def purge_diagram(self, diagram_id: str) -> int:
        """Delete all jobs and buffered events linked to a diagram."""
        deleted = 0
        for job_id in list(self._jobs_store.keys("*")):
            payload = self._jobs_store.get(job_id) or {}
            if payload.get("diagram_id") != diagram_id:
                continue
            job = Job.from_dict(payload)
            if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
                self.cancel(job_id)
                deleted += 1
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


def _phase_for_status(status: JobStatus) -> str:
    return {
        JobStatus.QUEUED: "queued",
        JobStatus.RUNNING: "running",
        JobStatus.COMPLETED: "completed",
        JobStatus.FAILED: "failed",
        JobStatus.CANCELLED: "cancelled",
    }.get(status, "queued")


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _seconds_between(start: Optional[datetime], end: Optional[datetime]) -> int:
    if not start or not end:
        return 0
    return max(0, int((end - start).total_seconds()))


def _job_timing(job: Job) -> Dict[str, int]:
    now = datetime.now(timezone.utc)
    created_at = _parse_iso(job.created_at)
    started_at = _parse_iso(job.started_at)
    completed_at = _parse_iso(job.completed_at)
    terminal_at = completed_at or now
    return {
        "elapsed_seconds": _seconds_between(created_at, terminal_at),
        "queue_wait_seconds": _seconds_between(created_at, started_at or terminal_at),
        "running_seconds": _seconds_between(started_at, terminal_at),
    }


def _progress_payload(job: Job) -> Dict[str, Any]:
    return {
        "progress": job.progress,
        "message": job.progress_message,
        "phase": job.phase,
        **_job_timing(job),
    }


def _percentile(values: List[int], percentile: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((percentile / 100) * (len(ordered) - 1)))))
    return ordered[index]


# ─────────────────────────────────────────────────────────────
# Singleton instance
# ─────────────────────────────────────────────────────────────
job_manager = JobManager()


class DurableJobWorker:
    """Shared-store worker for restart-safe analysis, IaC, and HLD execution."""

    def __init__(
        self,
        manager: JobManager = job_manager,
        *,
        poll_seconds: Optional[float] = None,
        heartbeat_seconds: Optional[float] = None,
        recovery_seconds: Optional[float] = None,
    ):
        self.manager = manager
        self.poll_seconds = max(0.1, poll_seconds or float(os.getenv("JOB_POLL_SECONDS", "1")))
        self.heartbeat_seconds = max(
            1.0,
            heartbeat_seconds or float(os.getenv("JOB_HEARTBEAT_SECONDS", "15")),
        )
        if self.heartbeat_seconds >= self.manager._lease_seconds:
            raise ValueError("JOB_HEARTBEAT_SECONDS must be lower than JOB_LEASE_SECONDS")
        self.recovery_seconds = max(
            self.poll_seconds,
            recovery_seconds or float(os.getenv("JOB_RECOVERY_SECONDS", "30")),
        )
        self._handlers: Dict[str, Any] = {}
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_task: Optional[asyncio.Task] = None
        self._running_tasks: Dict[str, asyncio.Task] = {}

    def register(self, job_type: str, handler: Any) -> None:
        self._handlers[job_type] = handler

    async def start(self) -> Dict[str, Any]:
        """Reconcile abandoned jobs and start polling shared queued work."""
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._loop = asyncio.get_running_loop()
        self.manager.add_submission_listener(self._notify_submission)
        reconciliation = self.manager.reconcile_abandoned(rebuild_counters=True)
        self.manager.metrics()
        self._loop_task = asyncio.create_task(self._run_loop(), name="durable-job-worker")
        return reconciliation

    async def stop(self) -> None:
        self.manager.remove_submission_listener(self._notify_submission)
        self._stop_event.set()
        self._wake_event.set()
        if self._loop_task:
            self._loop_task.cancel()
            await asyncio.gather(self._loop_task, return_exceptions=True)
            self._loop_task = None
        if self._running_tasks:
            for task in self._running_tasks.values():
                task.cancel()
            await asyncio.gather(*self._running_tasks.values(), return_exceptions=True)
            self._running_tasks.clear()
        self._loop = None

    def _notify_submission(self) -> None:
        loop = self._loop
        if loop and not loop.is_closed():
            loop.call_soon_threadsafe(self._wake_event.set)

    async def _run_loop(self) -> None:
        next_recovery_at = time.monotonic()
        while not self._stop_event.is_set():
            if time.monotonic() >= next_recovery_at:
                self.manager.reconcile_abandoned()
                self.manager.metrics()
                next_recovery_at = time.monotonic() + self.recovery_seconds
            for job_payload in reversed(self.manager.list_jobs(status=JobStatus.QUEUED.value, limit=self.manager._max_jobs)):
                job_id = job_payload["job_id"]
                if job_id in self._running_tasks:
                    continue
                lease_token = self.manager.claim(job_id)
                if not lease_token:
                    continue
                task = asyncio.create_task(
                    self._execute(job_id, lease_token),
                    name=f"durable-job-{job_id}",
                )
                self._running_tasks[job_id] = task
                task.add_done_callback(lambda _task, jid=job_id: self._running_tasks.pop(jid, None))
            try:
                await asyncio.wait_for(self._wake_event.wait(), timeout=self.poll_seconds)
                self._wake_event.clear()
            except asyncio.TimeoutError:
                pass

    async def _heartbeat_loop(self, job_id: str, lease_token: str) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.heartbeat_seconds)
                return
            except asyncio.TimeoutError:
                if not self.manager.heartbeat(job_id, lease_token):
                    return

    async def _execute(self, job_id: str, lease_token: str) -> None:
        job = self.manager.get(job_id)
        if not job:
            return
        handler = self._handlers.get(job.job_type)
        if not handler:
            with self.manager.lease_context(lease_token):
                self.manager.fail(job_id, f"No durable handler registered for {job.job_type}")
            return

        heartbeat_task = asyncio.create_task(self._heartbeat_loop(job_id, lease_token))
        try:
            with self.manager.lease_context(lease_token):
                await handler(job_id, dict(job.execution_payload))
                latest = self.manager.get(job_id)
                if latest and latest.status == JobStatus.RUNNING:
                    self.manager.fail(job_id, "Durable handler exited without terminal status")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "Durable job execution failed (job_type=%s, error_type=%s)",
                job.job_type,
                type(exc).__name__,
                exc_info=True,
            )
            with self.manager.lease_context(lease_token):
                self.manager.fail(job_id, "Durable job execution failed")
        finally:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)


durable_job_worker = DurableJobWorker()
