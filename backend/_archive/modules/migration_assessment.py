"""
Migration Complexity Scoring — Issue #65

Provides per-service migration complexity scores, recommended migration tools,
and migration approach recommendations. Integrates with the cross-cloud
mappings and migration runbook generator.

Usage:
    from migration_assessment import assess_migration_complexity

    result = assess_migration_complexity(analysis)
    # → { overall_score, risk_level, services: [...], recommendations: [...] }
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Complexity Metadata — per-service migration complexity
# ─────────────────────────────────────────────────────────────
# complexity: 1 (trivial) to 5 (very hard)
# migration_tool: recommended Azure tool
# migration_approach: recommended strategy (rehost / replatform / refactor)
# estimated_hours: effort estimate per instance

SERVICE_COMPLEXITY: Dict[str, Dict[str, Any]] = {
    # ── Compute ──────────────────────────────────────────────
    "EC2": {
        "complexity": 2,
        "migration_tool": "Azure Migrate / Azure Site Recovery",
        "migration_approach": "rehost",
        "estimated_hours": 4,
        "notes": "Lift-and-shift via ASR; may need driver / agent updates",
    },
    "Lambda": {
        "complexity": 3,
        "migration_tool": "Manual migration",
        "migration_approach": "replatform",
        "estimated_hours": 8,
        "notes": "Rewrite triggers and bindings for Azure Functions; runtime parity varies",
    },
    "ECS": {
        "complexity": 3,
        "migration_tool": "Manual migration",
        "migration_approach": "replatform",
        "estimated_hours": 6,
        "notes": "Convert ECS task definitions to Azure Container Apps or ACI templates",
    },
    "EKS": {
        "complexity": 2,
        "migration_tool": "Azure Migrate (containers)",
        "migration_approach": "replatform",
        "estimated_hours": 8,
        "notes": "K8s workloads are portable; update ingress, storage classes, and service mesh",
    },
    "Fargate": {
        "complexity": 2,
        "migration_tool": "Manual migration",
        "migration_approach": "replatform",
        "estimated_hours": 4,
        "notes": "Map to Azure Container Apps; convert task definitions to container app specs",
    },
    "App Runner": {
        "complexity": 1,
        "migration_tool": "Manual migration",
        "migration_approach": "replatform",
        "estimated_hours": 2,
        "notes": "Simple containerized workload — deploy to Container Apps with minimal changes",
    },
    "Elastic Beanstalk": {
        "complexity": 2,
        "migration_tool": "Manual migration",
        "migration_approach": "replatform",
        "estimated_hours": 4,
        "notes": "Repackage for Azure App Service; environment variables and config differ",
    },
    "Outposts": {
        "complexity": 5,
        "migration_tool": "Azure Arc / Azure Stack HCI",
        "migration_approach": "refactor",
        "estimated_hours": 40,
        "notes": "Hybrid infrastructure requires hardware assessment and Arc deployment",
    },
    "Batch": {
        "complexity": 2,
        "migration_tool": "Manual migration",
        "migration_approach": "replatform",
        "estimated_hours": 6,
        "notes": "Map job definitions to Azure Batch; pool configurations differ",
    },

    # ── Storage ──────────────────────────────────────────────
    "S3": {
        "complexity": 1,
        "migration_tool": "AzCopy / Azure Data Factory",
        "migration_approach": "rehost",
        "estimated_hours": 2,
        "notes": "AzCopy supports S3-to-Blob direct copy; update SDK calls",
    },
    "EFS": {
        "complexity": 2,
        "migration_tool": "Azure File Sync / rsync",
        "migration_approach": "rehost",
        "estimated_hours": 4,
        "notes": "Map NFS shares to Azure Files; SMB/NFS protocol selection",
    },
    "S3 Glacier": {
        "complexity": 1,
        "migration_tool": "AzCopy",
        "migration_approach": "rehost",
        "estimated_hours": 2,
        "notes": "Restore from Glacier first, then copy to Azure Archive Storage",
    },

    # ── Database ─────────────────────────────────────────────
    "RDS": {
        "complexity": 3,
        "migration_tool": "Azure Database Migration Service (DMS)",
        "migration_approach": "replatform",
        "estimated_hours": 12,
        "notes": "DMS supports online migration with minimal downtime; test stored procedures",
    },
    "Aurora": {
        "complexity": 3,
        "migration_tool": "Azure Database Migration Service (DMS)",
        "migration_approach": "replatform",
        "estimated_hours": 16,
        "notes": "Aurora-specific features (global DB, serverless) need Azure equivalents",
    },
    "DynamoDB": {
        "complexity": 4,
        "migration_tool": "Custom ETL / Azure Data Factory",
        "migration_approach": "refactor",
        "estimated_hours": 20,
        "notes": "Remodel DynamoDB to Cosmos DB; capacity model, indexes, and queries differ significantly",
    },
    "ElastiCache": {
        "complexity": 2,
        "migration_tool": "redis-cli / Azure Cache migration tool",
        "migration_approach": "replatform",
        "estimated_hours": 4,
        "notes": "Export RDB snapshot and import to Azure Cache for Redis",
    },
    "Redshift": {
        "complexity": 4,
        "migration_tool": "Azure Data Factory / COPY INTO",
        "migration_approach": "refactor",
        "estimated_hours": 24,
        "notes": "Migrate to Synapse Analytics; SQL dialect, distribution, and query patterns differ",
    },
    "Neptune": {
        "complexity": 4,
        "migration_tool": "Custom export/import",
        "migration_approach": "refactor",
        "estimated_hours": 20,
        "notes": "Export graph data and import to Cosmos DB Gremlin API; query translation required",
    },
    "DocumentDB": {
        "complexity": 3,
        "migration_tool": "mongodump/mongorestore",
        "migration_approach": "replatform",
        "estimated_hours": 8,
        "notes": "Use MongoDB tools to migrate to Cosmos DB MongoDB API; index strategy may differ",
    },

    # ── Networking ───────────────────────────────────────────
    "VPC": {
        "complexity": 3,
        "migration_tool": "Manual IaC translation",
        "migration_approach": "refactor",
        "estimated_hours": 8,
        "notes": "Redesign CIDR ranges, subnets, and route tables for Azure VNet topology",
    },
    "CloudFront": {
        "complexity": 2,
        "migration_tool": "Manual configuration",
        "migration_approach": "replatform",
        "estimated_hours": 4,
        "notes": "Migrate to Azure Front Door; configure origins, rules, and WAF policies",
    },
    "Route 53": {
        "complexity": 2,
        "migration_tool": "Azure CLI / Terraform",
        "migration_approach": "replatform",
        "estimated_hours": 4,
        "notes": "Export DNS zones and import to Azure DNS; update NS records at registrar",
    },
    "API Gateway": {
        "complexity": 3,
        "migration_tool": "Manual migration",
        "migration_approach": "replatform",
        "estimated_hours": 12,
        "notes": "Recreate APIs in Azure API Management; authorizers and custom domains differ",
    },
    "Direct Connect": {
        "complexity": 4,
        "migration_tool": "ExpressRoute provisioning",
        "migration_approach": "replatform",
        "estimated_hours": 40,
        "notes": "Provision ExpressRoute circuit; coordinate with carrier for cross-connect",
    },

    # ── Security ─────────────────────────────────────────────
    "IAM": {
        "complexity": 4,
        "migration_tool": "Manual policy translation",
        "migration_approach": "refactor",
        "estimated_hours": 16,
        "notes": "Translate IAM policies to Azure RBAC role assignments; identity model fundamentally differs",
    },
    "Cognito": {
        "complexity": 4,
        "migration_tool": "Manual migration",
        "migration_approach": "refactor",
        "estimated_hours": 16,
        "notes": "Migrate user pools to Entra External ID (B2C); auth flows and tokens differ",
    },
    "KMS": {
        "complexity": 2,
        "migration_tool": "Manual migration",
        "migration_approach": "replatform",
        "estimated_hours": 4,
        "notes": "Recreate key hierarchy in Azure Key Vault; re-encrypt data with new keys",
    },

    # ── AI/ML ────────────────────────────────────────────────
    "SageMaker": {
        "complexity": 4,
        "migration_tool": "Manual migration",
        "migration_approach": "refactor",
        "estimated_hours": 24,
        "notes": "Migrate models, pipelines, and endpoints to Azure ML; framework code is portable, platform code isn't",
    },
    "Bedrock": {
        "complexity": 2,
        "migration_tool": "Manual migration",
        "migration_approach": "replatform",
        "estimated_hours": 8,
        "notes": "Switch API calls to Azure OpenAI; prompt engineering is portable, APIs differ",
    },
    "Bedrock Agents": {
        "complexity": 3,
        "migration_tool": "Manual migration",
        "migration_approach": "refactor",
        "estimated_hours": 16,
        "notes": "Recreate agent definitions in Azure AI Agent Service; tool schemas and orchestration differ",
    },

    # ── Analytics ────────────────────────────────────────────
    "Kinesis": {
        "complexity": 3,
        "migration_tool": "Manual migration",
        "migration_approach": "replatform",
        "estimated_hours": 8,
        "notes": "Migrate to Azure Event Hubs; Kafka surface eases transition for Kafka clients",
    },
    "Glue": {
        "complexity": 3,
        "migration_tool": "Manual migration",
        "migration_approach": "replatform",
        "estimated_hours": 12,
        "notes": "Rewrite Glue jobs as Azure Data Factory pipelines; PySpark code is mostly portable",
    },
    "EMR": {
        "complexity": 3,
        "migration_tool": "Manual migration",
        "migration_approach": "replatform",
        "estimated_hours": 12,
        "notes": "Migrate to HDInsight or Databricks; Spark code is portable, cluster config differs",
    },
    "Athena": {
        "complexity": 2,
        "migration_tool": "Manual migration",
        "migration_approach": "replatform",
        "estimated_hours": 4,
        "notes": "Recreate queries in Synapse Serverless SQL; ANSI SQL is portable, external tables differ",
    },

    # ── Integration ──────────────────────────────────────────
    "SQS": {
        "complexity": 2,
        "migration_tool": "Manual migration",
        "migration_approach": "replatform",
        "estimated_hours": 4,
        "notes": "Switch to Azure Service Bus queues; message format and SDK calls differ",
    },
    "SNS": {
        "complexity": 2,
        "migration_tool": "Manual migration",
        "migration_approach": "replatform",
        "estimated_hours": 4,
        "notes": "Replace with Azure Event Grid or Notification Hubs",
    },
    "EventBridge": {
        "complexity": 3,
        "migration_tool": "Manual migration",
        "migration_approach": "replatform",
        "estimated_hours": 8,
        "notes": "Recreate event rules in Azure Event Grid; event schema translation required",
    },
    "Step Functions": {
        "complexity": 3,
        "migration_tool": "Manual migration",
        "migration_approach": "refactor",
        "estimated_hours": 12,
        "notes": "Convert state machine definitions to Azure Logic Apps or Durable Functions",
    },

    # ── IoT ──────────────────────────────────────────────────
    "IoT Core": {
        "complexity": 3,
        "migration_tool": "Manual migration",
        "migration_approach": "replatform",
        "estimated_hours": 12,
        "notes": "Migrate device registrations to IoT Hub; MQTT endpoints and device SDKs differ",
    },
    "IoT Greengrass": {
        "complexity": 4,
        "migration_tool": "Manual migration",
        "migration_approach": "refactor",
        "estimated_hours": 20,
        "notes": "Rewrite Greengrass components as IoT Edge modules; edge runtime differs significantly",
    },

    # ── Monitoring ───────────────────────────────────────────
    "CloudWatch": {
        "complexity": 2,
        "migration_tool": "Manual migration",
        "migration_approach": "replatform",
        "estimated_hours": 4,
        "notes": "Recreate dashboards and alarms in Azure Monitor; log query syntax differs (KQL vs CloudWatch Insights)",
    },

    # ── New categories (Issues #60-#67) ──────────────────────
    "EKS Anywhere": {
        "complexity": 4,
        "migration_tool": "Azure Arc-enabled Kubernetes",
        "migration_approach": "replatform",
        "estimated_hours": 20,
        "notes": "Onboard existing K8s clusters to Azure Arc; GitOps and policy management differ",
    },
    "Wavelength": {
        "complexity": 4,
        "migration_tool": "Azure Edge Zones",
        "migration_approach": "refactor",
        "estimated_hours": 24,
        "notes": "Telco edge deployment requires carrier partnership and network reconfiguration",
    },
    "Managed Grafana": {
        "complexity": 1,
        "migration_tool": "Grafana export/import",
        "migration_approach": "rehost",
        "estimated_hours": 2,
        "notes": "Export dashboards as JSON and import into Azure Managed Grafana",
    },
    "Managed Prometheus": {
        "complexity": 2,
        "migration_tool": "Manual migration",
        "migration_approach": "replatform",
        "estimated_hours": 4,
        "notes": "Configure Azure Monitor Prometheus endpoint; recording rules may need adjustment",
    },
    "DataZone": {
        "complexity": 3,
        "migration_tool": "Manual migration",
        "migration_approach": "replatform",
        "estimated_hours": 12,
        "notes": "Recreate data domains and governance policies in Microsoft Purview",
    },
    "Verified Access": {
        "complexity": 3,
        "migration_tool": "Manual migration",
        "migration_approach": "replatform",
        "estimated_hours": 8,
        "notes": "Migrate to Entra Private Access; trust policies and identity provider integration differ",
    },
    "Security Lake": {
        "complexity": 3,
        "migration_tool": "Manual migration",
        "migration_approach": "replatform",
        "estimated_hours": 12,
        "notes": "Configure Microsoft Sentinel data connectors; OCSF schema mapping to Sentinel tables",
    },
}

# Fall-back complexity by category
CATEGORY_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "Compute":          {"complexity": 2, "migration_tool": "Azure Migrate",                "migration_approach": "rehost",      "estimated_hours": 4},
    "Storage":          {"complexity": 1, "migration_tool": "AzCopy / Azure Data Factory",  "migration_approach": "rehost",      "estimated_hours": 2},
    "Database":         {"complexity": 3, "migration_tool": "Azure DMS",                    "migration_approach": "replatform",  "estimated_hours": 12},
    "Networking":       {"complexity": 3, "migration_tool": "Manual IaC translation",       "migration_approach": "refactor",    "estimated_hours": 8},
    "Security":         {"complexity": 3, "migration_tool": "Manual migration",             "migration_approach": "refactor",    "estimated_hours": 8},
    "AI/ML":            {"complexity": 3, "migration_tool": "Manual migration",             "migration_approach": "replatform",  "estimated_hours": 12},
    "Analytics":        {"complexity": 3, "migration_tool": "Manual migration",             "migration_approach": "replatform",  "estimated_hours": 8},
    "Integration":      {"complexity": 2, "migration_tool": "Manual migration",             "migration_approach": "replatform",  "estimated_hours": 4},
    "DevTools":         {"complexity": 2, "migration_tool": "Manual migration",             "migration_approach": "replatform",  "estimated_hours": 4},
    "Management":       {"complexity": 2, "migration_tool": "Manual migration",             "migration_approach": "replatform",  "estimated_hours": 4},
    "IoT":              {"complexity": 4, "migration_tool": "Manual migration",             "migration_approach": "refactor",    "estimated_hours": 16},
    "Media":            {"complexity": 3, "migration_tool": "Manual migration",             "migration_approach": "replatform",  "estimated_hours": 8},
    "Migration":        {"complexity": 1, "migration_tool": "Azure Migrate",                "migration_approach": "rehost",      "estimated_hours": 2},
    "Business":         {"complexity": 2, "migration_tool": "Manual migration",             "migration_approach": "replatform",  "estimated_hours": 4},
    "Hybrid":           {"complexity": 4, "migration_tool": "Azure Arc / Azure Stack",      "migration_approach": "refactor",    "estimated_hours": 20},
    "Edge":             {"complexity": 4, "migration_tool": "Azure Edge Zones / Stack Edge", "migration_approach": "refactor",   "estimated_hours": 16},
    "Observability":    {"complexity": 2, "migration_tool": "Manual migration",             "migration_approach": "replatform",  "estimated_hours": 4},
    "Data Governance":  {"complexity": 3, "migration_tool": "Microsoft Purview",            "migration_approach": "replatform",  "estimated_hours": 8},
    "Zero Trust":       {"complexity": 3, "migration_tool": "Manual migration",             "migration_approach": "refactor",    "estimated_hours": 8},
}


def _get_service_complexity(service_name: str, category: str) -> Dict[str, Any]:
    """Look up migration complexity metadata for a service."""
    if service_name in SERVICE_COMPLEXITY:
        return SERVICE_COMPLEXITY[service_name]
    return CATEGORY_DEFAULTS.get(category, {
        "complexity": 3,
        "migration_tool": "Manual migration",
        "migration_approach": "replatform",
        "estimated_hours": 8,
    })


def assess_migration_complexity(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """
    Assess migration complexity for all services in an architecture analysis.

    Args:
        analysis: The diagram analysis result containing mappings with source
                  services, Azure targets, categories, and confidence scores.

    Returns:
        Dict with overall_score (1-5), risk_level, per-service assessments,
        summary statistics, and recommendations.
    """
    mappings = analysis.get("mappings", [])
    if not mappings:
        return {
            "overall_score": 0,
            "risk_level": "unknown",
            "total_services": 0,
            "services": [],
            "summary": {},
            "recommendations": ["No services detected — upload an architecture diagram first."],
        }

    service_assessments: List[Dict[str, Any]] = []
    total_complexity = 0
    total_hours = 0
    approach_counts: Dict[str, int] = {"rehost": 0, "replatform": 0, "refactor": 0}

    for mapping in mappings:
        source = mapping.get("source_service", mapping.get("aws", ""))
        azure = mapping.get("azure_service", mapping.get("azure", ""))
        category = mapping.get("category", "Unknown")
        confidence = mapping.get("confidence", 0.85)

        meta = _get_service_complexity(source, category)
        # Adjust complexity if confidence is low
        adjusted_complexity = meta["complexity"]
        if confidence < 0.75:
            adjusted_complexity = min(5, adjusted_complexity + 1)

        service_assessments.append({
            "source_service": source,
            "azure_service": azure,
            "category": category,
            "confidence": confidence,
            "complexity": adjusted_complexity,
            "migration_tool": meta["migration_tool"],
            "migration_approach": meta["migration_approach"],
            "estimated_hours": meta["estimated_hours"],
            "notes": meta.get("notes", ""),
        })

        total_complexity += adjusted_complexity
        total_hours += meta["estimated_hours"]
        approach_counts[meta["migration_approach"]] = (
            approach_counts.get(meta["migration_approach"], 0) + 1
        )

    # Calculate overall score (weighted average)
    overall_score = round(total_complexity / len(service_assessments), 1) if service_assessments else 0

    # Determine risk level
    if overall_score >= 4:
        risk_level = "critical"
    elif overall_score >= 3:
        risk_level = "high"
    elif overall_score >= 2:
        risk_level = "medium"
    else:
        risk_level = "low"

    # Count by complexity bucket
    complexity_distribution = {
        "trivial (1)": sum(1 for s in service_assessments if s["complexity"] == 1),
        "easy (2)": sum(1 for s in service_assessments if s["complexity"] == 2),
        "moderate (3)": sum(1 for s in service_assessments if s["complexity"] == 3),
        "hard (4)": sum(1 for s in service_assessments if s["complexity"] == 4),
        "very_hard (5)": sum(1 for s in service_assessments if s["complexity"] == 5),
    }

    # Generate recommendations
    recommendations: List[str] = []
    hard_services = [s for s in service_assessments if s["complexity"] >= 4]
    if hard_services:
        names = ", ".join(s["source_service"] for s in hard_services[:5])
        recommendations.append(
            f"High-complexity services ({names}) may benefit from a proof-of-concept migration before full cutover."
        )

    low_confidence = [s for s in service_assessments if s["confidence"] < 0.75]
    if low_confidence:
        recommendations.append(
            f"{len(low_confidence)} service(s) have low mapping confidence — validate Azure equivalents manually."
        )

    if approach_counts.get("refactor", 0) > len(service_assessments) * 0.3:
        recommendations.append(
            "Over 30% of services require refactoring. Consider a phased migration with rehost-first for quick wins."
        )

    if total_hours > 200:
        recommendations.append(
            f"Total estimated effort is {total_hours}h ({round(total_hours / 8)} working days). "
            "Consider parallel work-streams or engaging Microsoft FastTrack."
        )

    # Sort services by complexity descending (hardest first)
    service_assessments.sort(key=lambda s: (-s["complexity"], s["source_service"]))

    return {
        "overall_score": overall_score,
        "risk_level": risk_level,
        "total_services": len(service_assessments),
        "total_estimated_hours": total_hours,
        "estimated_work_days": round(total_hours / 8),
        "primary_approach": max(approach_counts, key=approach_counts.get) if approach_counts else "replatform",
        "approach_breakdown": approach_counts,
        "complexity_distribution": complexity_distribution,
        "services": service_assessments,
        "recommendations": recommendations,
    }
