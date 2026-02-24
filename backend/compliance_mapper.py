"""
Compliance-Aware Migration — Issue #160

Auto-detect regulatory requirements from source architecture and generate
compliance-aware target configurations. Detects HIPAA, PCI-DSS, SOC 2,
GDPR, ISO 27001, and FedRAMP frameworks.

Usage:
    from compliance_mapper import assess_compliance

    result = assess_compliance(analysis)
    # → { frameworks, overall_score, gaps, recommendations, ... }
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Set

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Compliance Framework Definitions
# ─────────────────────────────────────────────────────────────

FRAMEWORKS = {
    "HIPAA": {
        "full_name": "Health Insurance Portability and Accountability Act",
        "description": "US healthcare data protection regulation",
        "detection_signals": {
            "services": {"HealthLake", "Comprehend Medical", "Cloud Healthcare API"},
            "keywords": {"health", "patient", "medical", "phi", "ehr", "hipaa"},
            "categories": set(),
        },
        "azure_controls": {
            "encryption_at_rest": "Azure Disk Encryption + Storage Service Encryption",
            "encryption_in_transit": "TLS 1.2+ enforced on all endpoints",
            "access_control": "Azure RBAC + Conditional Access",
            "audit_logging": "Azure Monitor + Microsoft Defender audit logs",
            "backup": "Azure Backup with geo-redundancy",
            "baa": "Microsoft Business Associate Agreement (BAA)",
            "data_residency": "Azure region selection for data sovereignty",
        },
        "azure_policies": [
            "HIPAA HITRUST 9.2",
        ],
        "weight": 1.0,
    },
    "PCI-DSS": {
        "full_name": "Payment Card Industry Data Security Standard",
        "description": "Payment card data security standard",
        "detection_signals": {
            "services": {"WAF", "Shield", "GuardDuty", "Security Hub",
                        "Security Command Center", "KMS", "CloudTrail"},
            "keywords": {"payment", "card", "checkout", "stripe", "pci", "credit"},
            "categories": set(),
        },
        "azure_controls": {
            "network_segmentation": "Azure VNet + NSGs + Azure Firewall",
            "encryption": "Azure Key Vault + CMK + TDE",
            "monitoring": "Microsoft Defender for Cloud + Azure Sentinel",
            "access_control": "Azure RBAC + PIM + MFA enforcement",
            "vulnerability_scanning": "Microsoft Defender vulnerability assessment",
            "logging": "Azure Monitor + Log Analytics 90-day retention",
            "waf": "Azure WAF on Application Gateway / Front Door",
        },
        "azure_policies": [
            "PCI DSS v4",
        ],
        "weight": 1.0,
    },
    "SOC 2": {
        "full_name": "System and Organization Controls 2",
        "description": "Trust service criteria for data security",
        "detection_signals": {
            "services": {"CloudTrail", "Config", "GuardDuty", "Security Hub",
                        "Audit Manager", "Cloud Audit Logs"},
            "keywords": {"audit", "compliance", "soc", "trust", "governance"},
            "categories": {"Security", "Management"},
        },
        "azure_controls": {
            "change_management": "Azure DevOps + deployment gates",
            "logical_access": "Azure RBAC + Conditional Access + PIM",
            "monitoring": "Azure Monitor + alerts + Microsoft Defender",
            "incident_response": "Microsoft Defender incident management",
            "risk_assessment": "Microsoft Defender for Cloud secure score",
            "availability": "Azure SLA + availability zones + geo-redundancy",
            "confidentiality": "Azure Key Vault + disk/storage encryption",
        },
        "azure_policies": [
            "SOC 2 Type 2",
        ],
        "weight": 0.9,
    },
    "GDPR": {
        "full_name": "General Data Protection Regulation",
        "description": "EU data protection and privacy regulation",
        "detection_signals": {
            "services": {"RDS", "Aurora", "DynamoDB", "S3", "Cognito",
                        "Cloud SQL", "Firestore", "Bigtable", "Cloud Storage",
                        "Macie", "DataZone"},
            "keywords": {"gdpr", "privacy", "personal", "consent", "data subject",
                        "eu", "european", "dpa"},
            "categories": {"Database", "Storage"},
        },
        "azure_controls": {
            "data_residency": "Azure EU regions (West Europe, North Europe)",
            "data_subject_rights": "Microsoft Purview data subject requests",
            "consent_management": "Azure AD B2C consent flows",
            "data_discovery": "Microsoft Purview data classification",
            "encryption": "CMK for data at rest + TLS in transit",
            "breach_notification": "Microsoft Defender alerts + 72hr GDPR notification",
            "dpo_tools": "Microsoft Compliance Manager",
            "right_to_erasure": "Data lifecycle management + soft delete",
        },
        "azure_policies": [
            "GDPR",
        ],
        "weight": 0.9,
    },
    "ISO 27001": {
        "full_name": "ISO/IEC 27001 Information Security Management",
        "description": "International information security standard",
        "detection_signals": {
            "services": {"IAM", "KMS", "CloudTrail", "Config", "GuardDuty",
                        "Cloud IAM", "Cloud KMS", "Cloud Audit Logs"},
            "keywords": {"iso", "isms", "information security", "27001"},
            "categories": {"Security"},
        },
        "azure_controls": {
            "isms": "Azure Security Center + Microsoft Defender",
            "asset_management": "Azure Resource Graph + tags",
            "access_control": "Azure RBAC + PIM + Conditional Access",
            "cryptography": "Azure Key Vault + managed keys",
            "operations_security": "Azure Monitor + Log Analytics",
            "communications_security": "Azure VNet + NSGs + Private Endpoints",
            "supplier_management": "Microsoft Trust Center",
            "incident_management": "Microsoft Defender incident management",
            "business_continuity": "Azure Site Recovery + geo-replication",
        },
        "azure_policies": [
            "ISO 27001:2013",
        ],
        "weight": 0.8,
    },
    "FedRAMP": {
        "full_name": "Federal Risk and Authorization Management Program",
        "description": "US federal cloud security authorization",
        "detection_signals": {
            "services": {"GovCloud", "FedRAMP"},
            "keywords": {"fedramp", "federal", "government", "govcloud", "fisma",
                        "nist", "fips"},
            "categories": set(),
        },
        "azure_controls": {
            "authorization": "Azure Government regions",
            "continuous_monitoring": "Microsoft Defender for Cloud",
            "access_control": "Azure RBAC + PIV/CAC + MFA",
            "audit": "Azure Monitor + FedRAMP audit logging",
            "incident_response": "Azure Government incident response",
            "encryption": "FIPS 140-2 validated modules",
            "boundary_protection": "Azure Firewall + NSGs + DDoS Protection",
        },
        "azure_policies": [
            "FedRAMP High",
            "FedRAMP Moderate",
        ],
        "weight": 0.7,
    },
}


# ─────────────────────────────────────────────────────────────
# Gap Analysis Definitions
# ─────────────────────────────────────────────────────────────

COMMON_GAPS = {
    "encryption_at_rest": {
        "title": "Data Encryption at Rest",
        "description": "All data stores must use encryption at rest",
        "check": lambda svcs: any(s in svcs for s in
                                  ["RDS", "Aurora", "DynamoDB", "S3", "EFS",
                                   "Cloud SQL", "Cloud Storage", "Firestore", "Bigtable"]),
        "remediation": "Enable Azure Storage Service Encryption, Azure SQL TDE, "
                      "and Azure Disk Encryption. Use Customer-Managed Keys (CMK) "
                      "for enhanced control.",
        "frameworks": {"HIPAA", "PCI-DSS", "SOC 2", "GDPR", "ISO 27001", "FedRAMP"},
        "severity": "high",
    },
    "encryption_in_transit": {
        "title": "Data Encryption in Transit",
        "description": "All network communication must use TLS 1.2+",
        "check": lambda svcs: len(svcs) > 0,  # Always relevant
        "remediation": "Enforce TLS 1.2 minimum on all Azure services. "
                      "Use Azure Front Door or Application Gateway for TLS termination.",
        "frameworks": {"HIPAA", "PCI-DSS", "SOC 2", "GDPR", "ISO 27001", "FedRAMP"},
        "severity": "high",
    },
    "access_control": {
        "title": "Identity & Access Management",
        "description": "Role-based access control with MFA enforcement",
        "check": lambda svcs: any(s in svcs for s in ["IAM", "Cognito", "Cloud IAM"]),
        "remediation": "Implement Azure RBAC with least-privilege roles. "
                      "Enable MFA via Conditional Access. Use PIM for JIT access.",
        "frameworks": {"HIPAA", "PCI-DSS", "SOC 2", "GDPR", "ISO 27001", "FedRAMP"},
        "severity": "high",
    },
    "audit_logging": {
        "title": "Audit Logging & Monitoring",
        "description": "Comprehensive audit trail with tamper-proof storage",
        "check": lambda svcs: any(s in svcs for s in
                                  ["CloudTrail", "CloudWatch", "Config",
                                   "Cloud Audit Logs", "Cloud Monitoring"]),
        "remediation": "Enable Azure Monitor diagnostic settings for all resources. "
                      "Configure Log Analytics with 90+ day retention. "
                      "Enable Microsoft Defender for Cloud.",
        "frameworks": {"HIPAA", "PCI-DSS", "SOC 2", "ISO 27001", "FedRAMP"},
        "severity": "high",
    },
    "network_segmentation": {
        "title": "Network Segmentation",
        "description": "Isolated network zones with strict access controls",
        "check": lambda svcs: any(s in svcs for s in
                                  ["VPC", "Transit Gateway", "Direct Connect"]),
        "remediation": "Deploy Azure VNet with subnets for each tier. "
                      "Use NSGs and Azure Firewall for micro-segmentation. "
                      "Enable Private Endpoints for PaaS services.",
        "frameworks": {"PCI-DSS", "ISO 27001", "FedRAMP"},
        "severity": "medium",
    },
    "data_residency": {
        "title": "Data Residency & Sovereignty",
        "description": "Data stored in compliant geographic regions",
        "check": lambda svcs: any(s in svcs for s in
                                  ["RDS", "Aurora", "DynamoDB", "S3",
                                   "Cloud SQL", "Cloud Storage"]),
        "remediation": "Select Azure regions that comply with data residency requirements. "
                      "Use Azure Policy to enforce resource location constraints.",
        "frameworks": {"GDPR", "FedRAMP"},
        "severity": "medium",
    },
    "backup_recovery": {
        "title": "Backup & Disaster Recovery",
        "description": "Regular backups with tested recovery procedures",
        "check": lambda svcs: any(s in svcs for s in
                                  ["RDS", "Aurora", "DynamoDB",
                                   "Cloud SQL", "Cloud Spanner", "Firestore"]),
        "remediation": "Enable Azure Backup for all data services. "
                      "Configure geo-redundant storage (GRS). "
                      "Test recovery procedures quarterly.",
        "frameworks": {"HIPAA", "SOC 2", "ISO 27001"},
        "severity": "medium",
    },
    "vulnerability_management": {
        "title": "Vulnerability Management",
        "description": "Regular vulnerability scanning and patching",
        "check": lambda svcs: any(s in svcs for s in ["EC2", "ECS", "EKS",
                                                       "Compute Engine", "GKE"]),
        "remediation": "Enable Microsoft Defender for Cloud vulnerability assessment. "
                      "Configure automatic OS patching where applicable. "
                      "Implement container image scanning in ACR.",
        "frameworks": {"PCI-DSS", "SOC 2", "ISO 27001", "FedRAMP"},
        "severity": "medium",
    },
    "key_management": {
        "title": "Cryptographic Key Management",
        "description": "Centralized key management with rotation policies",
        "check": lambda svcs: any(s in svcs for s in
                                  ["KMS", "Secrets Manager", "Cloud KMS", "Secret Manager"]),
        "remediation": "Use Azure Key Vault for all secrets and keys. "
                      "Enable automatic key rotation. "
                      "Use HSM-backed keys for high-security requirements.",
        "frameworks": {"PCI-DSS", "SOC 2", "ISO 27001", "FedRAMP"},
        "severity": "medium",
    },
    "data_classification": {
        "title": "Data Classification & Discovery",
        "description": "Automated data classification and sensitive data detection",
        "check": lambda svcs: any(s in svcs for s in
                                  ["S3", "RDS", "DynamoDB", "Macie",
                                   "Cloud Storage", "Cloud SQL", "Firestore"]),
        "remediation": "Deploy Microsoft Purview for data classification. "
                      "Enable Azure SQL data discovery & classification. "
                      "Configure sensitivity labels.",
        "frameworks": {"GDPR", "HIPAA", "PCI-DSS"},
        "severity": "low",
    },
}


# ─────────────────────────────────────────────────────────────
# Detection Engine
# ─────────────────────────────────────────────────────────────

def _detect_frameworks(
    analysis: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """Detect likely compliance frameworks from analysis data."""
    detected: Dict[str, Dict[str, Any]] = {}

    # Extract all service names and categories
    service_names: Set[str] = set()
    categories: Set[str] = set()
    for m in analysis.get("mappings", []):
        source = m.get("source_service", m.get("aws", ""))
        if source:
            service_names.add(source)
        cat = m.get("category", "")
        if cat:
            categories.add(cat)

    for fw_id, fw_def in FRAMEWORKS.items():
        signals = fw_def["detection_signals"]
        reasons: List[str] = []
        confidence = 0.0

        # Check service-based signals
        service_matches = service_names & signals["services"]
        if service_matches:
            confidence += 0.4
            reasons.append(f"Services detected: {', '.join(sorted(service_matches))}")

        # Check category-based signals
        category_matches = categories & signals.get("categories", set())
        if category_matches:
            confidence += 0.2
            reasons.append(f"Categories: {', '.join(sorted(category_matches))}")

        # Data services trigger GDPR for any architecture with PII potential
        if fw_id == "GDPR":
            data_svcs = service_names & {"RDS", "Aurora", "DynamoDB", "S3",
                                         "Cloud SQL", "Firestore", "Cloud Storage"}
            if data_svcs:
                confidence += 0.3
                reasons.append(f"Data services with PII potential: {', '.join(sorted(data_svcs))}")

        # SOC 2 — any production architecture needs it
        if fw_id == "SOC 2" and len(service_names) >= 3:
            confidence += 0.3
            reasons.append("Multi-service architecture implies SOC 2 relevance")

        # ISO 27001 — security services present
        if fw_id == "ISO 27001":
            security_svcs = service_names & {"IAM", "KMS", "WAF", "GuardDuty",
                                              "Cloud IAM", "Cloud KMS"}
            if security_svcs:
                confidence += 0.2
                reasons.append(f"Security services: {', '.join(sorted(security_svcs))}")

        if confidence > 0:
            detected[fw_id] = {
                "framework": fw_id,
                "full_name": fw_def["full_name"],
                "description": fw_def["description"],
                "confidence": min(1.0, round(confidence, 2)),
                "reasons": reasons,
                "azure_controls": fw_def["azure_controls"],
                "azure_policies": fw_def["azure_policies"],
            }

    return detected


def _compute_compliance_score(
    framework_id: str,
    service_names: Set[str],
) -> Dict[str, Any]:
    """Compute compliance score for a specific framework (0-100)."""
    applicable_gaps: List[Dict[str, Any]] = []
    total_count = 0

    for gap_id, gap_def in COMMON_GAPS.items():
        if framework_id not in gap_def["frameworks"]:
            continue

        is_relevant = gap_def["check"](service_names)
        if not is_relevant:
            continue

        total_count += 1
        # For imported architectures, assume gaps exist (conservative)
        applicable_gaps.append({
            "id": gap_id,
            "title": gap_def["title"],
            "description": gap_def["description"],
            "severity": gap_def["severity"],
            "remediation": gap_def["remediation"],
            "status": "gap",
        })

    # Score: start at 100, deduct for gaps
    deductions = {"high": 15, "medium": 10, "low": 5}
    score = 100
    for gap in applicable_gaps:
        score -= deductions.get(gap["severity"], 5)

    score = max(0, score)

    return {
        "score": score,
        "total_controls": total_count,
        "gaps": applicable_gaps,
        "gap_count": len(applicable_gaps),
    }


# ─────────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────────

def assess_compliance(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """
    Assess compliance posture for an architecture analysis.

    Auto-detects applicable regulatory frameworks based on detected services,
    computes per-framework compliance scores, identifies gaps, and provides
    remediation guidance.

    Args:
        analysis: The diagram analysis result from vision_analyzer or infra_import.

    Returns:
        Dict with detected frameworks, scores, gaps, and recommendations.
    """
    start_time = time.time()

    mappings = analysis.get("mappings", [])
    if not mappings:
        return {
            "frameworks": {},
            "overall_score": 0,
            "applicable_framework_count": 0,
            "total_gaps": 0,
            "recommendations": [],
            "generated_at": time.time(),
            "computation_time_ms": 0,
        }

    # Extract service names
    service_names: Set[str] = set()
    for m in mappings:
        source = m.get("source_service", m.get("aws", ""))
        if source:
            service_names.add(source)

    # Detect applicable frameworks
    detected = _detect_frameworks(analysis)

    # Score each detected framework
    total_score = 0
    total_weight = 0
    total_gaps = 0
    framework_results: Dict[str, Dict[str, Any]] = {}

    for fw_id, fw_info in detected.items():
        scoring = _compute_compliance_score(fw_id, service_names)
        fw_weight = FRAMEWORKS[fw_id]["weight"]

        framework_results[fw_id] = {
            **fw_info,
            "score": scoring["score"],
            "total_controls": scoring["total_controls"],
            "gaps": scoring["gaps"],
            "gap_count": scoring["gap_count"],
        }

        total_score += scoring["score"] * fw_weight
        total_weight += fw_weight
        total_gaps += scoring["gap_count"]

    overall_score = round(total_score / total_weight) if total_weight > 0 else 100

    # Generate high-level recommendations
    recommendations = _generate_compliance_recommendations(
        framework_results, overall_score, service_names
    )

    computation_time = round((time.time() - start_time) * 1000, 1)

    logger.info(
        "Compliance assessment: %d frameworks detected, overall score %d, "
        "%d gaps found in %.1fms",
        len(detected), overall_score, total_gaps, computation_time,
    )

    return {
        "frameworks": framework_results,
        "overall_score": overall_score,
        "applicable_framework_count": len(detected),
        "total_gaps": total_gaps,
        "recommendations": recommendations,
        "service_count": len(service_names),
        "generated_at": time.time(),
        "computation_time_ms": computation_time,
    }


def _generate_compliance_recommendations(
    frameworks: Dict[str, Dict[str, Any]],
    overall_score: int,
    service_names: Set[str],
) -> List[Dict[str, Any]]:
    """Generate prioritized compliance recommendations."""
    recs: List[Dict[str, Any]] = []

    # Critical gaps across frameworks
    all_gaps: Dict[str, List[str]] = {}  # gap_id → [framework IDs]
    for fw_id, fw_data in frameworks.items():
        for gap in fw_data.get("gaps", []):
            gap_id = gap["id"]
            if gap_id not in all_gaps:
                all_gaps[gap_id] = []
            all_gaps[gap_id].append(fw_id)

    # Recommend addressing gaps that affect multiple frameworks first
    cross_cutting = [(gid, fws) for gid, fws in all_gaps.items() if len(fws) >= 2]
    cross_cutting.sort(key=lambda x: -len(x[1]))

    for gap_id, affected_fws in cross_cutting[:5]:
        gap_def = COMMON_GAPS[gap_id]
        recs.append({
            "id": f"COMP-{gap_id.upper()}",
            "title": gap_def["title"],
            "description": f"Affects {len(affected_fws)} frameworks: "
                          f"{', '.join(affected_fws)}. {gap_def['remediation']}",
            "priority": "critical" if gap_def["severity"] == "high" else "high",
            "affected_frameworks": affected_fws,
        })

    # Framework-specific recommendations
    for fw_id, fw_data in frameworks.items():
        if fw_data["score"] < 70:
            recs.append({
                "id": f"COMP-{fw_id}-SCORE",
                "title": f"{fw_id} Score Below Threshold",
                "description": f"{fw_id} compliance score is {fw_data['score']}/100. "
                              f"Address {fw_data['gap_count']} identified gaps to improve.",
                "priority": "high",
                "affected_frameworks": [fw_id],
            })

    # Azure Policy recommendation
    if frameworks:
        policy_initiatives = []
        for fw_data in frameworks.values():
            policy_initiatives.extend(fw_data.get("azure_policies", []))
        if policy_initiatives:
            recs.append({
                "id": "COMP-POLICY",
                "title": "Apply Azure Policy Initiatives",
                "description": f"Assign these Azure Policy initiatives for continuous compliance: "
                              f"{', '.join(set(policy_initiatives))}",
                "priority": "medium",
                "affected_frameworks": list(frameworks.keys()),
            })

    # Overall score recommendation
    if overall_score < 50:
        recs.append({
            "id": "COMP-OVERALL",
            "title": "Critical Compliance Risk",
            "description": "Overall compliance score is below 50. Engage a compliance "
                          "consultant and prioritize high-severity gaps before migration.",
            "priority": "critical",
            "affected_frameworks": list(frameworks.keys()),
        })

    return recs
