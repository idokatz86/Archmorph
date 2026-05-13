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
        assert job.job_type == "analyze"
        assert job.diagram_id == "d1"
        assert job.job_id is not None

    def test_start_transitions_to_running(self):
        mgr = self._make_manager()
        job = mgr.submit("analyze")
        mgr.start(job.job_id)
        assert job.status == "running"
        assert job.started_at is not None

    def test_update_progress(self):
        mgr = self._make_manager()
        job = mgr.submit("analyze")
        mgr.start(job.job_id)
        mgr.update_progress(job.job_id, 50, "Halfway done")
        assert job.progress == 50
        assert job.progress_message == "Halfway done"

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
        assert "job_type" in d
        assert "progress" in d
        assert "created_at" in d
        assert d["status"] == "queued"
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

    def test_analyze_async_no_upload_returns_404(self, test_client, auth_headers):
        """Without uploading first, should get 404."""
        res = test_client.post("/api/diagrams/nonexistent/analyze-async", headers=auth_headers)
        assert res.status_code == 404

    def test_generate_async_invalid_format(self, test_client, auth_headers):
        """Invalid IaC format should return 422 from schema validation."""
        res = test_client.post("/api/diagrams/test/generate-async?format=invalid", headers=auth_headers)
        assert res.status_code == 422

    def test_generate_hld_async_no_analysis(self, test_client, auth_headers):
        """Without prior analysis, should return 404."""
        res = test_client.post("/api/diagrams/nonexistent/generate-hld-async", headers=auth_headers)
        assert res.status_code == 404

    def test_api_key_async_iac_create_status_stream_cancel(self, test_client, api_key_headers, monkeypatch):
        from job_queue import job_manager
        from routers.shared import SESSION_STORE

        async def _fake_run_iac_job(job_id: str, diagram_id: str, iac_format: str) -> None:
            await asyncio.sleep(0)

        monkeypatch.setattr("routers.iac_routes._run_iac_job", _fake_run_iac_job)
        diagram_id = "api-key-iac-diagram"
        SESSION_STORE[diagram_id] = {"services_detected": 0, "mappings": []}
        try:
            create = test_client.post(f"/api/diagrams/{diagram_id}/generate-async", headers=api_key_headers)
            assert create.status_code == 202, create.text
            job_id = create.json()["job_id"]
            principal_id = _api_key_principal(api_key_headers)
            created = job_manager.get(job_id)
            assert created is not None
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
