"""Tests for customer-facing architecture package exports."""

from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from architecture_package import generate_architecture_package
from analysis_payload_bounds import MAX_ANALYSIS_LIST_ITEMS
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


HIGH_DR_ANALYSIS: dict = {
    **SAMPLE_ANALYSIS,
    "title": "High DR Package Test",
    "mappings": [
        {"source_service": "Route 53", "azure_service": "Azure Front Door", "category": "Networking", "confidence": 0.95},
        {"source_service": "RDS", "azure_service": "Azure SQL", "category": "Database", "confidence": 0.92},
        {"source_service": "S3", "azure_service": "Blob Storage", "category": "Storage", "confidence": 0.94},
        {"source_service": "IAM", "azure_service": "Entra ID", "category": "Identity", "confidence": 0.91},
        {"source_service": "KMS", "azure_service": "Key Vault", "category": "Secrets", "confidence": 0.91},
        {"source_service": "CloudWatch", "azure_service": "Azure Monitor", "category": "Monitoring", "confidence": 0.93},
        {"source_service": "AWS Backup", "azure_service": "Recovery Services vault", "category": "Backup", "confidence": 0.9},
    ],
    "guided_answers": {
        **SAMPLE_ANALYSIS["guided_answers"],
        "arch_ha": "Multi-region active-passive with geo-replication",
        "arch_dr_rpo": "<5 min",
        "ops_runbook_owner": "Platform operations owner with quarterly game day",
        "ops_failover_test": "Documented failover test and rollback runbook",
        "data_backup_policy": "Recovery Services vault backup with restore testing",
    },
}


LOW_DR_ANALYSIS: dict = {
    "title": "Low DR Package Test",
    "source_provider": "AWS",
    "target_provider": "azure",
    "zones": [{"id": 1, "name": "single-tier", "number": 1, "services": []}],
    "mappings": [
        {"source_service": "EC2", "azure_service": "Virtual Machines", "category": "Compute", "confidence": 0.83},
    ],
    "guided_answers": {
        "env_target": "Development",
        "arch_deploy_region": "East US",
        "arch_ha": "Single region",
    },
}


MIXED_ANALYSIS: dict = json.loads(
    (Path(__file__).parent / "fixtures" / "architecture_package_mixed_analysis.json").read_text(
        encoding="utf-8"
    )
)


@pytest.fixture(autouse=True)
def architecture_package_cost_fixture(monkeypatch):
    def estimate_cost_fixture(mappings, *, region="westeurope", sku_strategy="Balanced"):
        services = []
        for mapping in mappings:
            azure_service = mapping.get("azure_service") or mapping.get("target") or "Unknown service"
            services.append({
                "service": azure_service,
                "sku": "Standard",
                "meter": "Default meter",
                "category": mapping.get("category", "Other"),
                "monthly_low": 10.0,
                "monthly_high": 20.0,
                "monthly_estimate": 15.0,
                "price_source": "contract fixture",
                "base_price_usd": 15.0,
                "hourly_rate_usd": 0.0205,
                "sku_multiplier": 1.0,
                "assumptions": ["Region: East US", "Pay-as-you-go pricing"],
                "formula": f"{azure_service}: fixture monthly estimate",
            })
        return {
            "currency": "USD",
            "region": "East US",
            "arm_region": region,
            "sku_strategy": sku_strategy,
            "pricing_source": "contract fixture",
            "total_monthly_estimate": {"low": round(10.0 * len(services), 2), "high": round(20.0 * len(services), 2)},
            "services": services,
            "service_count": len(services),
            "cache_age_days": 0,
        }

    monkeypatch.setattr("cost_assumptions.estimate_services_cost", estimate_cost_fixture)


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
    metadata = root.find("{http://www.w3.org/2000/svg}metadata")
    assert metadata is not None
    assert metadata.attrib["id"] == "archmorph-artifact-manifest"


def test_architecture_package_html_manifest_contains_traceability_fields():
    result = generate_architecture_package(
        SAMPLE_ANALYSIS,
        format="html",
        analysis_id="analysis-676",
    )
    manifest = result["manifest"]

    assert manifest["schema_version"] == "architecture-package-manifest/v1"
    assert manifest["analysis_id"] == "analysis-676"
    assert manifest["source_provider"] == "AWS"
    assert manifest["target_provider"] == "Azure"
    assert manifest["export"] == {"format": "html", "diagram": "primary"}
    assert manifest["renderer"] == {"name": "architecture_package", "version": "1"}
    assert len(manifest["customer_intent_profile_hash"]) == 64
    assert result["filename"] in manifest["artifact_filenames"]
    assert {"source_service": "ALB", "azure_service": "Application Gateway", "category": "Networking", "confidence": 0.96} in manifest["mapping_references"]
    assert manifest["dr_readiness"]["schema_version"] == "dr-readiness-rubric/v1"
    assert len(manifest["dr_readiness"]["dimensions"]) == 7
    assert manifest["cost_assumptions"]["schema_version"] == "cost-assumptions/v1"
    assert manifest["cost_assumptions"]["directional_notice"].startswith("Cost estimates are directional")
    assert any(artifact["role"] == "cost-assumptions" for artifact in manifest["artifacts"])
    assert "archmorph-artifact-manifest" in result["content"]
    assert "archmorph-cost-assumptions" in result["content"]
    assert "five review outputs" in result["content"]
    assert "E · Cost Assumptions JSON" in result["content"]


def test_architecture_package_svg_manifest_tracks_selected_diagram():
    result = generate_architecture_package(
        SAMPLE_ANALYSIS,
        format="svg",
        diagram="dr",
        analysis_id="svg-analysis-676",
    )
    manifest = result["manifest"]

    assert manifest["analysis_id"] == "svg-analysis-676"
    assert manifest["export"] == {"format": "svg", "diagram": "dr"}
    assert result["filename"] in manifest["artifact_filenames"]
    assert manifest["artifacts"] == [
        {"filename": result["filename"], "role": "selected-topology", "format": "svg"},
        {"filename": "archmorph-web-tier-cost-assumptions.json", "role": "cost-assumptions", "format": "json"},
    ]
    assert "archmorph-artifact-manifest" in result["content"]


def test_architecture_package_manifest_redacts_secret_like_values():
    analysis = {
        **SAMPLE_ANALYSIS,
        "warnings": ["password=hunter2", "review customer RTO"],
        "unsupported_assumptions": ["token: abc123"],
        "mappings": [
            {
                "source_service": "Legacy API",
                "azure_service": "Container Apps",
                "category": "Compute",
                "confidence": 0.74,
                "credential_note": "super-secret",
            }
        ],
    }

    result = generate_architecture_package(analysis, format="html", analysis_id="privacy-test")
    manifest_text = json.dumps(result["manifest"])

    assert "hunter2" not in manifest_text
    assert "abc123" not in manifest_text
    assert "super-secret" not in manifest_text
    assert "hunter2" not in result["content"]


def test_html_package_contains_tabs_and_namespaced_svg_ids():
    result = generate_architecture_package(SAMPLE_ANALYSIS, format="html")
    content = result["content"]
    assert result["format"] == "architecture-package-html"
    assert result["filename"].endswith(".html")
    assert "Archmorph — Package Test Architecture Package" in content
    assert "A — Target Azure Topology" in content
    assert "B — DR Topology" in content
    assert "DR Readiness Rubric" in content
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
    ("analysis", "rating"),
    [
        (HIGH_DR_ANALYSIS, "High readiness"),
        (SAMPLE_ANALYSIS, "Medium readiness"),
        (LOW_DR_ANALYSIS, "Low readiness"),
    ],
)
def test_dr_readiness_rubric_scores_high_medium_and_low_examples(analysis, rating):
    result = generate_architecture_package(analysis, format="html")
    readiness = result["manifest"]["dr_readiness"]

    assert readiness["rating"] == rating
    if rating == "High readiness":
        assert readiness["score"] >= 80
    if rating == "Low readiness":
        assert readiness["score"] < 50
    assert "DR Readiness Rubric" in result["content"]
    assert rating in result["content"]
    assert {item["key"] for item in readiness["dimensions"]} == {
        "backup",
        "replication",
        "failover",
        "identity",
        "durability",
        "observability",
        "runbook",
    }


def test_dr_readiness_rubric_surfaces_missing_inputs_as_limitations():
    result = generate_architecture_package(LOW_DR_ANALYSIS, format="html")
    readiness = result["manifest"]["dr_readiness"]

    assert readiness["limitations"]
    assert any("Backup" in item for item in readiness["limitations"])
    assert any("Runbook" in item for item in readiness["limitations"])
    assert "No backup or restore input was provided" in result["content"]


def test_dr_readiness_rubric_ties_notes_to_detected_services_and_intent():
    result = generate_architecture_package(HIGH_DR_ANALYSIS, format="html")
    readiness = result["manifest"]["dr_readiness"]
    notes = " ".join(str(item["note"]) for item in readiness["dimensions"])

    assert "Multi-region active-passive" in readiness["summary"]
    assert "Azure SQL" in notes
    assert "Azure Front Door" in result["content"]


def test_dr_readiness_html_uses_sanitized_manifest_rubric():
    analysis = {
        **LOW_DR_ANALYSIS,
        "mappings": [
            {
                "source_service": "Sensitive Store",
                "azure_service": "Blob Storage",
                "category": "Storage",
                "confidence": 0.82,
            }
        ],
        "dr_readiness_inputs": {"backup_note": "token: restore-token"},
    }

    result = generate_architecture_package(analysis, format="html")
    manifest_text = json.dumps(result["manifest"])

    assert "restore-token" not in manifest_text
    assert "restore-token" not in result["content"]
    assert "token: restore-token" not in result["content"]


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
    assert data["manifest"]["analysis_id"] == diagram_id


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
    assert data["manifest"]["analysis_id"] == diagram_id
    ET.fromstring(data["content"])


def test_export_architecture_package_rejects_oversized_analysis_with_413(test_client):
    diagram_id = "package-endpoint-oversized-test"
    SESSION_STORE[diagram_id] = {
        **SAMPLE_ANALYSIS,
        "tiers": {
            "app": [
                {"name": f"App Service {i}", "category": "Compute"}
                for i in range(MAX_ANALYSIS_LIST_ITEMS + 1)
            ]
        },
    }

    try:
        response = test_client.post(
            f"/api/diagrams/{diagram_id}/export-architecture-package?format=html"
        )
    finally:
        SESSION_STORE.delete(diagram_id)

    assert response.status_code == 413, response.text
    assert response.json()["error"]["details"] == {
        "field": "tiers.app",
        "count": MAX_ANALYSIS_LIST_ITEMS + 1,
        "limit": MAX_ANALYSIS_LIST_ITEMS,
    }