"""Concurrency regressions for deterministic analysis-version retention."""

from __future__ import annotations

import os
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import SAWarning
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401 — register all ORM models with Base.metadata
from database import Base
from models.workspace import Analysis, AnalysisVersion
from workspace_store import (
    MAX_VERSIONS_PER_ANALYSIS,
    _trim_old_versions,
    persist_analysis_state,
)


def test_auto_sqlite_database_is_worker_scoped_under_xdist(request):
    worker_id = os.environ.get("PYTEST_XDIST_WORKER")
    if worker_id is None:
        pytest.skip("xdist worker scope is only observable in parallel runs")
    from database import DATABASE_URL

    assert os.environ.get("ARCHMORPH_PYTEST_AUTO_DATABASE") == "1"
    assert DATABASE_URL.endswith(f"-{worker_id}.db")


@pytest.fixture()
def sqlite_retention_factory(tmp_path):
    database_path = tmp_path / "retention-race.db"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 20},
    )

    @event.listens_for(engine, "connect")
    def _enable_sqlite_concurrency(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory, engine
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_over_cap_history(factory):
    db = factory()
    try:
        seeded = persist_analysis_state(
            db,
            owner_user_id="retention-owner",
            tenant_id="retention-tenant",
            diagram_id="retention-diagram",
            snapshot={"value": 1, "mappings": []},
            label="seed-v1",
        )
        analysis_id = seeded.analysis.id
        for version_number in range(2, MAX_VERSIONS_PER_ANALYSIS + 7):
            db.add(
                AnalysisVersion(
                    analysis_id=analysis_id,
                    version_number=version_number,
                    label=f"seed-v{version_number}",
                    snapshot=f'{{"value":{version_number}}}',
                    created_by="retention-owner",
                    restored_from=(
                        1 if version_number == MAX_VERSIONS_PER_ANALYSIS + 6 else None
                    ),
                )
            )
        analysis = db.get(Analysis, analysis_id)
        analysis.current_version = MAX_VERSIONS_PER_ANALYSIS + 6
        db.commit()
        return analysis_id
    finally:
        db.close()


def _retained_numbers(factory, analysis_id: str) -> list[int]:
    db = factory()
    try:
        return [
            int(number)
            for (number,) in db.query(AnalysisVersion.version_number)
            .filter(AnalysisVersion.analysis_id == analysis_id)
            .order_by(AnalysisVersion.version_number.asc())
            .all()
        ]
    finally:
        db.close()


def test_sqlite_six_concurrent_trims_are_warning_free_and_idempotent(
    sqlite_retention_factory,
):
    factory, engine = sqlite_retention_factory
    analysis_id = _seed_over_cap_history(factory)
    delete_barrier = threading.Barrier(6)
    barrier_threads: set[int] = set()
    barrier_lock = threading.Lock()

    @event.listens_for(engine, "before_cursor_execute")
    def _align_first_delete(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ):
        normalized = " ".join(statement.lower().split())
        if not normalized.startswith("delete from analysis_versions"):
            return
        thread_id = threading.get_ident()
        with barrier_lock:
            if thread_id not in barrier_threads and len(barrier_threads) >= 6:
                return
            first_delete = thread_id not in barrier_threads
            barrier_threads.add(thread_id)
        if first_delete:
            delete_barrier.wait(timeout=20)

    def trim_once(_index: int) -> None:
        db = factory()
        try:
            _trim_old_versions(db, analysis_id)
        finally:
            db.close()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", SAWarning)
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(trim_once, range(6)))

    sqlalchemy_warnings = [
        warning for warning in caught if issubclass(warning.category, SAWarning)
    ]
    expected_numbers = [1, *range(8, MAX_VERSIONS_PER_ANALYSIS + 7)]
    assert len(barrier_threads) == 6
    assert sqlalchemy_warnings == []
    assert _retained_numbers(factory, analysis_id) == expected_numbers

    retry_db = factory()
    try:
        _trim_old_versions(retry_db, analysis_id)
        _trim_old_versions(retry_db, analysis_id)
        first = persist_analysis_state(
            retry_db,
            owner_user_id="retention-owner",
            tenant_id="retention-tenant",
            diagram_id="retention-diagram",
            snapshot={
                "value": MAX_VERSIONS_PER_ANALYSIS + 7,
                "mappings": [],
                "_analysis_version": MAX_VERSIONS_PER_ANALYSIS + 6,
            },
            expected_version=MAX_VERSIONS_PER_ANALYSIS + 6,
            operation="retention-idempotency",
            request_hash="a" * 64,
        )
        replay = persist_analysis_state(
            retry_db,
            owner_user_id="retention-owner",
            tenant_id="retention-tenant",
            diagram_id="retention-diagram",
            snapshot={
                "value": MAX_VERSIONS_PER_ANALYSIS + 7,
                "mappings": [],
                "_analysis_version": MAX_VERSIONS_PER_ANALYSIS + 6,
            },
            expected_version=MAX_VERSIONS_PER_ANALYSIS + 6,
            operation="retention-idempotency",
            request_hash="a" * 64,
        )
        assert first.version.version_number == MAX_VERSIONS_PER_ANALYSIS + 7
        assert replay.version.id == first.version.id
        assert replay.idempotent_replay is True
    finally:
        retry_db.close()

    retained = _retained_numbers(factory, analysis_id)
    assert len(retained) == MAX_VERSIONS_PER_ANALYSIS
    assert retained[0] == 1
    assert retained[-1] == MAX_VERSIONS_PER_ANALYSIS + 7
