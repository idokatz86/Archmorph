"""
Archmorph — Cost Comparison Unit Tests
Tests for cost_comparison.py (Issue #66)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cost_comparison import (
    AWS_BASE_PRICES,
    _estimate_provider_cost,
    generate_cost_comparison,
)


# ====================================================================
# AWS_BASE_PRICES data quality
# ====================================================================

class TestAWSBasePrices:
    def test_not_empty(self):
        assert len(AWS_BASE_PRICES) > 20

    def test_all_non_negative(self):
        for name, price in AWS_BASE_PRICES.items():
            assert price >= 0, f"{name} has negative price {price}"

    def test_known_services_present(self):
        expected = ["EC2", "Lambda", "S3", "RDS", "DynamoDB"]
        for svc in expected:
            assert svc in AWS_BASE_PRICES, f"Missing {svc}"


# ====================================================================
# _estimate_provider_cost()
# ====================================================================

class TestEstimateProviderCost:
    def test_aws_returns_base_price(self):
        assert _estimate_provider_cost("EC2", "Compute", 150.0, "aws") == 150.0

    def test_azure_is_cheaper_than_aws(self):
        azure = _estimate_provider_cost("EC2", "Compute", 150.0, "azure")
        assert azure < 150.0

    def test_gcp_is_cheaper_than_aws(self):
        gcp = _estimate_provider_cost("EC2", "Compute", 150.0, "gcp")
        assert gcp < 150.0

    def test_unknown_provider_returns_base(self):
        result = _estimate_provider_cost("EC2", "Compute", 150.0, "oracle")
        assert result == 150.0

    def test_zero_base_price(self):
        assert _estimate_provider_cost("IAM", "Security", 0.0, "azure") == 0.0

    def test_category_adjustment_applied(self):
        # Monitoring has 0.80 Azure adjustment vs default 1.0
        monitoring = _estimate_provider_cost("CloudWatch", "Monitoring", 100.0, "azure")
        general = _estimate_provider_cost("X", "UnknownCat", 100.0, "azure")
        assert monitoring < general  # Monitoring adjustment should make it cheaper


# ====================================================================
# generate_cost_comparison()
# ====================================================================

class TestGenerateCostComparison:
    def test_empty_analysis(self):
        result = generate_cost_comparison({})
        assert result["total_services"] == 0
        assert result["providers"]["aws"] == 0
        assert result["cheapest_provider"] == "N/A"

    def test_empty_mappings(self):
        result = generate_cost_comparison({"mappings": []})
        assert result["total_services"] == 0

    def test_single_service(self):
        analysis = {
            "mappings": [
                {"source_service": "EC2", "azure_service": "Virtual Machines",
                 "category": "Compute", "confidence": 0.95}
            ]
        }
        result = generate_cost_comparison(analysis)
        assert result["total_services"] == 1
        assert result["providers"]["aws"] > 0
        assert result["providers"]["azure"] > 0
        assert result["providers"]["gcp"] > 0
        assert len(result["services"]) == 1

    def test_aws_is_most_expensive(self):
        """With default ratios, AWS should be the most expensive."""
        analysis = {
            "mappings": [
                {"source_service": "EC2", "azure_service": "VM", "category": "Compute"},
                {"source_service": "S3", "azure_service": "Blob", "category": "Storage"},
            ]
        }
        result = generate_cost_comparison(analysis)
        assert result["providers"]["aws"] >= result["providers"]["azure"]
        assert result["providers"]["aws"] >= result["providers"]["gcp"]

    def test_output_structure(self):
        analysis = {
            "mappings": [
                {"source_service": "Lambda", "azure_service": "Functions", "category": "Compute"}
            ]
        }
        result = generate_cost_comparison(analysis)
        assert "providers" in result
        assert "services" in result
        assert "total_services" in result
        assert "cheapest_provider" in result
        assert "azure_savings_vs_aws_pct" in result
        assert "gcp_savings_vs_aws_pct" in result
        assert "summary" in result

    def test_service_entry_has_all_costs(self):
        analysis = {
            "mappings": [
                {"source_service": "RDS", "azure_service": "Azure SQL", "category": "Database"}
            ]
        }
        result = generate_cost_comparison(analysis)
        svc = result["services"][0]
        assert "aws_monthly" in svc
        assert "azure_monthly" in svc
        assert "gcp_monthly" in svc
        assert "cheapest_provider" in svc
        assert "azure_savings_vs_aws" in svc

    def test_deduplicates_services(self):
        analysis = {
            "mappings": [
                {"source_service": "S3", "azure_service": "Blob", "category": "Storage"},
                {"source_service": "S3", "azure_service": "Blob", "category": "Storage"},
            ]
        }
        result = generate_cost_comparison(analysis)
        assert result["total_services"] == 1

    def test_services_sorted_by_aws_cost(self):
        analysis = {
            "mappings": [
                {"source_service": "S3", "azure_service": "Blob", "category": "Storage"},
                {"source_service": "Redshift", "azure_service": "Synapse", "category": "Analytics"},
                {"source_service": "Lambda", "azure_service": "Functions", "category": "Compute"},
            ]
        }
        result = generate_cost_comparison(analysis)
        aws_costs = [s["aws_monthly"] for s in result["services"]]
        assert aws_costs == sorted(aws_costs, reverse=True)

    def test_savings_percentage_positive(self):
        """Azure and GCP should show positive savings vs AWS."""
        analysis = {
            "mappings": [
                {"source_service": "EC2", "azure_service": "VM", "category": "Compute"}
            ]
        }
        result = generate_cost_comparison(analysis)
        assert result["azure_savings_vs_aws_pct"] > 0
        assert result["gcp_savings_vs_aws_pct"] > 0

    def test_summary_contains_provider_names(self):
        analysis = {
            "mappings": [
                {"source_service": "S3", "azure_service": "Blob", "category": "Storage"}
            ]
        }
        result = generate_cost_comparison(analysis)
        assert "AWS" in result["summary"]
        assert "Azure" in result["summary"]
        assert "GCP" in result["summary"]

    def test_unknown_service_gets_default_price(self):
        analysis = {
            "mappings": [
                {"source_service": "UnknownThing", "azure_service": "Something",
                 "category": "General"}
            ]
        }
        result = generate_cost_comparison(analysis)
        assert result["total_services"] == 1
        assert result["providers"]["aws"] > 0  # default $50
