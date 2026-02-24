"""
Unit tests for the cross-cloud service mappings module.

Covers:
  - CROSS_CLOUD_MAPPINGS structure and data integrity
  - All mappings have required fields
  - Category distribution
  - Confidence score ranges
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.mappings import CROSS_CLOUD_MAPPINGS


class TestMappingsStructure:
    """Validate the structure of CROSS_CLOUD_MAPPINGS."""

    def test_mappings_is_list(self):
        assert isinstance(CROSS_CLOUD_MAPPINGS, list)

    def test_mappings_not_empty(self):
        assert len(CROSS_CLOUD_MAPPINGS) > 0

    def test_each_mapping_has_required_fields(self):
        required = {"aws", "azure", "gcp", "category", "confidence", "notes"}
        for i, m in enumerate(CROSS_CLOUD_MAPPINGS):
            assert required.issubset(m.keys()), f"Mapping {i} missing fields: {required - m.keys()}"

    def test_all_aws_services_are_strings(self):
        for m in CROSS_CLOUD_MAPPINGS:
            assert isinstance(m["aws"], str)
            assert len(m["aws"]) > 0

    def test_all_azure_services_are_strings(self):
        for m in CROSS_CLOUD_MAPPINGS:
            assert isinstance(m["azure"], str)
            assert len(m["azure"]) > 0

    def test_all_gcp_services_are_strings(self):
        for m in CROSS_CLOUD_MAPPINGS:
            assert isinstance(m["gcp"], str)
            assert len(m["gcp"]) > 0


class TestMappingsConfidence:
    """Validate confidence scores are within range."""

    def test_confidence_between_0_and_1(self):
        for m in CROSS_CLOUD_MAPPINGS:
            assert 0 <= m["confidence"] <= 1, f"{m['aws']} has invalid confidence {m['confidence']}"

    def test_no_zero_confidence(self):
        for m in CROSS_CLOUD_MAPPINGS:
            assert m["confidence"] > 0, f"{m['aws']} has zero confidence"

    def test_high_confidence_for_direct_equivalents(self):
        # Well-known direct equivalents should have high confidence
        direct = {"EC2", "Lambda", "S3", "EKS", "VPC"}
        for m in CROSS_CLOUD_MAPPINGS:
            if m["aws"] in direct:
                assert m["confidence"] >= 0.90, f"{m['aws']} should have high confidence"


class TestMappingsCategories:
    """Validate category coverage."""

    def test_has_compute_category(self):
        cats = {m["category"] for m in CROSS_CLOUD_MAPPINGS}
        assert "Compute" in cats

    def test_has_storage_category(self):
        cats = {m["category"] for m in CROSS_CLOUD_MAPPINGS}
        assert "Storage" in cats

    def test_has_database_category(self):
        cats = {m["category"] for m in CROSS_CLOUD_MAPPINGS}
        assert "Database" in cats

    def test_has_networking_category(self):
        cats = {m["category"] for m in CROSS_CLOUD_MAPPINGS}
        assert "Networking" in cats

    def test_all_categories_are_strings(self):
        for m in CROSS_CLOUD_MAPPINGS:
            assert isinstance(m["category"], str)
            assert len(m["category"]) > 0

    def test_minimum_service_count(self):
        """Should have at least 50 mappings for a comprehensive catalog."""
        assert len(CROSS_CLOUD_MAPPINGS) >= 50


class TestMappingsNotes:
    """Validate notes field."""

    def test_all_notes_are_strings(self):
        for m in CROSS_CLOUD_MAPPINGS:
            assert isinstance(m["notes"], str)

    def test_notes_not_empty(self):
        for m in CROSS_CLOUD_MAPPINGS:
            assert len(m["notes"]) > 0, f"Mapping {m['aws']} has empty notes"
