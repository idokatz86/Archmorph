"""
Migration Risk Score (MRS) — Issue #158

Provides a composite risk score (0-100) that quantifies migration complexity
and risk before a single resource moves. A 30-second assessment, zero access
required — just upload a diagram.

Risk Score Components:
    - Service Complexity (20%): Number of services × complexity tiers
    - Mapping Confidence (25%): Average confidence score
    - Data Gravity (15%): Number/size of data services
    - Compliance Exposure (15%): Compliance-sensitive services detected
    - Architecture Coupling (15%): Service connection density / SPOFs
    - Estimated Downtime Risk (10%): Stateful services without live migration

Risk Tiers:
    0-25  → Low
    26-50 → Moderate
    51-75 → High
    76-100 → Critical

Usage:
    from migration_risk import compute_risk_score

    result = compute_risk_score(analysis)
    # → { overall_score, risk_tier, factors, recommendations, ... }
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Constants & Configuration
# ─────────────────────────────────────────────────────────────

RISK_TIERS = [
    (25, "low"),
    (50, "moderate"),
    (75, "high"),
    (100, "critical"),
]

FACTOR_WEIGHTS = {
    "service_complexity": 0.20,
    "mapping_confidence": 0.25,
    "data_gravity": 0.15,
    "compliance_exposure": 0.15,
    "architecture_coupling": 0.15,
    "downtime_risk": 0.10,
}

# Categories that contribute to data gravity
DATA_CATEGORIES = {"Database", "Storage", "Analytics", "Data Governance"}

# Services that are compliance-sensitive
COMPLIANCE_SENSITIVE_SERVICES = {
    # Database / storage with PII potential
    "RDS", "Aurora", "DynamoDB", "DocumentDB", "Keyspaces",
    "S3", "EFS", "FSx", "Glacier",
    "Redshift", "Athena", "Lake Formation",
    # Identity & access
    "Cognito", "IAM", "Directory Service",
    # Encryption / secrets
    "KMS", "Secrets Manager", "Certificate Manager",
    # Audit / compliance
    "CloudTrail", "Config", "GuardDuty", "Security Hub", "Macie",
    "Inspector", "Detective", "Audit Manager",
    # Healthcare / financial
    "HealthLake", "Comprehend Medical",
    # Data governance
    "DataZone", "Glue Data Catalog",
    # GCP equivalents
    "Cloud SQL", "Cloud Spanner", "BigQuery", "Cloud Storage",
    "Firestore", "Bigtable", "AlloyDB",
    "Cloud IAM", "Secret Manager", "Cloud KMS",
    "Cloud Audit Logs", "Security Command Center",
    "Cloud Healthcare API", "Data Catalog",
}

# Services that are stateful (downtime risk)
STATEFUL_SERVICES = {
    "RDS", "Aurora", "DynamoDB", "DocumentDB", "Keyspaces",
    "ElastiCache", "MemoryDB", "Neptune", "QLDB", "Timestream",
    "Elasticsearch", "OpenSearch",
    "EFS", "FSx",
    "Kafka", "MSK", "MQ", "SQS",
    "Redshift",
    # GCP
    "Cloud SQL", "Cloud Spanner", "Firestore", "Bigtable",
    "Memorystore", "AlloyDB", "Cloud Pub/Sub",
}

# Services with live migration paths (reduce downtime risk)
LIVE_MIGRATION_CAPABLE = {
    "EC2", "RDS", "S3", "DynamoDB", "EFS",
    "EKS",  # K8s is portable
}

# Service complexity tiers (aligned with migration_assessment.py)
COMPLEXITY_TIERS: Dict[str, int] = {
    # Tier 1 — trivial
    "S3": 1, "CloudFront": 1, "Route 53": 1, "SNS": 1, "SES": 1,
    "Cloud Storage": 1, "Cloud CDN": 1, "Cloud DNS": 1,
    "App Runner": 1, "Managed Grafana": 1,
    # Tier 2 — easy
    "EC2": 2, "ECS": 2, "EKS": 2, "Fargate": 2, "Elastic Beanstalk": 2,
    "ELB": 2, "ALB": 2, "NLB": 2, "SQS": 2, "CloudWatch": 2,
    "Batch": 2, "ECR": 2,
    "Compute Engine": 2, "GKE": 2, "Cloud Run": 2, "Cloud Pub/Sub": 2,
    # Tier 3 — moderate
    "Lambda": 3, "RDS": 3, "DynamoDB": 3, "Aurora": 3, "Redshift": 3,
    "VPC": 3, "API Gateway": 3, "Step Functions": 3, "Kinesis": 3,
    "Cognito": 3, "ElastiCache": 3, "OpenSearch": 3,
    "Cloud Functions": 3, "Cloud SQL": 3, "BigQuery": 3,
    "Firestore": 3, "Cloud Spanner": 3,
    # Tier 4 — hard
    "Transit Gateway": 4, "Direct Connect": 4, "IoT Core": 4,
    "SageMaker": 4, "EMR": 4, "Glue": 4, "Lake Formation": 4,
    "Outposts": 4, "Wavelength": 4, "Local Zones": 4,
    "Anthos": 4, "Cloud Interconnect": 4,
    # Tier 5 — very hard
    "Ground Station": 5, "Braket": 5,
}

DEFAULT_COMPLEXITY = 3  # moderate default


# ─────────────────────────────────────────────────────────────
# Factor Calculators
# ─────────────────────────────────────────────────────────────

def _score_service_complexity(mappings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Score based on number of services × their complexity tiers.
    More services + higher complexity = higher risk.
    Normalized to 0-100.
    """
    if not mappings:
        return {"score": 0, "detail": "No services detected"}

    total_services = len(mappings)
    complexity_sum = 0
    tier_distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}

    for m in mappings:
        source = m.get("source_service", m.get("aws", ""))
        tier = COMPLEXITY_TIERS.get(source, DEFAULT_COMPLEXITY)
        complexity_sum += tier
        tier_distribution[tier] = tier_distribution.get(tier, 0) + 1

    avg_complexity = complexity_sum / total_services
    # Scale: 1-5 avg complexity → 0-100 risk
    # Base = avg_complexity normalized to 0-100
    base_score = ((avg_complexity - 1) / 4) * 60  # 0-60 from complexity

    # Volume multiplier: more services = more risk (logarithmic)
    import math
    volume_bonus = min(40, math.log2(max(1, total_services)) * 8)
    score = min(100, round(base_score + volume_bonus))

    return {
        "score": score,
        "detail": f"{total_services} services, avg complexity {avg_complexity:.1f}/5",
        "total_services": total_services,
        "avg_complexity": round(avg_complexity, 2),
        "tier_distribution": tier_distribution,
    }


def _score_mapping_confidence(mappings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Score based on average mapping confidence.
    Lower average confidence = higher risk.
    Normalized to 0-100 (inverted — low confidence = high risk).
    """
    if not mappings:
        return {"score": 0, "detail": "No mappings"}

    confidences = [m.get("confidence", 0.85) for m in mappings]
    avg_confidence = sum(confidences) / len(confidences)
    low_count = sum(1 for c in confidences if c < 0.75)
    medium_count = sum(1 for c in confidences if 0.75 <= c < 0.90)
    high_count = sum(1 for c in confidences if c >= 0.90)

    # Invert: 1.0 confidence → 0 risk, 0.0 confidence → 100 risk
    score = round((1 - avg_confidence) * 100)
    # Penalty for low-confidence outliers
    outlier_penalty = min(20, low_count * 5)
    score = min(100, score + outlier_penalty)

    return {
        "score": score,
        "detail": f"Avg confidence {avg_confidence:.0%}, {low_count} low-confidence mappings",
        "avg_confidence": round(avg_confidence, 3),
        "high_confidence": high_count,
        "medium_confidence": medium_count,
        "low_confidence": low_count,
    }


def _score_data_gravity(mappings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Score based on number and proportion of data-heavy services.
    More data services = harder to migrate (data transfer, consistency).
    """
    if not mappings:
        return {"score": 0, "detail": "No services"}

    data_services = []
    for m in mappings:
        cat = m.get("category", "")
        if cat in DATA_CATEGORIES:
            data_services.append(m.get("source_service", m.get("aws", "")))

    data_count = len(data_services)
    data_ratio = data_count / len(mappings) if mappings else 0

    # Base score from count (each data service adds risk)
    base_score = min(60, data_count * 12)
    # Ratio bonus (architectures dominated by data are riskier)
    ratio_bonus = min(40, round(data_ratio * 60))
    score = min(100, base_score + ratio_bonus)

    return {
        "score": score,
        "detail": f"{data_count} data services ({data_ratio:.0%} of total)",
        "data_services": data_services[:10],
        "data_service_count": data_count,
        "data_ratio": round(data_ratio, 2),
    }


def _score_compliance_exposure(mappings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Score based on compliance-sensitive services detected.
    More compliance-sensitive services = more regulatory risk.
    """
    if not mappings:
        return {"score": 0, "detail": "No services"}

    sensitive = []
    for m in mappings:
        source = m.get("source_service", m.get("aws", ""))
        if source in COMPLIANCE_SENSITIVE_SERVICES:
            sensitive.append(source)

    sensitive_count = len(sensitive)
    sensitive_ratio = sensitive_count / len(mappings) if mappings else 0

    # Each sensitive service adds significant risk
    base_score = min(70, sensitive_count * 10)
    ratio_bonus = min(30, round(sensitive_ratio * 50))
    score = min(100, base_score + ratio_bonus)

    frameworks_likely: List[str] = []
    sensitive_set = set(sensitive)
    if sensitive_set & {"RDS", "Aurora", "DynamoDB", "S3", "Cognito", "Cloud SQL", "Firestore"}:
        frameworks_likely.append("GDPR")
    if sensitive_set & {"HealthLake", "Comprehend Medical", "Cloud Healthcare API"}:
        frameworks_likely.append("HIPAA")
    if sensitive_set & {"KMS", "Secrets Manager", "CloudTrail", "Cloud KMS", "Cloud Audit Logs"}:
        frameworks_likely.append("SOC 2")
    if sensitive_set & {"WAF", "Shield", "GuardDuty", "Security Hub", "Security Command Center"}:
        frameworks_likely.append("PCI-DSS")

    return {
        "score": score,
        "detail": f"{sensitive_count} compliance-sensitive services detected",
        "sensitive_services": sensitive[:10],
        "sensitive_count": sensitive_count,
        "likely_frameworks": frameworks_likely,
    }


def _score_architecture_coupling(
    mappings: List[Dict[str, Any]],
    connections: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Score based on service connection density and potential SPOFs.
    Dense interconnections + single points of failure = higher risk.
    """
    total_services = len(mappings) if mappings else 1
    total_connections = len(connections)

    if total_services <= 1:
        return {"score": 0, "detail": "Single service — no coupling"}

    # Connection density: connections / services ratio
    density = total_connections / total_services
    # Max expected density ~3 connections per service
    density_score = min(60, round(density * 20))

    # SPOF detection: services with many connections (>3 inbound or outbound)
    connection_counts: Dict[str, int] = {}
    for conn in connections:
        src = conn.get("from", "")
        dst = conn.get("to", "")
        if src:
            connection_counts[src] = connection_counts.get(src, 0) + 1
        if dst:
            connection_counts[dst] = connection_counts.get(dst, 0) + 1

    spofs = [svc for svc, count in connection_counts.items() if count > 3]
    spof_score = min(40, len(spofs) * 10)
    score = min(100, density_score + spof_score)

    return {
        "score": score,
        "detail": f"{total_connections} connections across {total_services} services, {len(spofs)} potential SPOFs",
        "connection_density": round(density, 2),
        "potential_spofs": spofs[:5],
        "spof_count": len(spofs),
    }


def _score_downtime_risk(mappings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Score based on stateful services without live migration path.
    Services that require downtime for cutover increase risk.
    """
    if not mappings:
        return {"score": 0, "detail": "No services"}

    stateful = []
    no_live_migration = []

    for m in mappings:
        source = m.get("source_service", m.get("aws", ""))
        if source in STATEFUL_SERVICES:
            stateful.append(source)
            if source not in LIVE_MIGRATION_CAPABLE:
                no_live_migration.append(source)

    stateful_count = len(stateful)
    no_live_count = len(no_live_migration)

    # Each stateful service without live migration adds risk
    base_score = min(60, no_live_count * 15)
    # Overall stateful ratio
    stateful_ratio = stateful_count / len(mappings) if mappings else 0
    ratio_bonus = min(40, round(stateful_ratio * 50))
    score = min(100, base_score + ratio_bonus)

    return {
        "score": score,
        "detail": f"{stateful_count} stateful services, {no_live_count} require downtime",
        "stateful_services": stateful[:10],
        "no_live_migration": no_live_migration[:10],
        "stateful_count": stateful_count,
        "downtime_required_count": no_live_count,
    }


# ─────────────────────────────────────────────────────────────
# Recommendations Engine
# ─────────────────────────────────────────────────────────────

def _generate_recommendations(
    overall_score: int,
    risk_tier: str,
    factors: Dict[str, Dict[str, Any]],
    mappings: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Generate actionable recommendations based on risk factors."""
    recs: List[Dict[str, Any]] = []

    # High complexity
    if factors["service_complexity"]["score"] >= 60:
        recs.append({
            "id": "MRS-001",
            "title": "High Service Complexity",
            "description": "Your architecture has many high-complexity services. "
                          "Consider a phased migration — start with low-complexity "
                          "services to build confidence.",
            "priority": "high",
            "effort": "medium",
        })

    # Low confidence mappings
    conf = factors["mapping_confidence"]
    if conf.get("low_confidence", 0) > 0:
        recs.append({
            "id": "MRS-002",
            "title": "Low-Confidence Service Mappings",
            "description": f"{conf['low_confidence']} service(s) have uncertain Azure mappings. "
                          "Validate these manually with a solutions architect before proceeding.",
            "priority": "high",
            "effort": "low",
        })

    # Data gravity
    if factors["data_gravity"]["score"] >= 50:
        recs.append({
            "id": "MRS-003",
            "title": "Significant Data Gravity",
            "description": "Data-intensive services dominate your architecture. "
                          "Plan data transfer windows, evaluate Azure Data Factory "
                          "or AzCopy for large-scale transfers. Consider data residency requirements.",
            "priority": "high",
            "effort": "high",
        })

    # Compliance
    if factors["compliance_exposure"]["score"] >= 30:
        frameworks = factors["compliance_exposure"].get("likely_frameworks", [])
        fw_str = ", ".join(frameworks) if frameworks else "multiple frameworks"
        recs.append({
            "id": "MRS-004",
            "title": "Compliance-Sensitive Migration",
            "description": f"Detected services likely subject to {fw_str}. "
                          "Engage compliance team early. Ensure Azure landing zone "
                          "meets regulatory requirements before migrating data.",
            "priority": "critical",
            "effort": "high",
        })

    # SPOFs
    coupling = factors["architecture_coupling"]
    if coupling.get("spof_count", 0) > 0:
        spofs = ", ".join(coupling.get("potential_spofs", [])[:3])
        recs.append({
            "id": "MRS-005",
            "title": "Single Points of Failure Detected",
            "description": f"Services with high connection density ({spofs}) are "
                          "potential SPOFs. Consider migrating these last with "
                          "thorough rollback plans.",
            "priority": "medium",
            "effort": "medium",
        })

    # Downtime risk
    if factors["downtime_risk"]["score"] >= 40:
        recs.append({
            "id": "MRS-006",
            "title": "Downtime-Required Services",
            "description": f"{factors['downtime_risk'].get('downtime_required_count', 0)} "
                          "stateful services lack live migration paths. Plan maintenance "
                          "windows, communicate with stakeholders, prepare rollback procedures.",
            "priority": "high",
            "effort": "medium",
        })

    # Overall risk-based
    if overall_score >= 76:
        recs.append({
            "id": "MRS-007",
            "title": "Critical Risk — Engage Migration Expert",
            "description": "Overall risk score is critical. Strongly recommend engaging "
                          "Microsoft FastTrack for Azure or a certified migration partner "
                          "before proceeding.",
            "priority": "critical",
            "effort": "low",
        })
    elif overall_score >= 51:
        recs.append({
            "id": "MRS-008",
            "title": "High Risk — Proof-of-Concept First",
            "description": "Consider running a proof-of-concept migration with 2-3 services "
                          "before committing to full migration. Validate assumptions early.",
            "priority": "medium",
            "effort": "medium",
        })

    # Quick win if score is low
    if overall_score <= 25:
        recs.append({
            "id": "MRS-009",
            "title": "Low Risk — Good Candidate for Migration",
            "description": "This architecture is a good candidate for migration. "
                          "Most services have direct Azure equivalents with high confidence.",
            "priority": "info",
            "effort": "low",
        })

    # Sort by priority
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    recs.sort(key=lambda r: priority_order.get(r["priority"], 5))

    return recs


# ─────────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────────

def compute_risk_score(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute the Migration Risk Score (MRS) for an architecture analysis.

    Args:
        analysis: The diagram analysis result from vision_analyzer,
                  containing mappings, service_connections, zones, etc.

    Returns:
        Dict with overall_score (0-100), risk_tier, per-factor breakdown,
        recommendations, and metadata.
    """
    start_time = time.time()

    mappings = analysis.get("mappings", [])
    connections = analysis.get("service_connections", [])

    if not mappings:
        return {
            "overall_score": 0,
            "risk_tier": "unknown",
            "factors": {},
            "recommendations": [{
                "id": "MRS-000",
                "title": "No Services Detected",
                "description": "Upload an architecture diagram first to compute risk score.",
                "priority": "info",
                "effort": "low",
            }],
            "total_services": 0,
            "generated_at": time.time(),
            "computation_time_ms": 0,
        }

    # Compute all 6 factors
    factors = {
        "service_complexity": _score_service_complexity(mappings),
        "mapping_confidence": _score_mapping_confidence(mappings),
        "data_gravity": _score_data_gravity(mappings),
        "compliance_exposure": _score_compliance_exposure(mappings),
        "architecture_coupling": _score_architecture_coupling(mappings, connections),
        "downtime_risk": _score_downtime_risk(mappings),
    }

    # Compute weighted overall score
    overall_score = 0
    for factor_name, weight in FACTOR_WEIGHTS.items():
        factor_score = factors[factor_name]["score"]
        overall_score += factor_score * weight

    overall_score = round(overall_score)
    overall_score = max(0, min(100, overall_score))

    # Determine risk tier
    risk_tier = "critical"
    for threshold, tier in RISK_TIERS:
        if overall_score <= threshold:
            risk_tier = tier
            break

    # Generate recommendations
    recommendations = _generate_recommendations(
        overall_score, risk_tier, factors, mappings
    )

    computation_time = round((time.time() - start_time) * 1000, 1)

    logger.info(
        "Migration Risk Score computed: %d (%s) for %d services in %.1fms",
        overall_score, risk_tier, len(mappings), computation_time,
    )

    return {
        "overall_score": overall_score,
        "risk_tier": risk_tier,
        "factors": {
            name: {
                "score": f["score"],
                "weight": FACTOR_WEIGHTS[name],
                "weighted_contribution": round(f["score"] * FACTOR_WEIGHTS[name], 1),
                "detail": f["detail"],
                **{k: v for k, v in f.items() if k not in ("score", "detail")},
            }
            for name, f in factors.items()
        },
        "recommendations": recommendations,
        "total_services": len(mappings),
        "risk_tier_thresholds": {tier: threshold for threshold, tier in RISK_TIERS},
        "generated_at": time.time(),
        "computation_time_ms": computation_time,
    }
