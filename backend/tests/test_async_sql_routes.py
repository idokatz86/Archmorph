"""Event-loop safety contracts for canonical project/version/diff SQL routes."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
import threading

import pytest

from routers import diff_routes, hld_routes, iac_routes, projects, report_routes, versioning


@pytest.mark.asyncio
@pytest.mark.parametrize("runner", [projects._db_call])
async def test_project_db_worker_keeps_loop_responsive_and_propagates_context(
    monkeypatch,
    runner,
):
    marker = ContextVar("sql-route-marker", default="missing")
    token = marker.set("request-context")
    started = threading.Event()
    release = threading.Event()
    worker_thread = None

    class FakeSession:
        created_thread = None

        def __init__(self):
            self.created_thread = threading.get_ident()
            FakeSession.created_thread = self.created_thread

        def close(self):
            assert threading.get_ident() == self.created_thread

    monkeypatch.setattr("database.SessionLocal", FakeSession)

    def blocked(db):
        nonlocal worker_thread
        worker_thread = threading.get_ident()
        assert db.created_thread == worker_thread
        assert marker.get() == "request-context"
        started.set()
        release.wait(timeout=2)
        return "done"

    try:
        task = asyncio.create_task(runner(blocked))
        await asyncio.to_thread(started.wait, 1)
        await asyncio.sleep(0)
        assert task.done() is False
        release.set()
        assert await task == "done"
        assert worker_thread != threading.get_ident()

        def fail(_db):
            raise RuntimeError("project repository failed")

        with pytest.raises(RuntimeError, match="project repository failed"):
            await runner(fail)
    finally:
        marker.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("module", [versioning, diff_routes])
async def test_version_and_diff_worker_propagate_exception_and_context(monkeypatch, module):
    marker = ContextVar("version-route-marker", default="missing")
    token = marker.set("version-context")

    class FakeSession:
        def close(self):
            return None

    monkeypatch.setattr("database.SessionLocal", FakeSession)
    monkeypatch.setattr("routers.shared.has_canonical_durable_principal", lambda _request: True)
    monkeypatch.setattr(
        "routers.shared.get_request_durable_principal",
        lambda _request: {"owner_user_id": "owner", "tenant_id": "tenant"},
    )
    monkeypatch.setattr(
        "workspace_store.get_analysis_by_diagram",
        lambda *_args, **_kwargs: object(),
    )

    def fail(_db, _principal, _analysis):
        assert marker.get() == "version-context"
        raise LookupError("repository exception")

    try:
        with pytest.raises(LookupError, match="repository exception"):
            await module._durable_call_async(object(), "diagram", fail)
    finally:
        marker.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "helper_name"),
    [
        (hld_routes, "_persist_async_hld"),
        (iac_routes, "_persist_async_iac"),
        (report_routes, "_analysis_version_created_at"),
    ],
)
async def test_job_and_report_sql_helpers_run_in_worker_with_context(
    monkeypatch,
    module,
    helper_name,
):
    marker = ContextVar("job-report-sql-marker", default="missing")
    token = marker.set("job-report-context")
    started = threading.Event()
    release = threading.Event()

    def blocked(**_kwargs):
        assert marker.get() == "job-report-context"
        started.set()
        release.wait(timeout=2)
        raise RuntimeError("worker repository failed")

    monkeypatch.setattr(module, helper_name, blocked)
    helper = getattr(module, helper_name)
    try:
        task = asyncio.create_task(asyncio.to_thread(helper))
        await asyncio.to_thread(started.wait, 1)
        await asyncio.sleep(0)
        assert task.done() is False
        release.set()
        with pytest.raises(RuntimeError, match="worker repository failed"):
            await task
    finally:
        marker.reset(token)