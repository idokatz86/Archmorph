"""
Guided Questionnaire System for Archmorph
==========================================

Generates context-aware questions based on detected AWS services to customize
the Azure architecture translation. Answers influence Azure SKU selection,
redundancy configuration, compliance posture, and IaC parameters.

Usage:
    from guided_questions import generate_questions, apply_answers

    questions = generate_questions(["EC2", "S3", "Lambda", "DynamoDB", "IoT Core"])
    # → present to user, collect answers dict  {question_id: answer_value}
    adjusted = apply_answers(original_analysis, user_answers)
"""

from __future__ import annotations

import copy
from typing import Any

# ─────────────────────────────────────────────────────────────
# Type aliases
# ─────────────────────────────────────────────────────────────
Question = dict[str, Any]
QuestionBank = dict[str, list[Question]]
AnalysisResult = dict[str, Any]
Answers = dict[str, Any]


# ═════════════════════════════════════════════════════════════
# QUESTION BANK
# ═════════════════════════════════════════════════════════════
# Each question:
#   id        – unique identifier (category prefix + ordinal)
#   question  – display text
#   type      – "single_choice" | "multiple_choice" | "scale" | "text"
#   options   – list of allowed values (for choice / scale types)
#   condition – list of AWS service names that trigger inclusion;
#               empty list means *always* included
#   impact    – human-readable note on what Azure decisions this affects
#   default   – sensible default answer

QUESTION_BANK: QuestionBank = {
    # ─────────────────────────────────────────────────────────
    # ENVIRONMENT & SCALE
    # ─────────────────────────────────────────────────────────
    "environment_scale": [
        {
            "id": "env_target",
            "question": "What environment is this architecture for?",
            "type": "single_choice",
            "options": ["Development", "Staging", "Production", "Multi-environment"],
            "condition": [],
            "impact": "Controls default SKU tiers, redundancy, and monitoring depth across all Azure resources",
            "default": "Production",
        },
        {
            "id": "env_data_volume",
            "question": "Expected data volume ingested per day?",
            "type": "single_choice",
            "options": ["<1 GB", "1–100 GB", "100 GB–1 TB", "1–10 TB", ">10 TB"],
            "condition": [
                "S3", "Kinesis", "Glue", "EMR", "Redshift", "Athena",
                "Lake Formation", "Data Pipeline", "MSK", "IoT Core",
                "IoT Analytics", "IoT SiteWise", "IoT FleetWise",
            ],
            "impact": "Sizes Azure Blob/ADLS storage tiers, Event Hubs throughput units, and Synapse DWU allocation",
            "default": "1–100 GB",
        },
        {
            "id": "env_concurrent_users",
            "question": "Expected number of concurrent users or connections?",
            "type": "single_choice",
            "options": ["<100", "100–1 K", "1 K–10 K", "10 K–100 K", ">100 K"],
            "condition": [
                "EC2", "ECS", "EKS", "Fargate", "Lambda", "API Gateway",
                "ELB", "CloudFront", "App Runner", "Elastic Beanstalk",
                "Lightsail", "Cognito", "AppSync",
            ],
            "impact": "Determines VM Scale Set sizing, App Service plan tier, Functions scaling limits, and CDN capacity",
            "default": "1 K–10 K",
        },
    ],

    # ─────────────────────────────────────────────────────────
    # COMPLIANCE & SECURITY
    # ─────────────────────────────────────────────────────────
    "compliance_security": [
        {
            "id": "sec_compliance",
            "question": "Which compliance frameworks apply to this workload?",
            "type": "multiple_choice",
            "options": [
                "HIPAA", "SOC 2", "PCI-DSS", "GDPR",
                "ISO 27001", "FedRAMP", "None",
            ],
            "condition": [],
            "impact": "Enables Azure Policy initiatives, activates Defender for Cloud regulatory dashboards, restricts allowed regions",
            "default": "None",
        },
        {
            "id": "sec_data_residency",
            "question": "Are there data residency requirements?",
            "type": "single_choice",
            "options": [
                "No restriction",
                "EU only",
                "US only",
                "Specific country",
                "Multi-region with data sovereignty",
            ],
            "condition": [],
            "impact": "Constrains Azure region selection and replication targets; adds geo-fencing policies in IaC",
            "default": "No restriction",
        },
        {
            "id": "sec_network_isolation",
            "question": "What level of network isolation is required?",
            "type": "single_choice",
            "options": [
                "Public endpoints OK",
                "VNet integration",
                "Full private endpoints",
                "Air-gapped / isolated",
            ],
            "condition": [],
            "impact": "Adds Private Link, VNet injection, NSGs, and Azure Firewall to IaC; may change service SKUs",
            "default": "VNet integration",
        },
        {
            "id": "sec_encryption",
            "question": "Encryption key management preference?",
            "type": "single_choice",
            "options": [
                "Platform-managed keys (default)",
                "Customer-managed keys (Azure Key Vault)",
                "Customer-managed keys (HSM-backed)",
            ],
            "condition": ["KMS", "CloudHSM", "Secrets Manager", "S3", "RDS", "DynamoDB"],
            "impact": "Toggles CMK configuration on storage accounts, databases, and disks; adds Key Vault resources to IaC",
            "default": "Platform-managed keys (default)",
        },
    ],

    # ─────────────────────────────────────────────────────────
    # ARCHITECTURE PREFERENCES
    # ─────────────────────────────────────────────────────────
    "architecture_preferences": [
        {
            "id": "arch_sku_strategy",
            "question": "Preferred tier / SKU strategy?",
            "type": "single_choice",
            "options": [
                "Cost-optimized (lowest viable tier)",
                "Balanced (good performance-to-cost ratio)",
                "Performance-first (premium tiers)",
                "Enterprise (maximum SLA and features)",
            ],
            "condition": [],
            "impact": "Selects Basic/Standard/Premium SKUs across Azure services; affects estimated monthly cost",
            "default": "Balanced (good performance-to-cost ratio)",
        },
        {
            "id": "arch_ha",
            "question": "High-availability requirements?",
            "type": "single_choice",
            "options": [
                "Single region (no redundancy)",
                "Multi-AZ within region (99.95 %)",
                "Multi-region active-passive (99.99 %)",
                "Multi-region active-active (99.999 %)",
            ],
            "condition": [],
            "impact": "Adds availability zones, geo-replication, Traffic Manager / Front Door profiles",
            "default": "Multi-AZ within region (99.95 %)",
        },
        {
            "id": "arch_dr_rto",
            "question": "Disaster-recovery RTO target?",
            "type": "single_choice",
            "options": [
                "<1 min (hot standby)",
                "<15 min",
                "<1 hour",
                "<4 hours",
                "<24 hours",
                "Not required",
            ],
            "condition": [],
            "impact": "Determines replication mode, standby resources, and Azure Site Recovery configuration",
            "default": "<1 hour",
        },
        {
            "id": "arch_iac_style",
            "question": "Preferred Infrastructure-as-Code format for the output?",
            "type": "single_choice",
            "options": [
                "Terraform (HCL)",
                "Bicep",
                "ARM Templates (JSON)",
                "Pulumi",
            ],
            "condition": [],
            "impact": "Sets the IaC language used in generated templates",
            "default": "Terraform (HCL)",
        },
        {
            "id": "arch_deploy_region",
            "question": "Target Azure deployment region?",
            "type": "single_choice",
            "options": [
                "West Europe",
                "North Europe",
                "East US",
                "East US 2",
                "West US 2",
                "UK South",
                "Southeast Asia",
                "Australia East",
                "Central US",
                "Canada Central",
                "Japan East",
                "France Central",
                "Germany West Central",
                "Switzerland North",
                "Brazil South",
                "Central India",
                "Korea Central",
                "South Africa North",
                "UAE North",
                "Sweden Central",
            ],
            "condition": [],
            "impact": "Determines the Azure region for deployment and cost estimation; affects pricing, latency, and compliance",
            "default": "West Europe",
        },
    ],

    # ─────────────────────────────────────────────────────────
    # DATA & PROCESSING
    # ─────────────────────────────────────────────────────────
    "data_processing": [
        {
            "id": "data_storage_redundancy",
            "question": "Preferred Azure storage redundancy level?",
            "type": "single_choice",
            "options": ["LRS", "ZRS", "GRS", "RA-GRS", "GZRS"],
            "condition": [
                "S3", "S3 Glacier", "EFS", "FSx", "Backup",
                "Storage Gateway", "DataSync",
            ],
            "impact": "Sets replication type on all Azure Storage Accounts and ADLS Gen2 resources",
            "default": "ZRS",
        },
        {
            "id": "data_spark_runtime",
            "question": "Preferred managed Spark runtime on Azure?",
            "type": "single_choice",
            "options": [
                "Azure Synapse Spark Pools",
                "Azure HDInsight",
                "Azure Databricks",
            ],
            "condition": ["EMR", "Glue", "Athena", "Lake Formation"],
            "impact": "Replaces default EMR → HDInsight/Synapse mapping; regenerates IaC with chosen runtime",
            "default": "Azure Synapse Spark Pools",
        },
        {
            "id": "data_functions_plan",
            "question": "Azure Functions hosting plan preference?",
            "type": "single_choice",
            "options": [
                "Consumption (pure serverless, pay-per-execution)",
                "Premium (pre-warmed instances, VNet support)",
                "Dedicated App Service Plan",
            ],
            "condition": ["Lambda", "Step Functions"],
            "impact": "Sets Azure Functions plan type; Premium required for VNet integration and >10 min execution",
            "default": "Consumption (pure serverless, pay-per-execution)",
        },
        {
            "id": "data_cosmosdb_throughput",
            "question": "Cosmos DB throughput model?",
            "type": "single_choice",
            "options": [
                "Serverless (intermittent traffic)",
                "Provisioned with manual scaling",
                "Provisioned with autoscale",
            ],
            "condition": ["DynamoDB", "Neptune", "DocumentDB", "Keyspaces"],
            "impact": "Configures Cosmos DB capacity mode; affects cost model and performance guarantees",
            "default": "Provisioned with autoscale",
        },
        {
            "id": "data_cosmosdb_api",
            "question": "Preferred Cosmos DB API?",
            "type": "single_choice",
            "options": [
                "NoSQL (native, recommended)",
                "MongoDB",
                "Cassandra",
                "Gremlin (graph)",
                "Table",
            ],
            "condition": ["DynamoDB", "DocumentDB", "Keyspaces", "Neptune"],
            "impact": "Selects the Cosmos DB API and SDK; Gremlin for graph workloads, NoSQL for key-value",
            "default": "NoSQL (native, recommended)",
        },
        {
            "id": "data_cache_tier",
            "question": "Azure Cache for Redis tier?",
            "type": "single_choice",
            "options": [
                "Basic (dev/test, no SLA)",
                "Standard (replicated, 99.9 %)",
                "Premium (clustering, VNet, geo-replication)",
                "Enterprise (Redis Enterprise modules)",
            ],
            "condition": ["ElastiCache", "MemoryDB"],
            "impact": "Sets Redis cache SKU; Enterprise required for RediSearch, RedisJSON",
            "default": "Standard (replicated, 99.9 %)",
        },
        {
            "id": "data_sql_tier",
            "question": "Azure SQL / PostgreSQL tier preference?",
            "type": "single_choice",
            "options": [
                "Basic / Burstable (B-series)",
                "General Purpose",
                "Business Critical / Memory-Optimized",
                "Hyperscale",
            ],
            "condition": ["RDS", "Aurora"],
            "impact": "Determines Azure SQL DB or Flexible Server compute tier and max IOPS",
            "default": "General Purpose",
        },
        {
            "id": "data_streaming_engine",
            "question": "Preferred real-time streaming engine on Azure?",
            "type": "single_choice",
            "options": [
                "Azure Event Hubs + Stream Analytics",
                "Azure Event Hubs + Spark Structured Streaming",
                "Azure Event Hubs (Kafka surface)",
            ],
            "condition": ["Kinesis", "MSK"],
            "impact": "Selects streaming analytics approach; Kafka surface allows existing Kafka client reuse",
            "default": "Azure Event Hubs + Stream Analytics",
        },
    ],

    # ─────────────────────────────────────────────────────────
    # IOT-SPECIFIC
    # ─────────────────────────────────────────────────────────
    "iot": [
        {
            "id": "iot_message_volume",
            "question": "Expected IoT message volume?",
            "type": "single_choice",
            "options": [
                "<1 M messages/day",
                "1 M–100 M messages/day",
                ">100 M messages/day",
            ],
            "condition": [
                "IoT Core", "IoT Greengrass", "IoT Analytics",
                "IoT SiteWise", "IoT Events", "IoT FleetWise",
            ],
            "impact": "Sizes IoT Hub tier (S1/S2/S3) and partition count; affects Event Hubs downstream capacity",
            "default": "1 M–100 M messages/day",
        },
        {
            "id": "iot_edge_computing",
            "question": "Is edge computing required?",
            "type": "single_choice",
            "options": [
                "Yes — Azure IoT Edge (local processing)",
                "No — cloud-only ingestion",
            ],
            "condition": [
                "IoT Greengrass", "IoT Core", "Outposts", "Wavelength",
            ],
            "impact": "Adds Azure IoT Edge module definitions and edge deployment manifests to IaC",
            "default": "Yes — Azure IoT Edge (local processing)",
        },
        {
            "id": "iot_device_scale",
            "question": "Device management scope — how many devices?",
            "type": "single_choice",
            "options": [
                "<100 devices",
                "100–10 K devices",
                "10 K–1 M devices",
                ">1 M devices",
            ],
            "condition": [
                "IoT Core", "IoT Greengrass", "IoT SiteWise",
                "IoT Events", "IoT FleetWise", "IoT TwinMaker",
            ],
            "impact": "Selects IoT Hub unit count and DPS (Device Provisioning Service) allocation",
            "default": "100–10 K devices",
        },
        {
            "id": "iot_digital_twins",
            "question": "Do you need a digital-twin model of physical assets?",
            "type": "single_choice",
            "options": [
                "Yes — Azure Digital Twins",
                "No",
            ],
            "condition": ["IoT TwinMaker", "IoT SiteWise"],
            "impact": "Adds Azure Digital Twins resource and DTDL model scaffolding to IaC",
            "default": "Yes — Azure Digital Twins",
        },
    ],

    # ─────────────────────────────────────────────────────────
    # MONITORING & OPERATIONS
    # ─────────────────────────────────────────────────────────
    "monitoring_operations": [
        {
            "id": "ops_monitoring_depth",
            "question": "Desired monitoring and observability depth?",
            "type": "single_choice",
            "options": [
                "None — no monitoring needed",
                "Basic metrics (Azure Monitor)",
                "Application Insights (APM + distributed tracing)",
                "Full observability (Azure Monitor + Grafana + Log Analytics)",
                "Security-focused (Azure Monitor + Microsoft Sentinel SIEM)",
            ],
            "condition": [],
            "impact": "Adds Log Analytics workspace, Application Insights, Managed Grafana, or Sentinel to IaC (or nothing if None)",
            "default": "Application Insights (APM + distributed tracing)",
        },
        {
            "id": "ops_cicd",
            "question": "Preferred CI/CD platform?",
            "type": "single_choice",
            "options": [
                "GitHub Actions",
                "Azure DevOps Pipelines",
                "Terraform Cloud / Spacelift",
                "None — manual deployment for now",
            ],
            "condition": [],
            "impact": "Generates starter CI/CD pipeline definition alongside IaC templates",
            "default": "GitHub Actions",
        },
        {
            "id": "ops_alerting",
            "question": "Alerting and notification channel?",
            "type": "single_choice",
            "options": [
                "None — no alerts needed",
                "Email only",
                "Email + Slack / Teams webhook",
                "PagerDuty / Opsgenie integration",
                "Custom webhook",
            ],
            "condition": ["CloudWatch", "SNS", "EventBridge"],
            "impact": "Configures Azure Monitor action groups and alert rules in IaC (or nothing if None)",
            "default": "Email + Slack / Teams webhook",
        },
    ],

    # ─────────────────────────────────────────────────────────
    # CONTAINER & KUBERNETES
    # ─────────────────────────────────────────────────────────
    "containers": [
        {
            "id": "k8s_cluster_tier",
            "question": "AKS cluster tier?",
            "type": "single_choice",
            "options": [
                "Free tier (dev/test)",
                "Standard (production SLA, 99.95 %)",
                "Premium (mission-critical, 99.99 %)",
            ],
            "condition": ["EKS"],
            "impact": "Sets AKS SKU tier, uptime SLA, and enables/disables Cluster Autoscaler",
            "default": "Standard (production SLA, 99.95 %)",
        },
        {
            "id": "k8s_node_pool",
            "question": "AKS default node pool VM size?",
            "type": "single_choice",
            "options": [
                "Standard_B2s (burstable, cost-optimized)",
                "Standard_D4s_v5 (general purpose)",
                "Standard_E8s_v5 (memory-optimized)",
                "Standard_F8s_v2 (compute-optimized)",
                "Standard_NC6s_v3 (GPU)",
            ],
            "condition": ["EKS", "ECS", "Fargate"],
            "impact": "Sets default node pool VM size; GPU nodes required for ML inference workloads",
            "default": "Standard_D4s_v5 (general purpose)",
        },
        {
            "id": "container_runtime_pref",
            "question": "Preferred container hosting model on Azure?",
            "type": "single_choice",
            "options": [
                "AKS (full Kubernetes)",
                "Azure Container Apps (serverless Kubernetes)",
                "Azure Container Instances (simple single-container)",
                "Azure App Service (containers on PaaS)",
            ],
            "condition": ["ECS", "Fargate", "App Runner"],
            "impact": "Overrides default ECS/Fargate/App Runner mapping to chosen Azure container service",
            "default": "Azure Container Apps (serverless Kubernetes)",
        },
    ],

    # ─────────────────────────────────────────────────────────
    # AI / ML
    # ─────────────────────────────────────────────────────────
    "ai_ml": [
        {
            "id": "ml_workspace_tier",
            "question": "Azure Machine Learning workspace edition?",
            "type": "single_choice",
            "options": [
                "Basic (notebook-only experimentation)",
                "Enterprise (managed endpoints, pipelines, AutoML)",
            ],
            "condition": ["SageMaker", "Bedrock", "Personalize", "Forecast"],
            "impact": "Sets AML workspace SKU; Enterprise required for managed online endpoints",
            "default": "Enterprise (managed endpoints, pipelines, AutoML)",
        },
        {
            "id": "ml_compute_target",
            "question": "Primary ML compute target?",
            "type": "single_choice",
            "options": [
                "CPU clusters (general training)",
                "GPU clusters (deep learning)",
                "Spark pools (big-data ML)",
                "Serverless compute (AML managed)",
            ],
            "condition": ["SageMaker", "Bedrock", "Rekognition"],
            "impact": "Provisions appropriate compute cluster type in Azure ML workspace",
            "default": "GPU clusters (deep learning)",
        },
    ],

    # ─────────────────────────────────────────────────────────
    # HYBRID & MULTI-CLOUD  (Issue #60)
    # ─────────────────────────────────────────────────────────
    "hybrid_multicloud": [
        {
            "id": "hybrid_strategy",
            "question": "What is your hybrid / multi-cloud strategy?",
            "type": "single_choice",
            "options": [
                "Full migration to Azure (no hybrid)",
                "Hybrid — keep some workloads on-premises",
                "Multi-cloud — run workloads across Azure + another cloud",
                "Edge + cloud — processing at the edge with cloud control plane",
            ],
            "condition": ["Outposts", "EKS Anywhere", "EKS", "ECS Anywhere"],
            "impact": "Adds Azure Arc, Azure Stack HCI, or Lighthouse resources to IaC depending on chosen strategy",
            "default": "Full migration to Azure (no hybrid)",
        },
        {
            "id": "hybrid_arc_scope",
            "question": "Which resources need Azure Arc management?",
            "type": "multiple_choice",
            "options": [
                "Kubernetes clusters",
                "SQL databases",
                "Linux/Windows servers",
                "None — cloud-only",
            ],
            "condition": ["Outposts", "EKS Anywhere", "SSM"],
            "impact": "Determines which Arc-enabled services to provision — Arc K8s, Arc SQL, or Arc Servers",
            "default": "None — cloud-only",
        },
    ],

    # ─────────────────────────────────────────────────────────
    # GENERATIVE AI & AI AGENTS  (Issue #61)
    # ─────────────────────────────────────────────────────────
    "generative_ai": [
        {
            "id": "genai_model_provider",
            "question": "Preferred foundation model provider on Azure?",
            "type": "single_choice",
            "options": [
                "Azure OpenAI (GPT-4o, GPT-4, GPT-3.5)",
                "Meta Llama (via Azure AI Foundry)",
                "Mistral (via Azure AI Foundry)",
                "Cohere (via Azure AI Foundry)",
                "Bring your own model",
            ],
            "condition": ["Bedrock", "Bedrock Agents", "Bedrock Knowledge Bases", "Q Business", "PartyRock"],
            "impact": "Selects the model deployment target — Azure OpenAI or AI Foundry model catalog",
            "default": "Azure OpenAI (GPT-4o, GPT-4, GPT-3.5)",
        },
        {
            "id": "genai_agent_pattern",
            "question": "Do you need autonomous AI agents with tool use?",
            "type": "single_choice",
            "options": [
                "Yes — Azure AI Agent Service (hosted agents)",
                "Yes — Semantic Kernel / LangChain (code-first)",
                "No — simple prompt/response pattern",
            ],
            "condition": ["Bedrock Agents", "Bedrock Knowledge Bases"],
            "impact": "Adds Azure AI Agent Service or custom agent framework resources to the architecture",
            "default": "No — simple prompt/response pattern",
        },
        {
            "id": "genai_content_safety",
            "question": "Content safety requirements for AI outputs?",
            "type": "single_choice",
            "options": [
                "Default Azure OpenAI content filters",
                "Custom Azure AI Content Safety policies",
                "No content filtering needed (internal use only)",
            ],
            "condition": ["Bedrock", "Bedrock Guardrails", "Bedrock Agents"],
            "impact": "Configures Azure AI Content Safety resources and custom filter policies",
            "default": "Default Azure OpenAI content filters",
        },
    ],

    # ─────────────────────────────────────────────────────────
    # EDGE COMPUTING  (Issue #62)
    # ─────────────────────────────────────────────────────────
    "edge_computing": [
        {
            "id": "edge_use_case",
            "question": "What is the primary edge computing use case?",
            "type": "single_choice",
            "options": [
                "Ultra-low-latency at 5G / telco edge (Azure Edge Zones)",
                "Metro-area proximity (Azure Extended Zones)",
                "CDN edge functions (Front Door Rules Engine)",
                "On-premises edge appliance (Azure Stack Edge)",
                "Not applicable",
            ],
            "condition": ["Wavelength", "Local Zones", "Lambda@Edge", "CloudFront Functions", "Outposts"],
            "impact": "Selects the appropriate Azure edge compute target and adds related IaC resources",
            "default": "Not applicable",
        },
    ],

    # ─────────────────────────────────────────────────────────
    # DATA GOVERNANCE  (Issue #64)
    # ─────────────────────────────────────────────────────────
    "data_governance": [
        {
            "id": "gov_data_catalog",
            "question": "Do you need a centralized data catalog and governance?",
            "type": "single_choice",
            "options": [
                "Yes — Microsoft Purview (full data governance)",
                "Basic metadata only (Azure Data Catalog)",
                "No — data governance not needed now",
            ],
            "condition": ["DataZone", "Lake Formation", "Glue", "Glue DataBrew"],
            "impact": "Adds Microsoft Purview resources for data catalog, lineage, and governance",
            "default": "No — data governance not needed now",
        },
        {
            "id": "gov_clean_rooms",
            "question": "Do you need privacy-preserving data collaboration (clean rooms)?",
            "type": "single_choice",
            "options": [
                "Yes — Azure Confidential Clean Rooms",
                "No",
            ],
            "condition": ["Clean Rooms"],
            "impact": "Adds Azure Confidential Clean Rooms with confidential computing guarantees",
            "default": "No",
        },
    ],

    # ─────────────────────────────────────────────────────────
    # ZERO TRUST & SASE SECURITY  (Issue #67)
    # ─────────────────────────────────────────────────────────
    "zero_trust": [
        {
            "id": "zt_network_access",
            "question": "How should users access internal applications?",
            "type": "single_choice",
            "options": [
                "Traditional VPN (Azure VPN Gateway)",
                "Zero Trust Network Access (Microsoft Entra Private Access)",
                "Conditional Access + App Proxy",
                "Not applicable — public apps only",
            ],
            "condition": ["Verified Access", "Client VPN", "VPN"],
            "impact": "Replaces VPN with Entra Private Access for zero-trust identity-based access to apps",
            "default": "Traditional VPN (Azure VPN Gateway)",
        },
        {
            "id": "zt_siem",
            "question": "Preferred SIEM / security analytics solution?",
            "type": "single_choice",
            "options": [
                "Microsoft Sentinel (full SIEM + SOAR)",
                "Microsoft Sentinel (SIEM only, no automation)",
                "Third-party SIEM (Splunk, Datadog, etc.)",
                "No SIEM needed",
            ],
            "condition": ["Security Hub", "Security Lake", "Detective", "GuardDuty"],
            "impact": "Provisions Microsoft Sentinel workspace with data connectors and analytics rules",
            "default": "Microsoft Sentinel (full SIEM + SOAR)",
        },
        {
            "id": "zt_firewall_tier",
            "question": "Azure Firewall tier?",
            "type": "single_choice",
            "options": [
                "Standard (L3-L7 filtering, threat intelligence)",
                "Premium (adds IDPS, TLS inspection, URL filtering)",
                "Basic (simplified, cost-optimized)",
                "No centralized firewall",
            ],
            "condition": ["Network Firewall", "Firewall Manager", "WAF"],
            "impact": "Selects Azure Firewall SKU; Premium required for intrusion detection and TLS inspection",
            "default": "Standard (L3-L7 filtering, threat intelligence)",
        },
    ],
}


# ═════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════

# Service name normalisation map — handles common variations that
# appear in diagram analysis output (e.g. "Amazon S3" → "S3").
_NORMALISE: dict[str, str] = {
    "Amazon S3": "S3",
    "Simple Storage Service": "S3",
    "Amazon EC2": "EC2",
    "Elastic Compute Cloud": "EC2",
    "AWS Lambda": "Lambda",
    "Amazon DynamoDB": "DynamoDB",
    "Amazon Aurora": "Aurora",
    "Amazon RDS": "RDS",
    "Amazon Kinesis": "Kinesis",
    "Amazon Kinesis Data Firehose": "Kinesis",
    "Amazon EMR": "EMR",
    "Elastic MapReduce": "EMR",
    "Amazon Redshift": "Redshift",
    "Amazon Neptune": "Neptune",
    "Amazon DocumentDB": "DocumentDB",
    "Amazon ElastiCache": "ElastiCache",
    "Amazon EKS": "EKS",
    "Amazon ECS": "ECS",
    "AWS Fargate": "Fargate",
    "AWS IoT Core": "IoT Core",
    "AWS IoT Greengrass": "IoT Greengrass",
    "AWS IoT SiteWise": "IoT SiteWise",
    "AWS IoT TwinMaker": "IoT TwinMaker",
    "AWS IoT FleetWise": "IoT FleetWise",
    "AWS IoT Events": "IoT Events",
    "AWS IoT Analytics": "IoT Analytics",
    "Amazon API Gateway": "API Gateway",
    "Amazon CloudFront": "CloudFront",
    "AWS Direct Connect": "Direct Connect",
    "AWS Outposts": "Outposts",
    "Amazon SageMaker": "SageMaker",
    "Amazon SageMaker Ground Truth": "SageMaker",
    "Amazon Bedrock": "Bedrock",
    "Amazon Rekognition": "Rekognition",
    "AWS Glue": "Glue",
    "AWS Glue Data Catalog": "Glue",
    "Amazon MWAA": "MWAA",
    "Amazon Athena": "Athena",
    "Amazon QuickSight": "QuickSight",
    "AWS Step Functions": "Step Functions",
    "Amazon SQS": "SQS",
    "Amazon SNS": "SNS",
    "Amazon EventBridge": "EventBridge",
    "Amazon MSK": "MSK",
    "Amazon Elasticsearch Service": "OpenSearch",
    "Amazon OpenSearch Service": "OpenSearch",
    "AWS AppSync": "AppSync",
    "Amazon Cognito": "Cognito",
    "AWS CloudFormation": "CloudFormation",
    "Amazon CloudWatch": "CloudWatch",
    "Amazon MemoryDB": "MemoryDB",
    "AWS CodePipeline": "CodePipeline",
    "AWS CodeBuild": "CodeBuild",
    "AWS CodeDeploy": "CodeDeploy",
    "Amazon ECR": "ECR",
    "AWS App Runner": "App Runner",
    "AWS KMS": "KMS",
    "AWS Secrets Manager": "Secrets Manager",
    "AWS CloudHSM": "CloudHSM",
    "AWS WAF": "WAF",
    "AWS VPN": "VPN",
    "Amazon VPC": "VPC",
    "Amazon Route 53": "Route 53",
    "AWS Elastic Beanstalk": "Elastic Beanstalk",
    "Amazon Lightsail": "Lightsail",
    "AWS Batch": "Batch",
    "Amazon Timestream": "Timestream",
    "Amazon Keyspaces": "Keyspaces",
    "Amazon Personalize": "Personalize",
    "Amazon Forecast": "Forecast",
    # ── Hybrid / Multi-cloud ──
    "Amazon EKS Anywhere": "EKS Anywhere",
    "AWS Systems Manager": "SSM",
    "AWS SSM": "SSM",
    "Amazon RDS on Outposts": "RDS on Outposts",
    # ── Generative AI ──
    "Amazon Bedrock Agents": "Bedrock Agents",
    "Amazon Bedrock Knowledge Bases": "Bedrock Knowledge Bases",
    "Amazon Q Business": "Q Business",
    "Amazon Q Developer": "Q Developer",
    "Amazon SageMaker Canvas": "SageMaker Canvas",
    "Amazon Bedrock Guardrails": "Bedrock Guardrails",
    "Amazon PartyRock": "PartyRock",
    "Amazon CodeGuru": "CodeGuru",
    # ── Edge Computing ──
    "AWS Wavelength": "Wavelength",
    "AWS Local Zones": "Local Zones",
    "CloudFront Functions": "CloudFront Functions",
    "Lambda@Edge": "Lambda@Edge",
    "AWS Elastic Disaster Recovery": "Elastic Disaster Recovery",
    # ── Observability ──
    "Amazon Managed Grafana": "Managed Grafana",
    "Amazon Managed Service for Prometheus": "Managed Prometheus",
    "AWS Distro for OpenTelemetry": "Distro for OpenTelemetry",
    "Amazon CloudWatch Container Insights": "CloudWatch Container Insights",
    # ── Data Governance ──
    "Amazon DataZone": "DataZone",
    "AWS Clean Rooms": "Clean Rooms",
    "Amazon AppFlow": "AppFlow",
    "AWS Audit Manager": "Audit Manager",
    "AWS Glue DataBrew": "Glue DataBrew",
    # ── Zero Trust / SASE ──
    "AWS Verified Access": "Verified Access",
    "Amazon Security Lake": "Security Lake",
    "Amazon Detective": "Detective",
    "AWS Firewall Manager": "Firewall Manager",
    "AWS Network Firewall": "Network Firewall",
    "Amazon VPC Lattice": "VPC Lattice",
}


def _normalise_service(name: str) -> str:
    """Normalise a detected AWS service name to its short canonical form."""
    return _NORMALISE.get(name, name)


def _flatten_questions() -> list[Question]:
    """Return a flat list of all questions across every category."""
    flat: list[Question] = []
    for questions in QUESTION_BANK.values():
        flat.extend(questions)
    return flat


# ═════════════════════════════════════════════════════════════
# PUBLIC API
# ═════════════════════════════════════════════════════════════

def generate_questions(detected_services: list[str]) -> list[dict]:
    """Return the relevant subset of guided questions for a set of detected AWS services.

    Questions are included if:
      • their ``condition`` list is empty (always relevant), *or*
      • at least one service in ``condition`` appears in *detected_services*.

    Typically returns 8–15 questions — enough to meaningfully customise the
    translation without overwhelming the user.

    Args:
        detected_services: AWS service names as they appear in the analysis
            (e.g. ``["EC2", "S3", "Lambda", "DynamoDB", "IoT Core"]``).  Both
            short names (``"S3"``) and long names (``"Amazon S3"``) are accepted.

    Returns:
        Ordered list of question dicts, each containing ``id``, ``question``,
        ``type``, ``options``, ``impact``, ``default``, and ``category``.
    """
    normalised: set[str] = {_normalise_service(s) for s in detected_services}

    selected: list[dict] = []
    seen_ids: set[str] = set()

    for category, questions in QUESTION_BANK.items():
        for q in questions:
            if q["id"] in seen_ids:
                continue

            conditions: list[str] = q["condition"]
            if not conditions or any(svc in normalised for svc in conditions):
                entry = {**q, "category": category}
                selected.append(entry)
                seen_ids.add(q["id"])

    # Cap at a reasonable upper bound to maintain UX quality.
    max_questions = 18
    if len(selected) > max_questions:
        # Prioritise: always-on questions first, then service-specific ones.
        always_on = [q for q in selected if not q["condition"]]
        conditional = [q for q in selected if q["condition"]]
        selected = always_on + conditional[: max_questions - len(always_on)]

    return selected


def apply_answers(analysis_result: dict, answers: dict) -> dict:
    """Apply user answers to refine an Azure architecture analysis.

    Creates a **deep copy** of *analysis_result* and mutates the copy — the
    original is never modified.

    Adjustments include:
      • Swapping Azure service mappings (e.g. EMR → Databricks instead of Synapse).
      • Upgrading or downgrading SKU references in mapping notes.
      • Modifying confidence scores when the user confirms preferences.
      • Appending compliance / networking / DR warnings.
      • Adding IaC parameter recommendations under a new ``iac_parameters`` key.

    Args:
        analysis_result: The dict returned by the ``/api/diagrams/{id}/analyze``
            endpoint (or equivalent).  Expected keys: ``mappings``, ``warnings``,
            and optional ``iac_parameters``.
        answers: ``{question_id: user_answer}`` mapping.  Any question not
            present is treated as accepting the default.

    Returns:
        A new analysis dict with adjusted mappings, updated warnings, refined
        confidence scores, and an ``iac_parameters`` section.
    """
    result: dict = copy.deepcopy(analysis_result)

    mappings: list[dict] = result.get("mappings", [])
    warnings: list[str] = result.get("warnings", [])
    iac_params: dict[str, Any] = result.get("iac_parameters", {})

    # Merge defaults for unanswered questions.
    effective: dict[str, Any] = _merge_defaults(answers)

    # ── Apply each rule ──────────────────────────────────────
    _apply_environment(effective, mappings, warnings, iac_params)
    _apply_sku_strategy(effective, mappings, warnings, iac_params)
    _apply_ha_and_dr(effective, mappings, warnings, iac_params)
    _apply_compliance(effective, mappings, warnings, iac_params)
    _apply_network_isolation(effective, mappings, warnings, iac_params)
    _apply_storage_redundancy(effective, mappings, iac_params)
    _apply_spark_runtime(effective, mappings, warnings)
    _apply_functions_plan(effective, mappings, iac_params)
    _apply_cosmosdb(effective, mappings, iac_params)
    _apply_cache_tier(effective, mappings, iac_params)
    _apply_sql_tier(effective, mappings, iac_params)
    _apply_streaming(effective, mappings, iac_params)
    _apply_iot(effective, mappings, warnings, iac_params)
    _apply_monitoring(effective, mappings, warnings, iac_params)
    _apply_containers(effective, mappings, iac_params)
    _apply_ml(effective, mappings, iac_params)
    _apply_iac_style(effective, iac_params)
    _apply_deploy_region(effective, iac_params)
    _apply_encryption(effective, mappings, warnings, iac_params)

    result["mappings"] = mappings
    result["warnings"] = warnings
    result["iac_parameters"] = iac_params

    # ── Recalculate confidence_summary after all rule adjustments ──
    high = len([m for m in mappings if m.get("confidence", 0) >= 0.90])
    medium = len([m for m in mappings if 0.80 <= m.get("confidence", 0) < 0.90])
    low = len([m for m in mappings if m.get("confidence", 0) < 0.80])
    avg = round(
        sum(m.get("confidence", 0) for m in mappings) / max(len(mappings), 1), 2
    )
    result["confidence_summary"] = {
        "high": high,
        "medium": medium,
        "low": low,
        "average": avg,
    }

    return result


# ═════════════════════════════════════════════════════════════
# INTERNAL RULE FUNCTIONS
# ═════════════════════════════════════════════════════════════

def _merge_defaults(answers: Answers) -> Answers:
    """Fill in default values for every question not answered by the user."""
    defaults: dict[str, Any] = {}
    for questions in QUESTION_BANK.values():
        for q in questions:
            defaults[q["id"]] = q["default"]
    merged = {**defaults, **answers}
    return merged


def _swap_azure_service(
    mappings: list[dict],
    source_contains: str,
    old_azure_fragment: str,
    new_azure: str,
    *,
    note_suffix: str = "",
    confidence_delta: float = 0.0,
) -> None:
    """Replace Azure service in any mapping whose source matches *source_contains*
    and whose current azure_service contains *old_azure_fragment*."""
    for m in mappings:
        src = m.get("source_service", "") or ""
        azure = m.get("azure_service", "") or ""
        if source_contains.lower() in src.lower() and old_azure_fragment.lower() in azure.lower():
            m["azure_service"] = new_azure
            if note_suffix:
                m["notes"] = f"{m.get('notes', '')} | {note_suffix}"
            if confidence_delta:
                m["confidence"] = min(1.0, max(0.0, m.get("confidence", 0.8) + confidence_delta))


def _boost_confidence(mappings: list[dict], delta: float) -> None:
    """Raise confidence on all mappings by *delta* (user confirmed preferences)."""
    for m in mappings:
        m["confidence"] = min(1.0, m.get("confidence", 0.8) + delta)


# ── Individual rule implementations ───────────────────────

def _apply_environment(
    answers: Answers,
    mappings: list[dict],
    warnings: list[str],
    iac: dict,
) -> None:
    env = answers.get("env_target", "Production")
    iac["environment"] = env.lower().replace("-", "_").replace(" ", "_")

    if env == "Development":
        iac["use_spot_instances"] = True
        iac["auto_shutdown"] = True
        warnings.append(
            "Development environment selected — using lowest-cost defaults, "
            "auto-shutdown enabled, no geo-replication"
        )
        for m in mappings:
            m["confidence"] = min(1.0, m.get("confidence", 0.8) + 0.05)
    elif env == "Multi-environment":
        iac["deploy_environments"] = ["dev", "staging", "prod"]
        warnings.append(
            "Multi-environment requested — IaC will use workspace/variable "
            "sets for dev, staging, and prod"
        )


def _apply_sku_strategy(
    answers: Answers,
    mappings: list[dict],
    warnings: list[str],
    iac: dict,
) -> None:
    strategy = answers.get("arch_sku_strategy", "Balanced")
    iac["sku_strategy"] = strategy

    tier_map = {
        "Cost-optimized (lowest viable tier)": "basic",
        "Balanced (good performance-to-cost ratio)": "standard",
        "Performance-first (premium tiers)": "premium",
        "Enterprise (maximum SLA and features)": "enterprise",
    }
    tier = tier_map.get(strategy, "standard")
    iac["default_tier"] = tier

    if tier == "enterprise":
        warnings.append(
            "Enterprise SKU strategy — all services upgraded to highest tier; "
            "review cost estimate carefully"
        )
        for m in mappings:
            azure = m.get("azure_service", "")
            if "Standard" in azure:
                m["azure_service"] = azure.replace("Standard", "Premium")
            m["confidence"] = min(1.0, m.get("confidence", 0.8) + 0.03)

    elif tier == "basic":
        warnings.append(
            "Cost-optimized tier — some SLA guarantees may be lower; "
            "not recommended for production workloads"
        )
        for m in mappings:
            azure = m.get("azure_service", "")
            if "Premium" in azure:
                m["azure_service"] = azure.replace("Premium", "Standard")


def _apply_ha_and_dr(
    answers: Answers,
    mappings: list[dict],
    warnings: list[str],
    iac: dict,
) -> None:
    ha = answers.get("arch_ha", "Multi-AZ within region (99.95 %)")
    rto = answers.get("arch_dr_rto", "<1 hour")

    iac["high_availability"] = ha
    iac["disaster_recovery_rto"] = rto

    if "active-active" in ha:
        iac["geo_replication"] = True
        iac["traffic_manager_profile"] = "performance"
        iac["paired_region"] = True
        warnings.append(
            "Multi-region active-active — Azure Front Door with geo-replicated "
            "backends will be provisioned; Cosmos DB multi-region writes enabled"
        )
        for m in mappings:
            azure = m.get("azure_service", "")
            if "Cosmos DB" in azure and "multi-region" not in azure.lower():
                m["azure_service"] = f"{azure} (multi-region writes)"
                m["confidence"] = min(1.0, m.get("confidence", 0.8) + 0.05)

    elif "active-passive" in ha:
        iac["geo_replication"] = True
        iac["traffic_manager_profile"] = "priority"
        warnings.append(
            "Multi-region active-passive — secondary region with Azure Site "
            "Recovery for failover"
        )

    elif "Single region" in ha:
        iac["availability_zones"] = False
        warnings.append(
            "Single-region deployment without zone redundancy — lower cost "
            "but no AZ-level fault tolerance"
        )
    else:
        iac["availability_zones"] = True

    if "<1 min" in rto:
        iac["hot_standby"] = True
        warnings.append(
            "Hot-standby DR target (<1 min RTO) — requires duplicate "
            "infrastructure in secondary region"
        )


def _apply_compliance(
    answers: Answers,
    mappings: list[dict],
    warnings: list[str],
    iac: dict,
) -> None:
    frameworks = answers.get("sec_compliance", "None")
    if isinstance(frameworks, str):
        frameworks = [frameworks]
    iac["compliance_frameworks"] = frameworks

    residency = answers.get("sec_data_residency", "No restriction")
    iac["data_residency"] = residency

    if "HIPAA" in frameworks:
        iac["hipaa_enabled"] = True
        warnings.append(
            "HIPAA compliance selected — Azure Policy HIPAA/HITRUST initiative "
            "will be assigned; BAA required with Microsoft"
        )

    if "GDPR" in frameworks:
        iac["gdpr_enabled"] = True
        if residency == "No restriction":
            warnings.append(
                "GDPR selected but no data-residency restriction set — "
                "consider restricting to EU regions for full compliance"
            )
        warnings.append(
            "GDPR compliance — data subject request automation and "
            "consent management may need application-level implementation"
        )

    if "PCI-DSS" in frameworks:
        iac["pci_dss_enabled"] = True
        warnings.append(
            "PCI-DSS compliance — CDE (Cardholder Data Environment) segments "
            "require dedicated subnets with NSG/ASG rules"
        )

    if "SOC 2" in frameworks:
        iac["soc2_enabled"] = True

    if "FedRAMP" in frameworks:
        iac["fedramp_enabled"] = True
        iac["azure_government"] = True
        warnings.append(
            "FedRAMP compliance — deployment should target Azure Government "
            "regions (usgovvirginia / usgovarizona)"
        )

    if "ISO 27001" in frameworks:
        iac["iso27001_enabled"] = True

    # Data residency constraints
    region_map = {
        "EU only": ["westeurope", "northeurope", "germanywestcentral", "francecentral"],
        "US only": ["eastus", "eastus2", "westus2", "centralus"],
    }
    if residency in region_map:
        iac["allowed_regions"] = region_map[residency]
        warnings.append(
            f"Data residency: {residency} — Azure Policy will restrict "
            f"deployments to {', '.join(region_map[residency])}"
        )
    elif residency == "Specific country":
        warnings.append(
            "Specific-country data residency — please specify country code "
            "so we can select the appropriate Azure region(s)"
        )


def _apply_network_isolation(
    answers: Answers,
    mappings: list[dict],
    warnings: list[str],
    iac: dict,
) -> None:
    level = answers.get("sec_network_isolation", "VNet integration")
    iac["network_isolation"] = level

    if level == "Full private endpoints":
        iac["private_endpoints"] = True
        iac["public_network_access"] = False
        iac["vnet_integration"] = True
        warnings.append(
            "Full private-endpoint mode — all PaaS services (Storage, SQL, "
            "Cosmos DB, Key Vault, etc.) will use Private Link; some services "
            "may require Premium SKU for PE support"
        )
        # Bump confidence for PE-compatible services
        for m in mappings:
            azure = m.get("azure_service", "")
            if any(svc in azure for svc in [
                "Blob", "SQL", "Cosmos", "Key Vault", "Functions",
                "Container", "Event Hubs", "Service Bus",
            ]):
                m["confidence"] = min(1.0, m.get("confidence", 0.8) + 0.02)

    elif level == "VNet integration":
        iac["vnet_integration"] = True
        iac["service_endpoints"] = True
        iac["public_network_access"] = True

    elif level == "Air-gapped / isolated":
        iac["air_gapped"] = True
        iac["private_endpoints"] = True
        iac["public_network_access"] = False
        iac["azure_firewall"] = True
        warnings.append(
            "Air-gapped deployment — Azure Firewall, forced tunnelling, "
            "and no public ingress/egress; requires Azure ExpressRoute "
            "or VPN Gateway for management"
        )

    else:
        iac["public_network_access"] = True


def _apply_storage_redundancy(
    answers: Answers,
    mappings: list[dict],
    iac: dict,
) -> None:
    redundancy = answers.get("data_storage_redundancy", "ZRS")
    iac["storage_redundancy"] = redundancy

    for m in mappings:
        azure = m.get("azure_service", "")
        if any(term in azure for term in ["Blob Storage", "ADLS", "Data Lake", "Azure Files"]):
            m["notes"] = f"{m.get('notes', '')} | Redundancy: {redundancy}"
            if redundancy in ("GRS", "RA-GRS", "GZRS"):
                m["confidence"] = min(1.0, m.get("confidence", 0.8) + 0.03)


def _apply_spark_runtime(
    answers: Answers,
    mappings: list[dict],
    warnings: list[str],
) -> None:
    runtime = answers.get("data_spark_runtime", "Azure Synapse Spark Pools")
    runtime_map = {
        "Azure Synapse Spark Pools": "Azure Synapse Spark Pool",
        "Azure HDInsight": "Azure HDInsight",
        "Azure Databricks": "Azure Databricks",
    }
    target = runtime_map.get(runtime, "Azure Synapse Spark Pool")

    for m in mappings:
        src = m.get("source_service", "") or ""
        azure = m.get("azure_service", "") or ""
        if "EMR" in src or "Elastic MapReduce" in src:
            if any(frag in azure for frag in ["Synapse", "HDInsight", "Databricks"]):
                m["azure_service"] = target
                m["notes"] = f"{m.get('notes', '')} | User selected: {runtime}"
                m["confidence"] = min(1.0, m.get("confidence", 0.8) + 0.05)

    if target == "Azure Databricks":
        warnings.append(
            "Databricks selected as Spark runtime — separate Databricks "
            "workspace will be provisioned; pricing differs from Synapse model"
        )
    elif target == "Azure HDInsight":
        warnings.append(
            "HDInsight selected as Spark runtime — consider HDInsight on AKS "
            "for improved startup times and cluster management"
        )


def _apply_functions_plan(
    answers: Answers,
    mappings: list[dict],
    iac: dict,
) -> None:
    plan = answers.get("data_functions_plan", "Consumption")
    plan_map = {
        "Consumption (pure serverless, pay-per-execution)": "consumption",
        "Premium (pre-warmed instances, VNet support)": "premium",
        "Dedicated App Service Plan": "dedicated",
    }
    plan_key = plan_map.get(plan, "consumption")
    iac["functions_plan"] = plan_key

    for m in mappings:
        azure = m.get("azure_service", "")
        if "Functions" in azure:
            m["notes"] = f"{m.get('notes', '')} | Plan: {plan_key}"
            if plan_key == "premium":
                m["confidence"] = min(1.0, m.get("confidence", 0.8) + 0.03)


def _apply_cosmosdb(
    answers: Answers,
    mappings: list[dict],
    iac: dict,
) -> None:
    throughput = answers.get("data_cosmosdb_throughput", "Provisioned with autoscale")
    api = answers.get("data_cosmosdb_api", "NoSQL (native, recommended)")

    throughput_map = {
        "Serverless (intermittent traffic)": "serverless",
        "Provisioned with manual scaling": "provisioned",
        "Provisioned with autoscale": "autoscale",
    }
    iac["cosmosdb_throughput_mode"] = throughput_map.get(throughput, "autoscale")

    api_map = {
        "NoSQL (native, recommended)": "nosql",
        "MongoDB": "mongodb",
        "Cassandra": "cassandra",
        "Gremlin (graph)": "gremlin",
        "Table": "table",
    }
    iac["cosmosdb_api"] = api_map.get(api, "nosql")

    for m in mappings:
        azure = m.get("azure_service", "")
        if "Cosmos DB" in azure:
            m["notes"] = (
                f"{m.get('notes', '')} | "
                f"API: {iac['cosmosdb_api']}, "
                f"Throughput: {iac['cosmosdb_throughput_mode']}"
            )


def _apply_cache_tier(
    answers: Answers,
    mappings: list[dict],
    iac: dict,
) -> None:
    tier = answers.get("data_cache_tier", "Standard (replicated, 99.9 %)")
    tier_map = {
        "Basic (dev/test, no SLA)": "basic",
        "Standard (replicated, 99.9 %)": "standard",
        "Premium (clustering, VNet, geo-replication)": "premium",
        "Enterprise (Redis Enterprise modules)": "enterprise",
    }
    iac["redis_tier"] = tier_map.get(tier, "standard")

    for m in mappings:
        azure = m.get("azure_service", "")
        if "Redis" in azure or "Cache" in azure:
            m["notes"] = f"{m.get('notes', '')} | Tier: {iac['redis_tier']}"


def _apply_sql_tier(
    answers: Answers,
    mappings: list[dict],
    iac: dict,
) -> None:
    tier = answers.get("data_sql_tier", "General Purpose")
    tier_map = {
        "Basic / Burstable (B-series)": "burstable",
        "General Purpose": "general_purpose",
        "Business Critical / Memory-Optimized": "business_critical",
        "Hyperscale": "hyperscale",
    }
    iac["sql_compute_tier"] = tier_map.get(tier, "general_purpose")

    for m in mappings:
        azure = m.get("azure_service", "")
        if any(db in azure for db in ["SQL Database", "PostgreSQL", "MySQL"]):
            m["notes"] = f"{m.get('notes', '')} | Compute tier: {iac['sql_compute_tier']}"


def _apply_streaming(
    answers: Answers,
    mappings: list[dict],
    iac: dict,
) -> None:
    engine = answers.get("data_streaming_engine", "Azure Event Hubs + Stream Analytics")
    iac["streaming_engine"] = engine

    for m in mappings:
        src = m.get("source_service", "") or ""
        m.get("azure_service", "") or ""
        if any(k in src for k in ["Kinesis", "MSK"]):
            if "Kafka" in engine:
                m["azure_service"] = "Azure Event Hubs (Kafka protocol)"
                m["notes"] = f"{m.get('notes', '')} | Kafka surface enabled"
            elif "Spark" in engine:
                m["azure_service"] = "Azure Event Hubs + Spark Structured Streaming"
                m["notes"] = f"{m.get('notes', '')} | Spark Structured Streaming"


def _apply_iot(
    answers: Answers,
    mappings: list[dict],
    warnings: list[str],
    iac: dict,
) -> None:
    volume = answers.get("iot_message_volume")
    edge = answers.get("iot_edge_computing")
    device_scale = answers.get("iot_device_scale")
    digital_twins = answers.get("iot_digital_twins")

    if volume:
        volume_tier = {
            "<1 M messages/day": "S1",
            "1 M–100 M messages/day": "S2",
            ">100 M messages/day": "S3",
        }
        iac["iot_hub_tier"] = volume_tier.get(volume, "S2")
        if volume == ">100 M messages/day":
            iac["iot_hub_units"] = 10
            warnings.append(
                "High IoT volume (>100 M/day) — IoT Hub S3 with 10 units; "
                "consider IoT Hub device partitions and downstream Event Hubs scaling"
            )

    if edge and "IoT Edge" in edge:
        iac["iot_edge_enabled"] = True

    if device_scale:
        scale_map = {
            "<100 devices": 1,
            "100–10 K devices": 2,
            "10 K–1 M devices": 5,
            ">1 M devices": 10,
        }
        iac["iot_hub_units"] = max(iac.get("iot_hub_units", 1), scale_map.get(device_scale, 1))
        iac["iot_dps_enabled"] = device_scale != "<100 devices"
        if device_scale == ">1 M devices":
            warnings.append(
                ">1 M devices — recommend multiple IoT Hub instances behind "
                "DPS (Device Provisioning Service) for load distribution"
            )

    if digital_twins and "Digital Twins" in digital_twins:
        iac["digital_twins_enabled"] = True
        for m in mappings:
            src = m.get("source_service", "") or ""
            if "TwinMaker" in src:
                m["azure_service"] = "Azure Digital Twins"
                m["confidence"] = min(1.0, m.get("confidence", 0.8) + 0.05)
                m["notes"] = f"{m.get('notes', '')} | User confirmed digital twins"


def _apply_monitoring(
    answers: Answers,
    mappings: list[dict],
    warnings: list[str],
    iac: dict,
) -> None:
    depth = answers.get("ops_monitoring_depth", "Application Insights")
    cicd = answers.get("ops_cicd", "GitHub Actions")
    alerting = answers.get("ops_alerting")

    iac["monitoring_depth"] = depth
    iac["cicd_platform"] = cicd

    is_no_monitoring = "None" in depth or "no monitoring" in depth.lower()

    if is_no_monitoring:
        pass  # No monitoring resources added
    elif "Full observability" in depth:
        iac["managed_grafana"] = True
        iac["log_analytics_workspace"] = True
        iac["application_insights"] = True
        warnings.append(
            "Full observability stack — Azure Managed Grafana + Log Analytics "
            "+ Application Insights will be provisioned"
        )
    elif "Sentinel" in depth:
        iac["sentinel_enabled"] = True
        iac["log_analytics_workspace"] = True
        warnings.append(
            "Microsoft Sentinel SIEM enabled — all diagnostic logs will be "
            "forwarded to a centralised Log Analytics workspace"
        )
    elif "Application Insights" in depth:
        iac["application_insights"] = True
        iac["log_analytics_workspace"] = True
    else:
        iac["log_analytics_workspace"] = True

    if cicd == "Azure DevOps Pipelines":
        iac["azure_devops_project"] = True
    elif cicd == "GitHub Actions":
        iac["github_actions"] = True

    if alerting and not is_no_monitoring:
        if "None" not in alerting and "no alerts" not in alerting.lower():
            iac["alerting_channel"] = alerting


def _apply_containers(
    answers: Answers,
    mappings: list[dict],
    iac: dict,
) -> None:
    k8s_tier = answers.get("k8s_cluster_tier")
    node_vm = answers.get("k8s_node_pool")
    container_runtime = answers.get("container_runtime_pref")

    if k8s_tier:
        tier_map = {
            "Free tier (dev/test)": "free",
            "Standard (production SLA, 99.95 %)": "standard",
            "Premium (mission-critical, 99.99 %)": "premium",
        }
        iac["aks_tier"] = tier_map.get(k8s_tier, "standard")

    if node_vm:
        vm_map = {
            "Standard_B2s (burstable, cost-optimized)": "Standard_B2s",
            "Standard_D4s_v5 (general purpose)": "Standard_D4s_v5",
            "Standard_E8s_v5 (memory-optimized)": "Standard_E8s_v5",
            "Standard_F8s_v2 (compute-optimized)": "Standard_F8s_v2",
            "Standard_NC6s_v3 (GPU)": "Standard_NC6s_v3",
        }
        iac["aks_default_vm_size"] = vm_map.get(node_vm, "Standard_D4s_v5")

    if container_runtime:
        runtime_map = {
            "AKS (full Kubernetes)": "AKS",
            "Azure Container Apps (serverless Kubernetes)": "Container Apps",
            "Azure Container Instances (simple single-container)": "Container Instances",
            "Azure App Service (containers on PaaS)": "App Service",
        }
        target = runtime_map.get(container_runtime, "Container Apps")
        iac["container_platform"] = target

        # Remap ECS / Fargate / App Runner targets
        for m in mappings:
            src = m.get("source_service", "") or ""
            if any(svc in src for svc in ["ECS", "Fargate", "App Runner"]):
                azure = m.get("azure_service", "")
                if any(frag in azure for frag in [
                    "Container Instances", "Container Apps", "App Service",
                ]):
                    m["azure_service"] = f"Azure {target}"
                    m["notes"] = f"{m.get('notes', '')} | User selected: {target}"


def _apply_ml(
    answers: Answers,
    mappings: list[dict],
    iac: dict,
) -> None:
    workspace = answers.get("ml_workspace_tier")
    compute = answers.get("ml_compute_target")

    if workspace:
        tier_map = {
            "Basic (notebook-only experimentation)": "basic",
            "Enterprise (managed endpoints, pipelines, AutoML)": "enterprise",
        }
        iac["aml_workspace_tier"] = tier_map.get(workspace, "enterprise")

    if compute:
        compute_map = {
            "CPU clusters (general training)": "cpu",
            "GPU clusters (deep learning)": "gpu",
            "Spark pools (big-data ML)": "spark",
            "Serverless compute (AML managed)": "serverless",
        }
        iac["aml_compute_type"] = compute_map.get(compute, "gpu")

        for m in mappings:
            src = m.get("source_service", "") or ""
            if "SageMaker" in src:
                m["notes"] = f"{m.get('notes', '')} | Compute: {iac['aml_compute_type']}"


def _apply_iac_style(answers: Answers, iac: dict) -> None:
    style = answers.get("arch_iac_style", "Terraform (HCL)")
    style_map = {
        "Terraform (HCL)": "terraform",
        "Bicep": "bicep",
        "ARM Templates (JSON)": "arm",
        "Pulumi": "pulumi",
    }
    iac["iac_format"] = style_map.get(style, "terraform")


def _apply_deploy_region(answers: Answers, iac: dict) -> None:
    """Store the user's chosen deployment region for cost calculations."""
    from services.azure_pricing import display_to_arm
    region_display = answers.get("arch_deploy_region", "West Europe")
    iac["deploy_region"] = display_to_arm(region_display)
    iac["deploy_region_display"] = region_display


def _apply_encryption(
    answers: Answers,
    mappings: list[dict],
    warnings: list[str],
    iac: dict,
) -> None:
    pref = answers.get("sec_encryption", "Platform-managed keys (default)")

    if "Customer-managed" in pref:
        iac["cmk_enabled"] = True
        iac["key_vault_required"] = True
        if "HSM" in pref:
            iac["hsm_backed_keys"] = True
            warnings.append(
                "HSM-backed customer-managed keys — Azure Key Vault Managed HSM "
                "or Dedicated HSM will be provisioned"
            )
        else:
            warnings.append(
                "Customer-managed keys — Azure Key Vault will be provisioned; "
                "all storage, databases, and disks configured with CMK"
            )
        for m in mappings:
            azure = m.get("azure_service", "")
            if any(svc in azure for svc in [
                "Blob", "ADLS", "Data Lake", "SQL", "Cosmos",
                "Redis", "Managed Disk", "Functions",
            ]):
                m["notes"] = f"{m.get('notes', '')} | Encryption: CMK via Key Vault"
    else:
        iac["cmk_enabled"] = False
