"""CAF/AVM-aligned Azure Landing Zone profile defaults."""

from __future__ import annotations

from typing import Any

from azure_landing_zone_schema import infer_dr_mode, infer_regions
from customer_intent import build_customer_intent_profile


ALZ_PROFILE_SCHEMA_VERSION = "azure-landing-zone-profile/v1"
ALZ_PROFILE_NAME = "caf-avm-baseline"


def build_alz_profile(analysis: dict[str, Any] | None) -> dict[str, Any]:
    """Return deterministic CAF/AVM landing-zone assumptions for generated outputs."""
    if not isinstance(analysis, dict):
        analysis = {}

    profile = _customer_profile(analysis)
    dr_mode = infer_dr_mode(analysis)
    regions = infer_regions(analysis, dr_variant="dr" if dr_mode != "single-region" else "primary")
    environment = profile.get("environment") or "Production"
    compliance = profile.get("compliance") or "Not specified"
    network_isolation = profile.get("network_isolation") or "Private endpoints where supported"

    return {
        "schema_version": ALZ_PROFILE_SCHEMA_VERSION,
        "name": ALZ_PROFILE_NAME,
        "architecture_style": "CAF enterprise-scale landing zone with AVM-compatible resource defaults",
        "networking": {
            "topology": "hub-spoke",
            "vnet_address_space": ["10.0.0.0/16"],
            "default_subnet_prefixes": ["10.0.1.0/24"],
            "private_endpoints": "private endpoints enabled for data, storage, key vault, and PaaS ingress where supported",
            "dns": "Azure Private DNS zones linked from hub networking",
            "egress": "Azure Firewall or customer-managed egress for enterprise workloads",
        },
        "identity": {
            "tenant": "single Microsoft Entra tenant",
            "rbac": "least-privilege Azure RBAC assignments at resource group or workload scope",
            "managed_identity": "system-assigned or user-assigned managed identities for workload resources",
            "key_vault": "Azure Key Vault with RBAC authorization and purge protection",
        },
        "monitoring": {
            "log_analytics": "central workspace",
            "retention_days": 90 if environment.lower() == "production" else 30,
            "diagnostic_settings": "enabled for supported resources",
            "app_insights": "enabled for application workloads",
        },
        "backup": {
            "soft_delete": "enabled for Key Vault and storage where supported",
            "database_protection": "geo-replication or backup policy required for production data tiers",
            "recovery_vault": "recommended for VM and file-share workloads",
        },
        "policy": {
            "initiatives": [
                "Azure Security Benchmark",
                "Allowed locations",
                "Require diagnostic settings",
                "Deny public network access where private endpoints are required",
            ],
            "mode": "audit in simple profiles, deny/remediate in enterprise profiles after owner review",
        },
        "tagging": {
            "required_tags": [
                "workload",
                "environment",
                "owner",
                "costCenter",
                "dataClassification",
                "criticality",
                "landingZone",
            ],
            "defaults": {
                "environment": environment,
                "landingZone": ALZ_PROFILE_NAME,
                "dataClassification": "confidential" if compliance != "Not specified" else "internal",
                "criticality": "mission-critical" if dr_mode != "single-region" else "standard",
            },
        },
        "dr": {
            "mode": dr_mode,
            "regions": regions,
            "assumption": "single-region baseline unless customer intent or source topology requires standby or active-active regions",
        },
        "customer_intent": {
            "environment": environment,
            "compliance": compliance,
            "network_isolation": network_isolation,
            "sku_strategy": profile.get("sku_strategy") or "balanced",
        },
        "avm": {
            "module_convention": "Azure Verified Modules resource modules where generated IaC is promoted beyond scaffold",
            "versioning": "pin module/provider versions and upgrade deliberately",
            "naming": "CAF-aligned abbreviations with workload/environment prefixes",
        },
        "tradeoffs": [
            "Small workloads may collapse hub, spoke, policy, and monitoring resources into one subscription/resource group to reduce delivery overhead.",
            "Enterprise workloads should keep shared networking, identity, policy, and monitoring in platform-owned scopes.",
            "Private endpoints improve isolation but add DNS, subnet, and operations complexity that must be owned explicitly.",
        ],
    }


def alz_profile_summary(analysis: dict[str, Any] | None) -> list[str]:
    """Return concise customer-safe ALZ profile statements."""
    profile = build_alz_profile(analysis)
    return [
        f"{profile['name']}: {profile['architecture_style']}",
        f"Networking: {profile['networking']['topology']} with {profile['networking']['private_endpoints']}",
        f"Identity: {profile['identity']['managed_identity']} and {profile['identity']['key_vault']}",
        f"Monitoring: {profile['monitoring']['log_analytics']} with {profile['monitoring']['retention_days']} day retention",
        f"DR: {profile['dr']['mode']} across {', '.join(region['name'] for region in profile['dr']['regions'])}",
    ]


def _customer_profile(analysis: dict[str, Any]) -> dict[str, str]:
    profile = analysis.get("customer_intent")
    if isinstance(profile, dict) and profile:
        return {str(key): str(value) for key, value in profile.items()}
    answers = analysis.get("guided_answers")
    if isinstance(answers, dict):
        return build_customer_intent_profile(answers)
    return {}