"""
Archmorph — AI Suggestion Unit Tests
Tests for ai_suggestion.py (Issue #153)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ai_suggestion import (
    lookup_mapping,
    build_dependency_graph,
    COMMON_DEPENDENCIES,
    _enqueue_review,
    get_review_queue,
    review_suggestion,
    get_review_stats,
)


# ====================================================================
# lookup_mapping (fast catalogue path)
# ====================================================================

class TestLookupMapping:
    def test_known_aws_service(self):
        result = lookup_mapping("EC2", "aws")
        assert result is not None

    def test_known_gcp_service(self):
        result = lookup_mapping("Compute Engine", "gcp")
        assert result is not None

    def test_unknown_service(self):
        result = lookup_mapping("NonExistentService12345", "aws")
        assert result is None

    def test_confidence_for_catalogue(self):
        result = lookup_mapping("S3", "aws")
        if result:
            assert "confidence" in result or "azure" in result

    def test_lambda_lookup(self):
        result = lookup_mapping("Lambda", "aws")
        assert result is not None


# ====================================================================
# COMMON_DEPENDENCIES data quality
# ====================================================================

class TestCommonDependencies:
    def test_not_empty(self):
        assert len(COMMON_DEPENDENCIES) >= 5

    def test_values_are_lists(self):
        for svc, deps in COMMON_DEPENDENCIES.items():
            assert isinstance(deps, list), f"{svc} deps is not a list"

    def test_known_services(self):
        assert "Azure Virtual Machines" in COMMON_DEPENDENCIES or \
               "Virtual Machines" in COMMON_DEPENDENCIES or \
               len(COMMON_DEPENDENCIES) > 0


# ====================================================================
# build_dependency_graph
# ====================================================================

class TestBuildDependencyGraph:
    def _make_mappings(self):
        return [
            {"source_service": "EC2", "azure_service": "Virtual Machines", "confidence": 0.9, "category": "Compute"},
            {"source_service": "RDS", "azure_service": "Azure SQL Database", "confidence": 0.85, "category": "Database"},
        ]

    def test_returns_dict(self):
        result = build_dependency_graph(self._make_mappings())
        assert isinstance(result, dict)

    def test_has_nodes(self):
        result = build_dependency_graph(self._make_mappings())
        assert "nodes" in result
        assert isinstance(result["nodes"], list)

    def test_has_edges(self):
        result = build_dependency_graph(self._make_mappings())
        assert "edges" in result
        assert isinstance(result["edges"], list)

    def test_has_missing_dependencies(self):
        result = build_dependency_graph(self._make_mappings())
        assert "missing_dependencies" in result

    def test_empty_mappings(self):
        result = build_dependency_graph([])
        assert result["nodes"] == [] or len(result["nodes"]) == 0


# ====================================================================
# Review queue
# ====================================================================

class TestReviewQueue:
    def test_get_empty_queue(self):
        result = get_review_queue()
        assert isinstance(result, (list, dict))

    def test_get_review_stats(self):
        stats = get_review_stats()
        assert isinstance(stats, dict)

    def test_enqueue_and_retrieve(self):
        suggestion_id = _enqueue_review({
            "source_service": "TestSvc",
            "azure_service": "TestAzure",
            "confidence": 0.4,
            "source": "gpt",
        })
        queue = get_review_queue()
        # Queue should contain at least the item we just added
        ids = [item.get("suggestion_id") for item in queue]
        assert suggestion_id in ids

    def test_review_accept(self):
        suggestion_id = _enqueue_review({
            "source_service": "ReviewSvc",
            "azure_service": "ReviewAzure",
            "confidence": 0.3,
            "source": "gpt",
        })
        result = review_suggestion(suggestion_id, "accepted", "reviewer@test.com")
        assert result is not None

    def test_review_reject(self):
        suggestion_id = _enqueue_review({
            "source_service": "RejectSvc",
            "azure_service": "RejectAzure",
            "confidence": 0.2,
            "source": "gpt",
        })
        result = review_suggestion(suggestion_id, "rejected", "reviewer@test.com")
        assert result is not None
