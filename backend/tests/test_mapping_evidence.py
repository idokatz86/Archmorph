"""Tests for backend/mapping_evidence.py (issue #1130).

Validates evidence payload shape, needs_review flagging,
run metadata structure, and the attach_evidence_to_mappings helper.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mapping_evidence as me


# ─────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────

CATALOGUE_MAPPING = {
    "source_service": "EC2",
    "source_provider": "aws",
    "azure_service": "Virtual Machines",
    "confidence": 0.95,
    "source": "catalogue",
    "notes": "Direct equivalent — IaaS virtual machines",
    "review_status": "approved",
}

LOW_CONFIDENCE_MAPPING = {
    "source_service": "CustomProprietary",
    "source_provider": "aws",
    "azure_service": "Unknown",
    "confidence": 0.55,
    "source": "ai",
    "notes": "No clear Azure equivalent found",
    "review_status": "pending",
}

AI_MAPPING_WITH_ALTERNATIVES = {
    "source_service": "Fargate",
    "source_provider": "aws",
    "azure_service": "Container Apps",
    "confidence": 0.88,
    "source": "ai",
    "notes": "Serverless container execution",
    "alternatives": [
        {"name": "AKS", "confidence": 0.80, "rationale": "Full orchestration option"},
        {"name": "Container Instances", "confidence": 0.75, "rationale": "Simpler per-container option"},
    ],
    "feature_gaps": ["Fargate Spot pricing model differs from Container Apps consumption pricing"],
}

USER_MAPPING = {
    "source_service": "MyService",
    "source_provider": "aws",
    "azure_service": "Azure App Service",
    "confidence": 1.0,
    "source": "user",
    "user_added": True,
}

GCP_MAPPING = {
    "source_service": "GKE",
    "source_provider": "gcp",
    "azure_service": "AKS",
    "confidence": 0.92,
    "source": "catalogue",
}


# ─────────────────────────────────────────────────────────
# build_mapping_evidence
# ─────────────────────────────────────────────────────────

class TestBuildMappingEvidence:
    def test_required_fields_present(self):
        ev = me.build_mapping_evidence(CATALOGUE_MAPPING)
        assert "detection_source" in ev
        assert "detection_confidence" in ev
        assert "rationale" in ev
        assert "alternatives_considered" in ev
        assert "known_gaps" in ev
        assert "catalog_freshness" in ev
        assert "user_override" in ev
        assert "user_confirmed" in ev
        assert "needs_review" in ev
        assert "run_id" in ev
        assert "generated_at" in ev

    def test_catalogue_mapping_not_flagged_for_review(self):
        ev = me.build_mapping_evidence(CATALOGUE_MAPPING)
        assert ev["needs_review"] is False
        assert ev["detection_source"] == "catalogue"
        assert ev["user_confirmed"] is True  # review_status == "approved"

    def test_low_confidence_flagged_for_review(self):
        ev = me.build_mapping_evidence(LOW_CONFIDENCE_MAPPING)
        assert ev["needs_review"] is True
        assert ev["detection_confidence"] == pytest.approx(0.55)

    def test_needs_review_threshold_boundary(self):
        """Exactly at the threshold should NOT be flagged."""
        m = {**LOW_CONFIDENCE_MAPPING, "confidence": me.NEEDS_REVIEW_THRESHOLD}
        ev = me.build_mapping_evidence(m)
        assert ev["needs_review"] is False

    def test_needs_review_below_threshold(self):
        m = {**LOW_CONFIDENCE_MAPPING, "confidence": me.NEEDS_REVIEW_THRESHOLD - 0.01}
        ev = me.build_mapping_evidence(m)
        assert ev["needs_review"] is True

    def test_user_mapping_confirmed_and_not_needs_review(self):
        ev = me.build_mapping_evidence(USER_MAPPING)
        assert ev["user_override"] is True
        assert ev["user_confirmed"] is True
        assert ev["needs_review"] is False  # user confirmed overrides needs_review

    def test_rationale_contains_azure_service_name(self):
        ev = me.build_mapping_evidence(CATALOGUE_MAPPING)
        assert "Virtual Machines" in ev["rationale"]

    def test_rationale_catalogue_source(self):
        ev = me.build_mapping_evidence(CATALOGUE_MAPPING)
        assert "catalog" in ev["rationale"].lower() or "catalogue" in ev["rationale"].lower()

    def test_rationale_ai_source(self):
        ev = me.build_mapping_evidence(AI_MAPPING_WITH_ALTERNATIVES)
        assert "ai" in ev["rationale"].lower() or "analysis" in ev["rationale"].lower()

    def test_rationale_user_source(self):
        ev = me.build_mapping_evidence(USER_MAPPING)
        assert "user" in ev["rationale"].lower()

    def test_alternatives_extracted(self):
        ev = me.build_mapping_evidence(AI_MAPPING_WITH_ALTERNATIVES)
        alts = ev["alternatives_considered"]
        assert len(alts) == 2
        assert alts[0]["azure_service"] == "AKS"
        assert alts[1]["azure_service"] == "Container Instances"

    def test_alternatives_empty_for_catalogue(self):
        ev = me.build_mapping_evidence(CATALOGUE_MAPPING)
        assert ev["alternatives_considered"] == []

    def test_known_gaps_from_feature_gaps(self):
        ev = me.build_mapping_evidence(AI_MAPPING_WITH_ALTERNATIVES)
        assert len(ev["known_gaps"]) >= 1
        assert any("Fargate Spot" in g for g in ev["known_gaps"])

    def test_catalog_freshness_for_known_aws_service(self):
        ev = me.build_mapping_evidence(CATALOGUE_MAPPING)
        # EC2 is in the catalog with last_reviewed date
        assert ev["catalog_freshness"] is not None
        assert ev["catalog_freshness"].startswith("20")

    def test_catalog_freshness_none_for_unknown_service(self):
        m = {**LOW_CONFIDENCE_MAPPING, "source_service": "TotallyUnknownService42"}
        ev = me.build_mapping_evidence(m)
        assert ev["catalog_freshness"] is None

    def test_gcp_catalog_freshness(self):
        ev = me.build_mapping_evidence(GCP_MAPPING)
        # GKE should be in the GCP catalog
        assert ev["catalog_freshness"] is not None

    def test_detection_confidence_rounded(self):
        m = {**CATALOGUE_MAPPING, "confidence": 0.123456789}
        ev = me.build_mapping_evidence(m)
        assert ev["detection_confidence"] == pytest.approx(0.1235, abs=1e-4)

    def test_generated_at_is_iso_format(self):
        ev = me.build_mapping_evidence(CATALOGUE_MAPPING)
        # Should be parseable as ISO datetime
        ts = ev["generated_at"].replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        assert dt.tzinfo is not None

    def test_custom_run_id_passed_through(self):
        ev = me.build_mapping_evidence(CATALOGUE_MAPPING, run_id="test-run-123")
        assert ev["run_id"] == "test-run-123"

    def test_custom_analysis_timestamp_passed_through(self):
        ts = "2026-05-01T12:00:00Z"
        ev = me.build_mapping_evidence(CATALOGUE_MAPPING, analysis_timestamp=ts)
        assert ev["generated_at"] == ts

    def test_non_numeric_confidence_falls_back_to_zero(self):
        ev = me.build_mapping_evidence({**LOW_CONFIDENCE_MAPPING, "confidence": "not-a-number"})
        assert ev["detection_confidence"] == 0
        assert ev["needs_review"] is True

    def test_object_shaped_services_are_coerced_to_names(self):
        ev = me.build_mapping_evidence({
            "source_service": {"name": "EC2"},
            "azure_service": {"name": "Virtual Machines"},
            "confidence": 0.95,
            "source": "catalogue",
        })
        assert "EC2" in ev["rationale"]
        assert "Virtual Machines" in ev["rationale"]

    def test_alternative_confidence_accepts_non_numeric_values(self):
        ev = me.build_mapping_evidence({
            **AI_MAPPING_WITH_ALTERNATIVES,
            "alternatives": [{"name": "AKS", "confidence": "n/a", "rationale": {"message": "Full control"}}],
        })
        assert ev["alternatives_considered"][0]["confidence"] == 0
        assert ev["alternatives_considered"][0]["rationale"] == "Full control"


# ─────────────────────────────────────────────────────────
# build_run_metadata
# ─────────────────────────────────────────────────────────

class TestBuildRunMetadata:
    ANALYSIS = {
        "source_provider": "aws",
        "target_provider": "azure",
        "mappings": [
            {"source_service": "EC2", "azure_service": "Virtual Machines", "confidence": 0.95},
            {"source_service": "Lambda", "azure_service": "Azure Functions", "confidence": 0.88},
            {"source_service": "Unknown", "azure_service": "Unknown", "confidence": 0.55,
             "evidence": {"needs_review": True, "user_confirmed": False}},
        ],
    }

    def test_required_fields_present(self):
        meta = me.build_run_metadata(self.ANALYSIS)
        for field in ("schema_version", "run_id", "analysis_timestamp",
                      "source_provider", "target_provider", "catalog_freshness",
                      "model_version", "total_mappings", "low_confidence_count",
                      "needs_review_count", "methodology", "limitations"):
            assert field in meta, f"Missing field: {field}"

    def test_schema_version(self):
        meta = me.build_run_metadata(self.ANALYSIS)
        assert meta["schema_version"] == "run-metadata/v1"

    def test_source_and_target_provider(self):
        meta = me.build_run_metadata(self.ANALYSIS)
        assert meta["source_provider"] == "aws"
        assert meta["target_provider"] == "azure"

    def test_total_mappings_count(self):
        meta = me.build_run_metadata(self.ANALYSIS)
        assert meta["total_mappings"] == 3

    def test_low_confidence_count(self):
        meta = me.build_run_metadata(self.ANALYSIS)
        assert meta["low_confidence_count"] == 1  # only the 0.55 one

    def test_needs_review_count_uses_evidence_flag(self):
        meta = me.build_run_metadata(self.ANALYSIS)
        assert meta["needs_review_count"] >= 1

    def test_custom_run_id(self):
        meta = me.build_run_metadata(self.ANALYSIS, run_id="abc-123")
        assert meta["run_id"] == "abc-123"

    def test_run_id_generated_when_absent(self):
        meta = me.build_run_metadata(self.ANALYSIS)
        assert meta["run_id"]  # non-empty

    def test_methodology_is_nonempty_string(self):
        meta = me.build_run_metadata(self.ANALYSIS)
        assert isinstance(meta["methodology"], str)
        assert len(meta["methodology"]) > 20

    def test_limitations_is_nonempty_list(self):
        meta = me.build_run_metadata(self.ANALYSIS)
        assert isinstance(meta["limitations"], list)
        assert len(meta["limitations"]) > 0

    def test_catalog_freshness_structure(self):
        meta = me.build_run_metadata(self.ANALYSIS)
        cf = meta["catalog_freshness"]
        assert isinstance(cf, dict)
        assert "last_success" in cf
        assert "stale" in cf

    def test_non_numeric_confidence_does_not_break_run_metadata(self):
        meta = me.build_run_metadata({
            **self.ANALYSIS,
            "mappings": [{"source_service": "X", "azure_service": "Y", "confidence": "n/a"}],
        })
        assert meta["low_confidence_count"] == 1

    def test_model_version_not_empty(self):
        meta = me.build_run_metadata(self.ANALYSIS)
        assert meta["model_version"]


# ─────────────────────────────────────────────────────────
# attach_evidence_to_mappings
# ─────────────────────────────────────────────────────────

class TestAttachEvidenceToMappings:
    def test_evidence_attached_to_all_mappings(self):
        mappings = [
            {"source_service": "EC2", "azure_service": "Virtual Machines", "confidence": 0.95, "source": "catalogue"},
            {"source_service": "S3", "azure_service": "Blob Storage", "confidence": 0.90, "source": "catalogue"},
        ]
        me.attach_evidence_to_mappings(mappings, run_id="test-run")
        for m in mappings:
            assert "evidence" in m
            assert isinstance(m["evidence"], dict)
            assert "needs_review" in m["evidence"]

    def test_needs_review_promoted_to_top_level(self):
        mappings = [
            {"source_service": "Obscure", "azure_service": "Something", "confidence": 0.5, "source": "ai"},
        ]
        me.attach_evidence_to_mappings(mappings)
        assert "needs_review" in mappings[0]
        assert mappings[0]["needs_review"] is True

    def test_high_confidence_not_needs_review(self):
        mappings = [
            {"source_service": "EC2", "azure_service": "Virtual Machines", "confidence": 0.95, "source": "catalogue"},
        ]
        me.attach_evidence_to_mappings(mappings)
        assert mappings[0]["needs_review"] is False

    def test_idempotent_skips_existing_evidence(self):
        existing_evidence = {
            "detection_source": "catalogue",
            "detection_confidence": 0.95,
            "rationale": "Pre-existing rationale",
            "alternatives_considered": [],
            "known_gaps": [],
            "catalog_freshness": None,
            "user_override": False,
            "user_confirmed": True,
            "needs_review": False,
            "run_id": "old-run",
            "generated_at": "2026-01-01T00:00:00Z",
        }
        mappings = [
            {
                "source_service": "EC2",
                "azure_service": "Virtual Machines",
                "confidence": 0.95,
                "evidence": existing_evidence,
            }
        ]
        me.attach_evidence_to_mappings(mappings, run_id="new-run")
        # Evidence should NOT have been replaced (idempotent)
        assert mappings[0]["evidence"]["run_id"] == "old-run"
        assert mappings[0]["evidence"]["rationale"] == "Pre-existing rationale"

    def test_non_dict_items_skipped(self):
        mappings = ["string_item", None, {"source_service": "EC2", "azure_service": "VMs", "confidence": 0.9}]
        # Should not raise
        me.attach_evidence_to_mappings(mappings)
        assert "evidence" in mappings[2]

    def test_run_id_shared_across_all_mappings(self):
        mappings = [
            {"source_service": "EC2", "azure_service": "VMs", "confidence": 0.95},
            {"source_service": "S3", "azure_service": "Blob", "confidence": 0.95},
        ]
        me.attach_evidence_to_mappings(mappings, run_id="shared-run-xyz")
        for m in mappings:
            assert m["evidence"]["run_id"] == "shared-run-xyz"


# ─────────────────────────────────────────────────────────
# Constants / public API contract
# ─────────────────────────────────────────────────────────

class TestConstants:
    def test_needs_review_threshold_is_0_70(self):
        assert me.NEEDS_REVIEW_THRESHOLD == 0.70

    def test_methodology_summary_not_empty(self):
        assert len(me._METHODOLOGY_SUMMARY) > 50

    def test_customer_safe_limitations_not_empty(self):
        assert len(me._CUSTOMER_SAFE_LIMITATIONS) >= 3
        for item in me._CUSTOMER_SAFE_LIMITATIONS:
            assert isinstance(item, str)
