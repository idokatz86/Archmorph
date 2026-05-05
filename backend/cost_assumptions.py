"""Reviewable cost assumptions artifacts for package exports."""

from __future__ import annotations

from typing import Any

from services.azure_pricing import estimate_services_cost


DIRECTIONAL_COST_NOTICE = (
    "Cost estimates are directional planning inputs. Validate SKUs, usage, reservations, "
    "data transfer, and regional availability with FinOps and Azure Pricing Calculator before commitment."
)

_RI_DISCOUNTS = {"none": 0.0, "1yr": 0.30, "3yr": 0.50}


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
        cost_estimate = _cost_estimate_from_analysis(
            analysis,
            mappings=mappings,
            region=region,
            sku_strategy=sku_strategy,
        )

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
    service_mappings = _mappings_for_service(service_name, mappings)
    primary_mapping = service_mappings[0] if service_mappings else {}
    assumptions = [str(item) for item in service.get("assumptions", []) if item]
    formula = str(service.get("formula") or "")
    quantity = int(service.get("instance_count") or service.get("quantity") or 1)
    reserved_term = str(service.get("reserved_term") or "none")
    warnings = _missing_price_warnings(service_name, service, assumptions, formula)
    quantity_source = str(service.get("quantity_source") or "estimator")

    return {
        "service": service_name,
        "source_service": _source_service_name(primary_mapping),
        "source_services": [_source_service_name(mapping) for mapping in service_mappings if _source_service_name(mapping)],
        "category": str(service.get("category") or primary_mapping.get("category") or "Other"),
        "region": str(cost_estimate.get("region") or cost_estimate.get("arm_region") or "westeurope"),
        "sku": str(service.get("sku") or "Default tier"),
        "sku_pricing_note": str(service.get("sku_pricing_note") or ""),
        "meter": str(service.get("meter") or ""),
        "quantity": quantity,
        "quantity_assumption": (
            f"{quantity} instance(s) configured by the user."
            if quantity_source == "user_override"
            else f"{quantity} instance(s) from estimator defaults unless overridden by the user."
        ),
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


def _cost_estimate_from_analysis(
    analysis: dict[str, Any],
    *,
    mappings: list[dict[str, Any]],
    region: str,
    sku_strategy: str,
) -> dict[str, Any]:
    cached = analysis.get("_cached_cost_estimate") or analysis.get("cost_estimate")
    if _cached_estimate_matches(cached, region=region, sku_strategy=sku_strategy):
        base = cached
    else:
        base = estimate_services_cost(mappings, region=region, sku_strategy=sku_strategy) if mappings else {}
        if mappings:
            base = {**base, "cache_age_days": None}
            analysis["_cached_cost_estimate"] = base

    overrides = analysis.get("_cost_overrides") if isinstance(analysis.get("_cost_overrides"), dict) else {}
    if not overrides:
        return base

    configured = _apply_cost_overrides(base.get("services", []), overrides)
    total_low = sum(float(service.get("monthly_low") or 0) for service in configured)
    total_high = sum(float(service.get("monthly_high") or 0) for service in configured)
    return {
        **base,
        "services": configured,
        "service_count": len(configured),
        "total_monthly_estimate": {"low": round(total_low, 2), "high": round(total_high, 2)},
    }


def _apply_cost_overrides(services: list[Any], overrides: dict[str, Any]) -> list[dict[str, Any]]:
    configured: list[dict[str, Any]] = []
    for service in services:
        if not isinstance(service, dict):
            continue
        name = str(service.get("service") or "")
        override = overrides.get(name, {}) if isinstance(overrides.get(name, {}), dict) else {}
        instance_count = int(override.get("instance_count") or service.get("instance_count") or 1)
        override_sku = str(override.get("sku") or "")
        reserved_term = str(override.get("reserved_term") or service.get("reserved_term") or "none")
        discount = _RI_DISCOUNTS.get(reserved_term, 0.0)
        base_low = float(service.get("base_monthly_low") or service.get("monthly_low") or 0)
        base_high = float(service.get("base_monthly_high") or service.get("monthly_high") or 0)
        monthly_low = round(base_low * instance_count * (1 - discount), 2)
        monthly_high = round(base_high * instance_count * (1 - discount), 2)
        configured.append({
            **service,
            "instance_count": instance_count,
            "sku": override_sku or str(service.get("sku") or "Default tier"),
            "sku_pricing_note": (
                "User-selected SKU label; pricing remains based on the estimator baseline and must be validated."
                if override_sku and override_sku != str(service.get("sku") or "")
                else service.get("sku_pricing_note", "")
            ),
            "reserved_term": reserved_term,
            "quantity_source": "user_override" if "instance_count" in override else service.get("quantity_source", "estimator"),
            "monthly_low": monthly_low,
            "monthly_high": monthly_high,
            "monthly_estimate": round((monthly_low + monthly_high) / 2, 2),
            "base_monthly_low": base_low,
            "base_monthly_high": base_high,
            "ri_savings": round(((base_low + base_high) * instance_count / 2) - ((monthly_low + monthly_high) / 2), 2),
        })
    return configured


def _cached_estimate_matches(candidate: Any, *, region: str, sku_strategy: str) -> bool:
    if not isinstance(candidate, dict) or candidate.get("services") is None:
        return False
    cached_region = str(candidate.get("arm_region") or candidate.get("region") or "").lower()
    cached_strategy = str(candidate.get("sku_strategy") or "Balanced").lower()
    return cached_region == region.lower() and cached_strategy == sku_strategy.lower()


def _mappings_for_service(service_name: str, mappings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        mapping for mapping in mappings
        if str(mapping.get("azure_service") or mapping.get("target") or "") == service_name
    ]


def _source_service_name(mapping: dict[str, Any]) -> str:
    return str(mapping.get("source_service") or mapping.get("source") or mapping.get("aws_service") or mapping.get("gcp_service") or "")


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