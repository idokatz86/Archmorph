"""
Multi-Cloud Cost Comparison Service (#499).

Estimates monthly costs for an Archmorph analysis schema across AWS,
Azure, and GCP using hardcoded pricing tables for common service
categories.  Returns side-by-side TCO with savings recommendations.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Pricing tables (monthly USD, representative on-demand pricing)
# ─────────────────────────────────────────────────────────────

PRICING_CATALOG: Dict[str, Dict[str, Dict[str, Any]]] = {
    "Compute": {
        "small_vm": {
            "description": "2 vCPU / 4 GB RAM general-purpose VM",
            "aws": {"service": "EC2 t3.medium", "monthly_usd": 30.37},
            "azure": {"service": "Azure B2s", "monthly_usd": 30.66},
            "gcp": {"service": "e2-medium", "monthly_usd": 24.27},
        },
        "medium_vm": {
            "description": "4 vCPU / 16 GB RAM general-purpose VM",
            "aws": {"service": "EC2 m6i.xlarge", "monthly_usd": 138.24},
            "azure": {"service": "Azure D4s v5", "monthly_usd": 140.16},
            "gcp": {"service": "n2-standard-4", "monthly_usd": 131.40},
        },
        "large_vm": {
            "description": "8 vCPU / 32 GB RAM general-purpose VM",
            "aws": {"service": "EC2 m6i.2xlarge", "monthly_usd": 276.48},
            "azure": {"service": "Azure D8s v5", "monthly_usd": 280.32},
            "gcp": {"service": "n2-standard-8", "monthly_usd": 262.80},
        },
        "serverless_function": {
            "description": "Serverless function (1M invocations/month, 128MB, 200ms avg)",
            "aws": {"service": "Lambda", "monthly_usd": 3.54},
            "azure": {"service": "Azure Functions Consumption", "monthly_usd": 3.20},
            "gcp": {"service": "Cloud Functions", "monthly_usd": 4.00},
        },
        "container_service": {
            "description": "Managed container orchestration (small cluster, 3 nodes)",
            "aws": {"service": "ECS Fargate (3 tasks, 1vCPU/2GB)", "monthly_usd": 107.59},
            "azure": {"service": "Container Apps (3 replicas, 1vCPU/2GB)", "monthly_usd": 96.36},
            "gcp": {"service": "Cloud Run (3 instances, 1vCPU/2GB)", "monthly_usd": 98.45},
        },
        "kubernetes": {
            "description": "Managed Kubernetes (3-node cluster, 4vCPU/16GB per node)",
            "aws": {"service": "EKS + 3x m6i.xlarge", "monthly_usd": 487.72},
            "azure": {"service": "AKS + 3x D4s v5", "monthly_usd": 420.48},
            "gcp": {"service": "GKE + 3x n2-standard-4", "monthly_usd": 467.20},
        },
    },
    "Storage": {
        "object_storage": {
            "description": "100 GB object storage (standard tier)",
            "aws": {"service": "S3 Standard", "monthly_usd": 2.30},
            "azure": {"service": "Blob Storage Hot", "monthly_usd": 2.08},
            "gcp": {"service": "Cloud Storage Standard", "monthly_usd": 2.60},
        },
        "block_storage": {
            "description": "100 GB SSD block storage",
            "aws": {"service": "EBS gp3", "monthly_usd": 8.00},
            "azure": {"service": "Premium SSD P10", "monthly_usd": 17.92},
            "gcp": {"service": "Persistent Disk SSD", "monthly_usd": 17.00},
        },
        "file_storage": {
            "description": "100 GB managed file share",
            "aws": {"service": "EFS Standard", "monthly_usd": 30.00},
            "azure": {"service": "Azure Files Premium", "monthly_usd": 16.00},
            "gcp": {"service": "Filestore Basic HDD", "monthly_usd": 20.00},
        },
    },
    "Database": {
        "relational_small": {
            "description": "Managed SQL DB — 2 vCPU / 8 GB / 100 GB storage",
            "aws": {"service": "RDS db.t3.large (PostgreSQL)", "monthly_usd": 118.98},
            "azure": {"service": "Azure SQL S3", "monthly_usd": 150.38},
            "gcp": {"service": "Cloud SQL db-custom-2-8192", "monthly_usd": 128.47},
        },
        "relational_medium": {
            "description": "Managed SQL DB — 4 vCPU / 16 GB / 500 GB storage",
            "aws": {"service": "RDS db.m6i.xlarge (PostgreSQL)", "monthly_usd": 262.80},
            "azure": {"service": "Azure SQL P2", "monthly_usd": 450.56},
            "gcp": {"service": "Cloud SQL db-custom-4-16384", "monthly_usd": 285.94},
        },
        "nosql": {
            "description": "Managed NoSQL — 100 GB, 1000 RU/s or equivalent",
            "aws": {"service": "DynamoDB (25 WCU / 25 RCU)", "monthly_usd": 28.49},
            "azure": {"service": "Cosmos DB (1000 RU/s)", "monthly_usd": 58.40},
            "gcp": {"service": "Firestore", "monthly_usd": 18.26},
        },
        "cache": {
            "description": "Managed Redis cache — 6 GB",
            "aws": {"service": "ElastiCache cache.m6g.large", "monthly_usd": 109.50},
            "azure": {"service": "Azure Cache for Redis C2", "monthly_usd": 101.84},
            "gcp": {"service": "Memorystore for Redis 6GB", "monthly_usd": 146.00},
        },
    },
    "Networking": {
        "load_balancer": {
            "description": "Application Load Balancer (basic)",
            "aws": {"service": "ALB", "monthly_usd": 22.27},
            "azure": {"service": "Application Gateway Basic", "monthly_usd": 18.98},
            "gcp": {"service": "HTTP(S) Load Balancer", "monthly_usd": 18.26},
        },
        "cdn": {
            "description": "CDN — 1 TB transfer/month",
            "aws": {"service": "CloudFront", "monthly_usd": 85.00},
            "azure": {"service": "Azure CDN Standard", "monthly_usd": 74.75},
            "gcp": {"service": "Cloud CDN", "monthly_usd": 80.00},
        },
        "dns": {
            "description": "Managed DNS zone + 1M queries/month",
            "aws": {"service": "Route 53", "monthly_usd": 0.90},
            "azure": {"service": "Azure DNS", "monthly_usd": 0.90},
            "gcp": {"service": "Cloud DNS", "monthly_usd": 0.80},
        },
        "api_gateway": {
            "description": "API Gateway — 1M requests/month",
            "aws": {"service": "API Gateway REST", "monthly_usd": 3.50},
            "azure": {"service": "API Management Consumption", "monthly_usd": 3.50},
            "gcp": {"service": "API Gateway", "monthly_usd": 3.00},
        },
        "vpc": {
            "description": "Virtual network / VPC (no data transfer)",
            "aws": {"service": "VPC", "monthly_usd": 0.00},
            "azure": {"service": "VNet", "monthly_usd": 0.00},
            "gcp": {"service": "VPC", "monthly_usd": 0.00},
        },
        "nat_gateway": {
            "description": "NAT Gateway + 100 GB processed",
            "aws": {"service": "NAT Gateway", "monthly_usd": 37.74},
            "azure": {"service": "NAT Gateway", "monthly_usd": 32.85},
            "gcp": {"service": "Cloud NAT", "monthly_usd": 31.39},
        },
    },
    "Messaging": {
        "message_queue": {
            "description": "Managed message queue — 1M messages/month",
            "aws": {"service": "SQS Standard", "monthly_usd": 0.40},
            "azure": {"service": "Service Bus Basic", "monthly_usd": 0.05},
            "gcp": {"service": "Pub/Sub", "monthly_usd": 0.60},
        },
        "event_streaming": {
            "description": "Event streaming — 1 throughput unit, 1M events/month",
            "aws": {"service": "Kinesis Data Streams (1 shard)", "monthly_usd": 36.00},
            "azure": {"service": "Event Hubs Standard (1 TU)", "monthly_usd": 22.34},
            "gcp": {"service": "Pub/Sub (high throughput)", "monthly_usd": 30.00},
        },
    },
    "Security": {
        "secrets_manager": {
            "description": "Secrets/Key management — 10 secrets",
            "aws": {"service": "Secrets Manager", "monthly_usd": 4.00},
            "azure": {"service": "Key Vault (Standard)", "monthly_usd": 0.30},
            "gcp": {"service": "Secret Manager", "monthly_usd": 0.60},
        },
        "identity": {
            "description": "Managed identity / IAM (base cost)",
            "aws": {"service": "IAM", "monthly_usd": 0.00},
            "azure": {"service": "Entra ID Free", "monthly_usd": 0.00},
            "gcp": {"service": "IAM", "monthly_usd": 0.00},
        },
        "waf": {
            "description": "Web Application Firewall — basic rules",
            "aws": {"service": "AWS WAF", "monthly_usd": 20.00},
            "azure": {"service": "Azure WAF on App Gateway", "monthly_usd": 43.80},
            "gcp": {"service": "Cloud Armor", "monthly_usd": 25.00},
        },
    },
    "Monitoring": {
        "logging": {
            "description": "Log analytics — 5 GB/month ingestion",
            "aws": {"service": "CloudWatch Logs", "monthly_usd": 2.52},
            "azure": {"service": "Log Analytics", "monthly_usd": 11.58},
            "gcp": {"service": "Cloud Logging", "monthly_usd": 2.50},
        },
        "apm": {
            "description": "Application performance monitoring (basic)",
            "aws": {"service": "X-Ray (100K traces)", "monthly_usd": 5.00},
            "azure": {"service": "Application Insights", "monthly_usd": 3.29},
            "gcp": {"service": "Cloud Trace (100K spans)", "monthly_usd": 2.00},
        },
    },
    "AI/ML": {
        "inference_endpoint": {
            "description": "Model inference endpoint (GPU-based, basic)",
            "aws": {"service": "SageMaker ml.g4dn.xlarge", "monthly_usd": 399.96},
            "azure": {"service": "Azure ML NC4as T4 v3", "monthly_usd": 383.25},
            "gcp": {"service": "Vertex AI n1-standard-4 + T4", "monthly_usd": 372.00},
        },
    },
}

# ── Service type → sizing tier heuristic map ──
_SERVICE_SIZE_HINTS: Dict[str, str] = {
    # Compute
    "aws_instance": "medium_vm",
    "aws_autoscaling_group": "medium_vm",
    "aws_lambda_function": "serverless_function",
    "aws_ecs_cluster": "container_service",
    "aws_ecs_service": "container_service",
    "aws_eks_cluster": "kubernetes",
    "azurerm_virtual_machine": "medium_vm",
    "azurerm_linux_virtual_machine": "medium_vm",
    "azurerm_windows_virtual_machine": "medium_vm",
    "azurerm_function_app": "serverless_function",
    "azurerm_linux_function_app": "serverless_function",
    "azurerm_container_app": "container_service",
    "azurerm_kubernetes_cluster": "kubernetes",
    "azurerm_linux_web_app": "small_vm",
    "azurerm_app_service": "small_vm",
    "google_compute_instance": "medium_vm",
    "google_cloud_run_service": "container_service",
    "google_cloudfunctions_function": "serverless_function",
    "google_container_cluster": "kubernetes",
    # Storage
    "aws_s3_bucket": "object_storage",
    "aws_ebs_volume": "block_storage",
    "aws_efs_file_system": "file_storage",
    "azurerm_storage_account": "object_storage",
    "azurerm_managed_disk": "block_storage",
    "azurerm_storage_share": "file_storage",
    "google_storage_bucket": "object_storage",
    "google_compute_disk": "block_storage",
    # Database
    "aws_db_instance": "relational_small",
    "aws_rds_cluster": "relational_medium",
    "aws_dynamodb_table": "nosql",
    "aws_elasticache_cluster": "cache",
    "azurerm_mssql_database": "relational_small",
    "azurerm_postgresql_flexible_server": "relational_small",
    "azurerm_cosmosdb_account": "nosql",
    "azurerm_redis_cache": "cache",
    "google_sql_database_instance": "relational_small",
    "google_redis_instance": "cache",
    "google_firestore_database": "nosql",
    # Networking
    "aws_lb": "load_balancer",
    "aws_alb": "load_balancer",
    "aws_cloudfront_distribution": "cdn",
    "aws_route53_zone": "dns",
    "aws_api_gateway_rest_api": "api_gateway",
    "aws_vpc": "vpc",
    "aws_nat_gateway": "nat_gateway",
    "azurerm_lb": "load_balancer",
    "azurerm_application_gateway": "load_balancer",
    "azurerm_cdn_profile": "cdn",
    "azurerm_dns_zone": "dns",
    "azurerm_api_management": "api_gateway",
    "azurerm_virtual_network": "vpc",
    "google_compute_forwarding_rule": "load_balancer",
    "google_dns_managed_zone": "dns",
    "google_compute_router_nat": "nat_gateway",
    # Messaging
    "aws_sqs_queue": "message_queue",
    "aws_sns_topic": "message_queue",
    "aws_kinesis_stream": "event_streaming",
    "azurerm_servicebus_queue": "message_queue",
    "azurerm_eventhub": "event_streaming",
    "google_pubsub_topic": "message_queue",
    # Security
    "aws_kms_key": "secrets_manager",
    "aws_secretsmanager_secret": "secrets_manager",
    "aws_iam_role": "identity",
    "aws_wafv2_web_acl": "waf",
    "azurerm_key_vault": "secrets_manager",
    "azurerm_user_assigned_identity": "identity",
    "google_secret_manager_secret": "secrets_manager",
    "google_service_account": "identity",
    # Monitoring
    "aws_cloudwatch_log_group": "logging",
    "azurerm_log_analytics_workspace": "logging",
    "azurerm_application_insights": "apm",
    "google_monitoring_alert_policy": "apm",
    # AI/ML
    "aws_sagemaker_endpoint": "inference_endpoint",
    "azurerm_cognitive_account": "inference_endpoint",
    "google_vertex_ai_endpoint": "inference_endpoint",
}


def _resolve_tier(service_type: str, category: str) -> Optional[str]:
    """Map a resource type to a pricing tier within its category."""
    if service_type in _SERVICE_SIZE_HINTS:
        return _SERVICE_SIZE_HINTS[service_type]

    # Fallback: pick first tier in the category
    cat_pricing = PRICING_CATALOG.get(category, {})
    if cat_pricing:
        return next(iter(cat_pricing))
    return None


def estimate_costs(zones: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Estimate monthly costs on AWS, Azure, and GCP for an analysis schema.

    Parameters
    ----------
    zones : list
        Archmorph analysis zones, each with ``name`` (category) and
        ``services`` list.

    Returns
    -------
    dict
        Side-by-side cost comparison with TCO and savings recommendations.
    """
    totals = {"aws": 0.0, "azure": 0.0, "gcp": 0.0}
    line_items: List[Dict[str, Any]] = []

    for zone in zones:
        category = zone.get("name", "Other")
        cat_pricing = PRICING_CATALOG.get(category, {})

        for svc in zone.get("services", []):
            svc_type = svc.get("type", "")
            svc_name = svc.get("name", svc_type)

            tier = _resolve_tier(svc_type, category)
            if not tier or tier not in cat_pricing:
                line_items.append({
                    "service": svc_name,
                    "type": svc_type,
                    "category": category,
                    "tier": None,
                    "aws": None,
                    "azure": None,
                    "gcp": None,
                    "note": "No pricing data available for this resource type",
                })
                continue

            pricing = cat_pricing[tier]
            aws_cost = pricing["aws"]["monthly_usd"]
            azure_cost = pricing["azure"]["monthly_usd"]
            gcp_cost = pricing["gcp"]["monthly_usd"]

            totals["aws"] += aws_cost
            totals["azure"] += azure_cost
            totals["gcp"] += gcp_cost

            line_items.append({
                "service": svc_name,
                "type": svc_type,
                "category": category,
                "tier": tier,
                "description": pricing["description"],
                "aws": {"service": pricing["aws"]["service"], "monthly_usd": aws_cost},
                "azure": {"service": pricing["azure"]["service"], "monthly_usd": azure_cost},
                "gcp": {"service": pricing["gcp"]["service"], "monthly_usd": gcp_cost},
            })

    # Annual TCO
    annual = {cloud: round(monthly * 12, 2) for cloud, monthly in totals.items()}

    # Savings recommendations
    cheapest = min(totals, key=totals.get)  # type: ignore[arg-type]
    recommendations = _build_recommendations(totals, line_items)

    return {
        "monthly_estimate": {k: round(v, 2) for k, v in totals.items()},
        "annual_estimate": annual,
        "cheapest_cloud": cheapest,
        "line_items": line_items,
        "total_services_estimated": len([li for li in line_items if li.get("tier")]),
        "total_services_unpriced": len([li for li in line_items if not li.get("tier")]),
        "recommendations": recommendations,
    }


def _build_recommendations(
    totals: Dict[str, float],
    line_items: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """Generate per-cloud savings recommendations."""
    recs: List[Dict[str, str]] = []

    clouds = ["aws", "azure", "gcp"]
    cloud_labels = {"aws": "AWS", "azure": "Azure", "gcp": "GCP"}

    # Overall cheapest
    cheapest = min(totals, key=totals.get)  # type: ignore[arg-type]
    most_expensive = max(totals, key=totals.get)  # type: ignore[arg-type]
    if totals[most_expensive] > 0:
        saving = totals[most_expensive] - totals[cheapest]
        pct = (saving / totals[most_expensive]) * 100
        recs.append({
            "type": "overall",
            "message": (
                f"Moving to {cloud_labels[cheapest]} could save "
                f"~${saving:.2f}/month ({pct:.1f}%) vs {cloud_labels[most_expensive]}"
            ),
        })

    # Per-category best picks
    category_costs: Dict[str, Dict[str, float]] = {}
    for li in line_items:
        if not li.get("tier"):
            continue
        cat = li["category"]
        if cat not in category_costs:
            category_costs[cat] = {c: 0.0 for c in clouds}
        for c in clouds:
            if li.get(c) and isinstance(li[c], dict):
                category_costs[cat][c] += li[c].get("monthly_usd", 0)

    for cat, costs in category_costs.items():
        best = min(costs, key=costs.get)  # type: ignore[arg-type]
        worst = max(costs, key=costs.get)  # type: ignore[arg-type]
        if costs[worst] > 0 and costs[worst] - costs[best] > 5:
            saving = costs[worst] - costs[best]
            recs.append({
                "type": "category",
                "category": cat,
                "message": (
                    f"{cat}: {cloud_labels[best]} is ~${saving:.2f}/month "
                    f"cheaper than {cloud_labels[worst]}"
                ),
            })

    # Reserved/committed-use discount reminder
    recs.append({
        "type": "tip",
        "message": (
            "All estimates use on-demand pricing. "
            "Reserved instances or committed-use discounts (1-3 year) "
            "can save 30-60% on compute and database workloads."
        ),
    })

    return recs


def get_pricing_catalog() -> Dict[str, Any]:
    """Return the full pricing catalog for frontend display."""
    return {
        "catalog": PRICING_CATALOG,
        "disclaimer": (
            "Prices are approximate on-demand rates in USD/month. "
            "Actual costs vary by region, usage, and commitment tier."
        ),
    }
