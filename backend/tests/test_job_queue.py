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


# ─────────────────────────────────────────────────────────────
# JobManager unit tests
# ─────────────────────────────────────────────────────────────

class TestJobManager:
    """Unit tests for job_queue.JobManager."""

    def _make_manager(self):
        from job_queue import JobManager
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
