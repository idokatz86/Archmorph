"""
Archmorph — Azure Pricing Service Unit Tests
Tests for services/azure_pricing.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.azure_pricing import (
    get_region_options,
    display_to_arm,
    AZURE_REGIONS,
    ARM_TO_DISPLAY,
    _find_best_price_match,
    estimate_services_cost,
    SERVICE_PRICE_QUERIES,
)


# ====================================================================
# Region utilities
# ====================================================================

class TestRegionOptions:
    def test_returns_sorted_list(self):
        options = get_region_options()
        assert options == sorted(options)

    def test_includes_known_regions(self):
        options = get_region_options()
        assert "West Europe" in options
        assert "East US" in options
        assert "North Europe" in options

    def test_count_matches_dict(self):
        assert len(get_region_options()) == len(AZURE_REGIONS)


class TestDisplayToArm:
    def test_known_region(self):
        assert display_to_arm("West Europe") == "westeurope"

    def test_north_europe(self):
        assert display_to_arm("North Europe") == "northeurope"

    def test_east_us(self):
        assert display_to_arm("East US") == "eastus"

    def test_unknown_falls_back_to_westeurope(self):
        assert display_to_arm("Narnia") == "westeurope"

    def test_empty_string_falls_back(self):
        assert display_to_arm("") == "westeurope"

    def test_all_regions_have_arm_name(self):
        for display, arm in AZURE_REGIONS.items():
            assert display_to_arm(display) == arm

    def test_reverse_lookup_consistency(self):
        for display, arm in AZURE_REGIONS.items():
            assert ARM_TO_DISPLAY[arm] == display


# ====================================================================
# _find_best_price_match()
# ====================================================================

class TestFindBestPriceMatch:
    def test_exact_match(self):
        prices = {"Azure Blob Storage": 10.0, "Azure SQL": 50.0}
        assert _find_best_price_match("Azure Blob Storage", prices) == 10.0

    def test_prefix_match(self):
        prices = {"Azure Blob Storage": 10.0}
        # "Azure Blob Storage (Raw)" contains "Azure Blob Storage"
        result = _find_best_price_match("Azure Blob Storage (Raw)", prices)
        assert result == 10.0

    def test_partial_word_match(self):
        prices = {"Azure Virtual Machines": 100.0}
        # "Virtual Machines Scale Sets" shares >=2 words
        result = _find_best_price_match("Azure Virtual Machines Scale Sets", prices)
        assert result == 100.0

    def test_no_match_returns_zero(self):
        prices = {"Azure Blob Storage": 10.0}
        assert _find_best_price_match("Totally Unknown Service XYZ", prices) == 0

    def test_empty_prices_returns_zero(self):
        assert _find_best_price_match("Azure SQL", {}) == 0

    def test_fallback_to_service_price_queries(self):
        prices = {}  # No cached prices
        # Pick a known key from SERVICE_PRICE_QUERIES that has a fallback
        for key, query in SERVICE_PRICE_QUERIES.items():
            if query.get("fallback_monthly", 0) > 0:
                result = _find_best_price_match(key, prices)
                assert result == query["fallback_monthly"]
                break


# ====================================================================
# estimate_services_cost()
# ====================================================================

class TestEstimateServicesCost:
    @patch("services.azure_pricing.fetch_prices_for_region")
    def test_returns_expected_structure(self, mock_fetch):
        mock_fetch.return_value = {"Azure Functions": 20.0}
        mappings = [{"azure_service": "Azure Functions", "notes": "Zone 1"}]
        result = estimate_services_cost(mappings, region="westeurope")
        assert "total_monthly_estimate" in result
        assert "low" in result["total_monthly_estimate"]
        assert "high" in result["total_monthly_estimate"]
        assert result["currency"] == "USD"
        assert result["arm_region"] == "westeurope"
        assert len(result["services"]) == 1

    @patch("services.azure_pricing.fetch_prices_for_region")
    @patch("services.azure_pricing._load_cache")
    def test_partial_request_uses_global_scope_when_regional_cache_exists(self, mock_load_cache, mock_fetch):
        mock_load_cache.return_value = {
            "cached_at": 1_700_000_000,
            "prices_westeurope": {"Azure Functions": 20.0},
        }
        mock_fetch.return_value = {"Azure Functions": 20.0}
        mappings = [{"azure_service": "Azure Functions", "notes": "Zone 1"}]

        result = estimate_services_cost(mappings, region="westeurope")

        assert result["pricing_cache_scope"] == "global"
        assert result["pricing_cache_cached_at"] == 1_700_000_000

    @patch("services.azure_pricing.fetch_prices_for_region")
    def test_balanced_multiplier_is_1x(self, mock_fetch):
        mock_fetch.return_value = {"Azure Functions": 100.0}
        mappings = [{"azure_service": "Azure Functions"}]
        result = estimate_services_cost(mappings, sku_strategy="Balanced")
        svc = result["services"][0]
        assert svc["monthly_estimate"] == 100.0

    @patch("services.azure_pricing.fetch_prices_for_region")
    def test_cost_optimized_multiplier(self, mock_fetch):
        mock_fetch.return_value = {"Azure Functions": 100.0}
        mappings = [{"azure_service": "Azure Functions"}]
        result = estimate_services_cost(mappings, sku_strategy="Cost-optimized")
        svc = result["services"][0]
        assert svc["monthly_estimate"] == 65.0  # 100 * 0.65

    @patch("services.azure_pricing.fetch_prices_for_region")
    def test_enterprise_multiplier(self, mock_fetch):
        mock_fetch.return_value = {"Azure Functions": 100.0}
        mappings = [{"azure_service": "Azure Functions"}]
        result = estimate_services_cost(mappings, sku_strategy="Enterprise")
        svc = result["services"][0]
        assert svc["monthly_estimate"] == 220.0  # 100 * 2.2

    @patch("services.azure_pricing.fetch_prices_for_region")
    def test_deduplicates_services(self, mock_fetch):
        mock_fetch.return_value = {"Azure SQL": 50.0}
        mappings = [
            {"azure_service": "Azure SQL"},
            {"azure_service": "Azure SQL"},  # duplicate
        ]
        result = estimate_services_cost(mappings)
        assert result["service_count"] == 1

    @patch("services.azure_pricing.fetch_prices_for_region")
    def test_empty_mappings(self, mock_fetch):
        mock_fetch.return_value = {}
        result = estimate_services_cost([])
        assert result["service_count"] == 0
        assert result["total_monthly_estimate"]["low"] == 0
        assert result["total_monthly_estimate"]["high"] == 0

    @patch("services.azure_pricing.fetch_prices_for_region")
    def test_low_high_range(self, mock_fetch):
        mock_fetch.return_value = {"AKS": 200.0}
        mappings = [{"azure_service": "AKS"}]
        result = estimate_services_cost(mappings, sku_strategy="Balanced")
        svc = result["services"][0]
        assert svc["monthly_low"] == round(200.0 * 0.7, 2)
        assert svc["monthly_high"] == round(200.0 * 1.4, 2)

    @patch("services.azure_pricing.fetch_prices_for_region")
    def test_region_display_name(self, mock_fetch):
        mock_fetch.return_value = {}
        result = estimate_services_cost([], region="northeurope")
        assert result["region"] == "North Europe"

    @patch("services.azure_pricing.fetch_prices_for_region")
    def test_sorted_by_cost_descending(self, mock_fetch):
        mock_fetch.return_value = {"A": 10.0, "B": 50.0, "C": 30.0}
        mappings = [
            {"azure_service": "A"},
            {"azure_service": "B"},
            {"azure_service": "C"},
        ]
        result = estimate_services_cost(mappings, sku_strategy="Balanced")
        estimates = [s["monthly_estimate"] for s in result["services"]]
        assert estimates == sorted(estimates, reverse=True)

    def test_api_price_provenance_uses_successful_response_metadata(self, monkeypatch):
        import services.azure_pricing as pricing

        monkeypatch.setattr(pricing, "HAS_HTTPX", True)
        monkeypatch.setattr(pricing, "_load_cache", lambda **_kwargs: {})
        monkeypatch.setattr(
            pricing,
            "_fetch_price_from_api",
            lambda **_kwargs: {
                "retail_price": 0.1,
                "service_name": "Functions",
                "sku_name": "Consumption",
                "meter_name": "Execution Time",
                "currency_code": "USD",
            },
        )

        result = estimate_services_cost(
            [{"azure_service": "Azure Functions"}],
            persist_cache=False,
        )
        service = result["services"][0]

        assert service["price_source_id"] == "azure_retail_prices_api"
        assert service["price_source"] == "Azure Retail Prices API"
        assert service["price_evidence"]["returned_meter"] == "Execution Time"
        assert service["price_evidence"]["cache_age_days"] is None
        assert service["price_evidence"]["observed_at"]
        assert service["price_source_url"] == pricing.AZURE_PRICING_API

    def test_api_failure_is_not_reported_as_live_price(self, monkeypatch):
        import services.azure_pricing as pricing

        monkeypatch.setattr(pricing, "HAS_HTTPX", True)
        monkeypatch.setattr(pricing, "_load_cache", lambda **_kwargs: {})
        monkeypatch.setattr(pricing, "_fetch_price_from_api", lambda **_kwargs: None)

        result = estimate_services_cost(
            [{"azure_service": "Azure AI Vision"}],
            persist_cache=False,
        )
        service = result["services"][0]

        assert service["price_source_id"] == "built_in_estimate"
        assert service["price_source"] == "Built-in estimate"
        assert service["price_source_url"] is None

    def test_legacy_cache_without_provenance_is_not_attributed_to_api(self, monkeypatch):
        import time
        import services.azure_pricing as pricing

        monkeypatch.setattr(
            pricing,
            "_load_cache",
            lambda **_kwargs: {
                "cached_at": time.time(),
                "prices_westeurope": {"Azure Functions": 20.0},
            },
        )

        result = estimate_services_cost(
            [{"azure_service": "Azure Functions"}],
            persist_cache=False,
        )
        service = result["services"][0]

        assert service["price_source_id"] == "cached_source_unknown"
        assert service["price_source"] == "Cached value (source unverified)"
        assert service["price_source_url"] is None
        assert service["price_evidence"]["cache_age_days"] is None

    def test_cached_price_age_uses_its_observation_time(self, monkeypatch):
        import time
        import services.azure_pricing as pricing

        observed_at = (
            datetime.now(timezone.utc) - timedelta(days=2)
        ).isoformat().replace("+00:00", "Z")
        monkeypatch.setattr(
            pricing,
            "_load_cache",
            lambda **_kwargs: {
                "cached_at": time.time(),
                "prices_westeurope": {"Azure Functions": 20.0},
                "price_metadata_westeurope": {
                    "Azure Functions": {
                        "source": "azure_retail_prices_api",
                        "source_label": "Azure Retail Prices API",
                        "observed_at": observed_at,
                    },
                },
            },
        )

        result = estimate_services_cost(
            [{"azure_service": "Azure Functions"}],
            persist_cache=False,
        )

        assert result["services"][0]["price_evidence"]["cache_age_days"] == 2.0

    def test_uncached_region_does_not_inherit_other_region_cache_timestamp(self, monkeypatch):
        import time
        import services.azure_pricing as pricing

        cached_at = time.time() - 3 * 86400
        monkeypatch.setattr(
            pricing,
            "_load_cache",
            lambda **_kwargs: {
                "cached_at": cached_at,
                "prices_eastus": {"Azure Functions": 20.0},
            },
        )
        monkeypatch.setattr(pricing, "_fetch_price_from_api", lambda **_kwargs: None)

        fetched = pricing.fetch_prices_for_region(
            "westeurope",
            needed_services={"Azure Functions"},
            persist_cache=False,
        )
        result = estimate_services_cost(
            [{"azure_service": "Azure Functions"}],
            region="westeurope",
            persist_cache=False,
        )

        assert fetched.cache_timestamp is None
        assert result["pricing_cache_cached_at"] is None
        assert result["cache_age_days"] is None


# ====================================================================
# SERVICE_PRICE_QUERIES data quality
# ====================================================================

class TestServicePriceQueries:
    def test_not_empty(self):
        assert len(SERVICE_PRICE_QUERIES) > 40

    def test_all_have_service_name(self):
        for key, query in SERVICE_PRICE_QUERIES.items():
            assert "serviceName" in query or "productName" in query, (
                f"{key} missing serviceName/productName"
            )

    def test_all_have_fallback(self):
        for key, query in SERVICE_PRICE_QUERIES.items():
            assert "fallback_monthly" in query, f"{key} missing fallback_monthly"
            assert query["fallback_monthly"] >= 0

    def test_new_services_in_price_queries(self):
        """Issues #60-#67: new services should have pricing entries."""
        expected = [
            "Azure Arc-enabled Servers", "Azure Managed Grafana",
            "Azure Monitor (Prometheus)",
            "Azure AI Foundry", "Azure Edge Zones", "Microsoft Sentinel",
        ]
        for name in expected:
            assert name in SERVICE_PRICE_QUERIES, f"Missing pricing for {name}"

    def test_price_queries_count_increased(self):
        """After additions, should have more than the original ~40 entries."""
        assert len(SERVICE_PRICE_QUERIES) > 50
