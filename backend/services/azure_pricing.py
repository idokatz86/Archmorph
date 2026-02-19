"""
Azure Retail Prices Service for Archmorph
==========================================

Fetches real pricing from the Azure Retail Prices API and caches it monthly.
Uses the public REST API: https://prices.azure.com/api/retail/prices

Pricing is based on the deployment region selected by the user (defaults to
"westeurope") and the Azure services detected during architecture translation.
"""

from __future__ import annotations

import json
import os
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Cache configuration
# ─────────────────────────────────────────────────────────────
CACHE_DIR = Path(__file__).parent.parent / "data"
CACHE_FILE = CACHE_DIR / "azure_pricing_cache.json"
CACHE_MAX_AGE_SECONDS = 30 * 24 * 3600  # ~30 days

AZURE_PRICING_API = "https://prices.azure.com/api/retail/prices"

# ─────────────────────────────────────────────────────────────
# Region display name → armRegionName mapping
# ─────────────────────────────────────────────────────────────
AZURE_REGIONS: dict[str, str] = {
    "West Europe": "westeurope",
    "North Europe": "northeurope",
    "East US": "eastus",
    "East US 2": "eastus2",
    "West US": "westus",
    "West US 2": "westus2",
    "West US 3": "westus3",
    "Central US": "centralus",
    "UK South": "uksouth",
    "UK West": "ukwest",
    "France Central": "francecentral",
    "Germany West Central": "germanywestcentral",
    "Switzerland North": "switzerlandnorth",
    "Southeast Asia": "southeastasia",
    "East Asia": "eastasia",
    "Japan East": "japaneast",
    "Australia East": "australiaeast",
    "Canada Central": "canadacentral",
    "Brazil South": "brazilsouth",
    "South Africa North": "southafricanorth",
    "UAE North": "uaenorth",
    "Korea Central": "koreacentral",
    "Central India": "centralindia",
    "Norway East": "norwayeast",
    "Sweden Central": "swedencentral",
    "Qatar Central": "qatarcentral",
    "Poland Central": "polandcentral",
    "Italy North": "italynorth",
}

# armRegionName → display name (reverse lookup)
ARM_TO_DISPLAY: dict[str, str] = {v: k for k, v in AZURE_REGIONS.items()}


def get_region_options() -> list[str]:
    """Return sorted list of display region names for the guided question."""
    return sorted(AZURE_REGIONS.keys())


def display_to_arm(display_name: str) -> str:
    """Convert display region name to ARM region name. Falls back to westeurope."""
    return AZURE_REGIONS.get(display_name, "westeurope")


# ─────────────────────────────────────────────────────────────
# Azure service → pricing query mapping
# ─────────────────────────────────────────────────────────────
# Maps the Azure service names used in Archmorph mappings to
# Azure Retail Prices API filter parameters.
# Each entry: { "serviceName": ..., "skuName": ..., "meterName": ... }
# Some services use "productName" instead.

SERVICE_PRICE_QUERIES: dict[str, dict[str, Any]] = {
    "Azure ExpressRoute": {
        "serviceName": "Azure ExpressRoute",
        "skuName": "Standard",
        "meterName": "Standard Metered",
        "fallback_monthly": 290,
    },
    "Azure IoT Hub": {
        "serviceName": "IoT Hub",
        "skuName": "S1",
        "meterName": "S1 Unit",
        "fallback_monthly": 25,
    },
    "Azure IoT Edge": {
        "serviceName": "IoT Hub",
        "fallback_monthly": 0,  # IoT Edge is free (runtime); cost is in IoT Hub
    },
    "Azure Event Hubs": {
        "serviceName": "Event Hubs",
        "skuName": "Standard",
        "meterName": "Throughput Unit",
        "fallback_monthly": 22,
    },
    "Azure Event Hubs + Capture": {
        "serviceName": "Event Hubs",
        "skuName": "Standard",
        "meterName": "Throughput Unit",
        "fallback_monthly": 85,
    },
    "Azure Blob Storage": {
        "serviceName": "Storage",
        "skuName": "Hot LRS",
        "meterName": "Data Stored",
        "fallback_monthly": 21,  # per TB
        "unit_multiplier": 1024,  # GB price * 1024 for TB estimate
    },
    "Azure Blob Storage (Raw)": {
        "serviceName": "Storage",
        "skuName": "Hot LRS",
        "meterName": "Data Stored",
        "fallback_monthly": 21,
        "unit_multiplier": 1024,
    },
    "Azure Blob Storage (Curated)": {
        "serviceName": "Storage",
        "skuName": "Hot LRS",
        "meterName": "Data Stored",
        "fallback_monthly": 21,
        "unit_multiplier": 1024,
    },
    "Azure Blob Storage (Rejected)": {
        "serviceName": "Storage",
        "skuName": "Cool LRS",
        "meterName": "Data Stored",
        "fallback_monthly": 10,
        "unit_multiplier": 1024,
    },
    "Azure Data Lake Storage Gen2": {
        "serviceName": "Azure Data Lake Storage Gen2",
        "skuName": "Hot LRS",
        "meterName": "Data Stored",
        "fallback_monthly": 23,
        "unit_multiplier": 1024,
    },
    "Azure Data Factory": {
        "serviceName": "Azure Data Factory v2",
        "skuName": "Data Pipeline",
        "meterName": "Activity Runs",
        "fallback_monthly": 180,
    },
    "Azure HDInsight": {
        "serviceName": "HDInsight",
        "fallback_monthly": 600,
    },
    "Azure HDInsight / Synapse Spark": {
        "serviceName": "Azure Synapse Analytics",
        "skuName": "Apache Spark Pool",
        "fallback_monthly": 1200,
    },
    "Azure Synapse Analytics": {
        "serviceName": "Azure Synapse Analytics",
        "fallback_monthly": 1200,
    },
    "Azure Container Apps": {
        "serviceName": "Azure Container Apps",
        "skuName": "Consumption",
        "meterName": "vCPU",
        "fallback_monthly": 50,
    },
    "Azure Container Instances": {
        "serviceName": "Container Instances",
        "skuName": "Standard",
        "meterName": "vCPU Duration",
        "fallback_monthly": 110,
    },
    "Microsoft Purview": {
        "serviceName": "Microsoft Purview",
        "fallback_monthly": 450,
    },
    "Azure Cosmos DB": {
        "serviceName": "Azure Cosmos DB",
        "skuName": "Autoscale",
        "meterName": "RUs",
        "fallback_monthly": 200,
    },
    "Azure Cosmos DB Gremlin": {
        "serviceName": "Azure Cosmos DB",
        "fallback_monthly": 250,
    },
    "Azure Cosmos DB NoSQL": {
        "serviceName": "Azure Cosmos DB",
        "fallback_monthly": 200,
    },
    "Azure AI Search": {
        "serviceName": "Azure AI Search",
        "skuName": "Standard",
        "fallback_monthly": 250,
    },
    "Azure Functions": {
        "serviceName": "Functions",
        "skuName": "Consumption",
        "meterName": "Execution",
        "fallback_monthly": 0,  # Consumption plan has generous free tier
    },
    "Azure AI Vision": {
        "serviceName": "Cognitive Services",
        "skuName": "S1",
        "fallback_monthly": 100,
    },
    "Azure Machine Learning": {
        "serviceName": "Azure Machine Learning",
        "fallback_monthly": 350,
    },
    "Azure ML Workspace": {
        "serviceName": "Azure Machine Learning",
        "fallback_monthly": 350,
    },
    "Azure API Management": {
        "serviceName": "API Management",
        "skuName": "Consumption",
        "meterName": "API Calls",
        "fallback_monthly": 3.50,  # per 10k calls
    },
    "Azure API Management + SignalR": {
        "serviceName": "API Management",
        "skuName": "Consumption",
        "fallback_monthly": 50,
    },
    "Microsoft Power BI": {
        "serviceName": "Power BI",
        "fallback_monthly": 10,  # per user/month
    },
    "Azure Stack Edge": {
        "serviceName": "Azure Stack Edge",
        "fallback_monthly": 490,
    },
    "Azure SQL Database": {
        "serviceName": "SQL Database",
        "skuName": "Standard",
        "meterName": "S2 DTUs",
        "fallback_monthly": 75,
    },
    "Azure Database for PostgreSQL": {
        "serviceName": "Azure Database for PostgreSQL",
        "skuName": "General Purpose",
        "fallback_monthly": 170,
    },
    "Azure Database for MySQL": {
        "serviceName": "Azure Database for MySQL",
        "skuName": "General Purpose",
        "fallback_monthly": 170,
    },
    "Azure Cache for Redis": {
        "serviceName": "Redis Cache",
        "skuName": "Standard",
        "meterName": "C1",
        "fallback_monthly": 45,
    },
    "Azure Virtual Machines": {
        "serviceName": "Virtual Machines",
        "skuName": "D2s v3",
        "meterName": "D2s v3",
        "fallback_monthly": 98,
    },
    "Azure Kubernetes Service (AKS)": {
        "serviceName": "Azure Kubernetes Service",
        "fallback_monthly": 0,  # AKS control plane is free; costs are in VMs
    },
    "Azure App Service": {
        "serviceName": "Azure App Service",
        "skuName": "Standard",
        "meterName": "S1",
        "fallback_monthly": 73,
    },
    "Azure Front Door": {
        "serviceName": "Azure Front Door Service",
        "fallback_monthly": 35,
    },
    "Azure CDN": {
        "serviceName": "Content Delivery Network",
        "fallback_monthly": 24,
    },
    "Azure Monitor": {
        "serviceName": "Azure Monitor",
        "fallback_monthly": 0,  # Basic metrics free
    },
    "Azure Key Vault": {
        "serviceName": "Key Vault",
        "skuName": "Standard",
        "fallback_monthly": 3,
    },
    "Azure Active Directory": {
        "serviceName": "Microsoft Entra ID",
        "fallback_monthly": 0,  # Free tier
    },
    "Azure Service Bus": {
        "serviceName": "Service Bus",
        "skuName": "Standard",
        "fallback_monthly": 10,
    },
    "Azure Cognitive Services": {
        "serviceName": "Cognitive Services",
        "fallback_monthly": 50,
    },
    "Azure SignalR Service": {
        "serviceName": "SignalR",
        "skuName": "Standard",
        "fallback_monthly": 49,
    },
    "Azure Notification Hubs": {
        "serviceName": "Notification Hubs",
        "skuName": "Standard",
        "fallback_monthly": 10,
    },
    "Azure Logic Apps": {
        "serviceName": "Logic Apps",
        "skuName": "Consumption",
        "fallback_monthly": 15,
    },
    "Azure Batch": {
        "serviceName": "Batch",
        "fallback_monthly": 0,  # Free; costs are in VMs
    },
    "Azure Stream Analytics": {
        "serviceName": "Stream Analytics",
        "skuName": "Standard",
        "meterName": "Streaming Unit",
        "fallback_monthly": 85,
    },
    "Azure Cognitive Search": {
        "serviceName": "Azure AI Search",
        "skuName": "Standard",
        "fallback_monthly": 250,
    },
    "Azure Databricks": {
        "serviceName": "Azure Databricks",
        "fallback_monthly": 400,
    },
}


# ─────────────────────────────────────────────────────────────
# Cache management
# ─────────────────────────────────────────────────────────────
_price_cache: dict[str, Any] = {}
_cache_loaded = False


def _load_cache() -> dict[str, Any]:
    """Load pricing cache from disk if valid."""
    global _price_cache, _cache_loaded
    if _cache_loaded and _price_cache:
        return _price_cache

    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text())
            cached_at = data.get("cached_at", 0)
            if time.time() - cached_at < CACHE_MAX_AGE_SECONDS:
                _price_cache = data
                _cache_loaded = True
                logger.info("Loaded Azure pricing cache (age: %.1f days)",
                            (time.time() - cached_at) / 86400)
                return _price_cache
            else:
                logger.info("Azure pricing cache expired, will refresh")
        except (json.JSONDecodeError, KeyError):
            logger.warning("Corrupt pricing cache, will refresh")

    _cache_loaded = True
    return {}


def _save_cache(data: dict[str, Any]) -> None:
    """Persist pricing cache to disk."""
    global _price_cache
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data["cached_at"] = time.time()
    data["cached_date"] = datetime.now(timezone.utc).isoformat()
    CACHE_FILE.write_text(json.dumps(data, indent=2))
    _price_cache = data
    logger.info("Saved Azure pricing cache to %s", CACHE_FILE)


def invalidate_cache() -> None:
    """Force cache refresh on next pricing request."""
    global _price_cache, _cache_loaded
    _price_cache = {}
    _cache_loaded = False
    if CACHE_FILE.exists():
        CACHE_FILE.unlink()
    logger.info("Azure pricing cache invalidated")


# ─────────────────────────────────────────────────────────────
# Azure Retail Prices API
# ─────────────────────────────────────────────────────────────

def _fetch_price_from_api(
    service_name: str,
    arm_region: str,
    sku_name: str | None = None,
    meter_name: str | None = None,
) -> float | None:
    """Query Azure Retail Prices API for a specific service/SKU."""
    if not HAS_HTTPX:
        return None

    filters = [
        f"serviceName eq '{service_name}'",
        f"armRegionName eq '{arm_region}'",
        "currencyCode eq 'USD'",
        "type eq 'Consumption'",
    ]
    if sku_name:
        filters.append(f"contains(skuName, '{sku_name}')")
    if meter_name:
        filters.append(f"contains(meterName, '{meter_name}')")

    params = {"$filter": " and ".join(filters), "$top": 5}

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(AZURE_PRICING_API, params=params)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("Items", [])
            if items:
                # Get the first non-zero retail price
                for item in items:
                    price = item.get("retailPrice", 0)
                    if price > 0:
                        return price
    except Exception as e:
        logger.warning("Azure pricing API error for %s: %s", service_name, e)

    return None


def fetch_prices_for_region(arm_region: str) -> dict[str, float]:
    """
    Fetch pricing for all known services in a given region.
    Returns dict of { azure_service_name: monthly_estimate_usd }.
    Uses cache when available.
    """
    cache = _load_cache()
    cache_key = f"prices_{arm_region}"

    if cache_key in cache:
        logger.info("Using cached prices for region %s", arm_region)
        return cache[cache_key]

    prices: dict[str, float] = {}

    for service_name, query in SERVICE_PRICE_QUERIES.items():
        fallback = query.get("fallback_monthly", 0)
        multiplier = query.get("unit_multiplier", 730)  # Default: hourly → monthly (730 hrs)

        api_price = _fetch_price_from_api(
            service_name=query.get("serviceName", service_name),
            arm_region=arm_region,
            sku_name=query.get("skuName"),
            meter_name=query.get("meterName"),
        )

        if api_price is not None and api_price > 0:
            # Convert hourly price to monthly
            if query.get("unit_multiplier"):
                monthly = api_price * query["unit_multiplier"]
            else:
                monthly = api_price * 730  # hours in a month
            prices[service_name] = round(monthly, 2)
        else:
            prices[service_name] = fallback

    # Cache results
    if not cache:
        cache = {"cached_at": time.time()}
    cache[cache_key] = prices
    _save_cache(cache)

    return prices


def _find_best_price_match(azure_service: str, prices: dict[str, float]) -> float:
    """Find the best matching price for an Azure service name."""
    # Exact match
    if azure_service in prices:
        return prices[azure_service]

    # Try prefix match (e.g. "Azure Blob Storage (Raw)" → "Azure Blob Storage")
    service_lower = azure_service.lower()
    for key, price in prices.items():
        if key.lower() in service_lower or service_lower.startswith(key.lower()):
            return price

    # Try partial word match
    words = set(azure_service.lower().replace("(", "").replace(")", "").split())
    best_match = None
    best_score = 0
    for key, price in prices.items():
        key_words = set(key.lower().replace("(", "").replace(")", "").split())
        overlap = len(words & key_words)
        if overlap > best_score and overlap >= 2:
            best_score = overlap
            best_match = price

    if best_match is not None:
        return best_match

    # Check SERVICE_PRICE_QUERIES fallback
    for key, query in SERVICE_PRICE_QUERIES.items():
        if key.lower() in service_lower or service_lower.startswith(key.lower()):
            return query.get("fallback_monthly", 0)

    return 0


def estimate_services_cost(
    mappings: list[dict[str, Any]],
    region: str = "westeurope",
    sku_strategy: str = "Balanced",
) -> dict[str, Any]:
    """
    Calculate cost estimate for translated Azure services.

    Args:
        mappings: List of service mappings from the analysis
        region: ARM region name (e.g. "westeurope")
        sku_strategy: One of "Cost-optimized", "Balanced", "Performance-first", "Enterprise"

    Returns:
        Dict with total_monthly_estimate, services, region, currency
    """
    prices = fetch_prices_for_region(region)

    # SKU strategy multipliers
    strategy_multipliers = {
        "Cost-optimized (lowest viable tier)": 0.65,
        "Cost-optimized": 0.65,
        "Balanced (good performance-to-cost ratio)": 1.0,
        "Balanced": 1.0,
        "Performance-first (premium tiers)": 1.6,
        "Performance-first": 1.6,
        "Enterprise (maximum SLA and features)": 2.2,
        "Enterprise": 2.2,
    }
    multiplier = strategy_multipliers.get(sku_strategy, 1.0)

    service_costs: list[dict[str, Any]] = []
    seen_services: set[str] = set()

    for m in mappings:
        azure_svc = m.get("azure_service", "")
        if not azure_svc or azure_svc in seen_services:
            continue
        seen_services.add(azure_svc)

        base_price = _find_best_price_match(azure_svc, prices)
        adjusted = round(base_price * multiplier, 2)

        # Calculate low/high range
        low = round(adjusted * 0.7, 2)
        high = round(adjusted * 1.4, 2)

        service_costs.append({
            "service": azure_svc,
            "monthly_low": low,
            "monthly_high": high,
            "monthly_estimate": adjusted,
            "zone": m.get("notes", "").split("Zone ")[-1].split(" ")[0] if "Zone" in m.get("notes", "") else "",
        })

    # Sort by estimated cost descending
    service_costs.sort(key=lambda x: x["monthly_estimate"], reverse=True)

    total_low = sum(s["monthly_low"] for s in service_costs)
    total_high = sum(s["monthly_high"] for s in service_costs)

    region_display = ARM_TO_DISPLAY.get(region, region)

    return {
        "total_monthly_estimate": {
            "low": round(total_low, 2),
            "high": round(total_high, 2),
        },
        "currency": "USD",
        "region": region_display,
        "arm_region": region,
        "sku_strategy": sku_strategy,
        "services": service_costs,
        "service_count": len(service_costs),
        "pricing_source": "Azure Retail Prices API" if HAS_HTTPX else "built-in estimates",
        "cache_age_days": round((time.time() - _price_cache.get("cached_at", time.time())) / 86400, 1) if _price_cache else 0,
    }
