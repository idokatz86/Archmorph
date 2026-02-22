"""
Archmorph — Migration Risk Score Unit Tests
Tests for migration_risk.py (Issue #158)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from migration_risk import (
    FACTOR_WEIGHTS,
    RISK_TIERS,
    compute_risk_score,
)


# ────────────────────────────────────────────────────────────────────
# Fixture: minimal analysis dict
# ────────────────────────────────────────────────────────────────────
def _make_analysis(**overrides):
    base = {
        "diagram_id": "test-001",
        "diagram_type": "architecture",
        "source_provider": "aws",
        "mappings": [
            {
                "source_service": "EC2",
                "azure_service": "Virtual Machines",
                "confidence": 0.95,
                "category": "Compute",
                "notes": "",
            },
            {
                "source_service": "S3",
                "azure_service": "Blob Storage",
                "confidence": 0.90,
                "category": "Storage",
                "notes": "",
            },
        ],
        "zones": ["us-east-1"],
        "service_connections": [],
        "confidence_summary": {"average": 0.925, "min": 0.90, "max": 0.95},
        "warnings": [],
        "architecture_patterns": [],
    }
    base.update(overrides)
    return base


# ====================================================================
# FACTOR_WEIGHTS validation
# ====================================================================

class TestFactorWeights:
    def test_weights_sum_to_one(self):
        total = sum(FACTOR_WEIGHTS.values())
        assert abs(total - 1.0) < 0.01, f"Weights sum to {total}, expected ~1.0"

    def test_all_factors_present(self):
        expected = {
            "service_complexity",
            "mapping_confidence",
            "data_gravity",
            "compliance_exposure",
            "architecture_coupling",
            "downtime_risk",
        }
        assert set(FACTOR_WEIGHTS.keys()) == expected

    def test_weights_positive(self):
        for name, w in FACTOR_WEIGHTS.items():
            assert w > 0, f"{name} weight is non-positive"


# ====================================================================
# RISK_TIERS validation
# ====================================================================

class TestRiskTiers:
    def test_tiers_defined(self):
        assert len(RISK_TIERS) >= 4

    def test_tier_keys(self):
        expected_tiers = {"low", "moderate", "high", "critical"}
        actual = {t[1] for t in RISK_TIERS}
        assert expected_tiers.issubset(actual)


# ====================================================================
# Individual factor scoring
# ====================================================================

class TestFactorScoring:
    """Factor scoring is tested indirectly via compute_risk_score."""

    def test_all_factors_scored(self):
        result = compute_risk_score(_make_analysis())
        for factor in FACTOR_WEIGHTS:
            assert factor in result["factors"]
            f = result["factors"][factor]
            assert "score" in f
            assert 0 <= f["score"] <= 100

    def test_high_confidence_low_mapping_risk(self):
        result = compute_risk_score(_make_analysis())
        mc = result["factors"]["mapping_confidence"]
        assert mc["score"] < 30

    def test_low_confidence_high_mapping_risk(self):
        result = compute_risk_score(_make_analysis(
            mappings=[
                {"source_service": "X", "azure_service": "Y", "confidence": 0.2, "category": "Compute", "notes": ""},
                {"source_service": "A", "azure_service": "B", "confidence": 0.3, "category": "Storage", "notes": ""},
            ],
            confidence_summary={"average": 0.25, "min": 0.2, "max": 0.3},
        ))
        mc = result["factors"]["mapping_confidence"]
        assert mc["score"] > 50


# ====================================================================
# compute_risk_score end-to-end
# ====================================================================

class TestComputeRiskScore:
    def test_returns_expected_keys(self):
        result = compute_risk_score(_make_analysis())
        assert "overall_score" in result
        assert "risk_tier" in result
        assert "factors" in result
        assert "recommendations" in result

    def test_score_range(self):
        result = compute_risk_score(_make_analysis())
        assert 0 <= result["overall_score"] <= 100

    def test_tier_assigned(self):
        result = compute_risk_score(_make_analysis())
        assert result["risk_tier"] in {"low", "moderate", "high", "critical"}

    def test_factors_all_present(self):
        result = compute_risk_score(_make_analysis())
        for key in FACTOR_WEIGHTS:
            assert key in result["factors"]

    def test_recommendations_is_list(self):
        result = compute_risk_score(_make_analysis())
        assert isinstance(result["recommendations"], list)

    def test_empty_mappings(self):
        result = compute_risk_score(_make_analysis(mappings=[]))
        assert result["overall_score"] >= 0

    def test_large_architecture(self):
        mappings = [
            {"source_service": f"Svc{i}", "azure_service": f"Az{i}", "confidence": 0.5, "category": "Compute", "notes": ""}
            for i in range(50)
        ]
        result = compute_risk_score(
            _make_analysis(mappings=mappings, confidence_summary={"average": 0.5, "min": 0.5, "max": 0.5})
        )
        assert result["overall_score"] > 0
        assert result["risk_tier"] in {"low", "moderate", "high", "critical"}


# ====================================================================
# _generate_recommendations
# ====================================================================

class TestRecommendations:
    def test_returns_list(self):
        result = compute_risk_score(_make_analysis())
        assert isinstance(result["recommendations"], list)

    def test_high_risk_generates_recs(self):
        mappings = [
            {"source_service": f"Svc{i}", "azure_service": f"Az{i}", "confidence": 0.3, "category": "Compute", "notes": ""}
            for i in range(20)
        ]
        result = compute_risk_score(
            _make_analysis(mappings=mappings, confidence_summary={"average": 0.3, "min": 0.3, "max": 0.3})
        )
        assert len(result["recommendations"]) > 0
