"""Tests for CAF/AVM Azure Landing Zone profile defaults (#675)."""

from __future__ import annotations

import json

from alz_profile import ALZ_PROFILE_SCHEMA_VERSION, build_alz_profile
from architecture_package import generate_architecture_package
from iac_scaffold import generate_scaffold


ALZ_ANALYSIS = {
    "title": "ALZ Profile Fixture",
    "source_provider": "aws",
    "dr_mode": "active-standby",
    "regions": [
        {"name": "East US", "role": "primary", "traffic_pct": 100},
        {"name": "West US 3", "role": "standby", "traffic_pct": 0},
    ],
    "mappings": [
        {"source_service": "ALB", "azure_service": "Application Gateway", "category": "Networking", "confidence": 0.96},
        {"source_service": "RDS", "azure_service": "Azure SQL", "category": "Database", "confidence": 0.91},
        {"source_service": "CloudWatch", "azure_service": "Log Analytics", "category": "Monitoring", "confidence": 0.9},
    ],
    "guided_answers": {
        "env_target": "Production",
        "arch_deploy_region": "East US",
        "sec_network_isolation": "Private endpoints",
        "sec_compliance": "PCI DSS",
    },
}


def test_alz_profile_contract_has_caf_avm_defaults():
    profile = build_alz_profile(ALZ_ANALYSIS)

    assert profile["schema_version"] == ALZ_PROFILE_SCHEMA_VERSION
    assert profile["name"] == "caf-avm-baseline"
    assert profile["networking"]["topology"] == "hub-spoke"
    assert "private endpoints" in profile["networking"]["private_endpoints"].lower()
    assert profile["identity"]["managed_identity"].startswith("system-assigned")
    assert profile["monitoring"]["retention_days"] == 90
    assert "Require diagnostic settings" in profile["policy"]["initiatives"]
    assert "landingZone" in profile["tagging"]["required_tags"]
    assert profile["tagging"]["defaults"]["criticality"] == "mission-critical"
    assert profile["avm"]["versioning"] == "pin module/provider versions and upgrade deliberately"
    assert profile["tradeoffs"]


def test_iac_scaffold_emits_alz_profile_and_caf_tags():
    files = generate_scaffold(ALZ_ANALYSIS, {"project_name": "alz-app", "region": "eastus"})
    profile = json.loads(files["terraform/alz-profile.json"])

    assert profile["schema_version"] == ALZ_PROFILE_SCHEMA_VERSION
    assert profile["name"] == "caf-avm-baseline"
    assert profile["dr"]["mode"] == "active-standby"

    prod_tfvars = files["terraform/environments/prod/terraform.tfvars"]
    assert 'criticality         = "mission-critical"' in prod_tfvars
    assert 'data_classification = "internal"' in prod_tfvars

    env_main = files["terraform/environments/prod/main.tf"]
    assert 'landingZone        = "caf-avm-baseline"' in env_main
    assert "costCenter" in env_main

    networking_main = files["terraform/modules/networking/main.tf"]
    assert 'landingZone        = "caf-avm-baseline"' in networking_main
    assert "dataClassification" in networking_main


def test_architecture_package_names_alz_assumptions_and_limitations():
    result = generate_architecture_package(ALZ_ANALYSIS, format="html", analysis_id="alz-profile")

    assert result["manifest"]["alz_profile"]["schema_version"] == ALZ_PROFILE_SCHEMA_VERSION
    assert result["manifest"]["alz_profile"]["name"] == "caf-avm-baseline"
    assert "Name the CAF/AVM landing zone assumptions" in result["content"]
    assert "Review CAF/AVM landing zone profile" in result["content"]
    assert "caf-avm-baseline" in result["content"]