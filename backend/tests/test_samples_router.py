"""
Unit tests for the sample diagrams router.

Covers:
  - GET /api/samples — list sample diagrams
  - POST /api/samples/{sample_id}/analyze — analyze a sample
  - build_sample_analysis helper
  - get_or_recreate_session helper
"""

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

from main import app, SESSION_STORE
from routers.samples import build_sample_analysis, get_or_recreate_session, SAMPLE_DIAGRAMS


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean():
    yield
    # Don't clear the entire store — just clean up sample entries
    keys_to_remove = [k for k in SESSION_STORE.keys() if k.startswith("sample-")]
    for k in keys_to_remove:
        SESSION_STORE.delete(k)


class TestListSamples:
    """GET /api/samples returns available samples."""

    def test_list_returns_200(self, client):
        resp = client.get("/api/samples")
        assert resp.status_code == 200

    def test_list_returns_samples_array(self, client):
        resp = client.get("/api/samples")
        data = resp.json()
        assert "samples" in data
        assert isinstance(data["samples"], list)
        assert len(data["samples"]) > 0

    def test_each_sample_has_required_fields(self, client):
        resp = client.get("/api/samples")
        for s in resp.json()["samples"]:
            assert "id" in s
            assert "name" in s
            assert "description" in s
            assert "provider" in s
            assert "complexity" in s

    def test_samples_include_aws_and_gcp(self, client):
        resp = client.get("/api/samples")
        providers = {s["provider"] for s in resp.json()["samples"]}
        assert "aws" in providers
        assert "gcp" in providers


class TestAnalyzeSample:
    """POST /api/samples/{sample_id}/analyze creates analysis."""

    def test_analyze_known_sample(self, client):
        sample_id = SAMPLE_DIAGRAMS[0]["id"]
        resp = client.post(f"/api/samples/{sample_id}/analyze")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source_provider"] == SAMPLE_DIAGRAMS[0]["provider"]
        assert data["target_provider"] == "azure"
        assert data["is_sample"] is True
        assert len(data["mappings"]) > 0

    def test_analyze_unknown_sample_404(self, client):
        resp = client.post("/api/samples/nonexistent-sample/analyze")
        assert resp.status_code == 404

    def test_analyze_creates_session(self, client):
        sample_id = SAMPLE_DIAGRAMS[0]["id"]
        resp = client.post(f"/api/samples/{sample_id}/analyze")
        diagram_id = resp.json()["diagram_id"]
        assert diagram_id in SESSION_STORE

    def test_analyze_returns_zones(self, client):
        sample_id = SAMPLE_DIAGRAMS[0]["id"]
        resp = client.post(f"/api/samples/{sample_id}/analyze")
        data = resp.json()
        assert "zones" in data
        assert len(data["zones"]) > 0
        for zone in data["zones"]:
            assert "name" in zone
            assert "services" in zone

    def test_analyze_returns_confidence_summary(self, client):
        sample_id = SAMPLE_DIAGRAMS[0]["id"]
        resp = client.post(f"/api/samples/{sample_id}/analyze")
        data = resp.json()
        cs = data["confidence_summary"]
        assert "high" in cs
        assert "medium" in cs
        assert "low" in cs
        assert "average" in cs


class TestBuildSampleAnalysis:
    """Unit tests for build_sample_analysis helper."""

    def test_returns_none_for_unknown(self):
        result = build_sample_analysis("unknown-xyz", "diag-1")
        assert result is None

    def test_returns_dict_for_known(self):
        sample_id = SAMPLE_DIAGRAMS[0]["id"]
        result = build_sample_analysis(sample_id, "diag-test")
        assert isinstance(result, dict)
        assert result["diagram_id"] == "diag-test"

    def test_mappings_have_required_fields(self):
        sample_id = SAMPLE_DIAGRAMS[0]["id"]
        result = build_sample_analysis(sample_id, "diag-test")
        for m in result["mappings"]:
            assert "source_service" in m
            assert "azure_service" in m
            assert "confidence" in m
            assert 0 <= m["confidence"] <= 1


class TestGetOrRecreateSession:
    """Unit tests for get_or_recreate_session helper."""

    def test_returns_none_for_non_sample(self):
        result = get_or_recreate_session("random-diagram-id")
        assert result is None

    def test_recreates_evicted_sample_session(self):
        # Simulate an evicted session for a known sample
        sample_id = SAMPLE_DIAGRAMS[0]["id"]
        diagram_id = f"sample-{sample_id}-abc123"
        # Ensure not in store
        SESSION_STORE.delete(diagram_id)
        result = get_or_recreate_session(diagram_id)
        assert result is not None
        assert result["is_sample"] is True
        assert diagram_id in SESSION_STORE

    def test_returns_existing_session(self):
        diagram_id = "sample-aws-iaas-def456"
        SESSION_STORE[diagram_id] = {"test": True}
        result = get_or_recreate_session(diagram_id)
        assert result == {"test": True}
        SESSION_STORE.delete(diagram_id)
