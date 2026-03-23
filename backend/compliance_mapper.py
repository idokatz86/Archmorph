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



# ─────────────────────────────────────────────────────────────
# Live IaC / Scanner Compliance Assessment (#239)
# ─────────────────────────────────────────────────────────────

LIVE_COMPLIANCE_RULES = [
    {
        "rule_id": "storage_secure_transfer",
        "title": "Storage accounts should require secure transfer",
        "description": "Ensure 'supportsHttpsTrafficOnly' is true for Storage Accounts.",
        "severity": "high",
        "frameworks": ["SOC 2", "HIPAA", "PCI-DSS"],
        "check": lambda res: (
            res.get("type", "").lower() == "microsoft.storage/storageaccounts"
            and not res.get("attributes", {}).get("supportsHttpsTrafficOnly", True)
        ),
        "remediation": "Set supportsHttpsTrafficOnly to true for the Storage Account."
    },
    {
        "rule_id": "keyvault_purge_protection",
        "title": "Key Vault should have purge protection enabled",
        "description": "Protect Key Vaults from accidental or malicious deletion.",
        "severity": "high",
        "frameworks": ["SOC 2", "HIPAA", "PCI-DSS"],
        "check": lambda res: (
            res.get("type", "").lower() == "microsoft.keyvault/vaults"
            and not res.get("attributes", {}).get("enableSoftDelete", False)
        ),
        "remediation": "Enable Soft Delete and Purge Protection on the Key Vault."
    },
    {
        "rule_id": "postgresql_ssl_enforcement",
        "title": "PostgreSQL should enforce SSL",
        "description": "Ensure PostgreSQL servers enforce SSL connections.",
        "severity": "high",
        "frameworks": ["SOC 2", "HIPAA", "PCI-DSS", "GDPR"],
        "check": lambda res: (
            "dbforpostgresql" in res.get("type", "").lower()
            and res.get("attributes", {}).get("sslEnforcement", "Enabled") != "Enabled"
        ),
        "remediation": "Set sslEnforcement to Enabled."
    },
    {
        "rule_id": "compute_endpoint_protection",
        "title": "Endpoint protection should be installed on machines",
        "description": "Ensure virtual machines have endpoint protection installed.",
        "severity": "medium",
        "frameworks": ["SOC 2", "PCI-DSS"],
        "check": lambda res: (
            res.get("type", "").lower() == "microsoft.compute/virtualmachines"
            and "endpointProtection" not in res.get("tags", {})
        ),
        "remediation": "Install endpoint protection and enforce via tags or policies."
    }
]

def analyze_live_compliance(live_schema: Dict[str, Any]) -> Dict[str, Any]:
    resources = live_schema.get("resources", [])
    if isinstance(resources, dict):
        resources = []
    
    # Extract dict if it's a Pydantic model or Dataclass
    parsed_resources = []
    for r in resources:
        if hasattr(r, "model_dump"):
            parsed_resources.append(r.model_dump())
        elif hasattr(r, "__dict__"):
            from dataclasses import asdict
            try:
                parsed_resources.append(asdict(r))
            except (TypeError, Exception):
                parsed_resources.append(vars(r))
        elif isinstance(r, dict):
            parsed_resources.append(r)
            
    violations = []
    framework_stats = {
        "SOC 2": {"total_rules": 0, "passed_rules": 0},
        "HIPAA": {"total_rules": 0, "passed_rules": 0},
        "PCI-DSS": {"total_rules": 0, "passed_rules": 0},
        "GDPR": {"total_rules": 0, "passed_rules": 0},
    }
    
    for rule in LIVE_COMPLIANCE_RULES:
        for res in parsed_resources:
            try:
                is_violation = rule["check"](res)
            except Exception:
                is_violation = False
            
            if is_violation:
                violations.append({
                    "rule_id": rule["rule_id"],
                    "title": rule["title"],
                    "description": rule["description"],
                    "severity": rule["severity"],
                    "frameworks": rule["frameworks"],
                    "resource_id": res.get("id", "unknown"),
                    "resource_name": res.get("name", "unknown"),
                    "remediation": rule["remediation"]
                })
                for fw in rule["frameworks"]:
                    if fw in framework_stats:
                        framework_stats[fw]["total_rules"] += 1
                
    frameworks_result = {}
    for fw, stats in framework_stats.items():
        score = max(0, 100 - (stats["total_rules"] * 10))
        
        status = "Passing"
        if score < 80:
            status = "Warning"
        if score < 60:
            status = "Failing"
            
        frameworks_result[fw] = {
            "score": score,
            "status": status,
            "total_violations": stats["total_rules"]
        }
    
    total_score = sum(f["score"] for f in frameworks_result.values())
    overall_score = total_score // len(frameworks_result) if frameworks_result else 100
        
    return {
        "frameworks": frameworks_result,
        "overall_score": overall_score,
        "violations": violations
    }


# ─────────────────────────────────────────────────────────────
# Framework Mapping & Gap Analysis (Issue #239)
# ─────────────────────────────────────────────────────────────

# Canonical framework IDs accepted in query params → internal keys
FRAMEWORK_ALIASES: Dict[str, str] = {
    "soc2": "SOC 2",
    "soc_2": "SOC 2",
    "hipaa": "HIPAA",
    "pci_dss": "PCI-DSS",
    "pci-dss": "PCI-DSS",
    "pcidss": "PCI-DSS",
    "gdpr": "GDPR",
    "iso27001": "ISO 27001",
    "iso_27001": "ISO 27001",
    "fedramp": "FedRAMP",
}

# ── Per-framework required controls with official control IDs ──

FRAMEWORK_CONTROLS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "SOC 2": {
        "CC6.1": {
            "title": "Logical & Physical Access — Encryption & Key Management",
            "description": "Restrict access to information assets using encryption, "
                           "key management, and credential controls.",
            "category": "security",
        },
        "CC6.2": {
            "title": "Logical & Physical Access — Credentials & Authentication",
            "description": "Issue credentials based on authorization and require MFA.",
            "category": "identity",
        },
        "CC6.3": {
            "title": "Logical & Physical Access — RBAC & Least Privilege",
            "description": "Assign role-based access with least-privilege enforcement.",
            "category": "identity",
        },
        "CC7.1": {
            "title": "System Operations — Infrastructure & Software Monitoring",
            "description": "Detect and respond to security events in infrastructure.",
            "category": "monitoring",
        },
        "CC7.2": {
            "title": "System Operations — Anomaly Detection & Incident Response",
            "description": "Monitor for anomalies and maintain incident procedures.",
            "category": "monitoring",
        },
        "CC8.1": {
            "title": "Change Management — Authorized Changes",
            "description": "Manage changes through testing, approval, and implementation.",
            "category": "devops",
        },
        "A1.1": {
            "title": "Availability — Processing Capacity & Demand Management",
            "description": "Maintain availability commitments through capacity planning.",
            "category": "availability",
        },
        "C1.1": {
            "title": "Confidentiality — Data Classification & Protection",
            "description": "Identify and protect confidential information.",
            "category": "data_protection",
        },
    },
    "HIPAA": {
        "§164.312(a)(1)": {
            "title": "Access Control",
            "description": "Implement policies and procedures for electronic PHI access.",
            "category": "identity",
        },
        "§164.312(a)(2)(iv)": {
            "title": "Encryption & Decryption",
            "description": "Encrypt and decrypt electronic PHI.",
            "category": "security",
        },
        "§164.312(b)": {
            "title": "Audit Controls",
            "description": "Implement mechanisms to record and examine PHI access.",
            "category": "monitoring",
        },
        "§164.312(c)(1)": {
            "title": "Integrity Controls",
            "description": "Protect electronic PHI from improper alteration or destruction.",
            "category": "data_protection",
        },
        "§164.312(d)": {
            "title": "Person or Entity Authentication",
            "description": "Verify the identity of persons seeking access to PHI.",
            "category": "identity",
        },
        "§164.312(e)(1)": {
            "title": "Transmission Security",
            "description": "Guard against unauthorized access to PHI during transmission.",
            "category": "network",
        },
        "§164.308(a)(7)": {
            "title": "Contingency Plan",
            "description": "Establish policies for responding to system emergencies.",
            "category": "availability",
        },
        "§164.314(a)": {
            "title": "Business Associate Agreement",
            "description": "Satisfactory assurances from business associates.",
            "category": "compliance",
        },
    },
    "PCI-DSS": {
        "1.1": {
            "title": "Install & Maintain Network Security Controls",
            "description": "Firewall / network segmentation between CDE and untrusted networks.",
            "category": "network",
        },
        "3.4": {
            "title": "Render PAN Unreadable Anywhere It Is Stored",
            "description": "Encrypt stored cardholder data using strong cryptography.",
            "category": "security",
        },
        "3.5": {
            "title": "Protect Cryptographic Keys",
            "description": "Restrict access to cryptographic keys to the fewest custodians.",
            "category": "security",
        },
        "4.1": {
            "title": "Encrypt Transmission of Cardholder Data",
            "description": "Use strong cryptography when transmitting cardholder data.",
            "category": "network",
        },
        "6.6": {
            "title": "Protect Public-Facing Web Applications",
            "description": "Deploy WAF or perform code reviews for public apps.",
            "category": "application",
        },
        "8.3": {
            "title": "Multi-Factor Authentication",
            "description": "Secure all individual non-console admin access with MFA.",
            "category": "identity",
        },
        "10.1": {
            "title": "Audit Trail — Log All Access",
            "description": "Link all access to system components to individual users.",
            "category": "monitoring",
        },
        "10.7": {
            "title": "Audit Trail — Retain History",
            "description": "Retain audit trail history for at least one year.",
            "category": "monitoring",
        },
    },
    "GDPR": {
        "Art.5(1)(f)": {
            "title": "Integrity & Confidentiality",
            "description": "Appropriate security including protection against unauthorised "
                           "processing, accidental loss, destruction, or damage.",
            "category": "security",
        },
        "Art.17": {
            "title": "Right to Erasure",
            "description": "Data subjects may request deletion of personal data.",
            "category": "data_protection",
        },
        "Art.20": {
            "title": "Right to Data Portability",
            "description": "Data subjects may receive their data in machine-readable format.",
            "category": "data_protection",
        },
        "Art.25": {
            "title": "Data Protection by Design & Default",
            "description": "Implement data-minimisation and pseudonymisation measures.",
            "category": "compliance",
        },
        "Art.30": {
            "title": "Records of Processing Activities",
            "description": "Maintain records of all processing activities.",
            "category": "monitoring",
        },
        "Art.32": {
            "title": "Security of Processing",
            "description": "Implement encryption, pseudonymisation, resilience, "
                           "and regular testing of security measures.",
            "category": "security",
        },
        "Art.33": {
            "title": "Breach Notification — Supervisory Authority",
            "description": "Notify supervisory authority within 72 hours of breach.",
            "category": "monitoring",
        },
        "Art.44": {
            "title": "Data Transfers — Adequate Safeguards",
            "description": "Transfer personal data only to countries with adequate protection.",
            "category": "data_residency",
        },
    },
    "ISO 27001": {
        "A.8": {
            "title": "Asset Management",
            "description": "Identify and classify information assets.",
            "category": "data_protection",
        },
        "A.9": {
            "title": "Access Control",
            "description": "Limit access to information and processing facilities.",
            "category": "identity",
        },
        "A.10": {
            "title": "Cryptography",
            "description": "Ensure proper use of cryptography to protect information.",
            "category": "security",
        },
        "A.12": {
            "title": "Operations Security",
            "description": "Ensure secure operations of information processing facilities.",
            "category": "monitoring",
        },
        "A.13": {
            "title": "Communications Security",
            "description": "Protect information in networks and transfers.",
            "category": "network",
        },
        "A.16": {
            "title": "Incident Management",
            "description": "Consistent approach to managing security incidents.",
            "category": "monitoring",
        },
        "A.17": {
            "title": "Business Continuity",
            "description": "Information security embedded in business continuity management.",
            "category": "availability",
        },
        "A.18": {
            "title": "Compliance",
            "description": "Avoid breaches of legal, statutory, or contractual obligations.",
            "category": "compliance",
        },
    },
    "FedRAMP": {
        "AC-2": {
            "title": "Account Management",
            "description": "Manage information system accounts.",
            "category": "identity",
        },
        "AU-2": {
            "title": "Audit Events",
            "description": "Determine auditable events for the system.",
            "category": "monitoring",
        },
        "SC-8": {
            "title": "Transmission Confidentiality & Integrity",
            "description": "Protect transmitted information confidentiality and integrity.",
            "category": "network",
        },
        "SC-13": {
            "title": "Cryptographic Protection",
            "description": "Use FIPS-validated cryptographic mechanisms.",
            "category": "security",
        },
        "SC-28": {
            "title": "Protection of Information at Rest",
            "description": "Protect the confidentiality and integrity of stored information.",
            "category": "security",
        },
        "CP-9": {
            "title": "Information System Backup",
            "description": "Conduct backups of system-level and user-level information.",
            "category": "availability",
        },
        "IR-6": {
            "title": "Incident Reporting",
            "description": "Report incidents to appropriate authorities.",
            "category": "monitoring",
        },
        "RA-5": {
            "title": "Vulnerability Scanning",
            "description": "Scan for vulnerabilities and remediate findings.",
            "category": "security",
        },
    },
}

# ── Azure service → compliance control mapping ──
# Each service maps to a list of (framework, control_id) pairs it satisfies.

SERVICE_CONTROL_MAP: Dict[str, List[Dict[str, str]]] = {
    # ── Identity & Access ──
    "Azure AD": [
        {"framework": "SOC 2", "control": "CC6.1"},
        {"framework": "SOC 2", "control": "CC6.2"},
        {"framework": "SOC 2", "control": "CC6.3"},
        {"framework": "HIPAA", "control": "§164.312(a)(1)"},
        {"framework": "HIPAA", "control": "§164.312(d)"},
        {"framework": "PCI-DSS", "control": "8.3"},
        {"framework": "GDPR", "control": "Art.5(1)(f)"},
        {"framework": "ISO 27001", "control": "A.9"},
        {"framework": "FedRAMP", "control": "AC-2"},
    ],
    "Entra ID": [
        {"framework": "SOC 2", "control": "CC6.1"},
        {"framework": "SOC 2", "control": "CC6.2"},
        {"framework": "SOC 2", "control": "CC6.3"},
        {"framework": "HIPAA", "control": "§164.312(a)(1)"},
        {"framework": "HIPAA", "control": "§164.312(d)"},
        {"framework": "PCI-DSS", "control": "8.3"},
        {"framework": "GDPR", "control": "Art.5(1)(f)"},
        {"framework": "ISO 27001", "control": "A.9"},
        {"framework": "FedRAMP", "control": "AC-2"},
    ],
    # ── Encryption & Key Management ──
    "Azure Key Vault": [
        {"framework": "SOC 2", "control": "CC6.1"},
        {"framework": "SOC 2", "control": "C1.1"},
        {"framework": "HIPAA", "control": "§164.312(a)(2)(iv)"},
        {"framework": "PCI-DSS", "control": "3.4"},
        {"framework": "PCI-DSS", "control": "3.5"},
        {"framework": "GDPR", "control": "Art.32"},
        {"framework": "ISO 27001", "control": "A.10"},
        {"framework": "FedRAMP", "control": "SC-13"},
    ],
    "Key Vault": [
        {"framework": "SOC 2", "control": "CC6.1"},
        {"framework": "SOC 2", "control": "C1.1"},
        {"framework": "HIPAA", "control": "§164.312(a)(2)(iv)"},
        {"framework": "PCI-DSS", "control": "3.4"},
        {"framework": "PCI-DSS", "control": "3.5"},
        {"framework": "GDPR", "control": "Art.32"},
        {"framework": "ISO 27001", "control": "A.10"},
        {"framework": "FedRAMP", "control": "SC-13"},
    ],
    # ── Databases ──
    "Azure SQL": [
        {"framework": "SOC 2", "control": "CC6.1"},
        {"framework": "HIPAA", "control": "§164.312(a)(2)(iv)"},
        {"framework": "HIPAA", "control": "§164.312(e)(1)"},
        {"framework": "PCI-DSS", "control": "3.4"},
        {"framework": "GDPR", "control": "Art.32"},
        {"framework": "ISO 27001", "control": "A.10"},
        {"framework": "FedRAMP", "control": "SC-28"},
    ],
    "Azure SQL Database": [
        {"framework": "SOC 2", "control": "CC6.1"},
        {"framework": "HIPAA", "control": "§164.312(a)(2)(iv)"},
        {"framework": "HIPAA", "control": "§164.312(e)(1)"},
        {"framework": "PCI-DSS", "control": "3.4"},
        {"framework": "GDPR", "control": "Art.32"},
        {"framework": "ISO 27001", "control": "A.10"},
        {"framework": "FedRAMP", "control": "SC-28"},
    ],
    "Azure Cosmos DB": [
        {"framework": "SOC 2", "control": "CC6.1"},
        {"framework": "HIPAA", "control": "§164.312(a)(2)(iv)"},
        {"framework": "PCI-DSS", "control": "3.4"},
        {"framework": "GDPR", "control": "Art.32"},
        {"framework": "GDPR", "control": "Art.44"},
        {"framework": "ISO 27001", "control": "A.10"},
        {"framework": "FedRAMP", "control": "SC-28"},
    ],
    "Cosmos DB": [
        {"framework": "SOC 2", "control": "CC6.1"},
        {"framework": "HIPAA", "control": "§164.312(a)(2)(iv)"},
        {"framework": "PCI-DSS", "control": "3.4"},
        {"framework": "GDPR", "control": "Art.32"},
        {"framework": "GDPR", "control": "Art.44"},
        {"framework": "ISO 27001", "control": "A.10"},
        {"framework": "FedRAMP", "control": "SC-28"},
    ],
    "Azure Database for PostgreSQL": [
        {"framework": "SOC 2", "control": "CC6.1"},
        {"framework": "HIPAA", "control": "§164.312(a)(2)(iv)"},
        {"framework": "HIPAA", "control": "§164.312(e)(1)"},
        {"framework": "PCI-DSS", "control": "3.4"},
        {"framework": "GDPR", "control": "Art.32"},
        {"framework": "ISO 27001", "control": "A.10"},
        {"framework": "FedRAMP", "control": "SC-28"},
    ],
    "Azure Database for MySQL": [
        {"framework": "SOC 2", "control": "CC6.1"},
        {"framework": "HIPAA", "control": "§164.312(a)(2)(iv)"},
        {"framework": "PCI-DSS", "control": "3.4"},
        {"framework": "GDPR", "control": "Art.32"},
        {"framework": "ISO 27001", "control": "A.10"},
        {"framework": "FedRAMP", "control": "SC-28"},
    ],
    # ── Networking & WAF ──
    "Azure WAF": [
        {"framework": "PCI-DSS", "control": "6.6"},
        {"framework": "SOC 2", "control": "CC7.1"},
        {"framework": "ISO 27001", "control": "A.13"},
        {"framework": "FedRAMP", "control": "SC-8"},
    ],
    "Azure Firewall": [
        {"framework": "PCI-DSS", "control": "1.1"},
        {"framework": "SOC 2", "control": "CC7.1"},
        {"framework": "ISO 27001", "control": "A.13"},
        {"framework": "FedRAMP", "control": "SC-8"},
    ],
    "Azure Application Gateway": [
        {"framework": "PCI-DSS", "control": "6.6"},
        {"framework": "PCI-DSS", "control": "4.1"},
        {"framework": "SOC 2", "control": "CC7.1"},
        {"framework": "HIPAA", "control": "§164.312(e)(1)"},
        {"framework": "ISO 27001", "control": "A.13"},
    ],
    "Azure Front Door": [
        {"framework": "PCI-DSS", "control": "6.6"},
        {"framework": "PCI-DSS", "control": "4.1"},
        {"framework": "SOC 2", "control": "CC7.1"},
        {"framework": "HIPAA", "control": "§164.312(e)(1)"},
        {"framework": "ISO 27001", "control": "A.13"},
    ],
    "Azure VNet": [
        {"framework": "PCI-DSS", "control": "1.1"},
        {"framework": "ISO 27001", "control": "A.13"},
        {"framework": "FedRAMP", "control": "SC-8"},
    ],
    "Virtual Network": [
        {"framework": "PCI-DSS", "control": "1.1"},
        {"framework": "ISO 27001", "control": "A.13"},
        {"framework": "FedRAMP", "control": "SC-8"},
    ],
    "Azure DDoS Protection": [
        {"framework": "PCI-DSS", "control": "1.1"},
        {"framework": "SOC 2", "control": "A1.1"},
        {"framework": "ISO 27001", "control": "A.17"},
        {"framework": "FedRAMP", "control": "SC-8"},
    ],
    # ── Monitoring & Logging ──
    "Azure Monitor": [
        {"framework": "SOC 2", "control": "CC7.1"},
        {"framework": "SOC 2", "control": "CC7.2"},
        {"framework": "HIPAA", "control": "§164.312(b)"},
        {"framework": "PCI-DSS", "control": "10.1"},
        {"framework": "PCI-DSS", "control": "10.7"},
        {"framework": "GDPR", "control": "Art.30"},
        {"framework": "GDPR", "control": "Art.33"},
        {"framework": "ISO 27001", "control": "A.12"},
        {"framework": "ISO 27001", "control": "A.16"},
        {"framework": "FedRAMP", "control": "AU-2"},
        {"framework": "FedRAMP", "control": "IR-6"},
    ],
    "Log Analytics": [
        {"framework": "SOC 2", "control": "CC7.2"},
        {"framework": "HIPAA", "control": "§164.312(b)"},
        {"framework": "PCI-DSS", "control": "10.1"},
        {"framework": "PCI-DSS", "control": "10.7"},
        {"framework": "GDPR", "control": "Art.30"},
        {"framework": "ISO 27001", "control": "A.12"},
        {"framework": "FedRAMP", "control": "AU-2"},
    ],
    "Microsoft Sentinel": [
        {"framework": "SOC 2", "control": "CC7.2"},
        {"framework": "HIPAA", "control": "§164.312(b)"},
        {"framework": "PCI-DSS", "control": "10.1"},
        {"framework": "GDPR", "control": "Art.33"},
        {"framework": "ISO 27001", "control": "A.16"},
        {"framework": "FedRAMP", "control": "IR-6"},
    ],
    "Microsoft Defender for Cloud": [
        {"framework": "SOC 2", "control": "CC7.1"},
        {"framework": "SOC 2", "control": "CC7.2"},
        {"framework": "HIPAA", "control": "§164.312(b)"},
        {"framework": "PCI-DSS", "control": "10.1"},
        {"framework": "ISO 27001", "control": "A.12"},
        {"framework": "ISO 27001", "control": "A.16"},
        {"framework": "FedRAMP", "control": "RA-5"},
    ],
    # ── Storage ──
    "Azure Blob Storage": [
        {"framework": "SOC 2", "control": "CC6.1"},
        {"framework": "HIPAA", "control": "§164.312(a)(2)(iv)"},
        {"framework": "HIPAA", "control": "§164.312(c)(1)"},
        {"framework": "PCI-DSS", "control": "3.4"},
        {"framework": "GDPR", "control": "Art.32"},
        {"framework": "GDPR", "control": "Art.17"},
        {"framework": "ISO 27001", "control": "A.8"},
        {"framework": "FedRAMP", "control": "SC-28"},
    ],
    "Azure Storage": [
        {"framework": "SOC 2", "control": "CC6.1"},
        {"framework": "HIPAA", "control": "§164.312(a)(2)(iv)"},
        {"framework": "PCI-DSS", "control": "3.4"},
        {"framework": "GDPR", "control": "Art.32"},
        {"framework": "ISO 27001", "control": "A.8"},
        {"framework": "FedRAMP", "control": "SC-28"},
    ],
    # ── Backup & DR ──
    "Azure Backup": [
        {"framework": "HIPAA", "control": "§164.308(a)(7)"},
        {"framework": "SOC 2", "control": "A1.1"},
        {"framework": "ISO 27001", "control": "A.17"},
        {"framework": "FedRAMP", "control": "CP-9"},
    ],
    "Azure Site Recovery": [
        {"framework": "HIPAA", "control": "§164.308(a)(7)"},
        {"framework": "SOC 2", "control": "A1.1"},
        {"framework": "ISO 27001", "control": "A.17"},
        {"framework": "FedRAMP", "control": "CP-9"},
    ],
    # ── Compliance & Governance ──
    "Microsoft Purview": [
        {"framework": "GDPR", "control": "Art.17"},
        {"framework": "GDPR", "control": "Art.20"},
        {"framework": "GDPR", "control": "Art.25"},
        {"framework": "GDPR", "control": "Art.30"},
        {"framework": "HIPAA", "control": "§164.312(c)(1)"},
        {"framework": "ISO 27001", "control": "A.8"},
        {"framework": "ISO 27001", "control": "A.18"},
    ],
    "Azure Policy": [
        {"framework": "SOC 2", "control": "CC8.1"},
        {"framework": "GDPR", "control": "Art.25"},
        {"framework": "ISO 27001", "control": "A.18"},
        {"framework": "FedRAMP", "control": "AC-2"},
    ],
    # ── Compute & App Hosting ──
    "Azure App Service": [
        {"framework": "HIPAA", "control": "§164.312(e)(1)"},
        {"framework": "PCI-DSS", "control": "4.1"},
        {"framework": "GDPR", "control": "Art.32"},
    ],
    "Azure Container Apps": [
        {"framework": "HIPAA", "control": "§164.312(e)(1)"},
        {"framework": "PCI-DSS", "control": "4.1"},
        {"framework": "GDPR", "control": "Art.32"},
    ],
    "Azure Kubernetes Service": [
        {"framework": "HIPAA", "control": "§164.312(e)(1)"},
        {"framework": "PCI-DSS", "control": "4.1"},
        {"framework": "GDPR", "control": "Art.32"},
        {"framework": "ISO 27001", "control": "A.12"},
    ],
    "AKS": [
        {"framework": "HIPAA", "control": "§164.312(e)(1)"},
        {"framework": "PCI-DSS", "control": "4.1"},
        {"framework": "GDPR", "control": "Art.32"},
        {"framework": "ISO 27001", "control": "A.12"},
    ],
    "Azure Functions": [
        {"framework": "HIPAA", "control": "§164.312(e)(1)"},
        {"framework": "PCI-DSS", "control": "4.1"},
    ],
    # ── BAA / Governance ──
    "Microsoft BAA": [
        {"framework": "HIPAA", "control": "§164.314(a)"},
    ],
    "Azure Government": [
        {"framework": "FedRAMP", "control": "AC-2"},
        {"framework": "FedRAMP", "control": "SC-13"},
        {"framework": "FedRAMP", "control": "SC-28"},
    ],
}

# ── Gap definitions: what's missing when a control has no covering service ──

GAP_REMEDIATION: Dict[str, Dict[str, Any]] = {
    "identity": {
        "description": "No identity/access management service detected. "
                       "Authentication and authorization are uncovered.",
        "severity": "critical",
        "recommended_service": "Azure AD / Entra ID with Conditional Access and PIM",
    },
    "security": {
        "description": "No encryption or key management service detected. "
                       "Data-at-rest and secrets management are unprotected.",
        "severity": "critical",
        "recommended_service": "Azure Key Vault with Customer-Managed Keys (CMK)",
    },
    "monitoring": {
        "description": "No logging or monitoring service detected. "
                       "Audit trails and incident detection are absent.",
        "severity": "critical",
        "recommended_service": "Azure Monitor + Log Analytics + Microsoft Sentinel",
    },
    "network": {
        "description": "No network security or WAF service detected. "
                       "Transmission security and perimeter defence are missing.",
        "severity": "high",
        "recommended_service": "Azure Firewall + Azure WAF + VNet with NSGs",
    },
    "application": {
        "description": "No web application firewall detected. "
                       "Public-facing applications lack L7 protection.",
        "severity": "high",
        "recommended_service": "Azure WAF on Application Gateway or Front Door",
    },
    "data_protection": {
        "description": "No data classification or lifecycle management detected. "
                       "Data subject rights and data integrity are uncovered.",
        "severity": "high",
        "recommended_service": "Microsoft Purview for classification, discovery, and lifecycle",
    },
    "availability": {
        "description": "No backup or disaster recovery service detected. "
                       "Business continuity requirements are unmet.",
        "severity": "high",
        "recommended_service": "Azure Backup + Azure Site Recovery with geo-redundancy",
    },
    "data_residency": {
        "description": "No data residency controls detected. "
                       "Cross-border data transfer requirements may be violated.",
        "severity": "medium",
        "recommended_service": "Azure Policy with region restrictions + Cosmos DB multi-region",
    },
    "compliance": {
        "description": "No compliance tooling or governance framework detected.",
        "severity": "medium",
        "recommended_service": "Azure Policy + Microsoft Purview Compliance Manager",
    },
    "devops": {
        "description": "No change management or deployment gate controls detected.",
        "severity": "medium",
        "recommended_service": "Azure DevOps with approval gates and audit logging",
    },
}


def _resolve_frameworks(requested: List[str]) -> List[str]:
    """Resolve user-supplied framework aliases to canonical FRAMEWORKS keys."""
    resolved = []
    for raw in requested:
        key = FRAMEWORK_ALIASES.get(raw.lower().strip())
        if key and key in FRAMEWORK_CONTROLS:
            if key not in resolved:
                resolved.append(key)
    return resolved


def _extract_azure_services(analysis: Dict[str, Any]) -> Set[str]:
    """Extract Azure service names from analysis mappings."""
    services: Set[str] = set()
    for m in analysis.get("mappings", []):
        azure = m.get("azure", m.get("target_service", ""))
        if isinstance(azure, dict):
            azure = azure.get("name", "")
        if azure:
            services.add(azure)
    return services


def map_compliance(
    analysis: Dict[str, Any],
    requested_frameworks: List[str],
) -> Dict[str, Any]:
    """
    Map detected Azure services to compliance controls and compute gaps.

    Args:
        analysis: Diagram analysis with ``mappings`` containing Azure services.
        requested_frameworks: Framework aliases (e.g. ``["soc2", "hipaa"]``).

    Returns:
        Full compliance mapping with per-framework scores, control coverage,
        gaps, and recommendations.
    """
    start = time.time()

    frameworks = _resolve_frameworks(requested_frameworks)
    if not frameworks:
        frameworks = list(FRAMEWORK_CONTROLS.keys())

    azure_services = _extract_azure_services(analysis)

    # Build per-framework results
    results: Dict[str, Any] = {}
    for fw in frameworks:
        controls = FRAMEWORK_CONTROLS.get(fw, {})

        # Determine which controls are satisfied
        covered_controls: Dict[str, List[str]] = {}   # control_id → [services]
        for svc in azure_services:
            for mapping in SERVICE_CONTROL_MAP.get(svc, []):
                if mapping["framework"] == fw:
                    cid = mapping["control"]
                    if cid not in covered_controls:
                        covered_controls[cid] = []
                    covered_controls[cid].append(svc)

        # Compute gaps
        gaps: List[Dict[str, Any]] = []
        covered_categories: Set[str] = set()
        for cid, cdef in controls.items():
            cat = cdef.get("category", "")
            if cid in covered_controls:
                covered_categories.add(cat)
            else:
                gap_info = GAP_REMEDIATION.get(cat, {
                    "description": f"Control {cid} ({cdef['title']}) is not covered.",
                    "severity": "medium",
                    "recommended_service": "Review architecture for coverage",
                })
                gaps.append({
                    "control_id": cid,
                    "control_title": cdef["title"],
                    "description": gap_info["description"],
                    "severity": gap_info["severity"],
                    "recommended_service": gap_info["recommended_service"],
                    "category": cat,
                })

        total = len(controls)
        covered = len(covered_controls)
        score = round((covered / total) * 100) if total > 0 else 0

        results[fw] = {
            "framework": fw,
            "full_name": FRAMEWORKS[fw]["full_name"],
            "total_controls": total,
            "covered_controls": covered,
            "score": score,
            "status": "passing" if score >= 80 else ("warning" if score >= 50 else "failing"),
            "covered": {
                cid: {
                    "title": controls[cid]["title"],
                    "satisfied_by": svcs,
                }
                for cid, svcs in covered_controls.items()
            },
            "gaps": gaps,
            "gap_count": len(gaps),
            "azure_policies": FRAMEWORKS[fw].get("azure_policies", []),
        }

    # Overall
    all_scores = [r["score"] for r in results.values()]
    overall_score = round(sum(all_scores) / len(all_scores)) if all_scores else 0
    total_gaps = sum(r["gap_count"] for r in results.values())

    recommendations = _build_gap_recommendations(results, azure_services)

    elapsed = round((time.time() - start) * 1000, 1)
    logger.info(
        "Compliance mapping: %d frameworks, score=%d, gaps=%d, %.1fms",
        len(results), overall_score, total_gaps, elapsed,
    )

    return {
        "frameworks": results,
        "overall_score": overall_score,
        "total_gaps": total_gaps,
        "azure_services_detected": sorted(azure_services),
        "requested_frameworks": frameworks,
        "recommendations": recommendations,
        "generated_at": time.time(),
        "computation_time_ms": elapsed,
    }


def get_compliance_gaps(
    analysis: Dict[str, Any],
    requested_frameworks: List[str],
) -> Dict[str, Any]:
    """Return only the gap analysis portion, sorted by severity."""
    full = map_compliance(analysis, requested_frameworks)

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    all_gaps: List[Dict[str, Any]] = []
    for fw_id, fw_data in full["frameworks"].items():
        for gap in fw_data["gaps"]:
            all_gaps.append({**gap, "framework": fw_id})

    all_gaps.sort(key=lambda g: severity_order.get(g["severity"], 9))

    critical = sum(1 for g in all_gaps if g["severity"] == "critical")
    high = sum(1 for g in all_gaps if g["severity"] == "high")

    return {
        "total_gaps": len(all_gaps),
        "critical": critical,
        "high": high,
        "medium": len(all_gaps) - critical - high,
        "gaps": all_gaps,
        "overall_score": full["overall_score"],
        "recommendations": full["recommendations"],
    }


def export_compliance_report(
    analysis: Dict[str, Any],
    requested_frameworks: List[str],
    fmt: str = "json",
) -> Dict[str, Any]:
    """Export compliance report in JSON or Markdown format."""
    full = map_compliance(analysis, requested_frameworks)

    if fmt == "md":
        md = _render_markdown(full)
        return {"format": "markdown", "content": md, "data": full}

    return {"format": "json", "data": full}


def _build_gap_recommendations(
    framework_results: Dict[str, Any],
    azure_services: Set[str],
) -> List[Dict[str, Any]]:
    """Build prioritised remediation recommendations from gap analysis."""
    recs: List[Dict[str, Any]] = []
    seen_categories: Set[str] = set()

    # Aggregate gaps across frameworks by category
    category_gaps: Dict[str, List[str]] = {}
    for fw_id, fw_data in framework_results.items():
        for gap in fw_data.get("gaps", []):
            cat = gap.get("category", "other")
            if cat not in category_gaps:
                category_gaps[cat] = []
            category_gaps[cat].append(fw_id)

    severity_order = {"critical": 0, "high": 1, "medium": 2}

    for cat, affected_fws in sorted(
        category_gaps.items(),
        key=lambda x: -len(x[1]),
    ):
        if cat in seen_categories:
            continue
        seen_categories.add(cat)
        remedy = GAP_REMEDIATION.get(cat, {})
        sev = remedy.get("severity", "medium")
        unique_fws = sorted(set(affected_fws))
        recs.append({
            "id": f"GAP-{cat.upper().replace(' ', '_')}",
            "category": cat,
            "severity": sev,
            "affected_frameworks": unique_fws,
            "description": remedy.get("description", f"Gap in {cat} controls."),
            "recommended_service": remedy.get("recommended_service", ""),
            "priority_score": len(unique_fws) * 10 + (2 - severity_order.get(sev, 2)) * 5,
        })

    recs.sort(key=lambda r: -r["priority_score"])
    return recs


def _render_markdown(report: Dict[str, Any]) -> str:
    """Render a compliance report dict as Markdown."""
    lines: List[str] = []
    lines.append("# Compliance Framework Mapping & Gap Analysis")
    lines.append("")
    lines.append(f"**Overall Readiness Score:** {report['overall_score']}%")
    lines.append(f"**Azure Services Detected:** {len(report['azure_services_detected'])}")
    lines.append(f"**Total Gaps:** {report['total_gaps']}")
    lines.append("")

    for fw_id, fw in report["frameworks"].items():
        status_icon = {"passing": "✅", "warning": "⚠️", "failing": "❌"}.get(
            fw["status"], "❓"
        )
        lines.append(f"## {status_icon} {fw_id} — {fw['full_name']}")
        lines.append("")
        lines.append(f"**Score:** {fw['score']}% ({fw['covered_controls']}/{fw['total_controls']} controls)")
        lines.append(f"**Status:** {fw['status'].upper()}")
        lines.append("")

        if fw["covered"]:
            lines.append("### Controls Satisfied")
            lines.append("")
            lines.append("| Control | Title | Satisfied By |")
            lines.append("|---------|-------|-------------|")
            for cid, info in fw["covered"].items():
                svcs = ", ".join(info["satisfied_by"])
                lines.append(f"| {cid} | {info['title']} | {svcs} |")
            lines.append("")

        if fw["gaps"]:
            lines.append("### Gaps")
            lines.append("")
            lines.append("| Sev | Control | Title | Recommended Service |")
            lines.append("|-----|---------|-------|-------------------|")
            for gap in fw["gaps"]:
                sev_badge = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(
                    gap["severity"], "⚪"
                )
                lines.append(
                    f"| {sev_badge} {gap['severity']} | {gap['control_id']} "
                    f"| {gap['control_title']} | {gap['recommended_service']} |"
                )
            lines.append("")

    if report.get("recommendations"):
        lines.append("## Recommendations")
        lines.append("")
        for i, rec in enumerate(report["recommendations"], 1):
            lines.append(f"### {i}. {rec['id']}")
            lines.append(f"- **Severity:** {rec['severity']}")
            lines.append(f"- **Affected Frameworks:** {', '.join(rec['affected_frameworks'])}")
            lines.append(f"- **Description:** {rec['description']}")
            lines.append(f"- **Recommended Service:** {rec['recommended_service']}")
            lines.append("")

    lines.append("---")
    lines.append("*Generated by Archmorph Compliance Mapper*")
    lines.append("")

    return "\n".join(lines)
