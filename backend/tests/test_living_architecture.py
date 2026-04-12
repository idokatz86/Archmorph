"""Tests for living_architecture.py — health monitoring and drift detection."""

from living_architecture import (
    _register_architecture,
    _compute_health,
    _score_to_status,
    _generate_drift_items,
    _generate_cost_anomalies,
    _generate_recommendations,
    HealthDimension,
)


SAMPLE_ANALYSIS = {
    "diagram_type": "AWS Architecture",
    "source_provider": "aws",
    "target_provider": "azure",
    "mappings": [
        {"source_service": "EC2", "azure_service": "Azure VMs", "confidence": 0.9},
        {"source_service": "S3", "azure_service": "Blob Storage", "confidence": 0.95},
    ],
    "services_detected": 2,
}


class TestScoreToStatus:
    def test_healthy(self):
        assert _score_to_status(0.9) == "healthy"

    def test_critical(self):
        assert _score_to_status(0.7) == "critical"

    def test_very_low_critical(self):
        assert _score_to_status(0.4) == "critical"


class TestRegisterArchitecture:
    def test_register_returns_id(self):
        arch_id = _register_architecture("diag-1", SAMPLE_ANALYSIS)
        assert isinstance(arch_id, str)
        assert len(arch_id) > 0

    def test_register_same_diagram_returns_same_id(self):
        id1 = _register_architecture("diag-2", SAMPLE_ANALYSIS)
        id2 = _register_architecture("diag-2", SAMPLE_ANALYSIS)
        assert id1 == id2


class TestComputeHealth:
    def test_health_for_registered_arch(self):
        arch_id = _register_architecture("diag-health", SAMPLE_ANALYSIS)
        health = _compute_health(arch_id)
        assert health.overall_status in ("healthy", "warning", "critical")
        assert isinstance(health.dimensions, list)

    def test_health_for_unknown_arch_raises(self):
        import pytest
        with pytest.raises(Exception):
            _compute_health("nonexistent-arch-xyz")


class TestGenerateDriftItems:
    def test_generates_list(self):
        arch = {"mappings": SAMPLE_ANALYSIS["mappings"], "registered_at": "2026-01-01"}
        drifts = _generate_drift_items(arch)
        assert isinstance(drifts, list)


class TestGenerateCostAnomalies:
    def test_generates_list(self):
        arch = {"mappings": SAMPLE_ANALYSIS["mappings"]}
        anomalies = _generate_cost_anomalies(arch)
        assert isinstance(anomalies, list)


class TestGenerateRecommendations:
    def test_returns_list_of_strings(self):
        dims = [HealthDimension(name="availability", score=0.95, status="healthy", details="ok")]
        recs = _generate_recommendations(dims, [], [])
        assert isinstance(recs, list)
        assert all(isinstance(r, str) for r in recs)
