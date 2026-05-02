"""Tests for customer-facing architecture package exports."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from architecture_package import (
    build_customer_intent_profile,
    generate_architecture_package,
)
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
    assert "Target Topology" in content
    assert "DR Topology" in content
    assert "Customer Intent" in content
    assert "East US" in content
    assert 'id="a-primary"' in content
    assert 'id="a-dr"' in content
    assert 'marker-end="url(#a)"' not in content


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
    assert "Target Topology" in data["content"]


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