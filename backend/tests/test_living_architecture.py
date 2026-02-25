"""Tests for living_architecture module (#281)."""
import pytest
from living_architecture import (
    _register_architecture,
    _compute_health,
    _score_to_status,
    _ARCHITECTURE_REGISTRY,
)


SAMPLE_ANALYSIS = {
    "mappings": [
        {"azure_service": "Azure Virtual Machines", "source_service": "EC2"},
        {"azure_service": "Azure SQL Database", "source_service": "RDS"},
    ],
    "services_detected": 2,
}


class TestScoreToStatus:
    def test_healthy(self):
        assert _score_to_status(0.95) == "healthy"

    def test_warning(self):
        assert _score_to_status(0.80) == "warning"

    def test_critical(self):
        assert _score_to_status(0.50) == "critical"

    def test_boundary_90(self):
        assert _score_to_status(0.90) == "healthy"

    def test_boundary_75(self):
        assert _score_to_status(0.75) == "warning"


class TestRegisterArchitecture:
    def test_returns_arch_id(self):
        arch_id = _register_architecture("test-1", SAMPLE_ANALYSIS)
        assert arch_id.startswith("arch-")
        assert arch_id in _ARCHITECTURE_REGISTRY

    def test_stores_services(self):
        arch_id = _register_architecture("test-2", SAMPLE_ANALYSIS)
        entry = _ARCHITECTURE_REGISTRY[arch_id]
        assert "services" in entry
        assert len(entry["services"]) == 2


class TestComputeHealth:
    def test_returns_health_response(self):
        arch_id = _register_architecture("test-health", SAMPLE_ANALYSIS)
        health = _compute_health(arch_id)
        assert 0.0 <= health.overall_score <= 1.0
        assert health.overall_status in ("healthy", "warning", "critical")
        assert len(health.dimensions) == 5
        assert health.architecture_id == arch_id

    def test_unknown_arch_raises(self):
        with pytest.raises(ValueError):
            _compute_health("nonexistent-arch")

    def test_dimensions_are_valid(self):
        arch_id = _register_architecture("test-dims", SAMPLE_ANALYSIS)
        health = _compute_health(arch_id)
        for dim in health.dimensions:
            assert 0.0 <= dim.score <= 1.0
            assert dim.status in ("healthy", "warning", "critical")
            assert dim.name in ("Availability", "Cost Efficiency", "Compliance", "Performance", "Security")

    def test_recommendations_not_empty(self):
        arch_id = _register_architecture("test-recs", SAMPLE_ANALYSIS)
        health = _compute_health(arch_id)
        assert len(health.recommendations) >= 1
