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
import os  # noqa: E402

CACHE_DIR = Path(__file__).parent.parent / "data"
CACHE_FILE = CACHE_DIR / "azure_pricing_cache.json"
CACHE_MAX_AGE_SECONDS = int(os.getenv("PRICING_CACHE_TTL_SECONDS", str(24 * 3600)))  # 24h default

AZURE_PRICING_API = "https://prices.azure.com/api/retail/prices"

# Azure Blob Storage persistence — RBAC preferred, connection string fallback
AZURE_STORAGE_ACCOUNT_URL = os.getenv("AZURE_STORAGE_ACCOUNT_URL", "")
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")  # For user-assigned managed identity
PRICING_BLOB_CONTAINER = "pricing"
PRICING_BLOB_NAME = "azure_pricing_cache.json"

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
    # ── Networking ──────────────────────────────────────────
    "Azure Virtual Network": {
        "serviceName": "Virtual Network",
        "fallback_monthly": 0,  # VNet itself is free; peering/gateway has cost
    },
    "Azure NAT Gateway": {
        "serviceName": "NAT Gateway",
        "skuName": "Standard",
        "fallback_monthly": 35,  # ~$0.045/hr + data processing
    },
    "Azure Application Gateway": {
        "serviceName": "Application Gateway",
        "skuName": "Standard v2",
        "meterName": "Fixed Cost",
        "fallback_monthly": 180,  # v2 base + capacity units
    },
    "Azure Load Balancer": {
        "serviceName": "Load Balancer",
        "skuName": "Standard",
        "fallback_monthly": 18,  # ~$0.025/hr
    },
    "Azure Bastion": {
        "serviceName": "Azure Bastion",
        "skuName": "Standard",
        "fallback_monthly": 140,  # ~$0.19/hr
    },
    "Azure DDoS Protection": {
        "serviceName": "Azure DDoS Protection",
        "skuName": "Standard",
        "fallback_monthly": 2944,  # $2944/mo flat rate
    },
    "Azure VPN Gateway": {
        "serviceName": "VPN Gateway",
        "skuName": "VpnGw1",
        "fallback_monthly": 140,
    },
    "Azure DNS": {
        "serviceName": "Azure DNS",
        "fallback_monthly": 1,  # $0.50/zone/mo + queries
    },
    "Azure Virtual WAN": {
        "serviceName": "Virtual WAN",
        "fallback_monthly": 160,
    },
    "Azure Firewall": {
        "serviceName": "Azure Firewall",
        "skuName": "Standard",
        "fallback_monthly": 912,  # ~$1.25/hr
    },
    "Web Application Firewall": {
        "serviceName": "Application Gateway",
        "skuName": "WAF v2",
        "fallback_monthly": 260,
    },
    # ── Compute extras ──────────────────────────────────────
    "VM Scale Sets": {
        "serviceName": "Virtual Machines",
        "skuName": "D2s v3",
        "fallback_monthly": 196,  # 2× D2s v3 instances minimum
    },
    "Azure Static Web Apps": {
        "serviceName": "Static Web Apps",
        "fallback_monthly": 9,  # Standard plan
    },
    # ── Storage extras ──────────────────────────────────────
    "Azure Files": {
        "serviceName": "Storage",
        "skuName": "Hot LRS",
        "meterName": "File",
        "fallback_monthly": 60,  # transaction-heavy file storage
    },
    "Azure Files (NFS)": {
        "serviceName": "Storage",
        "skuName": "Premium LRS",
        "meterName": "File",
        "fallback_monthly": 100,  # Premium NFS tier
    },
    "Managed Disks": {
        "serviceName": "Storage",
        "skuName": "Premium SSD",
        "meterName": "P10",
        "fallback_monthly": 20,  # 128 GiB P10
    },
    "Azure NetApp Files": {
        "serviceName": "Azure NetApp Files",
        "skuName": "Standard",
        "fallback_monthly": 300,  # 4 TiB minimum pool
    },
    "Azure Backup": {
        "serviceName": "Backup",
        "fallback_monthly": 10,  # per instance
    },
    "Archive Storage": {
        "serviceName": "Storage",
        "skuName": "Archive LRS",
        "meterName": "Data Stored",
        "fallback_monthly": 2,  # per TB
    },
    "Data Box": {
        "serviceName": "Data Box",
        "fallback_monthly": 0,  # Per-use device rental
    },
    # ── Database extras ──────────────────────────────────────
    "Azure Database for MariaDB": {
        "serviceName": "Azure Database for MariaDB",
        "skuName": "General Purpose",
        "fallback_monthly": 170,
    },
    "Confidential Ledger": {
        "serviceName": "Azure Confidential Ledger",
        "fallback_monthly": 750,
    },
    "Database Migration Service": {
        "serviceName": "Database Migration Service",
        "fallback_monthly": 0,  # Free tier available
    },
    # ── Security / Identity ──────────────────────────────────
    "Azure Key Vault (Secrets)": {
        "serviceName": "Key Vault",
        "skuName": "Standard",
        "fallback_monthly": 3,
    },
    "Azure Key Vault (Certificates)": {
        "serviceName": "Key Vault",
        "skuName": "Standard",
        "fallback_monthly": 3,
    },
    "Entra ID / RBAC": {
        "serviceName": "Microsoft Entra ID",
        "fallback_monthly": 0,  # Free tier; P1/P2 is per-user
    },
    "Entra External ID (B2C)": {
        "serviceName": "Azure Active Directory B2C",
        "fallback_monthly": 0,  # first 50k MAU free
    },
    "Defender for Cloud": {
        "serviceName": "Microsoft Defender for Cloud",
        "fallback_monthly": 15,  # per server/month
    },
    "Microsoft Sentinel": {
        "serviceName": "Microsoft Sentinel",
        "fallback_monthly": 100,  # depends on data ingestion
    },
    "Dedicated HSM": {
        "serviceName": "Dedicated HSM",
        "fallback_monthly": 4600,
    },
    "Information Protection": {
        "serviceName": "Azure Information Protection",
        "fallback_monthly": 2,  # per user/month
    },
    "Private Link": {
        "serviceName": "Private Link",
        "fallback_monthly": 7,  # per endpoint/month
    },
    # ── AI / ML extras ────────────────────────────────────────
    "Bot Service": {
        "serviceName": "Bot Service",
        "fallback_monthly": 0,  # Free for standard channels; Premium $500
    },
    "Azure OpenAI Service": {
        "serviceName": "Azure OpenAI",
        "fallback_monthly": 100,  # token-based, highly variable
    },
    "AI Vision": {
        "serviceName": "Cognitive Services",
        "skuName": "S1",
        "fallback_monthly": 100,
    },
    "AI Language": {
        "serviceName": "Cognitive Services",
        "fallback_monthly": 75,
    },
    "AI Speech (TTS)": {
        "serviceName": "Cognitive Services",
        "fallback_monthly": 50,
    },
    "AI Speech (STT)": {
        "serviceName": "Cognitive Services",
        "fallback_monthly": 50,
    },
    "AI Translator": {
        "serviceName": "Cognitive Services",
        "fallback_monthly": 10,  # per million chars
    },
    "AI Document Intelligence": {
        "serviceName": "Cognitive Services",
        "fallback_monthly": 50,
    },
    "AI Search": {
        "serviceName": "Azure AI Search",
        "skuName": "Standard",
        "fallback_monthly": 250,
    },
    "Health Insights": {
        "serviceName": "Azure Health Insights",
        "fallback_monthly": 100,
    },
    "Personalizer": {
        "serviceName": "Cognitive Services",
        "fallback_monthly": 50,
    },
    # ── Integration extras ────────────────────────────────────
    "Event Grid": {
        "serviceName": "Event Grid",
        "fallback_monthly": 0.60,  # per million operations
    },
    "Event Grid / Notification Hubs": {
        "serviceName": "Event Grid",
        "fallback_monthly": 10,
    },
    # ── Business / Contact Center ─────────────────────────────
    "Dynamics 365 Contact Center": {
        "serviceName": "Dynamics 365",
        "fallback_monthly": 110,  # per agent digital messaging
    },
    "Azure Communication Services": {
        "serviceName": "Communication Services",
        "fallback_monthly": 0,  # pay-as-you-go
    },
    "Azure Virtual Desktop": {
        "serviceName": "Azure Virtual Desktop",
        "fallback_monthly": 0,  # licensing only; compute is VMs
    },
    # ── Analytics extras ──────────────────────────────────────
    "Data Explorer / AI Search": {
        "serviceName": "Azure Data Explorer",
        "fallback_monthly": 400,
    },
    "Data Factory": {
        "serviceName": "Azure Data Factory v2",
        "fallback_monthly": 180,
    },
    "HDInsight / Databricks": {
        "serviceName": "Azure Databricks",
        "fallback_monthly": 400,
    },
    "Event Hubs / Stream Analytics": {
        "serviceName": "Event Hubs",
        "skuName": "Standard",
        "fallback_monthly": 107,  # EH + SA combined estimate
    },
    "Event Hubs (Kafka)": {
        "serviceName": "Event Hubs",
        "skuName": "Standard",
        "fallback_monthly": 85,
    },
    "Power BI": {
        "serviceName": "Power BI",
        "fallback_monthly": 10,
    },
    "Data Share": {
        "serviceName": "Azure Data Share",
        "fallback_monthly": 0,  # per snapshot
    },
    "Synapse Analytics (Serverless SQL)": {
        "serviceName": "Azure Synapse Analytics",
        "fallback_monthly": 5,  # per TB scanned
    },
    # ── DevOps / DevTools extras ──────────────────────────────
    "Container Registry": {
        "serviceName": "Container Registry",
        "skuName": "Standard",
        "fallback_monthly": 20,
    },
    "Azure DevOps Repos": {
        "serviceName": "Azure DevOps",
        "fallback_monthly": 0,  # free for 5 users
    },
    "Azure Pipelines": {
        "serviceName": "Azure DevOps",
        "fallback_monthly": 40,  # per parallel job
    },
    "Azure Pipelines (Build)": {
        "serviceName": "Azure DevOps",
        "fallback_monthly": 40,
    },
    "Azure Pipelines (Deploy)": {
        "serviceName": "Azure DevOps",
        "fallback_monthly": 0,
    },
    "Azure Artifacts": {
        "serviceName": "Azure DevOps",
        "fallback_monthly": 0,  # 2 GiB free per organization
    },
    "Image Builder": {
        "serviceName": "Image Builder",
        "fallback_monthly": 0,  # Free; underlying VM usage only
    },
    "Azure Chaos Studio": {
        "serviceName": "Chaos Studio",
        "fallback_monthly": 0,  # per action
    },
    "Application Insights": {
        "serviceName": "Application Insights",
        "fallback_monthly": 0,  # 5 GB free ingestion
    },
    # ── Management extras ──────────────────────────────────
    "Azure Monitor / Log Analytics": {
        "serviceName": "Azure Monitor",
        "fallback_monthly": 0,
    },
    "Azure Monitor (Activity Logs)": {
        "serviceName": "Azure Monitor",
        "fallback_monthly": 0,
    },
    "Azure Policy": {
        "serviceName": "Azure Policy",
        "fallback_monthly": 0,  # Free
    },
    "Azure Automation": {
        "serviceName": "Azure Automation",
        "fallback_monthly": 0,  # 500 min/mo free
    },
    "Management Groups": {
        "serviceName": "Management Groups",
        "fallback_monthly": 0,
    },
    "Azure Advisor": {
        "serviceName": "Azure Advisor",
        "fallback_monthly": 0,
    },
    "Cost Management": {
        "serviceName": "Cost Management",
        "fallback_monthly": 0,
    },
    "Service Health": {
        "serviceName": "Service Health",
        "fallback_monthly": 0,
    },
    # ── Migration ──────────────────────────────────────────
    "Azure Migrate": {
        "serviceName": "Azure Migrate",
        "fallback_monthly": 0,  # Free
    },
    "Site Recovery": {
        "serviceName": "Azure Site Recovery",
        "fallback_monthly": 25,  # per instance
    },
    # ── Infrastructure (free/minimal cost) ────────────────
    "Internet (via VNet)": {
        "serviceName": "Virtual Network",
        "fallback_monthly": 0,
    },
    "Azure Subnet (public)": {
        "serviceName": "Virtual Network",
        "fallback_monthly": 0,
    },
    "Azure Subnet (private)": {
        "serviceName": "Virtual Network",
        "fallback_monthly": 0,
    },
    "Azure Availability Zone": {
        "serviceName": "Virtual Machines",
        "fallback_monthly": 0,  # No extra cost for AZ placement
    },
    "Network Security Group (NSG)": {
        "serviceName": "Virtual Network",
        "fallback_monthly": 0,
    },
    "Azure Route Table (UDR)": {
        "serviceName": "Virtual Network",
        "fallback_monthly": 0,
    },
    "Azure Bot Service (Workflows)": {
        "serviceName": "Bot Service",
        "fallback_monthly": 0,
    },
    # ── Notification/Messaging extras ──────────────────────
    "Notification Hubs": {
        "serviceName": "Notification Hubs",
        "skuName": "Standard",
        "fallback_monthly": 10,
    },
    # ── Hybrid & Multi-Cloud (Issue #60) ──────────────────
    "Azure Arc-enabled Kubernetes": {
        "serviceName": "Azure Arc",
        "fallback_monthly": 2,  # per vCPU/month for Arc-enabled K8s
    },
    "Azure Arc-enabled Servers": {
        "serviceName": "Azure Arc",
        "fallback_monthly": 0,  # Free for basic management; ESU/Defender extra
    },
    "Azure Arc-enabled SQL": {
        "serviceName": "Azure Arc",
        "fallback_monthly": 0,  # License-based; SQL Server license required
    },
    "Azure Lighthouse": {
        "serviceName": "Azure Lighthouse",
        "fallback_monthly": 0,  # Free service — revenue is managed-services
    },
    "Azure Stack HCI": {
        "serviceName": "Azure Stack HCI",
        "fallback_monthly": 10,  # per physical core/month
    },
    # ── Generative AI (Issue #61) ─────────────────────────
    "Azure AI Agent Service": {
        "serviceName": "Azure AI Services",
        "fallback_monthly": 150,  # Token-based; highly variable
    },
    "Azure AI Foundry": {
        "serviceName": "Azure AI Services",
        "fallback_monthly": 0,  # Platform free; model inference costs separate
    },
    "Azure AI Content Safety": {
        "serviceName": "Azure AI Services",
        "fallback_monthly": 75,  # per 1K images or 1M characters
    },
    "Azure ML AutoML": {
        "serviceName": "Azure Machine Learning",
        "fallback_monthly": 350,  # Compute-dependent
    },
    "Microsoft 365 Copilot / AI Foundry": {
        "serviceName": "Azure AI Services",
        "fallback_monthly": 30,  # per user/month (M365 Copilot license)
    },
    "Azure AI Foundry (low-code)": {
        "serviceName": "Azure AI Services",
        "fallback_monthly": 0,  # Platform free; inference costs separate
    },
    "GitHub Advanced Security": {
        "serviceName": "GitHub",
        "fallback_monthly": 49,  # per active committer/month
    },
    "Azure AI Search (RAG)": {
        "serviceName": "Azure AI Search",
        "skuName": "Standard",
        "fallback_monthly": 250,
    },
    # ── Edge Computing (Issue #62) ────────────────────────
    "Azure Edge Zones": {
        "serviceName": "Azure Edge Zones",
        "fallback_monthly": 200,  # Varies by telco partner; compute-based
    },
    "Azure Extended Zones": {
        "serviceName": "Azure Extended Zones",
        "fallback_monthly": 150,  # Regional VM pricing with premium
    },
    "Azure Front Door Rules Engine": {
        "serviceName": "Azure Front Door Service",
        "fallback_monthly": 35,  # Included in Front Door; route-based pricing
    },
    "Azure CDN Rules Engine": {
        "serviceName": "Content Delivery Network",
        "fallback_monthly": 24,  # Included in CDN pricing
    },
    # ── Managed Observability (Issue #63) ─────────────────
    "Azure Managed Grafana": {
        "serviceName": "Azure Managed Grafana",
        "fallback_monthly": 9,  # Essential tier; Standard ~$9/instance
    },
    "Azure Monitor (Prometheus)": {
        "serviceName": "Azure Monitor",
        "fallback_monthly": 6,  # per million samples ingested
    },
    "Azure Monitor (OpenTelemetry)": {
        "serviceName": "Azure Monitor",
        "fallback_monthly": 0,  # OTEL SDK free; data ingestion via Monitor pricing
    },
    "Container Insights (Azure Monitor)": {
        "serviceName": "Azure Monitor",
        "fallback_monthly": 0,  # Log Analytics workspace ingestion pricing
    },
    # ── Data Governance (Issue #64) ───────────────────────
    "Microsoft Purview (Data Governance)": {
        "serviceName": "Microsoft Purview",
        "fallback_monthly": 450,
    },
    "Azure Confidential Clean Rooms": {
        "serviceName": "Azure Confidential Ledger",
        "fallback_monthly": 500,  # Confidential computing + compute costs
    },
    "Azure Logic Apps (SaaS connectors)": {
        "serviceName": "Logic Apps",
        "skuName": "Consumption",
        "fallback_monthly": 15,
    },
    "Microsoft Purview Compliance Manager": {
        "serviceName": "Microsoft Purview",
        "fallback_monthly": 0,  # Included with E5 license; standalone varies
    },
    "Azure Data Factory (data wrangling)": {
        "serviceName": "Azure Data Factory v2",
        "fallback_monthly": 180,
    },
    # ── Zero Trust & SASE (Issue #67) ─────────────────────
    "Entra Private Access": {
        "serviceName": "Microsoft Entra ID",
        "fallback_monthly": 6,  # per user/month (Global Secure Access)
    },
    "Microsoft Sentinel (data lake)": {
        "serviceName": "Microsoft Sentinel",
        "fallback_monthly": 100,  # Data ingestion dependent
    },
    "Microsoft Sentinel (investigation)": {
        "serviceName": "Microsoft Sentinel",
        "fallback_monthly": 100,
    },
    "Azure Firewall Manager": {
        "serviceName": "Azure Firewall Manager",
        "fallback_monthly": 100,  # per firewall policy/month
    },
    "Azure Firewall Premium (IDPS)": {
        "serviceName": "Azure Firewall",
        "skuName": "Premium",
        "fallback_monthly": 1825,  # ~$2.50/hr Premium SKU
    },
    "Azure Private Link (service networking)": {
        "serviceName": "Private Link",
        "fallback_monthly": 7,  # per endpoint/month
    },
}

# ─────────────────────────────────────────────────────────────
# Service name aliasing – maps Azure names that appear in
# cross-cloud mappings to canonical SERVICE_PRICE_QUERIES keys
# ─────────────────────────────────────────────────────────────
_SERVICE_ALIASES: dict[str, str] = {
    # Compute
    "Virtual Machines": "Azure Virtual Machines",
    "Container Instances": "Azure Container Instances",
    "Container Apps": "Azure Container Apps",
    "App Service": "Azure App Service",
    "AKS": "Azure Kubernetes Service (AKS)",
    "Azure Batch": "Azure Batch",
    # Storage
    "Blob Storage": "Azure Blob Storage",
    "Azure Files": "Azure Files",
    "NetApp Files": "Azure NetApp Files",
    # Database
    "SQL Database": "Azure SQL Database",
    "SQL Database (Hyperscale)": "Azure SQL Database",
    "Cosmos DB": "Azure Cosmos DB",
    "Cosmos DB (Gremlin)": "Azure Cosmos DB Gremlin",
    "Cosmos DB (MongoDB API)": "Azure Cosmos DB NoSQL",
    "Cosmos DB (Cassandra)": "Azure Cosmos DB NoSQL",
    "Cache for Redis": "Azure Cache for Redis",
    "Cache for Redis (Enterprise)": "Azure Cache for Redis",
    "Synapse Analytics": "Azure Synapse Analytics",
    "Time Series Insights / Data Explorer": "Data Explorer / AI Search",
    "Time Series Insights / Stream Analytics": "Azure Stream Analytics",
    # Networking
    "Virtual Network": "Azure Virtual Network",
    "CDN / Front Door": "Azure Front Door",
    "Front Door": "Azure Front Door",
    "Azure DNS / Traffic Manager": "Azure DNS",
    "API Management": "Azure API Management",
    "Load Balancer / Application Gateway": "Azure Application Gateway",
    "ExpressRoute": "Azure ExpressRoute",
    "VPN Gateway": "Azure VPN Gateway",
    "Azure Firewall": "Azure Firewall",
    "Open Service Mesh": "Azure Kubernetes Service (AKS)",
    "Azure DNS (private zones)": "Azure DNS",
    "Private Link": "Private Link",
    # Security
    "Key Vault": "Azure Key Vault",
    "Key Vault (Secrets)": "Azure Key Vault (Secrets)",
    "Key Vault (Certificates)": "Azure Key Vault (Certificates)",
    "Entra ID (SSO)": "Entra ID / RBAC",
    "Entra Domain Services": "Entra ID / RBAC",
    "DDoS Protection": "Azure DDoS Protection",
    # AI / ML
    "Azure Machine Learning": "Azure Machine Learning",
    "Copilot Studio": "Azure OpenAI Service",
    # Analytics
    "Data Factory (orchestration)": "Data Factory",
    "Data Factory": "Azure Data Factory",
    # Integration
    "Service Bus (Queues)": "Azure Service Bus",
    "Service Bus (Premium)": "Azure Service Bus",
    "Logic Apps": "Azure Logic Apps",
    # DevTools
    "ARM Templates / Bicep": "Azure DevOps Repos",
    "Azure Blueprints / Landing Zones": "Management Groups",
    # Media
    "Media Services (encoding)": "Azure Cognitive Services",
    "Media Services (live)": "Azure Cognitive Services",
    "Communication Services": "Azure Communication Services",
    # Business
    "Email Communication": "Azure Communication Services",
    "Virtual Desktop": "Azure Virtual Desktop",
    # Management
    "Log Analytics": "Azure Monitor / Log Analytics",
    # Migration
    "Site Recovery": "Site Recovery",
}


# ─────────────────────────────────────────────────────────────
# Cache management
# ─────────────────────────────────────────────────────────────
_price_cache: dict[str, Any] = {}
_cache_loaded = False


def _get_blob_client():
    """Return an Azure BlobClient for pricing cache persistence, or None.

    Auth priority:
      1. RBAC via DefaultAzureCredential (production — managed identity)
      2. Connection string (local dev / legacy)
    """
    if not AZURE_STORAGE_ACCOUNT_URL and not AZURE_STORAGE_CONNECTION_STRING:
        return None
    try:
        from azure.storage.blob import BlobServiceClient

        if AZURE_STORAGE_ACCOUNT_URL:
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential(
                managed_identity_client_id=AZURE_CLIENT_ID or None
            )
            bsc = BlobServiceClient(AZURE_STORAGE_ACCOUNT_URL, credential=credential)
            logger.debug("Using RBAC auth for pricing blob storage")
        else:
            bsc = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
            logger.debug("Using connection string auth for pricing blob storage")

        container = bsc.get_container_client(PRICING_BLOB_CONTAINER)
        try:
            container.get_container_properties()
        except Exception:
            container.create_container()
            logger.info("Created blob container '%s' for pricing cache", PRICING_BLOB_CONTAINER)
        return container.get_blob_client(PRICING_BLOB_NAME)
    except Exception as exc:
        logger.warning("Failed to create pricing blob client: %s", exc)
        return None


def _is_cache_valid(data: dict[str, Any]) -> bool:
    """Check if cache data is within the configured TTL."""
    cached_at = data.get("cached_at", 0)
    return time.time() - cached_at < CACHE_MAX_AGE_SECONDS


def _load_cache() -> dict[str, Any]:
    """Load pricing cache from Azure Blob Storage (primary) or local disk (fallback)."""
    global _price_cache, _cache_loaded
    if _cache_loaded and _price_cache:
        return _price_cache

    # 1. Try Azure Blob Storage
    blob = _get_blob_client()
    if blob:
        try:
            raw = blob.download_blob().readall()
            data = json.loads(raw)
            if _is_cache_valid(data):
                _price_cache = data
                _cache_loaded = True
                logger.info("Loaded Azure pricing cache from Blob Storage (age: %.1f h)",
                            (time.time() - data.get("cached_at", 0)) / 3600)
                return _price_cache
            else:
                logger.info("Blob pricing cache expired, will refresh")
        except Exception as exc:
            logger.info("Blob pricing cache load skipped (%s) — trying local file", exc)

    # 2. Fallback to local file
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text())
            if _is_cache_valid(data):
                _price_cache = data
                _cache_loaded = True
                logger.info("Loaded Azure pricing cache from local disk (age: %.1f h)",
                            (time.time() - data.get("cached_at", 0)) / 3600)
                return _price_cache
            else:
                logger.info("Local pricing cache expired, will refresh")
        except (json.JSONDecodeError, KeyError):
            logger.warning("Corrupt pricing cache, will refresh")

    _cache_loaded = True
    return {}


def _save_cache(data: dict[str, Any]) -> None:
    """Persist pricing cache to Azure Blob Storage (primary) and local disk (fallback)."""
    global _price_cache
    data["cached_at"] = time.time()
    data["cached_date"] = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(data, indent=2)

    saved = False

    # 1. Try Azure Blob Storage
    blob = _get_blob_client()
    if blob:
        try:
            blob.upload_blob(payload, overwrite=True)
            logger.info("Saved Azure pricing cache to Blob Storage")
            saved = True
        except Exception as exc:
            logger.warning("Blob pricing save failed (%s) — falling back to disk", exc)

    # 2. Always save to local disk as secondary backup
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(payload)
        saved = True
        if not blob:
            logger.info("Saved Azure pricing cache to %s", CACHE_FILE)
    except Exception as exc:
        logger.warning("Failed to save pricing cache to disk: %s", exc)

    if saved:
        _price_cache = data


def invalidate_cache() -> None:
    """Force cache refresh on next pricing request."""
    global _price_cache, _cache_loaded
    _price_cache = {}
    _cache_loaded = False
    if CACHE_FILE.exists():
        CACHE_FILE.unlink()
    # Also invalidate blob cache
    blob = _get_blob_client()
    if blob:
        try:
            blob.delete_blob()
            logger.info("Deleted pricing cache blob")
        except Exception:
            pass  # nosec B110 — Blob may not exist
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


def fetch_prices_for_region(
    arm_region: str,
    needed_services: set[str] | None = None,
) -> dict[str, float]:
    """
    Fetch pricing for services in a given region.

    Args:
        arm_region: ARM region name (e.g. "westeurope")
        needed_services: If provided, only fetch prices for these
            SERVICE_PRICE_QUERIES keys.  Otherwise fetch all.

    Returns dict of { azure_service_name: monthly_estimate_usd }.
    Uses cache when available.
    """
    cache = _load_cache()
    cache_key = f"prices_{arm_region}"

    if cache_key in cache:
        logger.info("Using cached prices for region %s", arm_region)
        return cache[cache_key]

    prices: dict[str, float] = {}

    queries_to_fetch = SERVICE_PRICE_QUERIES.items()
    if needed_services:
        queries_to_fetch = [
            (k, v) for k, v in SERVICE_PRICE_QUERIES.items()
            if k in needed_services
        ]

    for service_name, query in queries_to_fetch:
        fallback = query.get("fallback_monthly", 0)

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

    # Also populate fallback prices for any remaining needed services
    # that didn't need an API call (ensures comprehensive coverage)
    if needed_services:
        for svc in needed_services:
            if svc not in prices and svc in SERVICE_PRICE_QUERIES:
                prices[svc] = SERVICE_PRICE_QUERIES[svc].get("fallback_monthly", 0)

    # Only cache a full fetch (all services) to avoid partial caches
    if not needed_services:
        if not cache:
            cache = {"cached_at": time.time()}
        cache[cache_key] = prices
        _save_cache(cache)

    return prices


def _find_best_price_match(azure_service: str, prices: dict[str, float]) -> float:
    """Find the best matching price for an Azure service name."""
    # 0. Strip "[Manual mapping needed]" prefix
    if azure_service.startswith("[Manual mapping needed]"):
        return 0

    # 1. Exact match in prices dict
    if azure_service in prices:
        return prices[azure_service]

    # 2. Check alias map → canonical key → prices
    canonical = _SERVICE_ALIASES.get(azure_service)
    if canonical and canonical in prices:
        return prices[canonical]

    # 3. Try prefix match (e.g. "Azure Blob Storage (Raw)" → "Azure Blob Storage")
    service_lower = azure_service.lower()
    for key, price in prices.items():
        if key.lower() in service_lower or service_lower.startswith(key.lower()):
            return price

    # 4. Try partial word match (need ≥ 2 overlapping words)
    words = set(service_lower.replace("(", "").replace(")", "").split())
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

    # 5. Check SERVICE_PRICE_QUERIES fallback via alias → query
    if canonical and canonical in SERVICE_PRICE_QUERIES:
        return SERVICE_PRICE_QUERIES[canonical].get("fallback_monthly", 0)

    # 6. Check SERVICE_PRICE_QUERIES fallback via substring
    for key, query in SERVICE_PRICE_QUERIES.items():
        if key.lower() in service_lower or service_lower.startswith(key.lower()):
            return query.get("fallback_monthly", 0)

    return 0


# ─────────────────────────────────────────────────────────────
# SKU-level cost formula builder
# ─────────────────────────────────────────────────────────────
# Maps service patterns to specific SKU details for human-readable formulas.

_SKU_FORMULAS: dict[str, dict[str, Any]] = {
    "virtual machines": {
        "sku": "Standard_D2s_v3", "vcpu": 2, "ram_gb": 8,
        "hourly": 0.096, "instances": 1, "hours": 730,
        "formula_tpl": "{instances}x {sku} ({vcpu} vCPU, {ram_gb} GB RAM) × ${hourly}/hr × {hours} hrs/mo",
        "assumptions": [
            "{sku} — 2 vCPU, 8 GB RAM, SSD temp storage",
            "Pay-as-you-go pricing (no reservations)",
            "1 instance running 24/7 (730 hrs/month)",
            "Region: {region}",
            "Does not include OS license, managed disks, or data transfer",
        ],
    },
    "kubernetes": {
        "sku": "Standard_D4s_v3", "vcpu": 4, "ram_gb": 16,
        "hourly": 0.192, "instances": 2, "hours": 730,
        "formula_tpl": "{instances}x {sku} worker nodes ({vcpu} vCPU, {ram_gb} GB) × ${hourly}/hr × {hours} hrs/mo (control plane free)",
        "assumptions": [
            "AKS control plane: free",
            "{instances} worker nodes × {sku} ({vcpu} vCPU, {ram_gb} GB RAM)",
            "Pay-as-you-go VM pricing",
            "730 hrs/month per node",
            "Region: {region}",
            "Does not include container registry, load balancer, or persistent disks",
        ],
    },
    "app service": {
        "sku": "S1", "vcpu": 1, "ram_gb": 1.75,
        "hourly": 0.10, "instances": 1, "hours": 730,
        "formula_tpl": "{instances}x App Service Plan {sku} ({vcpu} vCPU, {ram_gb} GB RAM) × ${hourly}/hr × {hours} hrs/mo",
        "assumptions": [
            "App Service Plan S1 — Standard tier",
            "1 ACU (1 vCPU, 1.75 GB RAM)",
            "10 GB disk, 5 deployment slots, custom domains + SSL",
            "Region: {region}",
        ],
    },
    "container apps": {
        "sku": "Consumption", "vcpu": 0.5, "ram_gb": 1.0,
        "formula_tpl": "Consumption plan: {vcpu} vCPU × $0.000012/s + {ram_gb} GB × $0.0000015/s (active seconds only)",
        "assumptions": [
            "Consumption plan (scale-to-zero)",
            "Estimated 50% active time = ~365 hrs/mo",
            "0.5 vCPU, 1 GB RAM per replica",
            "First 180,000 vCPU-seconds/mo free",
            "Region: {region}",
        ],
    },
    "functions": {
        "sku": "Consumption",
        "formula_tpl": "Consumption plan: first 1M executions free, then $0.20 per 1M executions + $0.000016/GB-s",
        "assumptions": [
            "Consumption plan with generous free tier",
            "1M executions + 400,000 GB-s free monthly",
            "Estimated 500K additional executions/mo",
            "128 MB memory × 1s average duration",
            "Region: {region}",
        ],
    },
    "sql database": {
        "sku": "Standard S2", "dtu": 50,
        "formula_tpl": "SQL Database {sku} ({dtu} DTUs) — fixed monthly rate",
        "assumptions": [
            "Standard tier, S2 performance level (50 DTUs)",
            "250 GB included storage",
            "Automated backups (7-35 day retention)",
            "Region: {region}",
            "For higher workloads consider vCore-based General Purpose tier",
        ],
    },
    "postgresql": {
        "sku": "Burstable B2s", "vcpu": 2, "ram_gb": 4,
        "hourly": 0.0656, "instances": 1, "hours": 730,
        "formula_tpl": "Flexible Server {sku} ({vcpu} vCPU, {ram_gb} GB) × ${hourly}/hr × {hours} hrs/mo + 32 GB storage",
        "assumptions": [
            "Flexible Server Burstable B2s tier",
            "2 vCPU, 4 GB RAM",
            "32 GB storage ($0.115/GB/mo = $3.68/mo)",
            "Automated backups (7-day retention, free)",
            "Region: {region}",
        ],
    },
    "mysql": {
        "sku": "Burstable B2s", "vcpu": 2, "ram_gb": 4,
        "hourly": 0.0656, "instances": 1, "hours": 730,
        "formula_tpl": "Flexible Server {sku} ({vcpu} vCPU, {ram_gb} GB) × ${hourly}/hr × {hours} hrs/mo + 32 GB storage",
        "assumptions": [
            "Flexible Server Burstable B2s tier",
            "2 vCPU, 4 GB RAM",
            "32 GB storage ($0.115/GB/mo)",
            "Region: {region}",
        ],
    },
    "cosmos": {
        "sku": "Autoscale (400-4000 RU/s)",
        "formula_tpl": "Autoscale provisioned throughput: 400-4000 RU/s × $0.008 per 100 RU/hr + storage",
        "assumptions": [
            "Autoscale: 400 min to 4000 max RU/s",
            "~$0.008 per 100 RU/s per hour",
            "50 GB storage included ($0.25/GB/mo beyond)",
            "Single region write",
            "Region: {region}",
        ],
    },
    "redis": {
        "sku": "Standard C1", "ram_gb": 1,
        "formula_tpl": "Azure Cache for Redis {sku} ({ram_gb} GB) — fixed monthly rate",
        "assumptions": [
            "Standard C1: 1 GB cache, replication included",
            "99.9% SLA",
            "Region: {region}",
        ],
    },
    "blob storage": {
        "sku": "Hot LRS",
        "formula_tpl": "Blob Storage {sku}: $0.0184/GB/mo × estimated 1 TB = ~$18.84/mo + operations",
        "assumptions": [
            "Hot tier, Locally Redundant Storage (LRS)",
            "1 TB estimated storage",
            "10,000 write + 100,000 read operations/mo",
            "Region: {region}",
            "Cool tier would be ~50% cheaper for infrequent access",
        ],
    },
    "load balancer": {
        "sku": "Standard",
        "formula_tpl": "Standard Load Balancer: $0.025/hr × 730 hrs + $0.005/GB data processed",
        "assumptions": [
            "Standard SKU (required for availability zones)",
            "$0.025/hr base + first 5 rules included",
            "Estimated 100 GB/mo data processed",
            "Region: {region}",
        ],
    },
    "application gateway": {
        "sku": "Standard_v2",
        "formula_tpl": "Application Gateway v2: fixed cost $0.246/hr × 730 hrs + capacity units",
        "assumptions": [
            "Standard_v2 with autoscaling",
            "Base: $0.246/hr (fixed component)",
            "~2.5 capacity units average",
            "Region: {region}",
        ],
    },
    "front door": {
        "sku": "Standard",
        "formula_tpl": "Front Door Standard: $35/mo base + $0.01/GB outbound + routing rules",
        "assumptions": [
            "Standard tier",
            "$35/mo base fee",
            "Estimated 100 GB/mo outbound data",
            "Region: Global (anycast)",
        ],
    },
    "key vault": {
        "sku": "Standard",
        "formula_tpl": "Key Vault Standard: $0.03/10K operations + $3/key/mo (software-protected)",
        "assumptions": [
            "Standard tier (software-protected keys)",
            "Estimated 10K operations/mo",
            "5 keys, 10 secrets, 2 certificates",
            "Region: {region}",
        ],
    },
    "event hubs": {
        "sku": "Standard",
        "formula_tpl": "Event Hubs Standard: 1 throughput unit × $0.030/hr × 730 hrs/mo",
        "assumptions": [
            "Standard tier, 1 throughput unit (1 MB/s in, 2 MB/s out)",
            "1 consumer group included",
            "Region: {region}",
        ],
    },
    "service bus": {
        "sku": "Standard",
        "formula_tpl": "Service Bus Standard: $0.0135/hr base + $0.80 per 1M operations",
        "assumptions": [
            "Standard tier",
            "Estimated 1M operations/mo",
            "Region: {region}",
        ],
    },
    "monitor": {
        "sku": "Pay-as-you-go",
        "formula_tpl": "Azure Monitor: basic metrics free; Log Analytics at $2.76/GB ingested (first 5 GB/day free)",
        "assumptions": [
            "Platform metrics: free",
            "Log Analytics: $2.76/GB ingested",
            "First 5 GB/day free (31-day retention)",
            "Region: {region}",
        ],
    },
}


def _build_cost_formula(
    azure_service: str,
    base_price: float,
    adjusted: float,
    multiplier: float,
    strategy: str,
    sku_name: str,
    meter_name: str,
    hourly_rate: float,
    region: str,
) -> tuple[str, list[str]]:
    """Build a human-readable cost formula and assumptions list for a service.

    Returns (formula_string, assumptions_list).
    """
    svc_lower = azure_service.lower()

    # Find matching SKU formula template
    for key, tmpl in _SKU_FORMULAS.items():
        if key in svc_lower:
            fmt_vars = {
                **tmpl,
                "region": region,
                "strategy": strategy,
                "base_price": base_price,
                "adjusted": adjusted,
            }
            formula = tmpl.get("formula_tpl", "").format(**fmt_vars)
            if multiplier != 1.0:
                formula += f" × {multiplier:.1f} ({strategy})"
            assumptions = [a.format(**fmt_vars) for a in tmpl.get("assumptions", [])]
            if multiplier != 1.0:
                assumptions.append(f"Strategy multiplier: {multiplier:.1f}x ({strategy})")
            return formula, assumptions

    # Generic fallback with hourly rate if available
    if hourly_rate > 0 and sku_name:
        formula = f"{azure_service} [{sku_name}]: ${hourly_rate:.4f}/hr × 730 hrs/mo = ${base_price:.2f}/mo"
        if multiplier != 1.0:
            formula += f" × {multiplier:.1f} ({strategy}) = ${adjusted:.2f}/mo"
        return formula, [
            f"SKU: {sku_name}",
            f"Meter: {meter_name}" if meter_name else "Default meter",
            f"Hourly rate: ${hourly_rate:.4f}/hr",
            "730 hours/month (always-on)",
            f"Region: {region}",
            f"Strategy: {strategy}" if multiplier != 1.0 else "Pay-as-you-go pricing",
        ]

    # Minimal fallback
    if base_price > 0:
        formula = f"{azure_service}: ${base_price:.2f}/mo estimated"
        if multiplier != 1.0:
            formula += f" × {multiplier:.1f} ({strategy}) = ${adjusted:.2f}/mo"
        return formula, [
            f"Based on {strategy} tier in {region}",
            "Price from Azure Retail Prices API or built-in estimate",
            "Range reflects 0.7x-1.4x variance for usage patterns",
        ]

    return "Pricing not available — use Azure Pricing Calculator", [
        "No pricing data available for this service",
        "Check https://azure.microsoft.com/en-us/pricing/calculator/",
    ]


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
    # Determine which pricing entries are actually needed for this set of mappings
    needed_keys: set[str] = set()
    for m in mappings:
        azure_svc = m.get("azure_service", "")
        if not azure_svc:
            continue
        # Direct match
        if azure_svc in SERVICE_PRICE_QUERIES:
            needed_keys.add(azure_svc)
        # Alias match
        canonical = _SERVICE_ALIASES.get(azure_svc)
        if canonical and canonical in SERVICE_PRICE_QUERIES:
            needed_keys.add(canonical)

    prices = fetch_prices_for_region(region, needed_services=needed_keys or None)

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
    region_display = ARM_TO_DISPLAY.get(region, region)  # Moved up for cost rationale (#354)

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

        # ── SKU-level detail for cost transparency ──
        query = SERVICE_PRICE_QUERIES.get(azure_svc) or {}
        # Check alias
        canonical = _SERVICE_ALIASES.get(azure_svc)
        if not query and canonical:
            query = SERVICE_PRICE_QUERIES.get(canonical, {})

        sku_name = query.get("skuName", "")
        meter_name = query.get("meterName", "")
        hourly_rate = round(base_price / 730, 4) if base_price > 0 else 0

        # Build specific formula based on service type
        formula, assumptions_list = _build_cost_formula(
            azure_svc, base_price, adjusted, multiplier, sku_strategy,
            sku_name, meter_name, hourly_rate, region_display,
        )

        service_costs.append({
            "service": azure_svc,
            "sku": sku_name or "Default tier",
            "meter": meter_name,
            "monthly_low": low,
            "monthly_high": high,
            "monthly_estimate": adjusted,
            "zone": m.get("notes", "").split("Zone ")[-1].split(" ")[0] if "Zone" in m.get("notes", "") else "",
            "category": m.get("category", "Other"),
            # ── Cost rationale (#354) ──
            "price_source": "Azure Retail Prices API" if HAS_HTTPX and base_price > 0 else "built-in estimate",
            "base_price_usd": base_price,
            "hourly_rate_usd": hourly_rate,
            "sku_multiplier": multiplier,
            "assumptions": assumptions_list,
            "formula": formula,
        })

    # Sort by estimated cost descending
    service_costs.sort(key=lambda x: x["monthly_estimate"], reverse=True)

    total_low = sum(s["monthly_low"] for s in service_costs)
    total_high = sum(s["monthly_high"] for s in service_costs)

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
