"""
Tests for the async job queue and SSE streaming (Issue #172).

Covers:
  - Job submission, lifecycle (queued → running → completed/failed/cancelled)
  - Progress tracking
  - Job listing with filters
  - SSE stream format
  - Cancellation flow
  - Jobs API router endpoints
"""

import os
import sys
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import threading
import pytest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from auth import User, AuthProvider, UserTier, generate_session_token


@pytest.fixture()
def auth_headers():
    user = User(
        id="jobs-test-user",
        email="jobs@example.com",
        provider=AuthProvider.GITHUB,
        tier=UserTier.TEAM,
        tenant_id="tenant-jobs",
    )
    token = generate_session_token(user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def api_key_headers(monkeypatch):
    from routers import shared as shared_router

    key = "jobs-api-key"
    monkeypatch.setattr(shared_router, "API_KEY", key)
    return {"X-API-Key": key}


def _api_key_principal(headers: dict) -> str:
    from routers.shared import get_api_key_service_principal

    return get_api_key_service_principal({k.lower(): v for k, v in headers.items()})


# ─────────────────────────────────────────────────────────────
# JobManager unit tests
# ─────────────────────────────────────────────────────────────

class TestJobManager:
    """Unit tests for job_queue.JobManager."""

    def _make_manager(self):
        from job_queue import JobManager
        from session_store import reset_stores

        reset_stores()
        return JobManager(max_jobs=50)

    def test_submit_creates_queued_job(self):
        mgr = self._make_manager()
        job = mgr.submit("analyze", diagram_id="d1")
        assert job.status == "queued"
        assert job.phase == "queued"
        assert job.job_type == "analyze"
        assert job.diagram_id == "d1"
        assert job.job_id is not None

    def test_start_transitions_to_running(self):
        mgr = self._make_manager()
        job = mgr.submit("analyze")
        mgr.start(job.job_id)
        assert job.status == "running"
        assert job.phase == "running"
        assert job.started_at is not None

    def test_update_progress(self):
        mgr = self._make_manager()
        job = mgr.submit("analyze")
        mgr.start(job.job_id)
        mgr.update_progress(job.job_id, 50, "Halfway done", phase="analyzing")
        assert job.progress == 50
        assert job.phase == "analyzing"
        assert job.progress_message == "Halfway done"

    def test_update_progress_clamps_to_full_range(self):
        mgr = self._make_manager()
        job = mgr.submit("analyze")
        mgr.start(job.job_id)
        mgr.update_progress(job.job_id, -1, "negative")
        assert job.progress == 0
        mgr.update_progress(job.job_id, 101, "too high")
        assert job.progress == 100

    def test_complete_sets_result(self):
        mgr = self._make_manager()
        job = mgr.submit("analyze")
        mgr.start(job.job_id)
        mgr.complete(job.job_id, result={"data": "test"})
        from job_queue import JobStatus
        assert job.status == JobStatus.COMPLETED
        assert job.result == {"data": "test"}
        assert job.progress == 100
        assert job.completed_at is not None

    def test_fail_sets_error(self):
        mgr = self._make_manager()
        job = mgr.submit("analyze")
        mgr.start(job.job_id)
        mgr.fail(job.job_id, "Something broke")
        assert job.status == "failed"
        assert job.error == "Something broke"

    def test_cancel_sets_cancelled(self):
        mgr = self._make_manager()
        job = mgr.submit("analyze")
        mgr.start(job.job_id)
        mgr.cancel(job.job_id)
        assert job.status == "cancelled"
        assert mgr.is_cancelled(job.job_id) is True

    def test_is_cancelled_returns_false_for_running(self):
        mgr = self._make_manager()
        job = mgr.submit("analyze")
        mgr.start(job.job_id)
        assert mgr.is_cancelled(job.job_id) is False

    def test_list_jobs_no_filter(self):
        mgr = self._make_manager()
        mgr.submit("analyze", diagram_id="d1")
        mgr.submit("generate_iac", diagram_id="d2")
        jobs = mgr.list_jobs()
        assert len(jobs) == 2

    def test_list_jobs_with_status_filter(self):
        mgr = self._make_manager()
        j1 = mgr.submit("analyze")
        mgr.submit("analyze")  # second job, unused reference
        mgr.start(j1.job_id)
        mgr.complete(j1.job_id, result={})
        completed = mgr.list_jobs(status="completed")
        assert len(completed) == 1
        assert completed[0]["job_id"] == j1.job_id

    def test_list_jobs_contains_job_type(self):
        mgr = self._make_manager()
        mgr.submit("analyze")
        mgr.submit("generate_hld")
        all_jobs = mgr.list_jobs()
        types = [j["job_type"] for j in all_jobs]
        assert "analyze" in types
        assert "generate_hld" in types

    def test_submit_evicts_old_completed_jobs(self):
        mgr = self._make_manager()
        mgr._max_jobs = 5
        # Fill up with completed jobs
        for i in range(5):
            j = mgr.submit("analyze")
            mgr.start(j.job_id)
            mgr.complete(j.job_id, result={})
        # Should be able to submit one more (evicts oldest completed)
        j6 = mgr.submit("analyze")
        assert j6 is not None
        assert len(mgr._jobs) <= 5

    def test_get_nonexistent_job_returns_none(self):
        mgr = self._make_manager()
        job = mgr._jobs.get("nonexistent")
        assert job is None

    def test_event_ring_buffer_limits_and_drops(self):
        mgr = self._make_manager()
        mgr._max_events_per_job = 3
        job = mgr.submit("analyze")
        mgr.start(job.job_id)
        for i in range(6):
            mgr.update_progress(job.job_id, i * 10, f"step-{i}")
        state = mgr._events_store.get(job.job_id)
        assert len(state["events"]) == 3
        assert state["dropped_events"] >= 1
        metrics = mgr.metrics()
        assert metrics["events_dropped_total"] >= 1

    @pytest.mark.asyncio
    async def test_cross_worker_stream_continuity_with_shared_store(self, monkeypatch):
        from session_store import reset_stores
        from session_store import session_store_backend
        from job_queue import JobManager

        # Forces session_store.get_store() to select multi-worker-safe backend.
        monkeypatch.setenv("WEB_CONCURRENCY", "2")
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.delenv("REDIS_HOST", raising=False)
        reset_stores()
        try:
            writer = JobManager(max_jobs=50, max_events_per_job=10, ttl_seconds=120)
            reader = JobManager(max_jobs=50, max_events_per_job=10, ttl_seconds=120)
            assert session_store_backend() == "file"
            job = writer.submit("cross-worker", owner_api_key_id="api-key:test")
            writer.start(job.job_id)
            writer.update_progress(job.job_id, 42, "cross-worker progress")
            writer.complete(job.job_id, result={"ok": True})

            events = []
            async for payload in reader.stream(job.job_id, timeout=1.0):
                events.append(payload)
            event_types = []
            for payload in events:
                event_types.extend(
                    line.split(":", 1)[1].strip()
                    for line in payload.splitlines()
                    if line.startswith("event:")
                )
            assert "progress" in event_types
            assert "complete" in event_types
        finally:
            reset_stores()

    def test_cross_worker_cancel_visible_to_worker(self, monkeypatch):
        from session_store import reset_stores
        from job_queue import JobManager, JobStatus

        monkeypatch.setenv("WEB_CONCURRENCY", "2")
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.delenv("REDIS_HOST", raising=False)
        reset_stores()
        try:
            worker = JobManager(max_jobs=50, max_events_per_job=10, ttl_seconds=120)
            api = JobManager(max_jobs=50, max_events_per_job=10, ttl_seconds=120)
            job = worker.submit("cross-worker", owner_api_key_id="api-key:test")
            worker.start(job.job_id)

            assert api.cancel(job.job_id) is True
            assert worker.is_cancelled(job.job_id) is True
            worker.complete(job.job_id, result={"should_not": "win"})
            assert worker.get(job.job_id).status == JobStatus.CANCELLED
        finally:
            reset_stores()


class TestDurableJobRecovery:
    """Chaos and ownership tests for accepted restart-safe jobs (#1239)."""

    def _make_managers(self, *, max_attempts=3):
        from job_queue import JobManager
        from session_store import reset_stores

        reset_stores()
        writer = JobManager(max_jobs=50, lease_seconds=5, max_attempts=max_attempts, worker_id="writer")
        recovery = JobManager(max_jobs=50, lease_seconds=5, max_attempts=max_attempts, worker_id="recovery")
        return writer, recovery

    def test_atomic_input_hash_idempotency_returns_one_job(self):
        writer, recovery = self._make_managers()
        payload = {"diagram_id": "d1", "image_sha256": "abc", "model": "model-a"}

        first = writer.submit("analyze", diagram_id="d1", execution_payload=payload)
        duplicate = recovery.submit("analyze", diagram_id="d1", execution_payload=payload)

        assert duplicate.job_id == first.job_id
        assert len(writer.list_jobs()) == 1

    def test_changed_configuration_creates_new_job(self):
        writer, recovery = self._make_managers()
        first = writer.submit(
            "generate_iac",
            diagram_id="d1",
            execution_payload={"diagram_id": "d1", "format": "terraform", "model": "model-a"},
        )
        changed = recovery.submit(
            "generate_iac",
            diagram_id="d1",
            execution_payload={"diagram_id": "d1", "format": "terraform", "model": "model-b"},
        )
        assert changed.job_id != first.job_id

    def test_idempotency_is_scoped_to_job_owner(self):
        writer, recovery = self._make_managers()
        payload = {"diagram_id": "d1", "image_sha256": "abc"}

        first = writer.submit("analyze", owner_user_id="u1", tenant_id="t1", execution_payload=payload)
        other_owner = recovery.submit(
            "analyze",
            owner_user_id="u2",
            tenant_id="t1",
            execution_payload=payload,
        )

        assert other_owner.job_id != first.job_id

    def test_stale_idempotency_reservation_is_repaired(self):
        from job_queue import JobManager

        writer, _recovery = self._make_managers()
        payload = {"diagram_id": "d1"}
        input_hash = JobManager.input_hash("generate_hld", None, payload)
        key = JobManager._idempotency_key(
            input_hash,
            owner_user_id=None,
            tenant_id=None,
            owner_api_key_id=None,
        )
        writer._idempotency_store.set(
            key,
            {
                "job_id": "missing-job",
                "created_at": (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat(),
            },
        )

        job = writer.submit("generate_hld", execution_payload=payload)

        assert job.status == "queued"
        assert writer._idempotency_store.peek(key)["job_id"] == job.job_id

    def test_event_store_failure_does_not_rollback_accepted_job(self, monkeypatch):
        writer, recovery = self._make_managers()
        monkeypatch.setattr(writer._events_store, "set", lambda *args, **kwargs: False)
        payload = {"diagram_id": "d1", "analysis_hash": "abc"}

        job = writer.submit("generate_hld", execution_payload=payload)
        duplicate = recovery.submit("generate_hld", execution_payload=payload)

        assert writer.get(job.job_id) is not None
        assert duplicate.job_id == job.job_id
        assert len(writer.list_jobs()) == 1

    def test_worker_rejects_heartbeat_at_or_beyond_lease(self):
        from job_queue import DurableJobWorker

        writer, _recovery = self._make_managers()
        with pytest.raises(ValueError, match="JOB_HEARTBEAT_SECONDS"):
            DurableJobWorker(writer, heartbeat_seconds=5)

    def test_concurrent_idempotent_submissions_persist_one_job(self):
        writer, recovery = self._make_managers()
        payload = {"diagram_id": "d1", "analysis_hash": "abc"}

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(manager.submit, "generate_hld", execution_payload=payload)
                for manager in (writer, recovery)
            ]
        jobs = [future.result() for future in futures]

        assert len({job.job_id for job in jobs}) == 1
        assert len(writer.list_jobs()) == 1

    def test_concurrent_duplicate_waits_for_inflight_job_persistence(self, monkeypatch):
        writer, recovery = self._make_managers()
        payload = {"diagram_id": "d1", "analysis_hash": "abc"}
        entered = threading.Event()
        release = threading.Event()
        original_set = writer._jobs_store.set

        def delayed_set(key, value, ttl=None):
            entered.set()
            release.wait(timeout=1)
            return original_set(key, value, ttl=ttl)

        monkeypatch.setattr(writer._jobs_store, "set", delayed_set)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(writer.submit, "generate_hld", execution_payload=payload)
            assert entered.wait(timeout=1)
            duplicate = pool.submit(recovery.submit, "generate_hld", execution_payload=payload)
            release.set()
            first_job = first.result()
            duplicate_job = duplicate.result()

        assert duplicate_job.job_id == first_job.job_id

    @pytest.mark.chaos
    def test_crash_after_submit_is_claimable(self):
        writer, recovery = self._make_managers()
        job = writer.submit("generate_hld", execution_payload={"diagram_id": "d1"})

        assert recovery.claim(job.job_id) is not None
        claimed = recovery.get(job.job_id)
        assert claimed.status == "running"
        assert claimed.attempt == 1

    @pytest.mark.chaos
    def test_crash_after_claim_is_requeued_after_lease_expiry(self):
        writer, recovery = self._make_managers()
        job = writer.submit("analyze", execution_payload={"diagram_id": "d1"})
        claim_time = datetime.now(timezone.utc)
        stale_token = writer.claim(job.job_id, now=claim_time)
        assert stale_token

        result = recovery.reconcile_abandoned(now=claim_time + timedelta(seconds=6))

        assert result["recovered"] == [job.job_id]
        recovered = recovery.get(job.job_id)
        assert recovered.status == "queued"
        assert recovered.recovery_count == 1

    @pytest.mark.chaos
    def test_crash_before_completion_persistence_allows_retry(self):
        writer, recovery = self._make_managers()
        job = writer.submit("generate_iac", execution_payload={"diagram_id": "d1", "format": "bicep"})
        claim_time = datetime.now(timezone.utc)
        stale_token = writer.claim(job.job_id, now=claim_time)
        assert stale_token
        writer.update_progress(job.job_id, 80, "side effect finished")

        recovery.reconcile_abandoned(now=claim_time + timedelta(seconds=6))
        retry_token = recovery.claim(job.job_id, now=claim_time + timedelta(seconds=7))

        assert retry_token and retry_token != stale_token
        assert recovery.get(job.job_id).attempt == 2

    def test_stale_worker_cannot_progress_or_complete_after_reclaim(self):
        writer, recovery = self._make_managers()
        job = writer.submit("generate_hld", execution_payload={"diagram_id": "d1"})
        claim_time = datetime.now(timezone.utc)
        stale_token = writer.claim(job.job_id, now=claim_time)
        recovery.reconcile_abandoned(now=claim_time + timedelta(seconds=6))
        fresh_token = recovery.claim(job.job_id, now=claim_time + timedelta(seconds=7))
        assert fresh_token

        with writer.lease_context(stale_token):
            writer.update_progress(job.job_id, 99, "stale write")
            writer.complete(job.job_id, {"winner": "stale"})

        latest = recovery.get(job.job_id)
        assert latest.status == "running"
        assert latest.progress != 99
        assert latest.result is None

    def test_expired_worker_cannot_complete_before_reconciliation(self):
        writer, recovery = self._make_managers()
        job = writer.submit("generate_hld", execution_payload={"diagram_id": "d1"})
        expired_claim_time = datetime.now(timezone.utc) - timedelta(seconds=6)
        stale_token = writer.claim(job.job_id, now=expired_claim_time)
        assert stale_token

        with writer.lease_context(stale_token):
            writer.complete(job.job_id, {"winner": "expired"})

        latest = recovery.get(job.job_id)
        assert latest.status == "running"
        assert latest.result is None

    def test_running_job_cancel_revokes_worker_lease_and_releases_counter_once(self):
        writer, recovery = self._make_managers()
        job = writer.submit(
            "analyze",
            owner_user_id="u1",
            execution_payload={"diagram_id": "d1"},
            enforce_admission=True,
        )
        token = writer.claim(job.job_id)
        assert writer.count_active_jobs(user_id="u1") == 1

        assert recovery.cancel(job.job_id) is True
        assert recovery.cancel(job.job_id) is False
        assert writer.count_active_jobs(user_id="u1") == 0
        with writer.lease_context(token):
            writer.complete(job.job_id, {"should_not": "win"})
        assert recovery.get(job.job_id).status == "cancelled"

    def test_startup_rebuild_restores_analysis_admission_counters(self):
        writer, recovery = self._make_managers()
        writer.submit("analyze", owner_user_id="u1", tenant_id="t1", execution_payload={"diagram_id": "d1"})
        writer._active_counts_store.delete("totals")
        assert recovery.count_active_jobs(user_id="u1") == 0

        recovery.reconcile_abandoned(rebuild_counters=True)

        assert recovery.count_active_jobs(user_id="u1") == 1
        assert recovery.count_active_jobs(tenant_id="t1") == 1

    def test_periodic_recovery_does_not_double_rebuild_counters(self):
        writer, recovery = self._make_managers()
        writer.submit("analyze", owner_user_id="u1", execution_payload={"diagram_id": "d1"})
        recovery.reconcile_abandoned(rebuild_counters=True)

        recovery.reconcile_abandoned()

        assert recovery.count_active_jobs(user_id="u1") == 1

    def test_periodic_recovery_repairs_terminal_counter_reservation(self):
        writer, recovery = self._make_managers()
        job = writer.submit(
            "analyze",
            owner_user_id="u1",
            execution_payload={"diagram_id": "d1"},
            enforce_admission=True,
        )
        payload = writer._jobs_store.peek(job.job_id)
        payload.update(
            {
                "status": "completed",
                "phase": "completed",
                "active_counters_released": True,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        writer._jobs_store.set(job.job_id, payload)
        assert recovery.count_active_jobs(user_id="u1") == 1

        recovery.reconcile_abandoned()

        assert recovery.count_active_jobs(user_id="u1") == 0

    def test_retry_budget_exhaustion_fails_and_releases_counter(self):
        writer, recovery = self._make_managers(max_attempts=1)
        job = writer.submit(
            "analyze",
            owner_user_id="u1",
            execution_payload={"diagram_id": "d1"},
            enforce_admission=True,
        )
        claim_time = datetime.now(timezone.utc)
        writer.claim(job.job_id, now=claim_time)

        result = recovery.reconcile_abandoned(now=claim_time + timedelta(seconds=6))

        assert result["failed"] == [job.job_id]
        failed = recovery.get(job.job_id)
        assert failed.status == "failed"
        assert failed.retryable is False
        assert recovery.count_active_jobs(user_id="u1") == 0

    @pytest.mark.asyncio
    async def test_recovered_event_preserves_sse_continuity(self):
        writer, recovery = self._make_managers()
        job = writer.submit("generate_iac", execution_payload={"diagram_id": "d1"})
        claim_time = datetime.now(timezone.utc)
        writer.claim(job.job_id, now=claim_time)
        recovery.reconcile_abandoned(now=claim_time + timedelta(seconds=6))
        recovery.cancel(job.job_id)

        events = []
        async for event in writer.stream(job.job_id, timeout=1):
            events.append(event)
        combined = "".join(events)
        assert "event: recovered" in combined
        assert "event: cancelled" in combined

    def test_durable_metrics_expose_recovery_counts(self):
        writer, recovery = self._make_managers()
        job = writer.submit("generate_hld", execution_payload={"diagram_id": "d1"})
        claim_time = datetime.now(timezone.utc)
        writer.claim(job.job_id, now=claim_time)
        recovery.reconcile_abandoned(now=claim_time + timedelta(seconds=6))

        metrics = recovery.metrics()["durability"]
        assert metrics["abandoned_total"] == 1
        assert metrics["recovered_total"] == 1
        assert metrics["retried_total"] == 1
        assert metrics["retryable_jobs"] == 1

    @pytest.mark.asyncio
    async def test_worker_executes_claimed_envelope_to_completion(self):
        from job_queue import DurableJobWorker

        writer, _recovery = self._make_managers()
        worker = DurableJobWorker(writer, poll_seconds=0.01, heartbeat_seconds=1, recovery_seconds=1)

        async def handler(job_id, payload):
            assert payload == {"diagram_id": "d1"}
            writer.complete(job_id, {"ok": True})

        worker.register("generate_hld", handler)
        job = writer.submit("generate_hld", execution_payload={"diagram_id": "d1"})
        await worker.start()
        try:
            for _ in range(100):
                if writer.get(job.job_id).status == "completed":
                    break
                await asyncio.sleep(0.01)
            assert writer.get(job.job_id).result == {"ok": True}
        finally:
            await worker.stop()

    @pytest.mark.asyncio
    async def test_submission_wakes_worker_before_poll_interval(self):
        from job_queue import DurableJobWorker

        writer, _recovery = self._make_managers()
        worker = DurableJobWorker(writer, poll_seconds=30, heartbeat_seconds=1, recovery_seconds=30)

        async def handler(job_id, _payload):
            writer.complete(job_id, {"ok": True})

        worker.register("generate_hld", handler)
        await worker.start()
        try:
            await asyncio.sleep(0)
            job = writer.submit("generate_hld", execution_payload={"diagram_id": "d1"})
            for _ in range(50):
                if writer.get(job.job_id).status == "completed":
                    break
                await asyncio.sleep(0.01)
            assert writer.get(job.job_id).status == "completed"
        finally:
            await worker.stop()


# ─────────────────────────────────────────────────────────────
# Job serialization
# ─────────────────────────────────────────────────────────────

class TestJobSerialization:
    """Test Job.to_dict() serialization."""

    def test_to_dict_contains_required_fields(self):
        from job_queue import JobManager
        mgr = JobManager()
        job = mgr.submit("analyze", diagram_id="d1")
        d = job.to_dict()
        assert "job_id" in d
        assert "status" in d
        assert "phase" in d
        assert "job_type" in d
        assert "progress" in d
        assert "created_at" in d
        assert "updated_at" in d
        assert "elapsed_seconds" in d
        assert "queue_wait_seconds" in d
        assert "running_seconds" in d
        assert d["status"] == "queued"
        assert d["phase"] == "queued"
        assert d["job_type"] == "analyze"
        assert d["diagram_id"] == "d1"


# ─────────────────────────────────────────────────────────────
# SSE helpers
# ─────────────────────────────────────────────────────────────

class TestSSEHelpers:
    """Tests for sse.py helper functions."""

    def test_format_sse_basic(self):
        from sse import format_sse
        result = format_sse("progress", {"msg": "hello"})
        assert "data:" in result
        assert result.endswith("\n\n")
        assert "event: progress" in result
        data_line = [line for line in result.split("\n") if line.startswith("data:")][0]
        payload = json.loads(data_line.split("data:", 1)[1].strip())
        assert payload["msg"] == "hello"

    def test_format_sse_with_event(self):
        from sse import format_sse
        result = format_sse("status", {"x": 1})
        assert "event: status" in result
        assert "data:" in result

    def test_format_sse_with_id(self):
        from sse import format_sse
        result = format_sse("progress", {"x": 1}, event_id="42")
        assert "id: 42" in result


# ─────────────────────────────────────────────────────────────
# Jobs API router (via TestClient)
# ─────────────────────────────────────────────────────────────

class TestJobsRouter:
    """Integration tests for /api/jobs endpoints."""

    def test_get_job_status(self, test_client, auth_headers):
        """Submit a job via the manager, then GET its status."""
        from job_queue import job_manager
        job = job_manager.submit("test_type", diagram_id="test-d1", owner_user_id="jobs-test-user", tenant_id="tenant-jobs")
        res = test_client.get(f"/api/jobs/{job.job_id}", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["job_id"] == job.job_id
        assert data["status"] == "queued"

    def test_get_job_not_found(self, test_client, auth_headers):
        res = test_client.get("/api/jobs/nonexistent-id-12345", headers=auth_headers)
        assert res.status_code == 404

    def test_cancel_job(self, test_client, auth_headers):
        from job_queue import job_manager
        job = job_manager.submit("test_type", owner_user_id="jobs-test-user", tenant_id="tenant-jobs")
        job_manager.start(job.job_id)
        res = test_client.post(f"/api/jobs/{job.job_id}/cancel", headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["status"] == "cancelled"

    def test_cancel_completed_job_fails(self, test_client, auth_headers):
        from job_queue import job_manager
        job = job_manager.submit("test_type", owner_user_id="jobs-test-user", tenant_id="tenant-jobs")
        job_manager.start(job.job_id)
        job_manager.complete(job.job_id, result={})
        res = test_client.post(f"/api/jobs/{job.job_id}/cancel", headers=auth_headers)
        assert res.status_code == 409

    def test_list_jobs(self, test_client, auth_headers):
        res = test_client.get("/api/jobs", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert "jobs" in data
        assert isinstance(data["jobs"], list)

    def test_list_jobs_with_status_filter(self, test_client, auth_headers):
        res = test_client.get("/api/jobs?status=completed", headers=auth_headers)
        assert res.status_code == 200

    def test_stream_endpoint_returns_sse(self, test_client, auth_headers):
        """Verify the stream endpoint returns text/event-stream content type."""
        from job_queue import job_manager
        job = job_manager.submit("test_stream", owner_user_id="jobs-test-user", tenant_id="tenant-jobs")
        job_manager.start(job.job_id)
        job_manager.complete(job.job_id, result={"done": True})
        # TestClient doesn't support real SSE streaming, but we can verify
        # the endpoint exists and returns the right content type
        res = test_client.get(f"/api/jobs/{job.job_id}/stream", headers=auth_headers)
        assert res.status_code == 200
        assert "text/event-stream" in res.headers.get("content-type", "")

    def test_api_key_owned_job_status_stream_cancel(self, test_client, api_key_headers):
        from job_queue import job_manager

        principal_id = _api_key_principal(api_key_headers)
        stream_job = job_manager.submit("test_stream", owner_api_key_id=principal_id)
        job_manager.start(stream_job.job_id)
        job_manager.complete(stream_job.job_id, result={"done": True})

        status_res = test_client.get(f"/api/jobs/{stream_job.job_id}", headers=api_key_headers)
        assert status_res.status_code == 200
        stream_res = test_client.get(f"/api/jobs/{stream_job.job_id}/stream", headers=api_key_headers)
        assert stream_res.status_code == 200
        cancel_job = job_manager.submit("test_cancel", owner_api_key_id=principal_id)
        job_manager.start(cancel_job.job_id)
        cancel_res = test_client.post(f"/api/jobs/{cancel_job.job_id}/cancel", headers=api_key_headers)
        assert cancel_res.status_code == 200
        assert cancel_res.json()["status"] == "cancelled"

    def test_metrics_endpoint_exposes_queue_observability(self, test_client, api_key_headers):
        res = test_client.get("/api/jobs/metrics/summary", headers=api_key_headers)
        assert res.status_code == 200
        payload = res.json()
        assert "backend" in payload
        assert "events_dropped_total" in payload
        assert "max_events_per_job" in payload
        assert "active_workers" in payload
        assert "queued_jobs" in payload
        assert "oldest_queued_age_seconds" in payload
        assert "queued_age_p95_seconds" in payload

    def test_job_owner_mismatch_returns_not_found(self, test_client, auth_headers):
        from job_queue import job_manager
        job = job_manager.submit("test_stream", owner_user_id="other-user", tenant_id="tenant-jobs")
        res = test_client.get(f"/api/jobs/{job.job_id}", headers=auth_headers)
        assert res.status_code == 404


# ─────────────────────────────────────────────────────────────
# Async analyze endpoint
# ─────────────────────────────────────────────────────────────

class TestAsyncAnalyzeEndpoint:
    """Test the async analyze endpoint returns 202."""

    def test_async_endpoints_do_not_launch_process_local_runner_tasks(self):
        from pathlib import Path

        routers_dir = Path(__file__).resolve().parents[1] / "routers"
        for filename, runner in (
            ("diagrams.py", "_run_analysis_job"),
            ("iac_routes.py", "_run_iac_job"),
            ("hld_routes.py", "_run_hld_job"),
        ):
            source = (routers_dir / filename).read_text()
            assert f"create_task({runner}" not in source
            assert "execution_payload=" in source

    def test_analyze_async_no_upload_returns_404(self, test_client, auth_headers):
        """Without uploading first, should get 404."""
        res = test_client.post("/api/diagrams/nonexistent/analyze-async", headers=auth_headers)
        assert res.status_code == 404

    def test_generate_async_invalid_format(self, test_client, auth_headers):
        """Invalid IaC format should return 422 from schema validation."""
        from routers.shared import SESSION_STORE

        SESSION_STORE["test"] = {
            "services_detected": 0,
            "mappings": [],
            "_owner_user_id": "jobs-test-user",
            "_tenant_id": "tenant-jobs",
        }
        res = test_client.post("/api/diagrams/test/generate-async?format=invalid", headers=auth_headers)
        assert res.status_code == 422

    def test_generate_hld_async_no_analysis(self, test_client, auth_headers):
        """Without prior analysis, should return 404."""
        res = test_client.post("/api/diagrams/nonexistent/generate-hld-async", headers=auth_headers)
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_analysis_worker_rejects_changed_uploaded_image(self):
        from job_queue import JobManager
        from routers.diagrams import _run_analysis_job
        from routers.shared import IMAGE_STORE
        import routers.diagrams as diagrams_router

        manager = JobManager(max_jobs=20, worker_id="analysis-test")
        original_manager = diagrams_router.job_manager
        diagrams_router.job_manager = manager
        diagram_id = "changed-analysis-image"
        IMAGE_STORE[diagram_id] = (b"new-image", "image/png")
        try:
            job = manager.submit(
                "analyze",
                diagram_id=diagram_id,
                execution_payload={
                    "diagram_id": diagram_id,
                    "image_sha256": "stale-hash",
                    "content_type": "image/png",
                },
            )
            token = manager.claim(job.job_id)
            with manager.lease_context(token):
                await _run_analysis_job(job.job_id, job.execution_payload)
            failed = manager.get(job.job_id)
            assert failed.status == "failed"
            assert "image changed" in failed.error.lower()
        finally:
            diagrams_router.job_manager = original_manager
            IMAGE_STORE.delete(diagram_id)

    @pytest.mark.asyncio
    async def test_iac_worker_rejects_changed_analysis(self):
        from job_queue import JobManager
        from routers.iac_routes import _run_iac_job
        from routers.shared import SESSION_STORE
        import routers.iac_routes as iac_router

        manager = JobManager(max_jobs=20, worker_id="iac-test")
        original_manager = iac_router.job_manager
        iac_router.job_manager = manager
        diagram_id = "changed-iac-analysis"
        SESSION_STORE[diagram_id] = {"mappings": [{"source_service": "S3"}]}
        try:
            job = manager.submit(
                "generate_iac",
                diagram_id=diagram_id,
                execution_payload={
                    "diagram_id": diagram_id,
                    "format": "terraform",
                    "analysis_hash": "stale-hash",
                },
            )
            token = manager.claim(job.job_id)
            with manager.lease_context(token):
                await _run_iac_job(job.job_id, job.execution_payload)
            failed = manager.get(job.job_id)
            assert failed.status == "failed"
            assert "analysis changed" in failed.error.lower()
        finally:
            iac_router.job_manager = original_manager
            SESSION_STORE.delete(diagram_id)

    @pytest.mark.asyncio
    async def test_iac_worker_rejects_revoked_owner(self):
        from job_queue import JobManager
        from routers.iac_routes import _iac_generation_input_hash, _run_iac_job
        from routers.shared import SESSION_STORE
        import routers.iac_routes as iac_router

        manager = JobManager(max_jobs=20, worker_id="iac-owner-test")
        original_manager = iac_router.job_manager
        iac_router.job_manager = manager
        diagram_id = "revoked-iac-owner"
        session = {
            "mappings": [{"source_service": "S3"}],
            "_owner_user_id": "new-owner",
            "_tenant_id": "tenant-a",
        }
        SESSION_STORE[diagram_id] = session
        try:
            job = manager.submit(
                "generate_iac",
                diagram_id=diagram_id,
                owner_user_id="old-owner",
                tenant_id="tenant-a",
                execution_payload={
                    "diagram_id": diagram_id,
                    "format": "terraform",
                    "analysis_hash": _iac_generation_input_hash(session),
                },
            )
            token = manager.claim(job.job_id)
            with manager.lease_context(token):
                await _run_iac_job(job.job_id, job.execution_payload)
            failed = manager.get(job.job_id)
            assert failed.status == "failed"
            assert "access revoked" in failed.error.lower()
        finally:
            iac_router.job_manager = original_manager
            SESSION_STORE.delete(diagram_id)

    @pytest.mark.asyncio
    async def test_hld_worker_rejects_changed_analysis(self):
        from job_queue import JobManager
        from routers.hld_routes import _run_hld_job
        from routers.shared import SESSION_STORE
        import routers.hld_routes as hld_router

        manager = JobManager(max_jobs=20, worker_id="hld-test")
        original_manager = hld_router.job_manager
        hld_router.job_manager = manager
        diagram_id = "changed-hld-analysis"
        SESSION_STORE[diagram_id] = {"mappings": [{"source_service": "S3"}]}
        try:
            job = manager.submit(
                "generate_hld",
                diagram_id=diagram_id,
                execution_payload={"diagram_id": diagram_id, "analysis_hash": "stale-hash"},
            )
            token = manager.claim(job.job_id)
            with manager.lease_context(token):
                await _run_hld_job(job.job_id, job.execution_payload)
            failed = manager.get(job.job_id)
            assert failed.status == "failed"
            assert "analysis changed" in failed.error.lower()
        finally:
            hld_router.job_manager = original_manager
            SESSION_STORE.delete(diagram_id)

    def test_api_key_async_iac_create_status_stream_cancel(self, test_client, api_key_headers, monkeypatch):
        from job_queue import durable_job_worker, job_manager
        from routers.shared import SESSION_STORE

        async def _wait_for_cancellation(job_id, _payload):
            for _ in range(100):
                if job_manager.is_cancelled(job_id):
                    return
                await asyncio.sleep(0.01)

        monkeypatch.setitem(durable_job_worker._handlers, "generate_iac", _wait_for_cancellation)
        diagram_id = "api-key-iac-diagram"
        SESSION_STORE[diagram_id] = {
            "services_detected": 0,
            "mappings": [],
            "_owner_api_key_id": _api_key_principal(api_key_headers),
        }
        try:
            create = test_client.post(f"/api/diagrams/{diagram_id}/generate-async", headers=api_key_headers)
            assert create.status_code == 202, create.text
            job_id = create.json()["job_id"]
            principal_id = _api_key_principal(api_key_headers)
            created = job_manager.get(job_id)
            assert created is not None
            assert created.durable is True
            assert created.execution_payload["diagram_id"] == diagram_id
            assert created.execution_payload["format"] == "terraform"
            assert created.execution_payload["analysis_hash"]
            assert created.owner_user_id is None
            assert created.owner_api_key_id == principal_id

            status_res = test_client.get(f"/api/jobs/{job_id}", headers=api_key_headers)
            assert status_res.status_code == 200
            cancel_res = test_client.post(f"/api/jobs/{job_id}/cancel", headers=api_key_headers)
            assert cancel_res.status_code == 200
            stream_res = test_client.get(f"/api/jobs/{job_id}/stream", headers=api_key_headers)
            assert stream_res.status_code == 200
        finally:
            SESSION_STORE.delete(diagram_id)


# ─────────────────────────────────────────────────────────────
# Admission control (per-user / per-tenant limits)
# ─────────────────────────────────────────────────────────────

class TestAdmissionControl:
    """Tests for per-user and per-tenant active-job limits."""

    def _make_manager(self, max_per_user=2, max_per_tenant=5):
        from job_queue import JobManager
        from session_store import reset_stores

        reset_stores()
        return JobManager(max_jobs=50, max_active_jobs_per_user=max_per_user, max_active_jobs_per_tenant=max_per_tenant)

    def test_count_active_jobs_empty(self):
        mgr = self._make_manager()
        assert mgr.count_active_jobs(user_id="u1") == 0

    def test_count_active_jobs_by_user(self):
        mgr = self._make_manager()
        j1 = mgr.submit("analyze", owner_user_id="u1", tenant_id="t1")
        mgr.submit("analyze", owner_user_id="u1", tenant_id="t1")
        mgr.submit("analyze", owner_user_id="u2", tenant_id="t1")
        assert mgr.count_active_jobs(user_id="u1") == 2
        assert mgr.count_active_jobs(user_id="u2") == 1
        # Completing a job should reduce the count.
        mgr.start(j1.job_id)
        mgr.complete(j1.job_id, result={})
        assert mgr.count_active_jobs(user_id="u1") == 1

    def test_count_active_jobs_by_tenant(self):
        mgr = self._make_manager()
        for _ in range(3):
            mgr.submit("analyze", owner_user_id="u1", tenant_id="tenant-a")
        mgr.submit("analyze", owner_user_id="u2", tenant_id="tenant-b")
        assert mgr.count_active_jobs(tenant_id="tenant-a") == 3
        assert mgr.count_active_jobs(tenant_id="tenant-b") == 1

    def test_check_admission_passes_within_limit(self):
        mgr = self._make_manager(max_per_user=3)
        mgr.submit("analyze", owner_user_id="u1", tenant_id="t1")
        # Should not raise — 1 < 3
        mgr.check_admission(owner_user_id="u1", tenant_id="t1")

    def test_check_admission_raises_at_user_limit(self):
        from job_queue import AdmissionRejected
        mgr = self._make_manager(max_per_user=2)
        mgr.submit("analyze", owner_user_id="u1", tenant_id="t1")
        mgr.submit("analyze", owner_user_id="u1", tenant_id="t1")
        with pytest.raises(AdmissionRejected):
            mgr.check_admission(owner_user_id="u1", tenant_id="t1")

    def test_check_admission_raises_at_tenant_limit(self):
        from job_queue import AdmissionRejected
        mgr = self._make_manager(max_per_user=10, max_per_tenant=2)
        mgr.submit("analyze", owner_user_id="u1", tenant_id="tenant-x")
        mgr.submit("analyze", owner_user_id="u2", tenant_id="tenant-x")
        with pytest.raises(AdmissionRejected):
            mgr.check_admission(owner_user_id="u3", tenant_id="tenant-x")

    def test_check_admission_disabled_when_limit_is_zero(self):
        mgr = self._make_manager(max_per_user=0, max_per_tenant=0)
        # Fill with many jobs
        for _ in range(10):
            mgr.submit("analyze", owner_user_id="u1", tenant_id="t1")
        # Should never raise when limits are 0 (disabled)
        mgr.check_admission(owner_user_id="u1", tenant_id="t1")

    def test_check_admission_api_key_uses_user_limit(self):
        from job_queue import AdmissionRejected
        mgr = self._make_manager(max_per_user=2)
        mgr.submit("analyze", owner_api_key_id="api-key:svc")
        mgr.submit("analyze", owner_api_key_id="api-key:svc")
        with pytest.raises(AdmissionRejected):
            mgr.check_admission(owner_api_key_id="api-key:svc")

    def test_submit_enforce_admission_rejects_at_limit(self):
        from job_queue import AdmissionRejected
        mgr = self._make_manager(max_per_user=2)
        mgr.submit("analyze", owner_user_id="u1", tenant_id="t1")
        mgr.submit("analyze", owner_user_id="u1", tenant_id="t1")
        with pytest.raises(AdmissionRejected):
            mgr.submit("analyze", owner_user_id="u1", tenant_id="t1", enforce_admission=True)

    def test_submit_enforce_admission_surfaces_counter_store_failure(self, monkeypatch):
        from job_queue import AdmissionStoreError
        mgr = self._make_manager(max_per_user=2)
        monkeypatch.setattr(
            mgr._active_counts_store,
            "update_if",
            lambda *args, **kwargs: (False, {"counts": {"user:u1": 0}}),
        )
        with pytest.raises(AdmissionStoreError):
            mgr.submit("analyze", owner_user_id="u1", tenant_id="t1", enforce_admission=True)

    def test_concurrent_admission_reservations_do_not_oversubscribe(self):
        from job_queue import AdmissionRejected

        mgr = self._make_manager(max_per_user=1, max_per_tenant=1)

        def submit():
            return mgr.submit(
                "analyze",
                owner_user_id="u1",
                tenant_id="t1",
                enforce_admission=True,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(submit) for _ in range(2)]
        outcomes = []
        for future in futures:
            try:
                outcomes.append(future.result())
            except AdmissionRejected:
                outcomes.append("rejected")

        assert sum(item != "rejected" for item in outcomes) == 1
        assert mgr.count_active_jobs(user_id="u1") == 1
        assert mgr.count_active_jobs(tenant_id="t1") == 1

    def test_non_analysis_jobs_do_not_consume_analysis_quota(self):
        mgr = self._make_manager(max_per_user=2)
        mgr.submit("generate_iac", owner_user_id="u1", tenant_id="t1")
        mgr.submit("generate_hld", owner_user_id="u1", tenant_id="t1")
        assert mgr.count_active_jobs(user_id="u1") == 0
        mgr.submit("analyze", owner_user_id="u1", tenant_id="t1", enforce_admission=True)
        assert mgr.count_active_jobs(user_id="u1") == 1

    def test_active_counters_release_only_once_for_terminal_jobs(self):
        mgr = self._make_manager(max_per_user=2)
        job = mgr.submit("analyze", owner_user_id="u1", tenant_id="t1")
        assert mgr.count_active_jobs(user_id="u1") == 1
        mgr.complete(job.job_id, result={})
        mgr.complete(job.job_id, result={"duplicate": True})
        assert mgr.count_active_jobs(user_id="u1") == 0

        cancel_job = mgr.submit("analyze", owner_user_id="u1", tenant_id="t1")
        assert mgr.cancel(cancel_job.job_id) is True
        assert mgr.cancel(cancel_job.job_id) is False
        assert mgr.count_active_jobs(user_id="u1") == 0

    def test_analyze_async_returns_429_when_user_at_limit(self, test_client, auth_headers, monkeypatch):
        """analyze-async endpoint enforces per-user admission limit."""
        from job_queue import job_manager, AdmissionRejected

        # Simulate the user being over their limit at submission time.
        def _always_reject(*args, **kwargs):
            raise AdmissionRejected(
                "Active analysis job limit reached (5/5). Wait for current analysis jobs to finish and try again.",
                scope="user",
                active=5,
                limit=5,
            )

        monkeypatch.setattr(job_manager, "submit", _always_reject)

        from routers.shared import IMAGE_STORE
        IMAGE_STORE["adm-diagram"] = (b"fake", "image/png")
        try:
            res = test_client.post("/api/diagrams/adm-diagram/analyze-async", headers=auth_headers)
            assert res.status_code == 429
            body = res.json()
            assert body["error"]["details"]["error"] == "analysis_admission_rejected"
            assert body["error"]["details"]["scope"] == "user"
            assert "jobs-test-user" not in body["error"]["message"]
        finally:
            IMAGE_STORE.delete("adm-diagram")


# ─────────────────────────────────────────────────────────────
# OpenAI metrics
# ─────────────────────────────────────────────────────────────

class TestOpenAIMetrics:
    """Tests for OpenAI timeout/429 metric tracking."""

    def test_handle_openai_error_tracks_rate_limit(self, monkeypatch):
        from openai_client import handle_openai_error, get_openai_error_metrics
        from unittest.mock import MagicMock

        # Reset counters
        import openai_client
        with openai_client._openai_metrics_lock:
            openai_client._openai_metrics["rate_limit_total"] = 0

        # Build a minimal mock that passes as a RateLimitError
        from openai import RateLimitError as _RateLimitError
        mock_request = MagicMock()
        mock_response = MagicMock()
        mock_response.request = mock_request
        exc = _RateLimitError(message="rate limited", response=mock_response, body=None)
        handle_openai_error(exc, "test")
        stats = get_openai_error_metrics()
        assert stats["rate_limit_total"] >= 1

    def test_handle_openai_error_tracks_timeout(self, monkeypatch):
        from openai_client import handle_openai_error, get_openai_error_metrics
        from openai import APITimeoutError as _APITimeoutError
        from unittest.mock import MagicMock

        import openai_client
        with openai_client._openai_metrics_lock:
            openai_client._openai_metrics["timeout_total"] = 0

        exc = _APITimeoutError(request=MagicMock())
        handle_openai_error(exc, "test")
        stats = get_openai_error_metrics()
        assert stats["timeout_total"] >= 1

    def test_metrics_endpoint_includes_openai_section(self, test_client, api_key_headers):
        """The /api/jobs/metrics/summary endpoint should include openai sub-section."""
        res = test_client.get("/api/jobs/metrics/summary", headers=api_key_headers)
        assert res.status_code == 200
        payload = res.json()
        assert "openai" in payload
        assert "rate_limit_total" in payload["openai"]
        assert "timeout_total" in payload["openai"]
        assert "rate_limit_retry_total" in payload["openai"]
        assert "timeout_retry_total" in payload["openai"]
        assert payload["openai"]["scope"] == "process"
        assert "available" in payload["openai"]

