"""
Unit tests for review_queue_builder — Issue #1137.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from review_queue_builder import (
    build_review_queue,
    queue_summary,
    apply_risk_annotations,
    _stable_item_id,
    _classify_warning,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _make_analysis(**kwargs):
    base = {
        "mappings": [],
        "warnings": [],
        "assumptions": [],
    }
    base.update(kwargs)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# _stable_item_id
# ─────────────────────────────────────────────────────────────────────────────

class TestStableItemId:
    def test_returns_16_char_hex(self):
        result = _stable_item_id("bucket", "discriminator")
        assert len(result) == 16
        assert all(c in "0123456789abcdef" for c in result)

    def test_stable_across_calls(self):
        a = _stable_item_id("low_confidence", "EC2:Azure VM")
        b = _stable_item_id("low_confidence", "EC2:Azure VM")
        assert a == b

    def test_different_discriminators_differ(self):
        a = _stable_item_id("bucket", "x")
        b = _stable_item_id("bucket", "y")
        assert a != b


# ─────────────────────────────────────────────────────────────────────────────
# _classify_warning
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifyWarning:
    def test_cost_keywords(self):
        assert _classify_warning("Estimated monthly cost may be high") == "cost_warning"
        assert _classify_warning("License pricing not included") == "cost_warning"

    def test_security_keywords(self):
        assert _classify_warning("Encryption at rest is not configured") == "security_concern"
        assert _classify_warning("RBAC roles are not assigned") == "security_concern"

    def test_fallback_to_architecture_gap(self):
        assert _classify_warning("Missing load balancer in the frontend zone") == "architecture_gap"


# ─────────────────────────────────────────────────────────────────────────────
# build_review_queue
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildReviewQueue:
    def test_empty_analysis_returns_empty_list(self):
        result = build_review_queue(_make_analysis())
        assert result == []

    def test_low_confidence_mapping_appears(self):
        analysis = _make_analysis(
            mappings=[
                {"source_service": "EC2", "azure_service": "Azure VM", "confidence": 0.6},
            ]
        )
        items = build_review_queue(analysis)
        assert len(items) == 1
        assert items[0]["bucket"] == "low_confidence"
        assert "EC2" in items[0]["title"]
        assert "Azure VM" in items[0]["title"]

    def test_high_confidence_mapping_excluded(self):
        analysis = _make_analysis(
            mappings=[
                {"source_service": "RDS", "azure_service": "Azure SQL", "confidence": 0.95},
            ]
        )
        items = build_review_queue(analysis)
        assert items == []

    def test_confidence_below_0_5_is_high_severity(self):
        analysis = _make_analysis(
            mappings=[
                {"source_service": "MySvc", "azure_service": "SomeAzure", "confidence": 0.3},
            ]
        )
        items = build_review_queue(analysis)
        assert items[0]["severity"] == "high"

    def test_confidence_between_0_5_and_0_8_is_medium(self):
        analysis = _make_analysis(
            mappings=[
                {"source_service": "MySvc", "azure_service": "SomeAzure", "confidence": 0.7},
            ]
        )
        items = build_review_queue(analysis)
        assert items[0]["severity"] == "medium"

    def test_cost_warning_extracted(self):
        analysis = _make_analysis(
            warnings=["Monthly cost estimate may be high due to NAT Gateway egress."]
        )
        items = build_review_queue(analysis)
        assert any(i["bucket"] == "cost_warning" for i in items)

    def test_security_warning_extracted(self):
        analysis = _make_analysis(
            warnings=["Encryption at rest is not configured for Blob Storage."]
        )
        items = build_review_queue(analysis)
        assert any(i["bucket"] == "security_concern" for i in items)

    def test_architecture_gap_warning_extracted(self):
        analysis = _make_analysis(
            warnings=["Missing load balancer in frontend zone."]
        )
        items = build_review_queue(analysis)
        assert any(i["bucket"] == "architecture_gap" for i in items)

    def test_assumption_extracted(self):
        analysis = _make_analysis(
            assumptions=[
                {"question": "Is high availability required?", "assumed_answer": "Yes"},
            ]
        )
        items = build_review_queue(analysis)
        assert any(i["bucket"] == "assumptions" for i in items)
        assert any("Is high availability required?" in i["title"] for i in items)

    def test_assumption_empty_question_skipped(self):
        analysis = _make_analysis(
            assumptions=[{"question": "", "assumed_answer": "Yes"}]
        )
        items = build_review_queue(analysis)
        assert items == []

    def test_unmatched_service_flagged(self):
        analysis = _make_analysis(
            mappings=[
                {"source_service": "MyCustomSvc", "azure_service": "", "confidence": 0.9},
            ]
        )
        items = build_review_queue(analysis)
        assert any(i["bucket"] == "architecture_gap" for i in items)
        assert any("MyCustomSvc" in i["title"] for i in items)

    def test_compliance_flag_added(self):
        analysis = _make_analysis(profile={"compliance": "PCI-DSS"})
        items = build_review_queue(analysis)
        assert any(i["bucket"] == "security_concern" and "PCI-DSS" in i["title"] for i in items)

    def test_compliance_none_skipped(self):
        analysis = _make_analysis(profile={"compliance": "None"})
        items = build_review_queue(analysis)
        assert not any("compliance" in i.get("source", {}) for i in items)

    def test_items_sorted_high_before_medium(self):
        analysis = _make_analysis(
            mappings=[
                {"source_service": "SvcA", "azure_service": "AzA", "confidence": 0.7},  # medium
                {"source_service": "SvcB", "azure_service": "AzB", "confidence": 0.3},  # high
            ]
        )
        items = build_review_queue(analysis)
        severities = [i["severity"] for i in items]
        # All "high" items before any "medium"
        high_indices = [i for i, s in enumerate(severities) if s == "high"]
        medium_indices = [i for i, s in enumerate(severities) if s == "medium"]
        if high_indices and medium_indices:
            assert max(high_indices) < min(medium_indices)

    def test_duplicate_ids_deduplicated(self):
        # Two warnings with identical text → same id → only one item
        analysis = _make_analysis(
            warnings=[
                "Missing load balancer in frontend zone.",
                "Missing load balancer in frontend zone.",
            ]
        )
        items = build_review_queue(analysis)
        ids = [i["id"] for i in items]
        assert len(ids) == len(set(ids))

    def test_source_service_dict_form(self):
        analysis = _make_analysis(
            mappings=[
                {
                    "source_service": {"name": "DictSvc", "type": "compute"},
                    "azure_service": "Azure VM",
                    "confidence": 0.4,
                },
            ]
        )
        items = build_review_queue(analysis)
        assert any("DictSvc" in i["title"] for i in items)

    def test_string_warning_extracted(self):
        analysis = _make_analysis(warnings=["This is a plain string warning."])
        items = build_review_queue(analysis)
        assert len(items) == 1

    def test_dict_warning_with_message_key(self):
        analysis = _make_analysis(warnings=[{"message": "Security group is too permissive."}])
        items = build_review_queue(analysis)
        assert any("Security group" in i["description"] for i in items)


# ─────────────────────────────────────────────────────────────────────────────
# queue_summary
# ─────────────────────────────────────────────────────────────────────────────

class TestQueueSummary:
    def _items(self):
        return [
            {"id": "aaa", "severity": "high", "bucket": "security_concern"},
            {"id": "bbb", "severity": "medium", "bucket": "architecture_gap"},
            {"id": "ccc", "severity": "low", "bucket": "assumptions"},
        ]

    def test_empty_dispositions_all_unresolved(self):
        summary = queue_summary(self._items(), {})
        assert summary["total"] == 3
        assert summary["unresolved"] == 3
        assert summary["blocking"] == 1
        assert summary["resolved"] == 0
        assert summary["gated"] is True

    def test_all_accepted_not_gated(self):
        dispositions = {
            "aaa": {"action": "accept"},
            "bbb": {"action": "accept"},
            "ccc": {"action": "accept"},
        }
        summary = queue_summary(self._items(), dispositions)
        assert summary["blocking"] == 0
        assert summary["gated"] is False

    def test_mark_risk_counts_as_resolved(self):
        dispositions = {"aaa": {"action": "mark_risk"}}
        summary = queue_summary(self._items(), dispositions)
        assert summary["risks_accepted"] == 1
        assert summary["resolved"] == 1
        assert summary["blocking"] == 0

    def test_empty_queue_not_gated(self):
        summary = queue_summary([], {})
        assert summary["gated"] is False
        assert summary["total"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# apply_risk_annotations
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyRiskAnnotations:
    def test_mark_risk_injects_annotation(self):
        analysis = _make_analysis(
            mappings=[
                {"source_service": "SvcX", "azure_service": "AzureX", "confidence": 0.3}
            ]
        )
        items = build_review_queue(analysis)
        item_id = items[0]["id"]
        dispositions = {item_id: {"action": "mark_risk", "edited_text": "We accept this risk."}}
        result = apply_risk_annotations(analysis, dispositions)
        annotations = result.get("risk_annotations", [])
        assert len(annotations) == 1
        assert annotations[0]["id"] == item_id
        assert annotations[0]["note"] == "We accept this risk."

    def test_accept_does_not_inject_annotation(self):
        analysis = _make_analysis(
            mappings=[
                {"source_service": "SvcY", "azure_service": "AzureY", "confidence": 0.3}
            ]
        )
        items = build_review_queue(analysis)
        item_id = items[0]["id"]
        dispositions = {item_id: {"action": "accept"}}
        result = apply_risk_annotations(analysis, dispositions)
        assert result.get("risk_annotations", []) == []

    def test_does_not_mutate_original(self):
        analysis = _make_analysis(
            warnings=["Security group is overly permissive."]
        )
        original_warnings = list(analysis["warnings"])
        apply_risk_annotations(analysis, {})
        assert analysis["warnings"] == original_warnings

    def test_existing_annotations_preserved(self):
        analysis = _make_analysis(
            risk_annotations=[{"id": "existing", "note": "pre-existing risk"}],
            mappings=[{"source_service": "SvcZ", "azure_service": "AzureZ", "confidence": 0.2}],
        )
        items = build_review_queue(analysis)
        item_id = items[0]["id"]
        dispositions = {item_id: {"action": "mark_risk"}}
        result = apply_risk_annotations(analysis, dispositions)
        ids = [a["id"] for a in result["risk_annotations"]]
        assert "existing" in ids
        assert item_id in ids
