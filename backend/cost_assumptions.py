"""Reviewable cost assumptions artifacts for package exports."""

from __future__ import annotations

from typing import Any

from services.azure_pricing import estimate_services_cost


DIRECTIONAL_COST_NOTICE = (
    "Cost estimates are directional planning inputs. Validate SKUs, usage, reservations, "
    "data transfer, and regional availability with FinOps and Azure Pricing Calculator before commitment."
)


def build_cost_assumptions_artifact(
    analysis: dict[str, Any],
    *,
    cost_estimate: dict[str, Any] | None = None,
    analysis_id: str | None = None,
) -> dict[str, Any]:
    """Build a stable JSON artifact explaining the assumptions behind cost estimates."""
    if not isinstance(analysis, dict):
        raise ValueError("analysis must be a dict")

    iac_params = analysis.get("iac_parameters") if isinstance(analysis.get("iac_parameters"), dict) else {}
    region = str(iac_params.get("deploy_region") or iac_params.get("location") or iac_params.get("region") or "westeurope")
    sku_strategy = str(iac_params.get("sku_strategy") or "Balanced")
    mappings = [mapping for mapping in analysis.get("mappings", []) if isinstance(mapping, dict)]

    if cost_estimate is None:
        cost_estimate = estimate_services_cost(mappings, region=region, sku_strategy=sku_strategy) if mappings else {}

    services = [_service_assumptions(service, mappings, cost_estimate) for service in cost_estimate.get("services", []) if isinstance(service, dict)]
    missing_warnings = [warning for service in services for warning in service.get("missing_cost_warnings", [])]

    return {
        "schema_version": "cost-assumptions/v1",
        "analysis_id": str(analysis_id or analysis.get("analysis_id") or analysis.get("diagram_id") or "unknown"),
        "currency": str(cost_estimate.get("currency") or "USD"),
        "region": str(cost_estimate.get("region") or region),
        "arm_region": str(cost_estimate.get("arm_region") or region),
        "sku_strategy": str(cost_estimate.get("sku_strategy") or sku_strategy),
        "pricing_source": str(cost_estimate.get("pricing_source") or "not generated"),
        "cache_age_days": cost_estimate.get("cache_age_days", 0),
        "total_monthly_estimate": cost_estimate.get("total_monthly_estimate") or {"low": 0, "high": 0},
        "service_count": len(services),
        "directional_notice": DIRECTIONAL_COST_NOTICE,
        "missing_cost_warnings": missing_warnings[:50],
        "services": services,
    }


def _service_assumptions(
    service: dict[str, Any],
    mappings: list[dict[str, Any]],
    cost_estimate: dict[str, Any],
) -> dict[str, Any]:
    service_name = str(service.get("service") or "Unknown service")
    mapping = _mapping_for_service(service_name, mappings)
    assumptions = [str(item) for item in service.get("assumptions", []) if item]
    formula = str(service.get("formula") or "")
    quantity = int(service.get("instance_count") or service.get("quantity") or 1)
    reserved_term = str(service.get("reserved_term") or "none")
    warnings = _missing_price_warnings(service_name, service, assumptions, formula)

    return {
        "service": service_name,
        "source_service": str(mapping.get("source_service") or mapping.get("source") or mapping.get("aws_service") or mapping.get("gcp_service") or ""),
        "category": str(service.get("category") or mapping.get("category") or "Other"),
        "region": str(cost_estimate.get("region") or cost_estimate.get("arm_region") or "westeurope"),
        "sku": str(service.get("sku") or "Default tier"),
        "meter": str(service.get("meter") or ""),
        "quantity": quantity,
        "quantity_assumption": f"{quantity} instance(s) unless overridden by the user.",
        "storage_assumption": _first_matching_assumption(
            assumptions,
            ("storage", "gb", "tb", "data stored", "disk"),
            "Not specified in analysis; estimate uses the service default storage assumption.",
        ),
        "data_transfer_assumption": _first_matching_assumption(
            assumptions,
            ("outbound", "egress", "data transfer", "bandwidth", "processed"),
            "Not specified in analysis; excludes data transfer unless the formula states otherwise.",
        ),
        "reservation_assumption": (
            f"Reserved capacity applied: {reserved_term}."
            if reserved_term != "none"
            else "Pay-as-you-go; no reserved capacity unless configured by the user."
        ),
        "monthly_low": service.get("monthly_low", 0),
        "monthly_high": service.get("monthly_high", 0),
        "monthly_estimate": service.get("monthly_estimate", service.get("monthly_mid", 0)),
        "price_source": str(service.get("price_source") or "unknown"),
        "base_price_usd": service.get("base_price_usd", 0),
        "hourly_rate_usd": service.get("hourly_rate_usd", 0),
        "sku_multiplier": service.get("sku_multiplier", 1),
        "formula": formula,
        "assumptions": assumptions,
        "missing_cost_warnings": warnings,
    }


def _mapping_for_service(service_name: str, mappings: list[dict[str, Any]]) -> dict[str, Any]:
    for mapping in mappings:
        target = str(mapping.get("azure_service") or mapping.get("target") or "")
        if target == service_name:
            return mapping
    return {}


def _first_matching_assumption(assumptions: list[str], needles: tuple[str, ...], fallback: str) -> str:
    for assumption in assumptions:
        lower = assumption.lower()
        if any(needle in lower for needle in needles):
            return assumption
    return fallback


def _missing_price_warnings(
    service_name: str,
    service: dict[str, Any],
    assumptions: list[str],
    formula: str,
) -> list[str]:
    text = " ".join([formula, *assumptions]).lower()
    monthly = float(service.get("monthly_estimate") or service.get("monthly_mid") or 0)
    base = float(service.get("base_price_usd") or 0)
    if "pricing not available" in text or "no pricing data available" in text:
        return [f"{service_name}: no Azure Retail Prices API or built-in price match; verify manually."]
    if monthly == 0 and base == 0 and not _looks_like_known_free_service(service_name, text):
        return [f"{service_name}: zero-dollar estimate may mean missing usage or SKU data; verify manually."]
    return []


def _looks_like_known_free_service(service_name: str, text: str) -> bool:
    lower = service_name.lower()
    free_markers = ("free", "no charge", "included")
    free_services = ("vnet", "virtual network", "entra id", "managed identity", "iam")
    return any(marker in text for marker in free_markers) or any(name in lower for name in free_services)