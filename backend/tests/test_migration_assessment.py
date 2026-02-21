"""
Archmorph — Migration Assessment Unit Tests
Tests for migration_assessment.py (Issue #65)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from migration_assessment import (
    SERVICE_COMPLEXITY,
    CATEGORY_DEFAULTS,
    _get_service_complexity,
    assess_migration_complexity,
)


# ====================================================================
# SERVICE_COMPLEXITY data quality
# ====================================================================

class TestServiceComplexityData:
    """Validate the SERVICE_COMPLEXITY database."""

    def test_not_empty(self):
        """Database has substantial entries."""
        assert len(SERVICE_COMPLEXITY) > 30

    def test_all_have_required_fields(self):
        """Each entry has complexity, migration_tool, migration_approach, estimated_hours."""
        for name, meta in SERVICE_COMPLEXITY.items():
            assert "complexity" in meta, f"{name} missing complexity"
            assert "migration_tool" in meta, f"{name} missing migration_tool"
            assert "migration_approach" in meta, f"{name} missing migration_approach"
            assert "estimated_hours" in meta, f"{name} missing estimated_hours"

    def test_complexity_in_range(self):
        """Complexity scores are between 1 and 5."""
        for name, meta in SERVICE_COMPLEXITY.items():
            assert 1 <= meta["complexity"] <= 5, f"{name} complexity {meta['complexity']} out of range"

    def test_migration_approach_valid(self):
        """Migration approach is one of rehost, replatform, refactor."""
        valid = {"rehost", "replatform", "refactor"}
        for name, meta in SERVICE_COMPLEXITY.items():
            assert meta["migration_approach"] in valid, (
                f"{name} has invalid approach {meta['migration_approach']}"
            )

    def test_estimated_hours_positive(self):
        """Estimated hours are positive."""
        for name, meta in SERVICE_COMPLEXITY.items():
            assert meta["estimated_hours"] > 0, f"{name} has non-positive estimated_hours"

    def test_known_services_present(self):
        """Key AWS services are represented."""
        expected = ["EC2", "Lambda", "S3", "RDS", "DynamoDB", "EKS", "VPC", "CloudFront"]
        for svc in expected:
            assert svc in SERVICE_COMPLEXITY, f"Missing expected service {svc}"

    def test_new_issue_services_present(self):
        """New services from issues #60-#67 are present."""
        new = ["EKS Anywhere", "Wavelength", "Managed Grafana", "DataZone", "Security Lake"]
        for svc in new:
            assert svc in SERVICE_COMPLEXITY, f"Missing new service {svc}"


# ====================================================================
# CATEGORY_DEFAULTS data quality
# ====================================================================

class TestCategoryDefaults:
    def test_has_core_categories(self):
        expected = ["Compute", "Storage", "Database", "Networking", "Security"]
        for cat in expected:
            assert cat in CATEGORY_DEFAULTS, f"Missing category {cat}"

    def test_all_have_required_fields(self):
        for cat, meta in CATEGORY_DEFAULTS.items():
            assert "complexity" in meta
            assert "migration_tool" in meta
            assert "migration_approach" in meta
            assert "estimated_hours" in meta


# ====================================================================
# _get_service_complexity()
# ====================================================================

class TestGetServiceComplexity:
    def test_known_service(self):
        result = _get_service_complexity("EC2", "Compute")
        assert result["complexity"] == 2
        assert "Azure Migrate" in result["migration_tool"]

    def test_unknown_service_falls_back_to_category(self):
        result = _get_service_complexity("UnknownService123", "Storage")
        assert result == CATEGORY_DEFAULTS["Storage"]

    def test_unknown_category_returns_default(self):
        result = _get_service_complexity("UnknownService123", "UnknownCategory")
        assert result["complexity"] == 3  # global default
        assert result["migration_approach"] == "replatform"


# ====================================================================
# assess_migration_complexity()
# ====================================================================

class TestAssessMigrationComplexity:
    def test_empty_analysis(self):
        """Empty analysis returns zero score with unknown risk."""
        result = assess_migration_complexity({})
        assert result["overall_score"] == 0
        assert result["risk_level"] == "unknown"
        assert result["total_services"] == 0
        assert len(result["recommendations"]) >= 1

    def test_empty_mappings(self):
        result = assess_migration_complexity({"mappings": []})
        assert result["overall_score"] == 0
        assert result["total_services"] == 0

    def test_single_simple_service(self):
        """S3 migration should be low complexity."""
        analysis = {
            "mappings": [
                {"source_service": "S3", "azure_service": "Azure Blob Storage",
                 "category": "Storage", "confidence": 0.95}
            ]
        }
        result = assess_migration_complexity(analysis)
        assert result["overall_score"] <= 2
        assert result["risk_level"] in ("low", "medium")
        assert result["total_services"] == 1
        assert len(result["services"]) == 1
        assert result["services"][0]["source_service"] == "S3"

    def test_complex_architecture(self):
        """Multiple hard services should yield high score."""
        analysis = {
            "mappings": [
                {"source_service": "DynamoDB", "azure_service": "Cosmos DB",
                 "category": "Database", "confidence": 0.8},
                {"source_service": "IAM", "azure_service": "Entra ID",
                 "category": "Security", "confidence": 0.7},
                {"source_service": "Outposts", "azure_service": "Azure Stack HCI",
                 "category": "Hybrid", "confidence": 0.6},
            ]
        }
        result = assess_migration_complexity(analysis)
        assert result["overall_score"] >= 3
        assert result["risk_level"] in ("high", "critical")
        assert result["total_estimated_hours"] > 0
        assert result["estimated_work_days"] > 0

    def test_low_confidence_increases_complexity(self):
        """Low confidence (<0.75) should bump complexity by 1."""
        analysis = {
            "mappings": [
                {"source_service": "S3", "azure_service": "Azure Blob Storage",
                 "category": "Storage", "confidence": 0.5}
            ]
        }
        result = assess_migration_complexity(analysis)
        # S3 is normally 1 complexity, but low confidence adds +1
        assert result["services"][0]["complexity"] == 2

    def test_output_structure(self):
        """Result has all expected keys."""
        analysis = {
            "mappings": [
                {"source_service": "Lambda", "azure_service": "Azure Functions",
                 "category": "Compute", "confidence": 0.9}
            ]
        }
        result = assess_migration_complexity(analysis)
        assert "overall_score" in result
        assert "risk_level" in result
        assert "total_services" in result
        assert "total_estimated_hours" in result
        assert "estimated_work_days" in result
        assert "primary_approach" in result
        assert "approach_breakdown" in result
        assert "complexity_distribution" in result
        assert "services" in result
        assert "recommendations" in result

    def test_services_sorted_by_complexity(self):
        """Services should be sorted descending by complexity."""
        analysis = {
            "mappings": [
                {"source_service": "S3", "azure_service": "Blob", "category": "Storage", "confidence": 0.95},
                {"source_service": "DynamoDB", "azure_service": "Cosmos", "category": "Database", "confidence": 0.8},
                {"source_service": "EC2", "azure_service": "VM", "category": "Compute", "confidence": 0.9},
            ]
        }
        result = assess_migration_complexity(analysis)
        complexities = [s["complexity"] for s in result["services"]]
        assert complexities == sorted(complexities, reverse=True)

    def test_approach_breakdown_sums_correctly(self):
        """Approach breakdown should sum to total services."""
        analysis = {
            "mappings": [
                {"source_service": "S3", "azure_service": "Blob", "category": "Storage", "confidence": 0.95},
                {"source_service": "Lambda", "azure_service": "Functions", "category": "Compute", "confidence": 0.9},
                {"source_service": "DynamoDB", "azure_service": "Cosmos", "category": "Database", "confidence": 0.8},
            ]
        }
        result = assess_migration_complexity(analysis)
        total = sum(result["approach_breakdown"].values())
        assert total == result["total_services"]

    def test_recommendations_for_hard_services(self):
        """Hard services should trigger proof-of-concept recommendation."""
        analysis = {
            "mappings": [
                {"source_service": "Outposts", "azure_service": "Azure Stack HCI",
                 "category": "Hybrid", "confidence": 0.6}
            ]
        }
        result = assess_migration_complexity(analysis)
        rec_text = " ".join(result["recommendations"]).lower()
        assert "proof-of-concept" in rec_text or "high-complexity" in rec_text

    def test_risk_level_boundaries(self):
        """Verify risk-level assignment logic."""
        # Single trivial service → low
        result = assess_migration_complexity({"mappings": [
            {"source_service": "S3", "azure_service": "Blob", "category": "Storage", "confidence": 0.95}
        ]})
        assert result["risk_level"] == "low"
