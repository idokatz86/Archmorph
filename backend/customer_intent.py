"""Compact customer-intent profile helpers.

This module is intentionally lightweight so guided-question routes can persist
presentation intent without importing the architecture package/SVG pipeline.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class CustomerIntentProfile:
    """Compact, presentation-safe view of guided-question answers."""

    environment: str = "Production"
    region: str = "West Europe"
    availability: str = "Multi-AZ within region (99.95 %)"
    rto: str = "<1 hour"
    compliance: str = "None"
    data_residency: str = "No restriction"
    network_isolation: str = "VNet integration"
    sku_strategy: str = "Balanced (good performance-to-cost ratio)"
    iac_style: str = "Terraform (HCL)"


def build_customer_intent_profile(answers: dict[str, Any] | None) -> dict[str, str]:
    """Build a stable profile from guided-question answers.

    Unknown fields are ignored and list answers are rendered as comma-separated
    strings so the profile can safely travel through JSON, HTML, and reports.
    """
    answers = answers or {}

    def value(key: str, default: str) -> str:
        raw = answers.get(key, default)
        if isinstance(raw, list):
            return ", ".join(str(item) for item in raw if item) or default
        if raw is None:
            return default
        text = str(raw).strip()
        return text or default

    profile = CustomerIntentProfile(
        environment=value("env_target", "Production"),
        region=value("arch_deploy_region", "West Europe"),
        availability=value("arch_ha", "Multi-AZ within region (99.95 %)"),
        rto=value("arch_dr_rto", "<1 hour"),
        compliance=value("sec_compliance", "None"),
        data_residency=value("sec_data_residency", "No restriction"),
        network_isolation=value("sec_network_isolation", "VNet integration"),
        sku_strategy=value("arch_sku_strategy", "Balanced (good performance-to-cost ratio)"),
        iac_style=value("arch_iac_style", "Terraform (HCL)"),
    )
    return asdict(profile)