"""Tests for source-to-Azure IaC traceability maps (#670)."""

from __future__ import annotations

import copy
import json
from unittest.mock import MagicMock, patch

from architecture_package import generate_architecture_package
from hld_generator import generate_hld, generate_hld_markdown
from iac_scaffold import generate_scaffold
from traceability_map import TRACEABILITY_SCHEMA_VERSION, build_traceability_map


TRACE_ANALYSIS = {
    "title": "Traceability Fixture",
    "source_provider": "aws",
    "zones": [{"id": 1, "name": "edge", "number": 1, "services": []}],
    "mappings": [
        {
            "source_service": "ALB",
            "source_provider": "aws",
            "azure_service": "Application Gateway",
            "category": "Networking",
            "confidence": 0.96,
        },
        {
            "source_service": "EKS",
            "source_provider": "aws",
            "azure_service": "AKS",
            "category": "Containers",
            "confidence": 0.94,
        },
    ],
    "guided_answers": {
        "env_target": "Production",
        "arch_deploy_region": "East US",
        "sec_network_isolation": "Private endpoints",
    },
}


def test_traceability_map_schema_and_stable_trace_ids():
    trace_map = build_traceability_map(TRACE_ANALYSIS)

    assert trace_map["schema_version"] == TRACEABILITY_SCHEMA_VERSION
    trace_ids = [entry["trace_id"] for entry in trace_map["entries"]]
    assert "trace-4295818efa60" in trace_ids
    assert "trace-93d01d39661b" in trace_ids
    assert trace_ids == [entry["trace_id"] for entry in build_traceability_map(copy.deepcopy(TRACE_ANALYSIS))["entries"]]


def test_traceability_map_links_source_azure_iac_and_package_node():
    trace_map = build_traceability_map(TRACE_ANALYSIS)
    alb_entry = next(entry for entry in trace_map["entries"] if entry["source_service"] == "ALB")

    assert alb_entry["azure_service"] == "Application Gateway"
    assert alb_entry["confidence"] == 0.96
    assert alb_entry["migration_effort"] == "low"
    assert alb_entry["customer_intent_influence"]["region"] == "East US"
    assert alb_entry["generated_iac_resources"] == [
        {
            "format": "terraform",
            "module": "networking",
            "file": "terraform/modules/networking/main.tf",
            "resource_type": "azurerm_application_gateway",
            "resource_name": "application_gateway",
            "address": "module.networking.azurerm_application_gateway.application_gateway",
        }
    ]
    assert alb_entry["package_diagram_node"] == {
        "id": "diagram-node-trace-4295818efa60",
        "label": "Application Gateway",
        "zone": "Networking",
    }


def test_iac_scaffold_emits_traceability_artifact():
    files = generate_scaffold(TRACE_ANALYSIS, {"project_name": "trace-app", "region": "eastus"})
    trace_map = json.loads(files["terraform/traceability-map.json"])

    assert trace_map["schema_version"] == TRACEABILITY_SCHEMA_VERSION
    assert any(entry["trace_id"] == "trace-4295818efa60" for entry in trace_map["entries"])
    assert "module.networking.azurerm_application_gateway.application_gateway" in files["terraform/traceability-map.json"]


def test_architecture_package_manifest_and_limitations_include_traceability_evidence():
    result = generate_architecture_package(TRACE_ANALYSIS, format="html", analysis_id="trace-package")

    trace_map = result["manifest"]["traceability_map"]
    assert trace_map["schema_version"] == TRACEABILITY_SCHEMA_VERSION
    assert any(entry["trace_id"] == "trace-4295818efa60" for entry in trace_map["entries"])
    assert "Review IaC traceability evidence" in result["content"]
    assert "trace-4295818efa60" in result["content"]


@patch("hld_generator.cached_chat_completion")
def test_hld_output_includes_traceability_evidence(mock_cached):
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = json.dumps({
        "title": "Traceability HLD",
        "executive_summary": "summary",
        "next_steps": ["review traceability"],
    })
    mock_cached.return_value = response

    hld = generate_hld(TRACE_ANALYSIS)
    markdown = generate_hld_markdown(hld)

    assert hld["_metadata"]["traceability_map"]["schema_version"] == TRACEABILITY_SCHEMA_VERSION
    assert "Source-to-Azure IaC Traceability" in markdown
    assert "trace-4295818efa60" in markdown
    assert "module.networking.azurerm_application_gateway.application_gateway" in markdown