"""Tests for customer-facing architecture package exports."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from architecture_package import generate_architecture_package
from customer_intent import build_customer_intent_profile
from routers.shared import SESSION_STORE


SAMPLE_ANALYSIS: dict = {
    "title": "Package Test",
    "source_provider": "AWS",
    "target_provider": "azure",
    "zones": [{"id": 1, "name": "web-tier", "number": 1, "services": []}],
    "mappings": [
        {"source_service": "ALB", "azure_service": "Application Gateway", "category": "Networking", "confidence": 0.96},
        {"source_service": "EKS", "azure_service": "AKS", "category": "Containers", "confidence": 0.94},
        {"source_service": "RDS", "azure_service": "Azure SQL", "category": "Database", "confidence": 0.88},
        {"source_service": "CloudWatch", "azure_service": "Azure Monitor", "category": "Monitoring", "confidence": 0.92},
    ],
    "guided_answers": {
        "env_target": "Production",
        "arch_deploy_region": "East US",
        "arch_ha": "Multi-region active-passive (99.99 %)",
        "arch_dr_rto": "<15 min",
        "sec_compliance": ["SOC 2", "GDPR"],
        "sec_network_isolation": "Full private endpoints",
    },
}


GCP_ANALYSIS: dict = {
    "title": "GCP Package Test",
    "source_provider": "gcp",
    "target_provider": "azure",
    "source_filename": "gcp-topology.drawio",
    "zones": [{"id": 1, "name": "gcp-web-tier", "number": 1, "services": []}],
    "mappings": [
        {"source_service": "Cloud Load Balancing", "azure_service": "Application Gateway", "category": "Networking", "confidence": 0.93},
        {"source_service": "GKE", "azure_service": "AKS", "category": "Containers", "confidence": 0.95},
        {"source_service": "Cloud SQL", "azure_service": "Azure SQL", "category": "Database", "confidence": 0.91},
        {"source_service": "Pub/Sub", "azure_service": "Event Hubs", "category": "Messaging", "confidence": 0.86},
    ],
    "guided_answers": {
        "env_target": "Production",
        "arch_deploy_region": "West US 3",
        "arch_ha": "Multi-region active-passive (99.99 %)",
        "arch_dr_rto": "<30 min",
        "sec_compliance": ["HIPAA"],
    },
}


MIXED_ANALYSIS: dict = {
    "title": "Mixed Source Package Test",
    "source_provider": "aws",
    "source_providers": ["aws", "gcp"],
    "target_provider": "azure",
    "source_filename": "mixed-estate.pdf",
    "zones": [{"id": 1, "name": "mixed-platform", "number": 1, "services": []}],
    "mappings": [
        {"source_provider": "aws", "source_service": "EKS", "azure_service": "AKS", "category": "Containers", "confidence": 0.94},
        {"source_provider": "aws", "source_service": "RDS", "azure_service": "Azure SQL", "category": "Database", "confidence": 0.89},
        {"source_provider": "gcp", "source_service": "Pub/Sub", "azure_service": "Event Hubs", "category": "Messaging", "confidence": 0.87},
        {"source_provider": "gcp", "source_service": "Cloud Storage", "azure_service": "Blob Storage", "category": "Storage", "confidence": 0.9},
    ],
    "warnings": ["Mixed source estate requires source-owner validation before deployment."],
    "guided_answers": {
        "env_target": "Production",
        "arch_deploy_region": "East US",
        "arch_ha": "Multi-region active-passive (99.99 %)",
        "arch_dr_rto": "<1 hour",
        "sec_network_isolation": "Hub-spoke VNets with private endpoints",
    },
}


def test_customer_intent_profile_normalises_lists():
    profile = build_customer_intent_profile({"sec_compliance": ["SOC 2", "GDPR"]})
    assert profile["compliance"] == "SOC 2, GDPR"
    assert profile["environment"] == "Production"


def test_svg_package_is_parseable_xml():
    result = generate_architecture_package(SAMPLE_ANALYSIS, format="svg", diagram="primary")
    assert result["format"] == "architecture-package-svg"
    assert result["filename"].endswith(".svg")
    root = ET.fromstring(result["content"])
    assert root.tag.endswith("svg")


def test_html_package_contains_tabs_and_namespaced_svg_ids():
    result = generate_architecture_package(SAMPLE_ANALYSIS, format="html")
    content = result["content"]
    assert result["format"] == "architecture-package-html"
    assert result["filename"].endswith(".html")
    assert "Archmorph — Package Test Architecture Package" in content
    assert "A — Target Azure Topology" in content
    assert "B — DR Topology" in content
    assert "Customer Intent" in content
    assert "East US" in content
    assert "(empty)" not in content
    assert "data:image/svg+xml;base64" in content
    assert ">FD<" not in content
    assert ">AG<" not in content
    assert ">ST<" not in content
    assert ">AK<" not in content
    assert ">AF<" not in content
    assert ">DB<" not in content
    assert 'id="a-primary"' in content
    assert 'id="a-dr"' in content
    assert 'marker-end="url(#a)"' not in content


@pytest.mark.parametrize(
    ("analysis", "source_label", "expected_services"),
    [
        (SAMPLE_ANALYSIS, "AWS", ["Application Gateway", "AKS", "Azure SQL"]),
        (GCP_ANALYSIS, "GCP", ["Application Gateway", "AKS", "Event Hubs"]),
        (MIXED_ANALYSIS, "AWS/GCP", ["AKS", "Azure SQL", "Event Hubs", "Blob Storage"]),
    ],
)
def test_architecture_package_preserves_source_context_and_azure_target(
    analysis, source_label, expected_services
):
    result = generate_architecture_package(analysis, format="html")
    content = result["content"]

    assert f"Source: {source_label}" in content
    assert "Target: Azure" in content
    assert f"{source_label} → Azure" in content
    assert "A — Target Azure Topology" in content
    assert "B — DR Topology" in content
    assert "C — Talking Points" in content
    assert "D — Services Limitations" in content
    assert "Assumptions And Constraints" in content
    if analysis.get("source_filename"):
        assert str(analysis["source_filename"]) in content
    for service in expected_services:
        assert service in content


def test_mixed_architecture_package_surfaces_mixed_source_traceability():
    result = generate_architecture_package(MIXED_ANALYSIS, format="html")
    content = result["content"]

    assert "Source: AWS/GCP" in content
    assert "Mixed source estate requires source-owner validation before deployment." in content
    assert "mixed-estate.pdf" in content
    assert "Mixed Source Package Test — Target Azure Topology (AWS/GCP → Azure)" in content
    assert "Mixed Source Package Test — DR Azure Topology (AWS/GCP → Azure)" in content


@pytest.mark.parametrize("diagram", ["primary", "dr"])
def test_mixed_architecture_package_svg_outputs_are_parseable(diagram):
    result = generate_architecture_package(MIXED_ANALYSIS, format="svg", diagram=diagram)
    assert result["format"] == "architecture-package-svg"
    assert result["filename"].endswith(f"-{diagram}.svg")
    root = ET.fromstring(result["content"])
    assert root.tag.endswith("svg")
    assert f"Mixed Source Package Test — {'DR' if diagram == 'dr' else 'Target'} Azure Topology (AWS/GCP → Azure)" in result["content"]


def test_export_architecture_package_endpoint_returns_html(test_client):
    diagram_id = "package-endpoint-test"
    SESSION_STORE[diagram_id] = SAMPLE_ANALYSIS

    response = test_client.post(
        f"/api/diagrams/{diagram_id}/export-architecture-package?format=html"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["format"] == "architecture-package-html"
    assert data["filename"].endswith(".html")
    assert "A — Target Azure Topology" in data["content"]


def test_export_architecture_package_endpoint_returns_dr_svg(test_client):
    diagram_id = "package-endpoint-dr-test"
    SESSION_STORE[diagram_id] = SAMPLE_ANALYSIS

    response = test_client.post(
        f"/api/diagrams/{diagram_id}/export-architecture-package?format=svg&diagram=dr"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["format"] == "architecture-package-svg"
    assert data["filename"].endswith("-dr.svg")
    ET.fromstring(data["content"])