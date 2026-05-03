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