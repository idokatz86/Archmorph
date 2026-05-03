"""Source-to-Azure IaC traceability map helpers."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from customer_intent import build_customer_intent_profile


TRACEABILITY_SCHEMA_VERSION = "source-to-azure-iac-traceability/v1"

_RESOURCE_RULES: tuple[dict[str, Any], ...] = (
    {"key": "app service", "module": "compute", "resources": ["azurerm_service_plan", "azurerm_linux_web_app"]},
    {"key": "web app", "module": "compute", "resources": ["azurerm_service_plan", "azurerm_linux_web_app"], "name": "app_service"},
    {"key": "function app", "module": "compute", "resources": ["azurerm_service_plan", "azurerm_linux_function_app"]},
    {"key": "container app", "module": "compute", "resources": ["azurerm_container_app_environment", "azurerm_container_app"]},
    {"key": "virtual machine", "module": "compute", "resources": ["azurerm_linux_virtual_machine"]},
    {"key": "vm", "module": "compute", "resources": ["azurerm_linux_virtual_machine"], "name": "virtual_machine"},
    {"key": "aks", "module": "compute", "resources": ["azurerm_kubernetes_cluster"]},
    {"key": "kubernetes", "module": "compute", "resources": ["azurerm_kubernetes_cluster"], "name": "aks"},
    {"key": "azure sql", "module": "database", "resources": ["azurerm_mssql_server", "azurerm_mssql_database"]},
    {"key": "sql", "module": "database", "resources": ["azurerm_mssql_server", "azurerm_mssql_database"], "name": "azure_sql"},
    {"key": "postgresql", "module": "database", "resources": ["azurerm_postgresql_flexible_server"]},
    {"key": "cosmos db", "module": "database", "resources": ["azurerm_cosmosdb_account"]},
    {"key": "redis", "module": "database", "resources": ["azurerm_redis_cache"]},
    {"key": "storage account", "module": "storage", "resources": ["azurerm_storage_account"]},
    {"key": "blob storage", "module": "storage", "resources": ["azurerm_storage_account"]},
    {"key": "virtual network", "module": "networking", "resources": ["azurerm_virtual_network", "azurerm_subnet"]},
    {"key": "vnet", "module": "networking", "resources": ["azurerm_virtual_network", "azurerm_subnet"], "name": "virtual_network"},
    {"key": "application gateway", "module": "networking", "resources": ["azurerm_application_gateway"]},
    {"key": "load balancer", "module": "networking", "resources": ["azurerm_lb"]},
    {"key": "key vault", "module": "security", "resources": ["azurerm_key_vault"]},
    {"key": "managed identity", "module": "security", "resources": ["azurerm_user_assigned_identity"]},
    {"key": "log analytics", "module": "security", "resources": ["azurerm_log_analytics_workspace"]},
)


def build_traceability_map(analysis: dict[str, Any] | None) -> dict[str, Any]:
    """Build a stable source-service to Azure IaC traceability map."""
    if not isinstance(analysis, dict):
        analysis = {}

    entries = [_entry_for_mapping(mapping, analysis) for mapping in _mappings(analysis)]
    entries = [entry for entry in entries if entry]
    entries.extend(_platform_guardrail_entries(entries, analysis))
    entries.sort(key=lambda item: item["trace_id"])
    return {
        "schema_version": TRACEABILITY_SCHEMA_VERSION,
        "entries": entries,
    }


def traceability_summary(analysis: dict[str, Any] | None, *, limit: int = 8) -> list[str]:
    """Return compact customer-safe traceability summary lines."""
    trace_map = build_traceability_map(analysis)
    lines = []
    for entry in trace_map["entries"][:limit]:
        resources = ", ".join(resource["address"] for resource in entry["generated_iac_resources"][:3])
        lines.append(
            f"{entry['trace_id']}: {entry['source_service']} -> {entry['azure_service']} -> {resources or 'manual IaC review'}"
        )
    return lines


def _mappings(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    return [mapping for mapping in analysis.get("mappings", []) if isinstance(mapping, dict)]


def _entry_for_mapping(mapping: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any] | None:
    source = _string(mapping.get("source_service") or mapping.get("source") or mapping.get("aws_service") or mapping.get("gcp_service"))
    azure = _string(mapping.get("azure_service") or mapping.get("target_service") or mapping.get("target"))
    if not source or not azure:
        return None

    category = _string(mapping.get("category") or "Other")
    trace_id = _trace_id(source, azure, category)
    return {
        "trace_id": trace_id,
        "source_service": source,
        "source_provider": _string(mapping.get("source_provider") or analysis.get("source_provider") or "unknown"),
        "azure_service": azure,
        "category": category,
        "confidence": _confidence(mapping.get("confidence")),
        "migration_effort": _migration_effort(mapping),
        "customer_intent_influence": _customer_intent_influence(analysis),
        "generated_iac_resources": _iac_resources_for_service(azure),
        "package_diagram_node": {
            "id": f"diagram-node-{trace_id}",
            "label": azure,
            "zone": category,
        },
    }


def _platform_guardrail_entries(entries: list[dict[str, Any]], analysis: dict[str, Any]) -> list[dict[str, Any]]:
    existing = {entry["azure_service"].lower() for entry in entries}
    guardrails = [
        ("Key Vault", "credential management"),
        ("Managed Identity", "identity-based auth"),
        ("Log Analytics", "observability"),
    ]
    out = []
    for azure, purpose in guardrails:
        if any(azure.lower() in service for service in existing):
            continue
        trace_id = _trace_id("platform guardrail", azure, "security")
        out.append({
            "trace_id": trace_id,
            "source_service": "(platform guardrail)",
            "source_provider": _string(analysis.get("source_provider") or "archmorph"),
            "azure_service": azure,
            "category": "security",
            "confidence": 1.0,
            "migration_effort": "low",
            "customer_intent_influence": {"purpose": purpose},
            "generated_iac_resources": _iac_resources_for_service(azure),
            "package_diagram_node": {
                "id": f"diagram-node-{trace_id}",
                "label": azure,
                "zone": "security",
            },
        })
    return out


def _iac_resources_for_service(azure_service: str) -> list[dict[str, str]]:
    rule = _match_resource_rule(azure_service)
    if rule is None:
        return []
    name = _safe_tf_name(str(rule.get("name") or rule["key"]))
    module = str(rule["module"])
    file_path = f"terraform/modules/{module}/main.tf"
    return [
        {
            "format": "terraform",
            "module": module,
            "file": file_path,
            "resource_type": resource_type,
            "resource_name": f"{name}_default" if resource_type == "azurerm_subnet" else name,
            "address": f"module.{module}.{resource_type}.{f'{name}_default' if resource_type == 'azurerm_subnet' else name}",
        }
        for resource_type in rule["resources"]
    ]


def _match_resource_rule(azure_service: str) -> dict[str, Any] | None:
    lower = azure_service.lower()
    for rule in _RESOURCE_RULES:
        if rule["key"] in lower:
            return rule
    return None


def _customer_intent_influence(analysis: dict[str, Any]) -> dict[str, str]:
    profile = analysis.get("customer_intent")
    if isinstance(profile, dict) and profile:
        normalized = {str(key): str(value) for key, value in profile.items()}
    elif isinstance(analysis.get("guided_answers"), dict):
        normalized = build_customer_intent_profile(analysis["guided_answers"])
    else:
        normalized = {}
    return {
        key: normalized[key]
        for key in ("environment", "region", "availability", "compliance", "network_isolation", "sku_strategy")
        if normalized.get(key) and normalized[key] != "Not specified"
    }


def _migration_effort(mapping: dict[str, Any]) -> str:
    explicit = _string(mapping.get("migration_effort") or mapping.get("effort"))
    if explicit:
        return explicit.lower()
    confidence = _confidence(mapping.get("confidence"))
    if confidence >= 0.9:
        return "low"
    if confidence >= 0.8:
        return "medium"
    return "high"


def _confidence(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if score > 1:
        score = score / 100
    return round(max(0.0, min(1.0, score)), 4)


def _trace_id(source: str, azure: str, category: str) -> str:
    payload = json.dumps(
        {"source": source.lower(), "azure": azure.lower(), "category": category.lower()},
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"trace-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]}"


def _safe_tf_name(value: str) -> str:
    name = re.sub(r"[^a-z0-9_]", "_", value.lower())
    name = re.sub(r"_+", "_", name).strip("_")
    if name and name[0].isdigit():
        name = "svc_" + name
    return name or "svc"


def _string(value: Any) -> str:
    return str(value).strip() if value is not None else ""