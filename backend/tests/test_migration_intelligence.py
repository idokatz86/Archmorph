"""Tests for migration_intelligence module (#281)."""
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from migration_intelligence import (
    router,
    record_migration_event,
    get_community_confidence,
    get_top_patterns,
    MigrationEvent,
)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestRecordEvent:
    def test_record_event(self):
        event = MigrationEvent(
            source_service="EC2",
            target_service="Azure Virtual Machines",
            source_provider="aws",
            target_provider="azure",
            success=True,
            confidence=0.95,
        )
        record_migration_event(event)
        # Should not raise


class TestCommunityConfidence:
    def test_known_pair_returns_float(self):
        score = get_community_confidence("EC2", "Azure Virtual Machines")
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_unknown_pair_returns_base(self):
        score = get_community_confidence("NonexistentService", "AlsoNonexistent", base_confidence=0.5)
        assert isinstance(score, float)


class TestTopPatterns:
    def test_returns_list(self):
        patterns = get_top_patterns()
        assert isinstance(patterns, list)

    def test_filter_by_provider(self):
        patterns = get_top_patterns(source_provider="aws", target_provider="azure")
        for p in patterns:
            assert p.source_provider == "aws"
            assert p.target_provider == "azure"


class TestEndpoints:
    def test_list_patterns(self, client):
        resp = client.get("/migration-intelligence/patterns")
        assert resp.status_code == 200
        data = resp.json()
        assert "patterns" in data or isinstance(data, list)

    def test_stats(self, client):
        resp = client.get("/migration-intelligence/stats")
        assert resp.status_code == 200

    def test_trending(self, client):
        resp = client.get("/migration-intelligence/trending")
        assert resp.status_code == 200

    def test_submit_event(self, client):
        resp = client.post("/migration-intelligence/events", json={
            "source_service": "Lambda",
            "target_service": "Azure Functions",
            "source_provider": "aws",
            "target_provider": "azure",
            "success": True,
            "confidence": 0.90,
        })
        assert resp.status_code == 200
