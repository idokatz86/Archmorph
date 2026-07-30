"""Adversarial CISO regressions for cross-process erasure and telemetry I/O."""

from __future__ import annotations

import copy
import json
import multiprocessing
import os
from pathlib import Path
import time
import traceback
from types import SimpleNamespace
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from database import Base
from models.workspace import Workspace
from tests.conftest import SAMPLE_ANALYSIS
from workspace_store import persist_analysis_state

import openai_client as _openai_client_module

_REAL_CACHED_CHAT_COMPLETION = _openai_client_module.cached_chat_completion
_requires_top_level_process = pytest.mark.skipif(
    bool(os.getenv("PYTEST_XDIST_WORKER")),
    reason="nested fork/spawn is exercised by the dedicated serial security gate",
)


def _reset_usage_metrics(usage_metrics) -> None:
    usage_metrics._metrics = copy.deepcopy(usage_metrics._DEFAULT_METRICS)
    usage_metrics._metrics_baseline = copy.deepcopy(usage_metrics._metrics)
    usage_metrics._blob_metrics_baseline = copy.deepcopy(usage_metrics._metrics)


def test_psycopg2_url_is_postgres_and_uses_asyncpg_for_async_engine():
    import database

    url = "postgresql+psycopg2://user@example.invalid:5432/archmorph"
    assert database._is_postgres_url(url)
    assert (
        database._async_database_url(url)
        == "postgresql+asyncpg://user@example.invalid:5432/archmorph"
    )


def test_scoped_cache_access_fails_closed_when_purge_authority_is_unavailable(
    monkeypatch,
):
    import database
    from durable_purge_fence import (
        PurgeFenceUnavailableError,
        require_diagram_cache_access,
    )

    def unavailable():
        raise OSError("injected durable authority outage")

    monkeypatch.setattr(database, "SessionLocal", unavailable)
    with pytest.raises(PurgeFenceUnavailableError):
        require_diagram_cache_access("authority-outage-diagram")


def _process_runtime(database_path: str, metrics_path: str):
    """Bind process-local module globals to one isolated durable test runtime."""
    import database
    import usage_metrics

    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    database.SessionLocal = factory
    try:
        import durable_purge_fence

        durable_purge_fence.SessionLocal = factory
    except ImportError:
        pass
    usage_metrics.METRICS_FILE = metrics_path
    usage_metrics.AZURE_STORAGE_ACCOUNT_URL = ""
    usage_metrics.AZURE_STORAGE_CONNECTION_STRING = ""
    usage_metrics._load_metrics(prefer_blob=False)
    return engine, factory, usage_metrics


def _cache_worker(
    database_path: str,
    metrics_path: str,
    target_diagram: str,
    sibling_diagram: str,
    owner: str,
    tenant: str,
    connection,
) -> None:
    try:
        engine, _factory, _usage_metrics = _process_runtime(
            database_path,
            metrics_path,
        )
        import openai_client
        import versioning
        from durable_purge_fence import PurgedScopeError

        patch.stopall()
        openai_client.cached_chat_completion = _REAL_CACHED_CHAT_COMPLETION
        openai_client.reset_cache()
        versioning.VERSION_STORE.clear()
        messages = [{"role": "user", "content": "scoped model output"}]
        model = "fenced-test-model"

        def preload(diagram_id: str, marker: str) -> None:
            cache_key = openai_client._compute_cache_key(
                model=model,
                messages=messages,
                cache_owner_user_id=owner,
                cache_tenant_id=tenant,
                cache_diagram_id=diagram_id,
            )
            scope = openai_client._ResponseCacheScope(
                diagram_id=diagram_id,
                owner_user_id=owner,
                tenant_id=tenant,
            )
            with openai_client._cache_lock:
                openai_client._response_cache[cache_key] = marker
                openai_client._response_cache_scopes[cache_key] = scope
                openai_client._response_cache_refs.setdefault(
                    diagram_id,
                    set(),
                ).add(cache_key)

        preload(target_diagram, "target-response")
        preload(sibling_diagram, "sibling-response")
        versioning.create_version(
            target_diagram,
            {"diagram_id": target_diagram, "mappings": []},
        )
        versioning.create_version(
            sibling_diagram,
            {"diagram_id": sibling_diagram, "mappings": []},
        )
        connection.send({"state": "preloaded"})
        if connection.recv() != "purged":
            raise AssertionError("unexpected cache worker command")

        import durable_purge_fence

        target_fence = durable_purge_fence.diagram_purge_fence(target_diagram)
        sibling_fence = durable_purge_fence.diagram_purge_fence(sibling_diagram)
        target_cache_denied = False
        try:
            openai_client.cached_chat_completion(
                messages,
                model=model,
                cache_owner_user_id=owner,
                cache_tenant_id=tenant,
                cache_diagram_id=target_diagram,
            )
        except PurgedScopeError:
            target_cache_denied = True

        target_version_read_denied = False
        try:
            versioning.get_version_history(target_diagram)
        except PurgedScopeError:
            target_version_read_denied = True

        target_version_write_denied = False
        try:
            versioning.create_version(
                target_diagram,
                {"diagram_id": target_diagram, "mappings": []},
            )
        except PurgedScopeError:
            target_version_write_denied = True

        sibling_response = openai_client.cached_chat_completion(
            messages,
            model=model,
            cache_owner_user_id=owner,
            cache_tenant_id=tenant,
            cache_diagram_id=sibling_diagram,
        )
        sibling_response_preserved = sibling_response == "sibling-response"
        sibling_version = versioning.get_version(sibling_diagram, 1)
        connection.send(
            {
                "state": "verified",
                "target_fence": (
                    target_fence.purged,
                    target_fence.authoritative,
                ),
                "sibling_fence": (
                    sibling_fence.purged,
                    sibling_fence.authoritative,
                ),
                "cache_function_module": openai_client.cached_chat_completion.__module__,
                "target_cache_denied": target_cache_denied,
                "target_cache_absent": openai_client.diagram_response_cache_absent(
                    target_diagram
                ),
                "target_version_read_denied": target_version_read_denied,
                "target_version_write_denied": target_version_write_denied,
                "target_versions_absent": versioning.diagram_versions_absent(
                    target_diagram
                ),
                "sibling_response_preserved": sibling_response_preserved,
                "sibling_version": (
                    sibling_version.version_number
                    if sibling_version is not None
                    else None
                ),
            }
        )
        engine.dispose()
    except BaseException as exc:  # pragma: no cover - reported to parent
        connection.send(
            {
                "state": "error",
                "error_type": type(exc).__name__,
                "traceback": traceback.format_exc(),
            }
        )
    finally:
        connection.close()


def _purge_worker(
    database_path: str,
    metrics_path: str,
    target_diagram: str,
    owner: str,
    tenant: str,
    connection,
) -> None:
    try:
        engine, _factory, usage_metrics = _process_runtime(
            database_path,
            metrics_path,
        )
        _reset_usage_metrics(usage_metrics)
        from purge_service import purge_diagram

        result = purge_diagram(
            diagram_id=target_diagram,
            owner_user_id=owner,
            tenant_id=tenant,
        )
        connection.send(
            {
                "state": "purged",
                "status": result.status,
                "operation_id": result.operation_id,
            }
        )
        engine.dispose()
    except BaseException as exc:  # pragma: no cover - reported to parent
        connection.send(
            {
                "state": "error",
                "error_type": type(exc).__name__,
                "traceback": traceback.format_exc(),
            }
        )
    finally:
        connection.close()


def _restart_worker(
    database_path: str,
    metrics_path: str,
    target_diagram: str,
    owner: str,
    tenant: str,
    connection,
) -> None:
    try:
        engine, _factory, _usage_metrics = _process_runtime(
            database_path,
            metrics_path,
        )
        import openai_client
        import versioning
        from durable_purge_fence import PurgedScopeError

        openai_client.cached_chat_completion = _REAL_CACHED_CHAT_COMPLETION
        startup_evictions = (
            openai_client.apply_durable_purge_fences()
            + versioning.apply_durable_purge_fences()
        )
        cache_denied = False
        try:
            openai_client.cached_chat_completion(
                [{"role": "user", "content": "restart attempt"}],
                cache_owner_user_id=owner,
                cache_tenant_id=tenant,
                cache_diagram_id=target_diagram,
            )
        except PurgedScopeError:
            cache_denied = True
        version_denied = False
        try:
            versioning.create_version(
                target_diagram,
                {"diagram_id": target_diagram, "mappings": []},
            )
        except PurgedScopeError:
            version_denied = True
        connection.send(
            {
                "state": "verified",
                "cache_denied": cache_denied,
                "version_denied": version_denied,
                "startup_evictions": startup_evictions,
            }
        )
        engine.dispose()
    except BaseException as exc:  # pragma: no cover - reported to parent
        connection.send(
            {
                "state": "error",
                "error_type": type(exc).__name__,
                "traceback": traceback.format_exc(),
            }
        )
    finally:
        connection.close()


def _telemetry_writer(
    database_path: str,
    metrics_path: str,
    writer_id: int,
    iterations: int,
    connection,
) -> None:
    try:
        engine, _factory, usage_metrics = _process_runtime(
            database_path,
            metrics_path,
        )
        padding = "x" * 32768
        for sequence in range(iterations):
            usage_metrics.record_event(
                "concurrent_writer",
                {
                    "writer": writer_id,
                    "sequence": sequence,
                    "padding": padding,
                },
            )
            usage_metrics.flush_metrics()
        usage_metrics.record_event(
            "shutdown_writer",
            {"writer": writer_id, "padding": padding},
        )
        usage_metrics._shutdown_flush()
        connection.send({"state": "done"})
        engine.dispose()
    except BaseException as exc:  # pragma: no cover - reported to parent
        connection.send(
            {
                "state": "error",
                "error_type": type(exc).__name__,
                "traceback": traceback.format_exc(),
            }
        )
    finally:
        connection.close()


def _lock_holder(metrics_path: str, connection) -> None:
    try:
        import usage_metrics

        usage_metrics.METRICS_FILE = metrics_path
        with usage_metrics._metrics_file_lock(exclusive=True):
            connection.send({"state": "locked"})
            connection.recv()
    except BaseException as exc:  # pragma: no cover - reported to parent
        connection.send(
            {
                "state": "error",
                "error_type": type(exc).__name__,
                "traceback": traceback.format_exc(),
            }
        )
    finally:
        connection.close()


def _receive(connection, *, timeout: float = 30.0) -> dict:
    if not connection.poll(timeout):
        raise AssertionError("multiprocessing worker timed out")
    result = connection.recv()
    if result.get("state") == "error":
        raise AssertionError(result["traceback"])
    return result


def _join(process, *, timeout: float = 30.0) -> None:
    process.join(timeout)
    if process.is_alive():
        process.terminate()
        process.join(5)
        raise AssertionError("multiprocessing worker did not terminate")
    assert process.exitcode == 0


def _seed_cross_worker_runtime(database_path: Path):
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex
    owner = f"multiprocess-owner-{suffix}"
    tenant = f"multiprocess-tenant-{suffix}"
    workspace_id = f"multiprocess-workspace-{suffix[:12]}"
    target_diagram = f"multiprocess-target-{suffix}"
    sibling_diagram = f"multiprocess-sibling-{suffix}"
    db = factory()
    try:
        db.add(
            Workspace(
                id=workspace_id,
                owner_user_id=owner,
                tenant_id=tenant,
                name="Cross-worker purge",
                status="active",
                is_default=False,
            )
        )
        db.commit()
        for diagram_id in (target_diagram, sibling_diagram):
            snapshot = copy.deepcopy(SAMPLE_ANALYSIS)
            snapshot["diagram_id"] = diagram_id
            persist_analysis_state(
                db,
                owner_user_id=owner,
                tenant_id=tenant,
                diagram_id=diagram_id,
                snapshot=snapshot,
                workspace_id=workspace_id,
            )
    finally:
        db.close()
        engine.dispose()
    return owner, tenant, target_diagram, sibling_diagram


@pytest.mark.parametrize("start_method", ["fork", "spawn"])
@_requires_top_level_process
def test_cross_worker_purge_fences_response_and_version_caches(
    tmp_path,
    start_method,
):
    if start_method not in multiprocessing.get_all_start_methods():
        pytest.skip(f"{start_method} multiprocessing is unavailable")

    database_path = tmp_path / f"cross-worker-{start_method}.db"
    metrics_path = str(tmp_path / f"usage-{start_method}.json")
    owner, tenant, target_diagram, sibling_diagram = _seed_cross_worker_runtime(
        database_path
    )
    context = multiprocessing.get_context(start_method)

    parent_cache, child_cache = context.Pipe()
    cache_process = context.Process(
        target=_cache_worker,
        args=(
            str(database_path),
            metrics_path,
            target_diagram,
            sibling_diagram,
            owner,
            tenant,
            child_cache,
        ),
    )
    cache_process.start()
    assert _receive(parent_cache) == {"state": "preloaded"}

    parent_purge, child_purge = context.Pipe()
    purge_process = context.Process(
        target=_purge_worker,
        args=(
            str(database_path),
            metrics_path,
            target_diagram,
            owner,
            tenant,
            child_purge,
        ),
    )
    purge_process.start()
    purge_result = _receive(parent_purge)
    assert purge_result["status"] == "completed"
    _join(purge_process)

    parent_cache.send("purged")
    cache_result = _receive(parent_cache)
    print(f"cross-worker cache result: {cache_result}")
    assert cache_result["target_fence"] == (True, True)
    assert cache_result["sibling_fence"] == (False, True)
    assert cache_result["cache_function_module"] == "openai_client"
    assert cache_result == {
        "state": "verified",
        "target_fence": (True, True),
        "sibling_fence": (False, True),
        "cache_function_module": "openai_client",
        "target_cache_denied": True,
        "target_cache_absent": True,
        "target_version_read_denied": True,
        "target_version_write_denied": True,
        "target_versions_absent": True,
        "sibling_response_preserved": True,
        "sibling_version": 1,
    }
    _join(cache_process)

    parent_restart, child_restart = context.Pipe()
    restart_process = context.Process(
        target=_restart_worker,
        args=(
            str(database_path),
            metrics_path,
            target_diagram,
            owner,
            tenant,
            child_restart,
        ),
    )
    restart_process.start()
    restart_result = _receive(parent_restart)
    assert restart_result["cache_denied"] is True
    assert restart_result["version_denied"] is True
    assert restart_result["startup_evictions"] == 0
    _join(restart_process)


@pytest.mark.parametrize("start_method", ["fork", "spawn"])
@_requires_top_level_process
def test_atomic_metrics_file_has_zero_transient_residue_under_process_writers(
    tmp_path,
    monkeypatch,
    start_method,
):
    if start_method not in multiprocessing.get_all_start_methods():
        pytest.skip(f"{start_method} multiprocessing is unavailable")

    import database
    import usage_metrics

    database_path = tmp_path / f"metrics-race-{start_method}.db"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(database, "SessionLocal", factory)
    metrics_path = str(tmp_path / f"metrics-race-{start_method}.json")
    monkeypatch.setattr(usage_metrics, "METRICS_FILE", metrics_path)
    monkeypatch.setattr(usage_metrics, "AZURE_STORAGE_ACCOUNT_URL", "")
    monkeypatch.setattr(usage_metrics, "AZURE_STORAGE_CONNECTION_STRING", "")
    _reset_usage_metrics(usage_metrics)
    usage_metrics.flush_metrics()

    context = multiprocessing.get_context(start_method)
    workers = []
    parents = []
    for writer_id in range(3):
        parent, child = context.Pipe()
        process = context.Process(
            target=_telemetry_writer,
            args=(
                str(database_path),
                metrics_path,
                writer_id,
                24,
                child,
            ),
        )
        process.start()
        workers.append(process)
        parents.append(parent)

    attempts = 0
    false_residue = 0
    while attempts < 1200:
        attempts += 1
        if not usage_metrics.usage_telemetry_absent(
            owner_user_id="absent-owner",
            tenant_id="absent-tenant",
            diagram_id="absent-diagram",
        ):
            false_residue += 1
        if attempts >= 5000:
            break

    for parent in parents:
        assert _receive(parent) == {"state": "done"}
    for process in workers:
        _join(process)

    persisted = usage_metrics._read_local_metrics_file()
    assert isinstance(persisted, dict)
    assert persisted["counters"]["concurrent_writer"] == 3 * 24
    assert persisted["counters"]["shutdown_writer"] == 3
    assert false_residue == 0
    print(
        f"atomic metrics verification race rate: {false_residue}/{attempts} "
        f"({false_residue / attempts:.2%})"
    )
    engine.dispose()


def test_atomic_replace_failure_preserves_previous_generation_and_restart_recovers(
    tmp_path,
    monkeypatch,
):
    import usage_metrics

    metrics_path = str(tmp_path / "failure-restart.json")
    monkeypatch.setattr(usage_metrics, "METRICS_FILE", metrics_path)
    monkeypatch.setattr(usage_metrics, "AZURE_STORAGE_ACCOUNT_URL", "")
    monkeypatch.setattr(usage_metrics, "AZURE_STORAGE_CONNECTION_STRING", "")
    _reset_usage_metrics(usage_metrics)
    usage_metrics.record_event("before_failure")
    usage_metrics._save_metrics(require_all=True)
    previous = Path(metrics_path).read_bytes()

    usage_metrics.record_event("after_failure")
    real_replace = usage_metrics.os.replace

    def fail_replace(_source, _target):
        raise OSError("injected atomic replace failure")

    monkeypatch.setattr(usage_metrics.os, "replace", fail_replace)
    with pytest.raises(usage_metrics.UsageMetricsPersistenceError):
        usage_metrics._save_metrics(require_all=True)
    assert Path(metrics_path).read_bytes() == previous
    json.loads(previous)

    monkeypatch.setattr(usage_metrics.os, "replace", real_replace)
    _reset_usage_metrics(usage_metrics)
    usage_metrics._load_metrics(prefer_blob=False)
    assert usage_metrics._metrics["counters"]["before_failure"] == 1
    assert usage_metrics._metrics["counters"].get("after_failure", 0) == 0
    usage_metrics.record_event("after_restart")
    usage_metrics._save_metrics(require_all=True)
    reloaded = usage_metrics._read_local_metrics_file()
    assert reloaded is not None
    assert reloaded["counters"]["after_restart"] == 1


@_requires_top_level_process
def test_file_lock_is_bounded_and_process_death_releases_stale_lock(
    tmp_path,
    monkeypatch,
):
    import usage_metrics

    metrics_path = str(tmp_path / "stale-lock.json")
    monkeypatch.setattr(usage_metrics, "METRICS_FILE", metrics_path)
    monkeypatch.setattr(usage_metrics, "_FILE_LOCK_TIMEOUT_SECONDS", 0.1)
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_lock_holder, args=(metrics_path, child))
    process.start()
    assert _receive(parent) == {"state": "locked"}

    started = time.monotonic()
    with pytest.raises(usage_metrics.UsageMetricsLockTimeout):
        with usage_metrics._metrics_file_lock(exclusive=True):
            pass
    assert time.monotonic() - started < 1.0

    process.terminate()
    process.join(5)
    if process.is_alive():
        process.kill()
        process.join(5)
    assert not process.is_alive()
    with usage_metrics._metrics_file_lock(exclusive=True):
        pass


def test_blob_etag_merge_preserves_stale_replica_aggregate_deltas(monkeypatch):
    import usage_metrics

    class Downloader:
        def __init__(self, blob):
            self._blob = blob
            self.properties = SimpleNamespace(etag=blob.etag)

        def readall(self):
            return self._blob.payload

    class Blob:
        def __init__(self, payload):
            self.payload = payload
            self.generation = 1
            self.etag = '"generation-1"'
            self.conditions = []

        def download_blob(self):
            return Downloader(self)

        def upload_blob(
            self,
            payload,
            *,
            overwrite,
            etag=None,
            match_condition=None,
        ):
            assert overwrite is True
            assert etag == self.etag
            assert match_condition is not None
            self.conditions.append((etag, match_condition))
            self.payload = payload.encode() if isinstance(payload, str) else payload
            self.generation += 1
            self.etag = f'"generation-{self.generation}"'

    baseline = copy.deepcopy(usage_metrics._DEFAULT_METRICS)
    initial = copy.deepcopy(baseline)
    blob = Blob(json.dumps(initial).encode())
    monkeypatch.setattr(usage_metrics, "_scrub_durable_purges_locked", lambda: False)

    first = copy.deepcopy(baseline)
    first["counters"]["analyses_run"] += 1
    first_result = usage_metrics._save_blob_optimistically_locked(
        blob,
        current=first,
        baseline=baseline,
    )
    assert first_result["counters"]["analyses_run"] == 1

    stale_second = copy.deepcopy(baseline)
    stale_second["counters"]["analyses_run"] += 1
    second_result = usage_metrics._save_blob_optimistically_locked(
        blob,
        current=stale_second,
        baseline=baseline,
    )

    assert second_result["counters"]["analyses_run"] == 2
    assert json.loads(blob.payload)["counters"]["analyses_run"] == 2
    assert len(blob.conditions) == 2
