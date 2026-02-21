"""
Archmorph Best Practices Linter — Azure Well-Architected Framework Analysis

Analyzes detected architecture and provides recommendations based on:
- WAF pillars: Reliability, Security, Cost, Operational Excellence, Performance
- Azure best practices for each detected service category
- Security posture assessment
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class WAFPillar(str, Enum):
    RELIABILITY = "reliability"
    SECURITY = "security"
    COST = "cost"
    OPERATIONAL_EXCELLENCE = "operational_excellence"
    PERFORMANCE = "performance"


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class Recommendation:
    id: str
    title: str
    description: str
    pillar: WAFPillar
    severity: Severity
    category: str
    action: str
    azure_doc_link: Optional[str] = None
    services_affected: List[str] = None
    
    def __post_init__(self):
        if self.services_affected is None:
            self.services_affected = []


# ─────────────────────────────────────────────────────────────
# Best Practice Rules by Service Category
# ─────────────────────────────────────────────────────────────

RELIABILITY_RULES = [
    {
        "id": "rel-001",
        "trigger": lambda zones, services: any(z.get("name", "").lower() in ["compute", "web tier", "application"] for z in zones),
        "condition": lambda zones, services, answers: not any(s.lower() in ["availability zones", "availability_zones", "zone_redundant"] for s in str(answers).lower().split()),
        "rec": Recommendation(
            id="rel-001",
            title="Enable Availability Zones",
            description="Your compute tier lacks multi-AZ deployment. In Azure, deploying across Availability Zones provides 99.99% SLA.",
            pillar=WAFPillar.RELIABILITY,
            severity=Severity.HIGH,
            category="Compute",
            action="Configure zone-redundant deployment for VMs, AKS, or Container Apps",
            azure_doc_link="https://learn.microsoft.com/en-us/azure/reliability/availability-zones-overview"
        )
    },
    {
        "id": "rel-002",
        "trigger": lambda zones, services: any("database" in z.get("name", "").lower() or "data" in z.get("name", "").lower() for z in zones),
        "condition": lambda zones, services, answers: "geo" not in str(answers).lower() and "backup" not in str(answers).lower(),
        "rec": Recommendation(
            id="rel-002",
            title="Enable Geo-Redundant Backups",
            description="Database services should have geo-redundant backups for disaster recovery.",
            pillar=WAFPillar.RELIABILITY,
            severity=Severity.HIGH,
            category="Data",
            action="Enable geo-redundant backup for Azure SQL, PostgreSQL, or Cosmos DB",
            azure_doc_link="https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/concepts-backup-restore"
        )
    },
    {
        "id": "rel-003",
        "trigger": lambda zones, services: len(services) > 5,
        "condition": lambda zones, services, answers: True,
        "rec": Recommendation(
            id="rel-003",
            title="Implement Health Probes",
            description="Complex architectures benefit from health probes and automatic failover.",
            pillar=WAFPillar.RELIABILITY,
            severity=Severity.MEDIUM,
            category="Monitoring",
            action="Configure health probes on Load Balancer, Application Gateway, and Container Apps",
            azure_doc_link="https://learn.microsoft.com/en-us/azure/load-balancer/load-balancer-custom-probe-overview"
        )
    }
]

SECURITY_RULES = [
    {
        "id": "sec-001",
        "trigger": lambda zones, services: True,
        "condition": lambda zones, services, answers: "key vault" not in str(services).lower() and "keyvault" not in str(services).lower(),
        "rec": Recommendation(
            id="sec-001",
            title="Add Azure Key Vault for Secrets",
            description="No secrets management detected. Store connection strings, API keys, and certificates in Key Vault.",
            pillar=WAFPillar.SECURITY,
            severity=Severity.HIGH,
            category="Security",
            action="Add Azure Key Vault and reference secrets from application configuration",
            azure_doc_link="https://learn.microsoft.com/en-us/azure/key-vault/general/overview"
        )
    },
    {
        "id": "sec-002",
        "trigger": lambda zones, services: any("api" in s.lower() or "gateway" in s.lower() for s in services),
        "condition": lambda zones, services, answers: "waf" not in str(services).lower() and "firewall" not in str(services).lower(),
        "rec": Recommendation(
            id="sec-002",
            title="Add Web Application Firewall (WAF)",
            description="API Gateway detected without WAF protection. Add Azure WAF to protect against OWASP threats.",
            pillar=WAFPillar.SECURITY,
            severity=Severity.HIGH,
            category="Security",
            action="Enable WAF on Application Gateway or use Azure Front Door with WAF",
            azure_doc_link="https://learn.microsoft.com/en-us/azure/web-application-firewall/overview"
        )
    },
    {
        "id": "sec-003",
        "trigger": lambda zones, services: any("storage" in s.lower() or "blob" in s.lower() or "s3" in s.lower() for s in services),
        "condition": lambda zones, services, answers: True,
        "rec": Recommendation(
            id="sec-003",
            title="Enable Storage Encryption & Private Endpoints",
            description="Cloud storage should use encryption at rest and private endpoints for network isolation.",
            pillar=WAFPillar.SECURITY,
            severity=Severity.MEDIUM,
            category="Storage",
            action="Configure Azure Storage with customer-managed keys and private endpoints",
            azure_doc_link="https://learn.microsoft.com/en-us/azure/storage/common/storage-private-endpoints"
        )
    },
    {
        "id": "sec-004",
        "trigger": lambda zones, services: len(services) > 0,
        "condition": lambda zones, services, answers: True,
        "rec": Recommendation(
            id="sec-004",
            title="Use Managed Identities",
            description="Avoid storing credentials in code. Use Azure Managed Identities for service-to-service authentication.",
            pillar=WAFPillar.SECURITY,
            severity=Severity.MEDIUM,
            category="Identity",
            action="Enable System or User Assigned Managed Identity for all Azure resources",
            azure_doc_link="https://learn.microsoft.com/en-us/azure/active-directory/managed-identities-azure-resources/overview"
        )
    }
]

COST_RULES = [
    {
        "id": "cost-001",
        "trigger": lambda zones, services: any("vm" in s.lower() or "ec2" in s.lower() or "compute" in s.lower() for s in services),
        "condition": lambda zones, services, answers: "dev" in str(answers).lower() or "test" in str(answers).lower(),
        "rec": Recommendation(
            id="cost-001",
            title="Use Spot VMs for Dev/Test",
            description="Dev/Test workloads can use Azure Spot VMs for up to 90% cost savings.",
            pillar=WAFPillar.COST,
            severity=Severity.INFO,
            category="Compute",
            action="Configure Spot VM instances for non-production workloads",
            azure_doc_link="https://learn.microsoft.com/en-us/azure/virtual-machines/spot-vms"
        )
    },
    {
        "id": "cost-002",
        "trigger": lambda zones, services: any("database" in s.lower() or "sql" in s.lower() or "rds" in s.lower() for s in services),
        "condition": lambda zones, services, answers: "production" in str(answers).lower(),
        "rec": Recommendation(
            id="cost-002",
            title="Consider Reserved Capacity",
            description="Production databases benefit from 1-year or 3-year reserved capacity (up to 65% savings).",
            pillar=WAFPillar.COST,
            severity=Severity.MEDIUM,
            category="Data",
            action="Purchase Azure Reserved Capacity for predictable database workloads",
            azure_doc_link="https://learn.microsoft.com/en-us/azure/cost-management-billing/reservations/understand-reservation-charges"
        )
    },
    {
        "id": "cost-003",
        "trigger": lambda zones, services: True,
        "condition": lambda zones, services, answers: True,
        "rec": Recommendation(
            id="cost-003",
            title="Set Up Cost Alerts",
            description="Configure budget alerts to avoid unexpected charges.",
            pillar=WAFPillar.COST,
            severity=Severity.LOW,
            category="Governance",
            action="Create Azure Cost Management budgets with email alerts at 80% and 100% thresholds",
            azure_doc_link="https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets"
        )
    }
]

PERFORMANCE_RULES = [
    {
        "id": "perf-001",
        "trigger": lambda zones, services: any("web" in s.lower() or "frontend" in s.lower() or "static" in s.lower() for s in services),
        "condition": lambda zones, services, answers: "cdn" not in str(services).lower() and "cloudfront" not in str(services).lower(),
        "rec": Recommendation(
            id="perf-001",
            title="Add CDN for Static Assets",
            description="Web frontends benefit from Azure CDN or Front Door for global edge caching.",
            pillar=WAFPillar.PERFORMANCE,
            severity=Severity.MEDIUM,
            category="Networking",
            action="Configure Azure Front Door or CDN for static content delivery",
            azure_doc_link="https://learn.microsoft.com/en-us/azure/frontdoor/front-door-overview"
        )
    },
    {
        "id": "perf-002",
        "trigger": lambda zones, services: any("cache" in s.lower() or "redis" in s.lower() or "elasticache" in s.lower() for s in services),
        "condition": lambda zones, services, answers: True,
        "rec": Recommendation(
            id="perf-002",
            title="Optimize Cache Configuration",
            description="Redis cache detected. Ensure proper eviction policies and cluster mode for high throughput.",
            pillar=WAFPillar.PERFORMANCE,
            severity=Severity.LOW,
            category="Data",
            action="Configure Azure Cache for Redis with appropriate SKU and clustering",
            azure_doc_link="https://learn.microsoft.com/en-us/azure/azure-cache-for-redis/cache-best-practices"
        )
    },
    {
        "id": "perf-003",
        "trigger": lambda zones, services: len(services) > 10,
        "condition": lambda zones, services, answers: True,
        "rec": Recommendation(
            id="perf-003",
            title="Implement Application Insights",
            description="Complex architectures need APM for performance monitoring and distributed tracing.",
            pillar=WAFPillar.PERFORMANCE,
            severity=Severity.MEDIUM,
            category="Monitoring",
            action="Enable Application Insights with distributed tracing for all services",
            azure_doc_link="https://learn.microsoft.com/en-us/azure/azure-monitor/app/app-insights-overview"
        )
    }
]

OPS_RULES = [
    {
        "id": "ops-001",
        "trigger": lambda zones, services: True,
        "condition": lambda zones, services, answers: True,
        "rec": Recommendation(
            id="ops-001",
            title="Enable Diagnostic Settings",
            description="All Azure resources should send logs and metrics to Log Analytics for centralized monitoring.",
            pillar=WAFPillar.OPERATIONAL_EXCELLENCE,
            severity=Severity.MEDIUM,
            category="Monitoring",
            action="Configure diagnostic settings to send to Log Analytics workspace",
            azure_doc_link="https://learn.microsoft.com/en-us/azure/azure-monitor/essentials/diagnostic-settings"
        )
    },
    {
        "id": "ops-002",
        "trigger": lambda zones, services: True,
        "condition": lambda zones, services, answers: len(services) > 3,
        "rec": Recommendation(
            id="ops-002",
            title="Use Infrastructure as Code",
            description="Manage all resources through Terraform or Bicep for version control and repeatability.",
            pillar=WAFPillar.OPERATIONAL_EXCELLENCE,
            severity=Severity.HIGH,
            category="Automation",
            action="Store IaC in Git with CI/CD pipeline for automated deployments",
            azure_doc_link="https://learn.microsoft.com/en-us/azure/developer/terraform/overview"
        )
    },
    {
        "id": "ops-003",
        "trigger": lambda zones, services: any("container" in s.lower() or "kubernetes" in s.lower() or "aks" in s.lower() or "ecs" in s.lower() for s in services),
        "condition": lambda zones, services, answers: True,
        "rec": Recommendation(
            id="ops-003",
            title="Configure Auto-Scaling",
            description="Container workloads should use Horizontal Pod Autoscaler (HPA) or KEDA for automatic scaling.",
            pillar=WAFPillar.OPERATIONAL_EXCELLENCE,
            severity=Severity.MEDIUM,
            category="Containers",
            action="Configure HPA with CPU/memory metrics or KEDA for event-driven scaling",
            azure_doc_link="https://learn.microsoft.com/en-us/azure/aks/concepts-scale"
        )
    }
]

ALL_RULES = RELIABILITY_RULES + SECURITY_RULES + COST_RULES + PERFORMANCE_RULES + OPS_RULES

# ── Additional rules for new service categories (Issues #60–#67) ──

HYBRID_RULES = [
    {
        "id": "hybrid-001",
        "trigger": lambda zones, services: any("arc" in s.lower() or "hybrid" in s.lower() or "outposts" in s.lower() for s in services),
        "condition": lambda zones, services, answers: "arc" not in str(services).lower(),
        "rec": Recommendation(
            id="hybrid-001",
            title="Use Azure Arc for Hybrid Management",
            description="Hybrid workloads detected. Azure Arc provides a single control plane for multi-cloud and on-premises resources.",
            pillar=WAFPillar.OPERATIONAL_EXCELLENCE,
            severity=Severity.HIGH,
            category="Hybrid",
            action="Enable Azure Arc for unified governance across on-prem, edge, and multi-cloud resources",
            azure_doc_link="https://learn.microsoft.com/en-us/azure/azure-arc/overview"
        )
    },
    {
        "id": "hybrid-002",
        "trigger": lambda zones, services: any("arc" in s.lower() or "stack" in s.lower() for s in services),
        "condition": lambda zones, services, answers: True,
        "rec": Recommendation(
            id="hybrid-002",
            title="Apply Consistent Policies Across Hybrid Resources",
            description="Azure Policy should extend to Arc-managed resources for consistent compliance posture.",
            pillar=WAFPillar.SECURITY,
            severity=Severity.MEDIUM,
            category="Hybrid",
            action="Assign Azure Policy initiatives to Arc-enabled resources for compliance enforcement",
            azure_doc_link="https://learn.microsoft.com/en-us/azure/azure-arc/servers/security-overview"
        )
    },
]

GENAI_RULES = [
    {
        "id": "genai-001",
        "trigger": lambda zones, services: any("openai" in s.lower() or "bedrock" in s.lower() or "ai agent" in s.lower() or "foundry" in s.lower() for s in services),
        "condition": lambda zones, services, answers: "content safety" not in str(services).lower(),
        "rec": Recommendation(
            id="genai-001",
            title="Enable AI Content Safety",
            description="Generative AI services detected without content safety guardrails. Add Azure AI Content Safety.",
            pillar=WAFPillar.SECURITY,
            severity=Severity.HIGH,
            category="AI/ML",
            action="Configure Azure AI Content Safety to filter harmful content from LLM responses",
            azure_doc_link="https://learn.microsoft.com/en-us/azure/ai-services/content-safety/overview"
        )
    },
    {
        "id": "genai-002",
        "trigger": lambda zones, services: any("openai" in s.lower() or "bedrock" in s.lower() or "ai agent" in s.lower() for s in services),
        "condition": lambda zones, services, answers: True,
        "rec": Recommendation(
            id="genai-002",
            title="Implement Token/Rate Limiting for LLM APIs",
            description="LLM APIs can incur high costs without rate limits. Configure TPM/RPM limits in Azure OpenAI.",
            pillar=WAFPillar.COST,
            severity=Severity.HIGH,
            category="AI/ML",
            action="Set TPM (tokens per minute) and RPM (requests per minute) quotas in Azure OpenAI deployment",
            azure_doc_link="https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/quota"
        )
    },
]

EDGE_RULES = [
    {
        "id": "edge-001",
        "trigger": lambda zones, services: any("edge" in s.lower() or "wavelength" in s.lower() or "local zone" in s.lower() for s in services),
        "condition": lambda zones, services, answers: True,
        "rec": Recommendation(
            id="edge-001",
            title="Design for Edge Resilience",
            description="Edge deployments must handle intermittent connectivity. Design for store-and-forward patterns.",
            pillar=WAFPillar.RELIABILITY,
            severity=Severity.HIGH,
            category="Edge",
            action="Implement offline-capable patterns with data sync to cloud when connectivity resumes",
            azure_doc_link="https://learn.microsoft.com/en-us/azure/architecture/solution-ideas/articles/hybrid-connected-office"
        )
    },
]

OBSERVABILITY_RULES = [
    {
        "id": "obs-001",
        "trigger": lambda zones, services: any("kubernetes" in s.lower() or "aks" in s.lower() or "eks" in s.lower() or "container" in s.lower() for s in services),
        "condition": lambda zones, services, answers: "prometheus" not in str(services).lower() and "grafana" not in str(services).lower(),
        "rec": Recommendation(
            id="obs-001",
            title="Add Managed Prometheus and Grafana",
            description="Kubernetes workloads benefit from Prometheus metrics with Managed Grafana dashboards.",
            pillar=WAFPillar.OPERATIONAL_EXCELLENCE,
            severity=Severity.MEDIUM,
            category="Observability",
            action="Enable Azure Monitor managed service for Prometheus and connect to Managed Grafana",
            azure_doc_link="https://learn.microsoft.com/en-us/azure/azure-monitor/essentials/prometheus-metrics-overview"
        )
    },
]

DATA_GOV_RULES = [
    {
        "id": "dgov-001",
        "trigger": lambda zones, services: any("data lake" in s.lower() or "adls" in s.lower() or "lake formation" in s.lower() or "datazone" in s.lower() for s in services),
        "condition": lambda zones, services, answers: "purview" not in str(services).lower(),
        "rec": Recommendation(
            id="dgov-001",
            title="Implement Data Governance with Microsoft Purview",
            description="Data lake workloads need governance. Microsoft Purview provides catalog, lineage, and classification.",
            pillar=WAFPillar.OPERATIONAL_EXCELLENCE,
            severity=Severity.MEDIUM,
            category="Data Governance",
            action="Deploy Microsoft Purview for data catalog, sensitivity labeling, and lineage tracking",
            azure_doc_link="https://learn.microsoft.com/en-us/purview/purview"
        )
    },
]

ZERO_TRUST_RULES = [
    {
        "id": "zt-001",
        "trigger": lambda zones, services: any("vpn" in s.lower() for s in services),
        "condition": lambda zones, services, answers: "entra private" not in str(services).lower(),
        "rec": Recommendation(
            id="zt-001",
            title="Consider Zero Trust Network Access",
            description="VPN detected. Consider replacing with Microsoft Entra Private Access for identity-based access.",
            pillar=WAFPillar.SECURITY,
            severity=Severity.MEDIUM,
            category="Zero Trust",
            action="Evaluate Microsoft Entra Private Access as a VPN replacement for zero-trust network access",
            azure_doc_link="https://learn.microsoft.com/en-us/entra/global-secure-access/concept-private-access"
        )
    },
    {
        "id": "zt-002",
        "trigger": lambda zones, services: any("firewall" in s.lower() for s in services),
        "condition": lambda zones, services, answers: "firewall manager" not in str(services).lower(),
        "rec": Recommendation(
            id="zt-002",
            title="Centralize Firewall Management",
            description="Multiple firewall resources detected. Use Azure Firewall Manager for centralized policy management.",
            pillar=WAFPillar.SECURITY,
            severity=Severity.LOW,
            category="Zero Trust",
            action="Deploy Azure Firewall Manager to manage firewall policies across subscriptions",
            azure_doc_link="https://learn.microsoft.com/en-us/azure/firewall-manager/overview"
        )
    },
]

ALL_RULES = (
    RELIABILITY_RULES + SECURITY_RULES + COST_RULES + PERFORMANCE_RULES + OPS_RULES
    + HYBRID_RULES + GENAI_RULES + EDGE_RULES + OBSERVABILITY_RULES
    + DATA_GOV_RULES + ZERO_TRUST_RULES
)


def analyze_architecture(analysis: Dict[str, Any], answers: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Analyze detected architecture against WAF best practices.
    
    Args:
        analysis: The diagram analysis result containing zones and services
        answers: Optional user answers from guided questions
        
    Returns:
        Dictionary with recommendations, score, and summary by pillar
    """
    zones = analysis.get("zones", [])
    
    # Extract all service names from zones
    services = []
    for zone in zones:
        for svc in zone.get("services", []):
            if isinstance(svc, dict):
                services.append(svc.get("azure", svc.get("source", "")))
            elif isinstance(svc, str):
                services.append(svc)
    
    answers = answers or {}
    recommendations: List[Recommendation] = []
    
    # Evaluate each rule
    for rule in ALL_RULES:
        try:
            if rule["trigger"](zones, services):
                if rule["condition"](zones, services, answers):
                    rec = rule["rec"]
                    rec.services_affected = [s for s in services[:5]]  # Show first 5
                    recommendations.append(rec)
        except Exception as e:
            logger.warning("Rule %s failed: %s", rule.get('id', 'unknown'), e)
    
    # Calculate scores by pillar
    pillar_scores = {}
    pillar_counts = {p.value: {"total": 0, "high": 0, "medium": 0, "low": 0} for p in WAFPillar}
    
    for rec in recommendations:
        pillar_counts[rec.pillar.value]["total"] += 1
        pillar_counts[rec.pillar.value][rec.severity.value] += 1 if rec.severity.value != "info" else 0
    
    for pillar in WAFPillar:
        counts = pillar_counts[pillar.value]
        if counts["total"] == 0:
            pillar_scores[pillar.value] = 100
        else:
            # Deduct points: high=-20, medium=-10, low=-5
            deductions = counts["high"] * 20 + counts["medium"] * 10 + counts["low"] * 5
            pillar_scores[pillar.value] = max(0, 100 - deductions)
    
    overall_score = sum(pillar_scores.values()) / len(pillar_scores)
    
    # Group recommendations by pillar
    by_pillar = {}
    for pillar in WAFPillar:
        by_pillar[pillar.value] = [
            asdict(r) for r in recommendations if r.pillar == pillar
        ]
    
    # Summary stats
    high_count = sum(1 for r in recommendations if r.severity == Severity.HIGH)
    medium_count = sum(1 for r in recommendations if r.severity == Severity.MEDIUM)
    
    return {
        "overall_score": round(overall_score, 1),
        "pillar_scores": pillar_scores,
        "total_recommendations": len(recommendations),
        "high_priority": high_count,
        "medium_priority": medium_count,
        "recommendations": [asdict(r) for r in recommendations],
        "by_pillar": by_pillar,
        "waf_alignment": "good" if overall_score >= 80 else "needs_improvement" if overall_score >= 60 else "critical"
    }


def get_quick_wins(recommendations: List[Dict]) -> List[Dict]:
    """Get the top 3 actionable quick wins from recommendations."""
    # Prioritize high severity, then medium, filter out info
    actionable = [r for r in recommendations if r.get("severity") != "info"]
    sorted_recs = sorted(
        actionable,
        key=lambda r: (
            0 if r.get("severity") == "high" else 1 if r.get("severity") == "medium" else 2
        )
    )
    return sorted_recs[:3]
