"""
Multi-Cloud Cost Comparison — Issue #66

Generates side-by-side cost estimates across AWS, Azure, and GCP for
services detected in an architecture analysis.

Usage:
    from cost_comparison import generate_cost_comparison

    result = generate_cost_comparison(analysis)
    # → { providers: {...}, services: [...], summary: {...} }
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


# ── Base monthly pricing (AWS reference) ─────────────────────
# Representative prices per service category (USD/month per instance).
# These are rough estimates used for comparative ratios, not quotes.
AWS_BASE_PRICES: Dict[str, float] = {
    "EC2": 150.0,
    "Lambda": 30.0,
    "ECS": 120.0,
    "EKS": 180.0,
    "Fargate": 100.0,
    "S3": 25.0,
    "EFS": 40.0,
    "RDS": 200.0,
    "Aurora": 280.0,
    "DynamoDB": 80.0,
    "ElastiCache": 100.0,
    "Redshift": 300.0,
    "VPC": 0.0,
    "CloudFront": 50.0,
    "Route 53": 10.0,
    "API Gateway": 40.0,
    "CloudWatch": 20.0,
    "IAM": 0.0,
    "Cognito": 30.0,
    "KMS": 5.0,
    "SQS": 15.0,
    "SNS": 10.0,
    "EventBridge": 10.0,
    "Step Functions": 25.0,
    "SageMaker": 250.0,
    "Bedrock": 200.0,
    "Kinesis": 60.0,
    "Glue": 80.0,
    "EMR": 180.0,
    "Athena": 20.0,
    "IoT Core": 50.0,
}

# ── Provider cost ratios relative to AWS = 1.0 ──────────────
# Sourced from public TCO studies (Flexera, Gartner, etc.)
AZURE_RATIO = 0.92     # Azure is typically ~8% cheaper overall
GCP_RATIO = 0.88       # GCP is typically ~12% cheaper overall

# Per-category adjustments (Azure-specific relative to base ratio)
AZURE_CATEGORY_ADJUSTMENTS: Dict[str, float] = {
    "Compute": 0.90,
    "Containers": 0.88,
    "Storage": 0.95,
    "Database": 0.93,
    "Networking": 1.0,
    "Security": 0.85,    # Many Azure security services are free / included
    "AI/ML": 0.90,
    "Analytics": 0.92,
    "Integration": 0.95,
    "IoT": 0.95,
    "Monitoring": 0.80,  # Azure Monitor included in many services
}

GCP_CATEGORY_ADJUSTMENTS: Dict[str, float] = {
    "Compute": 0.85,     # Sustained use discounts
    "Containers": 0.82,  # GKE Autopilot is competitive
    "Storage": 0.90,
    "Database": 0.95,
    "Networking": 0.95,
    "Security": 0.90,
    "AI/ML": 0.88,
    "Analytics": 0.85,   # BigQuery is very competitive
    "Integration": 1.0,
    "IoT": 1.0,
    "Monitoring": 0.85,
}

# Map source services → category for adjustment lookup
SERVICE_CATEGORY_MAP: Dict[str, str] = {
    "EC2": "Compute", "Lambda": "Compute", "Fargate": "Containers",
    "ECS": "Containers", "EKS": "Containers",
    "S3": "Storage", "EFS": "Storage",
    "RDS": "Database", "Aurora": "Database", "DynamoDB": "Database",
    "ElastiCache": "Database", "Redshift": "Database",
    "VPC": "Networking", "CloudFront": "Networking",
    "Route 53": "Networking", "API Gateway": "Networking",
    "IAM": "Security", "Cognito": "Security", "KMS": "Security",
    "SQS": "Integration", "SNS": "Integration",
    "EventBridge": "Integration", "Step Functions": "Integration",
    "SageMaker": "AI/ML", "Bedrock": "AI/ML",
    "Kinesis": "Analytics", "Glue": "Analytics",
    "EMR": "Analytics", "Athena": "Analytics",
    "CloudWatch": "Monitoring", "IoT Core": "IoT",
}


def _estimate_provider_cost(
    service_name: str,
    category: str,
    base_price: float,
    provider: str,
) -> float:
    """Estimate monthly cost for a service on a given provider."""
    if provider == "aws":
        return round(base_price, 2)

    if provider == "azure":
        ratio = AZURE_RATIO
        adjustment = AZURE_CATEGORY_ADJUSTMENTS.get(category, 1.0)
    elif provider == "gcp":
        ratio = GCP_RATIO
        adjustment = GCP_CATEGORY_ADJUSTMENTS.get(category, 1.0)
    else:
        return round(base_price, 2)

    return round(base_price * ratio * adjustment, 2)


def generate_cost_comparison(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate a multi-cloud cost comparison from an architecture analysis.

    Args:
        analysis: Diagram analysis containing mappings.

    Returns:
        Dict with per-service comparison, provider totals, and summary.
    """
    mappings = analysis.get("mappings", [])
    if not mappings:
        return {
            "providers": {"aws": 0, "azure": 0, "gcp": 0},
            "services": [],
            "total_services": 0,
            "cheapest_provider": "N/A",
            "summary": "No services detected.",
        }

    service_comparisons: List[Dict[str, Any]] = []
    totals = {"aws": 0.0, "azure": 0.0, "gcp": 0.0}
    seen: set = set()

    for mapping in mappings:
        source = mapping.get("source_service", mapping.get("aws", ""))
        azure_svc = mapping.get("azure_service", mapping.get("azure", ""))
        category = mapping.get("category", SERVICE_CATEGORY_MAP.get(source, "General"))

        if source in seen:
            continue
        seen.add(source)

        base = AWS_BASE_PRICES.get(source, 50.0)  # default $50 for unknown
        aws_cost = _estimate_provider_cost(source, category, base, "aws")
        azure_cost = _estimate_provider_cost(source, category, base, "azure")
        gcp_cost = _estimate_provider_cost(source, category, base, "gcp")

        cheapest = min(
            [("aws", aws_cost), ("azure", azure_cost), ("gcp", gcp_cost)],
            key=lambda x: x[1],
        )[0]

        service_comparisons.append({
            "source_service": source,
            "azure_service": azure_svc,
            "category": category,
            "aws_monthly": aws_cost,
            "azure_monthly": azure_cost,
            "gcp_monthly": gcp_cost,
            "cheapest_provider": cheapest,
            "azure_savings_vs_aws": round(
                ((aws_cost - azure_cost) / aws_cost * 100) if aws_cost > 0 else 0, 1
            ),
        })

        totals["aws"] += aws_cost
        totals["azure"] += azure_cost
        totals["gcp"] += gcp_cost

    # Round totals
    totals = {k: round(v, 2) for k, v in totals.items()}

    # Determine cheapest overall
    cheapest_provider = min(totals, key=totals.get) if any(v > 0 for v in totals.values()) else "N/A"

    # Sort by AWS cost descending
    service_comparisons.sort(key=lambda s: -s["aws_monthly"])

    azure_savings_pct = (
        round((totals["aws"] - totals["azure"]) / totals["aws"] * 100, 1)
        if totals["aws"] > 0 else 0
    )
    gcp_savings_pct = (
        round((totals["aws"] - totals["gcp"]) / totals["aws"] * 100, 1)
        if totals["aws"] > 0 else 0
    )

    return {
        "providers": totals,
        "services": service_comparisons,
        "total_services": len(service_comparisons),
        "cheapest_provider": cheapest_provider,
        "azure_savings_vs_aws_pct": azure_savings_pct,
        "gcp_savings_vs_aws_pct": gcp_savings_pct,
        "summary": (
            f"Across {len(service_comparisons)} services: "
            f"AWS ${totals['aws']}/mo, Azure ${totals['azure']}/mo ({azure_savings_pct}% savings), "
            f"GCP ${totals['gcp']}/mo ({gcp_savings_pct}% savings). "
            f"Cheapest overall: {cheapest_provider.upper()}."
        ),
    }
