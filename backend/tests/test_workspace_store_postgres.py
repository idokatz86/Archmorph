"""PostgreSQL concurrency contracts for canonical analysis state (#1237).

Set ``ARCHMORPH_TEST_POSTGRES_URL`` to an isolated migrated database to enable.
"""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.workspace import Analysis, AnalysisVersion, Artifact, Workspace
from session_store import InMemoryStore
from workspace_store import persist_analysis_state


POSTGRES_URL = os.getenv("ARCHMORPH_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="isolated PostgreSQL URL not configured")


@pytest.fixture()
def postgres_factory():
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    try:
        db.query(Artifact).delete()
        db.query(AnalysisVersion).delete()
        db.query(Analysis).delete()
        db.query(Workspace).delete()
        db.commit()
    finally:
        db.close()
    yield factory
    engine.dispose()


def test_concurrent_first_write_upserts_one_analysis_and_monotonic_versions(postgres_factory):
    barrier = threading.Barrier(8)

    def write(index):
        db = postgres_factory()
        try:
            barrier.wait(timeout=10)
            result = persist_analysis_state(
                db,
                owner_user_id="pg-owner",
                tenant_id="pg-tenant",
                diagram_id="pg-concurrent-first-write",
                snapshot={"writer": index, "mappings": []},
                label=f"writer-{index}",
            )
            return result.analysis.id, result.version.version_number
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(write, range(8)))

    db = postgres_factory()
    try:
        analyses = db.query(Analysis).filter_by(
            owner_user_id="pg-owner",
            tenant_id="pg-tenant",
            diagram_id="pg-concurrent-first-write",
        ).all()
        versions = (
            db.query(AnalysisVersion)
            .filter(AnalysisVersion.analysis_id == analyses[0].id)
            .order_by(AnalysisVersion.version_number)
            .all()
        )
        assert len(analyses) == 1
        assert len({analysis_id for analysis_id, _ in results}) == 1
        assert [version.version_number for version in versions] == list(range(1, 9))
        assert analyses[0].current_version == 8
    finally:
        db.close()


def test_reversed_cache_projection_never_replaces_newer_version(postgres_factory):
    cache = InMemoryStore(maxsize=20, ttl=3600)
    db = postgres_factory()
    try:
        first = persist_analysis_state(
            db,
            owner_user_id="pg-cas-owner",
            tenant_id="pg-cas-tenant",
            diagram_id="pg-cache-cas",
            snapshot={"value": "first", "mappings": []},
            label="first",
        )
        second = persist_analysis_state(
            db,
            owner_user_id="pg-cas-owner",
            tenant_id="pg-cas-tenant",
            diagram_id="pg-cache-cas",
            snapshot={"value": "second", "mappings": []},
            session_store=cache,
            label="second",
            cache_required=True,
        )
    finally:
        db.close()

    from workspace_store import AnalysisCacheWriteError, _write_session_cache

    with pytest.raises(AnalysisCacheWriteError):
        _write_session_cache(
            cache,
            diagram_id="pg-cache-cas",
            owner_user_id="pg-cas-owner",
            tenant_id="pg-cas-tenant",
            snapshot=json.loads(first.version.snapshot),
            version_number=first.version.version_number,
        )
    assert second.version.version_number == 2
    assert cache.peek("pg-cache-cas")["value"] == "second"
    assert cache.peek("pg-cache-cas")["_analysis_version"] == 2
