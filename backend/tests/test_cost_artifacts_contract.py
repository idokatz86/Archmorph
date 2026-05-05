"""Contract tests for generated cost artifacts (#703)."""

from __future__ import annotations

import copy
import csv
import json
from decimal import Decimal
from pathlib import Path

import pytest

from main import SESSION_STORE


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "cost_estimate_contract.json"
DIAGRAM_ID = "diag-cost-contract"


@pytest.fixture()
def cost_contract_fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def cost_contract_session(monkeypatch, cost_contract_fixture):
    SESSION_STORE.clear()
    SESSION_STORE[DIAGRAM_ID] = {
        "diagram_id": DIAGRAM_ID,
        "mappings": [
            {
                "source_service": "Lambda",
                "source_provider": "aws",
                "azure_service": "Azure Functions",
                "confidence": 0.95,
            },
            {
                "source_service": "Amazon S3",
                "source_provider": "aws",
                "azure_service": "Azure Blob Storage",
                "confidence": 0.95,
            },
        ],
        "iac_parameters": {
            "deploy_region": "westeurope",
            "sku_strategy": "Balanced",
        },
    }

    def estimate_cost_fixture(mappings, *, region="westeurope", sku_strategy="Balanced"):
        assert len(mappings) == 2
        assert region == "westeurope"
        assert sku_strategy == "Balanced"
        return copy.deepcopy(cost_contract_fixture)

    monkeypatch.setattr(
        "routers.insights.estimate_services_cost",
        estimate_cost_fixture,
    )
    monkeypatch.setattr(
        "cost_assumptions.estimate_services_cost",
        estimate_cost_fixture,
    )
    yield SESSION_STORE[DIAGRAM_ID]
    SESSION_STORE.clear()


def _normalise_cost_contract(payload: dict) -> dict:
    services = sorted(payload["services"], key=lambda item: item["service"])
    return {
        "diagram_id": payload["diagram_id"],
        "currency": payload["currency"],
        "region": payload["region"],
        "arm_region": payload["arm_region"],
        "sku_strategy": payload["sku_strategy"],
        "pricing_source": payload["pricing_source"],
        "service_count": payload["service_count"],
        "total_monthly_estimate": payload["total_monthly_estimate"],
        "services": [
            {
                "service": service["service"],
                "sku": service["sku"],
                "meter": service["meter"],
                "category": service["category"],
                "monthly_low": service["monthly_low"],
                "monthly_high": service["monthly_high"],
                "monthly_estimate": service["monthly_estimate"],
                "price_source": service["price_source"],
                "base_price_usd": service["base_price_usd"],
                "hourly_rate_usd": service["hourly_rate_usd"],
                "sku_multiplier": service["sku_multiplier"],
                "assumptions": service["assumptions"],
                "formula": service["formula"],
            }
            for service in services
        ],
    }


def _decimal(value: str) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"))


def test_cost_estimate_json_contract_matches_snapshot(
    test_client,
    cost_contract_session,
    cost_contract_fixture,
):
    response = test_client.get(f"/api/diagrams/{DIAGRAM_ID}/cost-estimate")

    assert response.status_code == 200
    expected = {"diagram_id": DIAGRAM_ID, **cost_contract_fixture}
    assert _normalise_cost_contract(response.json()) == _normalise_cost_contract(expected)


def test_cost_estimate_json_contract_fields(test_client, cost_contract_session):
    response = test_client.get(f"/api/diagrams/{DIAGRAM_ID}/cost-estimate")

    assert response.status_code == 200
    payload = response.json()
    assert payload["diagram_id"] == DIAGRAM_ID
    assert payload["currency"] == "USD"
    assert payload["region"] == "West Europe"
    assert payload["arm_region"] == "westeurope"
    assert payload["sku_strategy"] == "Balanced"
    assert payload["service_count"] == len(payload["services"])

    service_low_total = Decimal("0.00")
    service_high_total = Decimal("0.00")
    for service in payload["services"]:
        for field in (
            "service",
            "sku",
            "meter",
            "category",
            "monthly_low",
            "monthly_high",
            "monthly_estimate",
            "price_source",
            "base_price_usd",
            "hourly_rate_usd",
            "sku_multiplier",
            "assumptions",
            "formula",
        ):
            assert field in service
        assert service["monthly_low"] <= service["monthly_estimate"] <= service["monthly_high"]
        service_low_total += Decimal(str(service["monthly_low"]))
        service_high_total += Decimal(str(service["monthly_high"]))

    total = payload["total_monthly_estimate"]
    assert Decimal(str(total["low"])) == service_low_total
    assert Decimal(str(total["high"])) == service_high_total


def test_cost_csv_export_contract_header_rows_and_total(test_client, cost_contract_session):
    response = test_client.get(f"/api/diagrams/{DIAGRAM_ID}/cost-estimate/export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(response.text.splitlines()))
    assert rows[0] == [
        "Service",
        "SKU",
        "Instances",
        "Reserved Term",
        "Monthly Low (USD)",
        "Monthly High (USD)",
        "RI Savings (USD)",
        "Total Mid (USD)",
    ]
    assert rows[1][0:4] == ["Azure Functions", "Consumption", "1", "none"]
    assert rows[2][0:4] == ["Azure Blob Storage", "Hot LRS", "1", "none"]
    assert rows[-1][0] == "TOTAL"
    assert _decimal(rows[-1][4]) == Decimal("15.00")
    assert _decimal(rows[-1][5]) == Decimal("35.00")
    assert _decimal(rows[-1][6]) == Decimal("0.00")
    assert _decimal(rows[-1][7]) == Decimal("25.00")


def test_cost_csv_export_totals_reconcile_with_rows(test_client, cost_contract_session):
    response = test_client.get(f"/api/diagrams/{DIAGRAM_ID}/cost-estimate/export")

    assert response.status_code == 200
    rows = list(csv.DictReader(response.text.splitlines()))
    service_rows = [row for row in rows if row["Service"] != "TOTAL"]
    total_row = rows[-1]

    low_total = sum(_decimal(row["Monthly Low (USD)"]) for row in service_rows)
    high_total = sum(_decimal(row["Monthly High (USD)"]) for row in service_rows)
    savings_total = sum(_decimal(row["RI Savings (USD)"]) for row in service_rows)
    mid_total = ((low_total + high_total) / Decimal("2")).quantize(Decimal("0.01"))

    assert _decimal(total_row["Monthly Low (USD)"]) == low_total
    assert _decimal(total_row["Monthly High (USD)"]) == high_total
    assert _decimal(total_row["RI Savings (USD)"]) == savings_total
    assert _decimal(total_row["Total Mid (USD)"]) == mid_total


def test_cost_csv_export_applies_configured_overrides(test_client, cost_contract_session):
    cost_contract_session["_cost_overrides"] = {
        "Azure Functions": {
            "instance_count": 3,
            "sku": "Premium",
            "reserved_term": "1yr",
        }
    }
    SESSION_STORE[DIAGRAM_ID] = cost_contract_session

    response = test_client.get(f"/api/diagrams/{DIAGRAM_ID}/cost-estimate/export")

    assert response.status_code == 200
    rows = list(csv.DictReader(response.text.splitlines()))
    functions_row = next(row for row in rows if row["Service"] == "Azure Functions")
    total_row = rows[-1]

    assert functions_row["SKU"] == "Premium"
    assert functions_row["Instances"] == "3"
    assert functions_row["Reserved Term"] == "1yr"
    assert _decimal(functions_row["Monthly Low (USD)"]) == Decimal("21.00")
    assert _decimal(functions_row["Monthly High (USD)"]) == Decimal("42.00")
    assert _decimal(functions_row["RI Savings (USD)"]) == Decimal("13.50")
    assert _decimal(functions_row["Total Mid (USD)"]) == Decimal("31.50")
    assert _decimal(total_row["Monthly Low (USD)"]) == Decimal("26.00")
    assert _decimal(total_row["Monthly High (USD)"]) == Decimal("57.00")
    assert _decimal(total_row["RI Savings (USD)"]) == Decimal("13.50")
    assert _decimal(total_row["Total Mid (USD)"]) == Decimal("41.50")


def test_cost_assumptions_endpoint_publishes_reviewable_artifact(test_client, cost_contract_session):
    response = test_client.get(f"/api/diagrams/{DIAGRAM_ID}/cost-assumptions")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "cost-assumptions/v1"
    assert payload["analysis_id"] == DIAGRAM_ID
    assert payload["directional_notice"].startswith("Cost estimates are directional")
    assert payload["total_monthly_estimate"] == {"low": 15.0, "high": 35.0}
    assert payload["missing_cost_warnings"] == []

    functions = next(service for service in payload["services"] if service["service"] == "Azure Functions")
    assert functions["source_service"] == "Lambda"
    assert functions["region"] == "West Europe"
    assert functions["sku"] == "Consumption"
    assert functions["quantity"] == 1
    assert functions["quantity_assumption"] == "1 instance(s) from estimator defaults unless overridden by the user."
    assert functions["reservation_assumption"] == "Pay-as-you-go; no reserved capacity unless configured by the user."
    assert functions["data_transfer_assumption"].startswith("Not specified")


def test_cost_assumptions_endpoint_applies_overrides(test_client, cost_contract_session):
    cost_contract_session["_cost_overrides"] = {
        "Azure Blob Storage": {
            "instance_count": 2,
            "sku": "Cool LRS",
            "reserved_term": "3yr",
        }
    }
    SESSION_STORE[DIAGRAM_ID] = cost_contract_session

    response = test_client.get(f"/api/diagrams/{DIAGRAM_ID}/cost-assumptions")

    assert response.status_code == 200
    payload = response.json()
    storage = next(service for service in payload["services"] if service["service"] == "Azure Blob Storage")
    assert storage["sku"] == "Cool LRS"
    assert storage["sku_pricing_note"].startswith("User-selected SKU label")
    assert storage["quantity"] == 2
    assert storage["quantity_assumption"] == "2 instance(s) configured by the user."
    assert storage["reservation_assumption"] == "Reserved capacity applied: 3yr."
    assert storage["monthly_low"] == 5.0
    assert storage["monthly_high"] == 15.0
    assert storage["monthly_estimate"] == 10.0


def test_cost_assumptions_endpoint_reuses_cached_estimate(monkeypatch, test_client, cost_contract_session, cost_contract_fixture):
    cached = copy.deepcopy(cost_contract_fixture)
    cached["services"][0]["monthly_low"] = 12.0
    cached["services"][0]["monthly_high"] = 24.0
    cached["services"][0]["monthly_estimate"] = 18.0
    cost_contract_session["_cached_cost_estimate"] = cached
    SESSION_STORE[DIAGRAM_ID] = cost_contract_session

    def fail_live_pricing(*_args, **_kwargs):
        raise AssertionError("cost assumptions endpoint should reuse cached cost estimates")

    monkeypatch.setattr("cost_assumptions.estimate_services_cost", fail_live_pricing)

    response = test_client.get(f"/api/diagrams/{DIAGRAM_ID}/cost-assumptions")

    assert response.status_code == 200
    payload = response.json()
    functions = next(service for service in payload["services"] if service["service"] == "Azure Functions")
    assert functions["monthly_low"] == 12.0
    assert functions["monthly_high"] == 24.0
    assert functions["monthly_estimate"] == 18.0


def test_cost_assumptions_endpoint_reprices_stale_cached_region(test_client, cost_contract_session, cost_contract_fixture):
    stale = copy.deepcopy(cost_contract_fixture)
    stale["arm_region"] = "eastus"
    stale["region"] = "East US"
    stale["services"][0]["monthly_low"] = 999.0
    cost_contract_session["_cached_cost_estimate"] = stale
    SESSION_STORE[DIAGRAM_ID] = cost_contract_session

    response = test_client.get(f"/api/diagrams/{DIAGRAM_ID}/cost-assumptions")

    assert response.status_code == 200
    payload = response.json()
    assert payload["arm_region"] == "westeurope"
    assert payload["cache_age_days"] is None
    assert SESSION_STORE[DIAGRAM_ID]["_cached_cost_estimate"]["arm_region"] == "westeurope"
    assert SESSION_STORE[DIAGRAM_ID]["_cached_cost_estimate"]["cache_age_days"] is None
    functions = next(service for service in payload["services"] if service["service"] == "Azure Functions")
    assert functions["monthly_low"] == 10.0


def test_cost_assumptions_endpoint_reuses_cached_estimate_with_case_insensitive_sku_strategy(
    monkeypatch,
    test_client,
    cost_contract_session,
    cost_contract_fixture,
):
    cached = copy.deepcopy(cost_contract_fixture)
    cached["sku_strategy"] = "balanced"
    cached["services"][0]["monthly_low"] = 12.0
    cost_contract_session["_cached_cost_estimate"] = cached
    SESSION_STORE[DIAGRAM_ID] = cost_contract_session

    def fail_live_pricing(*_args, **_kwargs):
        raise AssertionError("case-normalized SKU strategy should reuse compatible cached estimates")

    monkeypatch.setattr("cost_assumptions.estimate_services_cost", fail_live_pricing)

    response = test_client.get(f"/api/diagrams/{DIAGRAM_ID}/cost-assumptions")

    assert response.status_code == 200
    functions = next(service for service in response.json()["services"] if service["service"] == "Azure Functions")
    assert functions["monthly_low"] == 12.0


def test_cost_assumptions_endpoint_has_openapi_schema(test_client):
    response = test_client.get("/openapi.json")

    assert response.status_code == 200
    operation = response.json()["paths"]["/api/diagrams/{diagram_id}/cost-assumptions"]["get"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/CostAssumptionsResponse")
    cache_age_schema = response.json()["components"]["schemas"]["CostAssumptionsResponse"]["properties"]["cache_age_days"]
    assert cache_age_schema == {"anyOf": [{"type": "number"}, {"type": "null"}], "title": "Cache Age Days"}


def test_cost_assumptions_builder_flags_missing_prices(cost_contract_fixture):
    from cost_assumptions import build_cost_assumptions_artifact

    cost_estimate = {
        **cost_contract_fixture,
        "services": [
            {
                "service": "Unmapped Mainframe Queue",
                "sku": "Default tier",
                "meter": "",
                "category": "Integration",
                "monthly_low": 0,
                "monthly_high": 0,
                "monthly_estimate": 0,
                "price_source": "built-in estimate",
                "base_price_usd": 0,
                "hourly_rate_usd": 0,
                "sku_multiplier": 1,
                "assumptions": ["No pricing data available for this service"],
                "formula": "Pricing not available - use Azure Pricing Calculator",
            }
        ],
    }
    analysis = {
        "analysis_id": "missing-price-test",
        "mappings": [{"source_service": "Legacy MQ", "azure_service": "Unmapped Mainframe Queue"}],
    }

    artifact = build_cost_assumptions_artifact(analysis, cost_estimate=cost_estimate)

    assert artifact["missing_cost_warnings"] == [
        "Unmapped Mainframe Queue: no Azure Retail Prices API or built-in price match; verify manually."
    ]
    assert artifact["services"][0]["source_service"] == "Legacy MQ"


def test_cost_assumptions_builder_uses_cached_estimate_and_applies_overrides(monkeypatch, cost_contract_fixture):
    from cost_assumptions import build_cost_assumptions_artifact

    def fail_live_pricing(*_args, **_kwargs):
        raise AssertionError("package export should reuse cached cost estimates")

    monkeypatch.setattr("cost_assumptions.estimate_services_cost", fail_live_pricing)
    analysis = {
        "analysis_id": "cached-cost-test",
        "mappings": [
            {"source_service": "Lambda", "azure_service": "Azure Functions"},
            {"source_service": "Queue A", "azure_service": "Azure Service Bus"},
            {"source_service": "Queue B", "azure_service": "Azure Service Bus"},
        ],
        "_cached_cost_estimate": {
            **cost_contract_fixture,
            "services": [
                *cost_contract_fixture["services"],
                {
                    "service": "Azure Service Bus",
                    "sku": "Standard",
                    "meter": "Operations",
                    "category": "Integration",
                    "monthly_low": 8.0,
                    "monthly_high": 12.0,
                    "monthly_estimate": 10.0,
                    "price_source": "Azure Retail Prices API",
                    "base_price_usd": 10.0,
                    "hourly_rate_usd": 0.0137,
                    "sku_multiplier": 1.0,
                    "assumptions": ["Region: westeurope", "1M operations/month"],
                    "formula": "Standard tier operations estimate",
                },
            ],
        },
        "_cost_overrides": {
            "Azure Functions": {"instance_count": 2, "sku": "Premium", "reserved_term": "1yr"}
        },
    }

    artifact = build_cost_assumptions_artifact(analysis)

    functions = next(service for service in artifact["services"] if service["service"] == "Azure Functions")
    assert functions["sku"] == "Premium"
    assert functions["quantity"] == 2
    assert functions["quantity_assumption"] == "2 instance(s) configured by the user."
    assert functions["reservation_assumption"] == "Reserved capacity applied: 1yr."
    assert functions["monthly_low"] == 14.0
    assert functions["monthly_high"] == 28.0

    service_bus = next(service for service in artifact["services"] if service["service"] == "Azure Service Bus")
    assert service_bus["source_service"] == "Queue A"
    assert service_bus["source_services"] == ["Queue A", "Queue B"]