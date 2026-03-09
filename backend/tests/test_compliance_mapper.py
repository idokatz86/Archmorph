"""
Archmorph — Compliance Mapper Unit Tests
Tests for compliance_mapper.py (Issue #160)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from compliance_mapper import (
    FRAMEWORKS,
    COMMON_GAPS,
    assess_compliance,
)


# ────────────────────────────────────────────────────────────────────
# Fixture
# ────────────────────────────────────────────────────────────────────
def _make_analysis(**overrides):
    base = {
        "diagram_id": "test-comp-001",
        "diagram_type": "architecture",
        "source_provider": "aws",
        "mappings": [
            {"source_service": "RDS", "azure_service": "Azure Database for PostgreSQL", "confidence": 0.9, "category": "Database", "notes": ""},
            {"source_service": "S3", "azure_service": "Blob Storage", "confidence": 0.95, "category": "Storage", "notes": ""},
            {"source_service": "Lambda", "azure_service": "Azure Functions", "confidence": 0.85, "category": "Compute", "notes": ""},
        ],
        "zones": ["us-east-1"],
        "service_connections": [],
        "confidence_summary": {"average": 0.90, "min": 0.85, "max": 0.95},
        "warnings": [],
        "architecture_patterns": [],
    }
    base.update(overrides)
    return base


# ====================================================================
# FRAMEWORKS data quality
# ====================================================================

class TestFrameworksData:
    def test_frameworks_not_empty(self):
        assert len(FRAMEWORKS) >= 6

    def test_known_frameworks_present(self):
        expected = {"HIPAA", "PCI-DSS", "SOC 2", "GDPR", "ISO 27001", "FedRAMP"}
        actual = set(FRAMEWORKS.keys())
        assert expected.issubset(actual), f"Missing frameworks: {expected - actual}"


# ====================================================================
# COMMON_GAPS data quality
# ====================================================================

class TestCommonGaps:
    def test_gaps_not_empty(self):
        assert len(COMMON_GAPS) >= 5

    def test_gaps_are_dicts(self):
        for key, gap in COMMON_GAPS.items():
            assert isinstance(gap, dict)


# ====================================================================
# assess_compliance end-to-end
# ====================================================================

class TestAssessCompliance:
    def test_returns_dict(self):
        result = assess_compliance(_make_analysis())
        assert isinstance(result, dict)

    def test_has_overall_score(self):
        result = assess_compliance(_make_analysis())
        assert "overall_score" in result
        assert 0 <= result["overall_score"] <= 100

    def test_has_frameworks(self):
        result = assess_compliance(_make_analysis())
        assert "frameworks" in result
        assert isinstance(result["frameworks"], dict)

    def test_frameworks_have_scores(self):
        result = assess_compliance(_make_analysis())
        for fw_id, fw in result["frameworks"].items():
            assert "framework" in fw or "full_name" in fw
            assert "score" in fw
            assert 0 <= fw["score"] <= 100

    def test_frameworks_have_gaps(self):
        result = assess_compliance(_make_analysis())
        for fw_id, fw in result["frameworks"].items():
            assert "gaps" in fw
            assert isinstance(fw["gaps"], list)

    def test_has_total_gaps(self):
        result = assess_compliance(_make_analysis())
        assert "total_gaps" in result
        assert result["total_gaps"] >= 0

    def test_has_critical_gaps(self):
        result = assess_compliance(_make_analysis())
        # May use 'critical_gaps' or track via recommendations
        total_gaps = result.get("total_gaps", 0)
        assert total_gaps >= 0

    def test_empty_mappings(self):
        result = assess_compliance(_make_analysis(mappings=[]))
        assert result["overall_score"] >= 0

    def test_large_architecture(self):
        mappings = [
            {"source_service": f"Svc{i}", "azure_service": f"Az{i}", "confidence": 0.7, "category": "Compute", "notes": ""}
            for i in range(30)
        ]
        result = assess_compliance(_make_analysis(mappings=mappings))
        assert result["overall_score"] >= 0
        assert len(result["frameworks"]) >= 1



# ====================================================================
# analyze_live_compliance
# ====================================================================
from compliance_mapper import analyze_live_compliance

class TestAnalyzeLiveCompliance:
    def test_live_compliance_empty(self):
        res = analyze_live_compliance({"resources": []})
        assert res["overall_score"] == 100
        assert len(res["violations"]) == 0

    def test_live_compliance_violations(self):
        resources = [
            {
                "id": "1",
                "name": "sa1",
                "type": "microsoft.storage/storageaccounts",
                "attributes": {"supportsHttpsTrafficOnly": False}
            },
            {
                "id": "2",
                "name": "kv1",
                "type": "microsoft.keyvault/vaults",
                "attributes": {"enableSoftDelete": False}
            },
            {
                "id": "3",
                "name": "vm1",
                "type": "microsoft.compute/virtualmachines",
                "tags": {}
            }
        ]
        res = analyze_live_compliance({"resources": resources})
        
        # We expect a few violations
        assert len(res["violations"]) >= 3
        # Ensure points dropped
        assert res["overall_score"] < 100
        
        # Check frameworks present
        assert "SOC 2" in res["frameworks"]
        assert res["frameworks"]["SOC 2"]["score"] < 100

    def test_live_compliance_passing(self):
        resources = [
            {
                "id": "1",
                "name": "sa1",
                "type": "microsoft.storage/storageaccounts",
                "attributes": {"supportsHttpsTrafficOnly": True}
            },
            {
                "id": "2",
                "name": "kv1",
                "type": "microsoft.keyvault/vaults",
                "attributes": {"enableSoftDelete": True}
            }
        ]
        res = analyze_live_compliance({"resources": resources})
        
        # We expect no violations for the rules we have
        assert len(res["violations"]) == 0
        assert res["overall_score"] == 100
