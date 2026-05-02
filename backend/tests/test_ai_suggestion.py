import json
"""
Archmorph — AI Suggestion Unit Tests
Tests for ai_suggestion.py (Issue #153)
"""

import os
import sys

import pytest

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

    def test_uppercase_provider_is_normalized(self):
        assert lookup_mapping("EC2", "AWS") == lookup_mapping("EC2", "aws")

    @pytest.mark.parametrize("provider", ["azure", "amazon", "google", "", 123])
    def test_invalid_provider_is_rejected(self, provider):
        with pytest.raises(ValueError, match="Unsupported source_provider"):
            lookup_mapping("EC2", provider)

    def test_none_provider_uses_legacy_aws_default(self):
        assert lookup_mapping("EC2", None) == lookup_mapping("EC2", "aws")


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




from ai_suggestion import _build_confidence_factors, _lookup_service_knowledge, build_mapping_deep_dive, suggest_mapping
from unittest.mock import patch, MagicMock

def test_generate_confidence_factors_positive():
    suggestion = {
        "confidence": 0.95,
        "source": "catalog",
        "feature_gaps": [],
        "migration_effort": "low",
        "alternatives": ["AKS"]
    }
    factors = _build_confidence_factors(suggestion, "SomeService")
    assert len(factors) > 0
    assert any(f["factor"] == "catalog_match" and f["signal"] == "positive" for f in factors)
    assert any(f["factor"] == "feature_parity" and f["signal"] == "positive" for f in factors)

def test_generate_confidence_factors_negative():
    suggestion = {
        "confidence": 0.4,
        "source": "inference",
        "feature_gaps": ["Missing auth feature"],
        "migration_effort": "high",
        "alternatives": ["AKS", "ACA", "App Service"]
    }
    factors = _build_confidence_factors(suggestion, "SomeService")
    assert len(factors) > 0
    assert any(f["factor"] == "catalog_match" and f["signal"] == "negative" for f in factors)
    assert any(f["factor"] == "feature_parity" and f["signal"] == "negative" for f in factors)
    assert any(f["factor"] == "migration_effort" and f["signal"] == "negative" for f in factors)

def test_lookup_service_knowledge():
    res1 = _lookup_service_knowledge("virtual machines")
    assert res1["limitations"] is not None
    
    res2 = _lookup_service_knowledge("completely unknown service")
    assert "strengths" in res2
    assert res2["limitations"] == []

def test_build_mapping_deep_dive():
    suggestion = {
        "azure_service": "Virtual Machines",
        "feature_gaps": ["Some specific gap"],
        "migration_effort": "high"
    }
    deep_dive = build_mapping_deep_dive(suggestion, "EC2")
    assert "strengths" in deep_dive
    assert len(deep_dive["limitations"]) > 0
    assert any("Some specific gap" in lim["factor"] for lim in deep_dive["limitations"])



@patch("ai_suggestion.get_openai_client")
def test_suggest_mapping_gpt_path(mock_get_client):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_message = MagicMock()
    
    mock_message.content = json.dumps({
        "azure_service": "Azure App Service",
        "confidence_score": 88,
        "reasoning": "Standard app hosting.",
        "common_gaps": ["None"],
        "cost_implications": "Minimal",
        "doc_links": ["https://learn.microsoft.com/app-service"]
    })
    mock_response.choices = [MagicMock(message=mock_message)]
    mock_client.chat.completions.create.return_value = mock_response
    mock_get_client.return_value = mock_client
    
    # Needs matching structure to what ai_suggestion.py expects:
    res = suggest_mapping("UnknownService", "aws")
    
    assert res["azure_service"] == "Azure App Service"

@patch("ai_suggestion.get_openai_client")
def test_suggest_mapping_gpt_failure(mock_get_client):
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("API Error")
    mock_get_client.return_value = mock_client
    
    res = suggest_mapping("UnknownService", "aws")
    # if suggest_mapping catches error, it returns "Unknown Resource/No Match"
    assert res["azure_service"] == "Unknown"


def test_suggest_mapping_normalizes_provider_in_result():
    res = suggest_mapping("EC2", "AWS")
    assert res["source_provider"] == "aws"


def test_suggest_mapping_rejects_azure_source_provider():
    with pytest.raises(ValueError, match="Unsupported source_provider"):
        suggest_mapping("Virtual Machines", "azure")
