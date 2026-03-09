"""
Archmorph Cost Optimizer — AI-Powered Cost Optimization Recommendations

Analyzes architecture and provides cost-saving suggestions including:
- Reserved Instance opportunities
- Spot VM eligibility
- Right-sizing recommendations
- Storage tier optimization
- Auto-shutdown for dev/test
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class SavingsCategory(str, Enum):
    RESERVED_INSTANCES = "reserved_instances"
    SPOT_VMS = "spot_vms"
    RIGHT_SIZING = "right_sizing"
    STORAGE_TIERING = "storage_tiering"
    AUTO_SHUTDOWN = "auto_shutdown"
    HYBRID_BENEFIT = "hybrid_benefit"
    DEV_TEST_PRICING = "dev_test_pricing"


@dataclass
class CostOptimization:
    id: str
    title: str
    description: str
    category: SavingsCategory
    estimated_savings: str  # e.g., "30-40%", "up to 90%"
    effort: str  # "low", "medium", "high"
    services_affected: List[str]
    action_steps: List[str]
    azure_doc_link: Optional[str] = None
    requires_commitment: bool = False
    
    def __post_init__(self):
        if not self.services_affected:
            self.services_affected = []


# ─────────────────────────────────────────────────────────────
# Cost Optimization Rules
# ─────────────────────────────────────────────────────────────

COST_RULES = [
    {
        "id": "cost-ri-001",
        "trigger": lambda services, answers: any(
            s.lower() in ["azure vm", "virtual machines", "ec2", "compute engine", "azure sql", "postgresql", "cosmos db"]
            for s in services
        ),
        "condition": lambda services, answers: answers.get("env_target", "").lower() == "production",
        "optimization": lambda services: CostOptimization(
            id="cost-ri-001",
            title="Reserved Instances for Production Workloads",
            description="Your production VMs and databases are eligible for Reserved Instance pricing with 1-year or 3-year commitments.",
            category=SavingsCategory.RESERVED_INSTANCES,
            estimated_savings="35-65%",
            effort="low",
            services_affected=[s for s in services if any(k in s.lower() for k in ["vm", "sql", "database", "cosmos"])],
            action_steps=[
                "Review Azure Cost Management for usage patterns",
                "Identify steady-state workloads running 24/7",
                "Purchase Reserved Instances from Azure Portal > Reservations",
                "Apply RI to specific VMs or use shared scope"
            ],
            azure_doc_link="https://learn.microsoft.com/en-us/azure/cost-management-billing/reservations/save-compute-costs-reservations",
            requires_commitment=True
        )
    },
    {
        "id": "cost-spot-001",
        "trigger": lambda services, answers: any(
            s.lower() in ["azure vm", "virtual machines", "ec2", "compute engine", "aks", "kubernetes", "batch"]
            for s in services
        ),
        "condition": lambda services, answers: answers.get("env_target", "").lower() in ["development", "testing", "dev", "test"],
        "optimization": lambda services: CostOptimization(
            id="cost-spot-001",
            title="Spot VMs for Dev/Test Workloads",
            description="Dev/test environments can use Azure Spot VMs to save up to 90% on compute costs. These can be evicted with 30-second notice.",
            category=SavingsCategory.SPOT_VMS,
            estimated_savings="60-90%",
            effort="low",
            services_affected=[s for s in services if any(k in s.lower() for k in ["vm", "compute", "batch"])],
            action_steps=[
                "Convert non-critical workloads to Spot VMs",
                "Set eviction policy to 'Stop-Deallocate'",
                "Use spot-friendly instance sizes (D-series, E-series)",
                "Implement graceful shutdown handlers"
            ],
            azure_doc_link="https://learn.microsoft.com/en-us/azure/virtual-machines/spot-vms",
            requires_commitment=False
        )
    },
    {
        "id": "cost-storage-001",
        "trigger": lambda services, answers: any(
            s.lower() in ["blob storage", "azure storage", "s3", "cloud storage", "storage account"]
            for s in services
        ),
        "condition": lambda services, answers: True,
        "optimization": lambda services: CostOptimization(
            id="cost-storage-001",
            title="Storage Tier Optimization",
            description="Use lifecycle management to automatically move infrequently accessed data to Cool or Archive tiers.",
            category=SavingsCategory.STORAGE_TIERING,
            estimated_savings="40-80%",
            effort="medium",
            services_affected=[s for s in services if any(k in s.lower() for k in ["storage", "blob", "s3"])],
            action_steps=[
                "Analyze storage access patterns with Azure Monitor",
                "Create lifecycle management rules for aging data",
                "Move data not accessed in 30 days to Cool tier",
                "Archive data not accessed in 90 days",
                "Enable soft delete with reduced retention for dev"
            ],
            azure_doc_link="https://learn.microsoft.com/en-us/azure/storage/blobs/access-tiers-overview",
            requires_commitment=False
        )
    },
    {
        "id": "cost-auto-001",
        "trigger": lambda services, answers: any(
            s.lower() in ["azure vm", "virtual machines", "ec2", "compute engine"]
            for s in services
        ),
        "condition": lambda services, answers: answers.get("env_target", "").lower() in ["development", "testing", "dev", "test"],
        "optimization": lambda services: CostOptimization(
            id="cost-auto-001",
            title="Auto-Shutdown for Dev/Test VMs",
            description="Schedule automatic shutdown for dev/test VMs during non-business hours (e.g., 7PM-7AM).",
            category=SavingsCategory.AUTO_SHUTDOWN,
            estimated_savings="50-65%",
            effort="low",
            services_affected=[s for s in services if any(k in s.lower() for k in ["vm", "compute"])],
            action_steps=[
                "Enable Auto-shutdown in VM settings",
                "Set shutdown time to 7:00 PM local timezone",
                "Configure notification 30 minutes before",
                "Use Azure Automation for auto-start at 7:00 AM"
            ],
            azure_doc_link="https://learn.microsoft.com/en-us/azure/virtual-machines/auto-shutdown-vm",
            requires_commitment=False
        )
    },
    {
        "id": "cost-hybrid-001",
        "trigger": lambda services, answers: any(
            s.lower() in ["azure vm", "virtual machines", "azure sql", "sql server"]
            for s in services
        ),
        "condition": lambda services, answers: True,
        "optimization": lambda services: CostOptimization(
            id="cost-hybrid-001",
            title="Azure Hybrid Benefit",
            description="If you have existing Windows Server or SQL Server licenses with Software Assurance, apply them to Azure for significant savings.",
            category=SavingsCategory.HYBRID_BENEFIT,
            estimated_savings="40-55%",
            effort="low",
            services_affected=[s for s in services if any(k in s.lower() for k in ["vm", "sql"])],
            action_steps=[
                "Verify existing Windows/SQL Server licenses with SA",
                "Enable Hybrid Benefit on VMs via Azure Portal",
                "Apply to SQL databases in configuration",
                "Track usage in Azure Cost Management"
            ],
            azure_doc_link="https://learn.microsoft.com/en-us/azure/virtual-machines/windows/hybrid-use-benefit-licensing",
            requires_commitment=False
        )
    },
    {
        "id": "cost-devtest-001",
        "trigger": lambda services, answers: len(services) > 0,
        "condition": lambda services, answers: answers.get("env_target", "").lower() in ["development", "testing", "dev", "test"],
        "optimization": lambda services: CostOptimization(
            id="cost-devtest-001",
            title="Azure Dev/Test Subscription Pricing",
            description="Use Azure Dev/Test subscription pricing for discounted rates on Azure services (no Windows licensing fees, reduced rates).",
            category=SavingsCategory.DEV_TEST_PRICING,
            estimated_savings="25-40%",
            effort="medium",
            services_affected=services[:5],
            action_steps=[
                "Ensure Visual Studio subscription is active",
                "Create dedicated Dev/Test subscription",
                "Deploy non-production resources there",
                "Get discounted rates automatically"
            ],
            azure_doc_link="https://azure.microsoft.com/en-us/pricing/dev-test/",
            requires_commitment=False
        )
    },
    {
        "id": "cost-right-001",
        "trigger": lambda services, answers: any(
            s.lower() in ["azure vm", "virtual machines", "ec2", "compute engine", "aks", "kubernetes"]
            for s in services
        ),
        "condition": lambda services, answers: True,
        "optimization": lambda services: CostOptimization(
            id="cost-right-001",
            title="Right-Size VM SKUs",
            description="Review VM sizes after 14 days of metrics. Azure Advisor automatically identifies oversized VMs.",
            category=SavingsCategory.RIGHT_SIZING,
            estimated_savings="20-50%",
            effort="medium",
            services_affected=[s for s in services if any(k in s.lower() for k in ["vm", "compute", "kubernetes"])],
            action_steps=[
                "Enable Azure Monitor metrics collection",
                "Review Azure Advisor recommendations weekly",
                "Resize VMs using <60% CPU/memory to smaller SKUs",
                "Consider B-series for bursty workloads"
            ],
            azure_doc_link="https://learn.microsoft.com/en-us/azure/advisor/advisor-cost-recommendations",
            requires_commitment=False
        )
    }
]


def analyze_cost_optimizations(
    analysis: Dict[str, Any],
    answers: Optional[Dict[str, Any]] = None,
    cost_estimate: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Analyze architecture for cost optimization opportunities.
    
    Args:
        analysis: The diagram analysis result
        answers: User answers from guided questions
        cost_estimate: Optional current cost estimate
        
    Returns:
        Dictionary with optimization recommendations and estimated savings
    """
    zones = analysis.get("zones", [])
    
    # Extract all Azure service names
    services = []
    for zone in zones:
        for svc in zone.get("services", []):
            if isinstance(svc, dict):
                azure_name = svc.get("azure", "")
                if azure_name:
                    services.append(azure_name)
            elif isinstance(svc, str):
                services.append(svc)
    
    answers = answers or {}
    optimizations: List[CostOptimization] = []
    
    # Evaluate each rule
    for rule in COST_RULES:
        try:
            if rule["trigger"](services, answers):
                if rule["condition"](services, answers):
                    opt = rule["optimization"](services)
                    optimizations.append(opt)
        except Exception as e:
            logger.warning("Cost rule %s failed: %s", rule.get('id', 'unknown'), e)
    
    # Calculate potential savings
    current_monthly = cost_estimate.get("total_monthly_usd", 0) if cost_estimate else 0
    
    # Estimate total savings (conservative: take middle of ranges)
    
    # Group by category
    by_category = {}
    for cat in SavingsCategory:
        by_category[cat.value] = [
            asdict(o) for o in optimizations if o.category == cat
        ]
    
    # Calculate summary
    commitment_required = [o for o in optimizations if hasattr(o, "requires_commitment") and o.requires_commitment]
    no_commitment = [o for o in optimizations if not (hasattr(o, "requires_commitment") and o.requires_commitment)]
    
    return {
        "total_optimizations": len(optimizations),
        "requires_commitment": len(commitment_required),
        "quick_wins": len(no_commitment),
        "current_monthly_estimate": current_monthly,
        "optimizations": [asdict(o) for o in optimizations],
        "by_category": by_category,
        "top_3_quick_wins": [
            asdict(o) for o in sorted(
                no_commitment,
                key=lambda x: ("low", "medium", "high").index(x.effort)
            )[:3]
        ]
    }

def analyze_live_finops(live_schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze actual live cloud resources for FinOps optimizations.
    Uses precise heuristics targeting unattached storage, idle networking, and sizing.
    """
    optimizations = []
    metadata = live_schema.get("metadata", {})
    provider = metadata.get("provider", "unknown").lower()
    resources = live_schema.get("resources", [])
    
    unattached_disks = []
    idle_ips = []
    
    for res in resources:
        try:
            # We must handle both object properties and dict representations
            if isinstance(res, dict):
                res_type = res.get("type", "").lower()
                name = res.get("name", "Unknown")
                props = res.get("attributes", {})
            else:
                res_type = res.type.lower()
                name = res.name
                props = res.attributes or {}
            
            # Azure specific heuristics
            if provider == "azure":
                # 1. Unattached Disks
                if res_type == "microsoft.compute/disks":
                    disk_state = props.get("diskState", "").lower()
                    if disk_state == "unattached":
                        unattached_disks.append(name)
                
                # 2. Idle Public IPs
                elif res_type == "microsoft.network/publicipaddresses":
                    ip_config = props.get("ipConfiguration")
                    if not ip_config:
                        idle_ips.append(name)
                        
                # 3. App Service Plans with low density
                elif res_type == "microsoft.web/serverfarms":
                    num_sites = props.get("numberOfSites", 1)  # if unknown assume 1
                    if num_sites == 0:
                        optimizations.append(
                            CostOptimization(
                                id=f"idle_app_plan_{name}",
                                title=f"Delete Idle App Service Plan ({name})",
                                description="This App Service Plan has no hosted applications and is accruing charges.",
                                category=SavingsCategory.RIGHT_SIZING,
                                estimated_savings="100% of plan cost",
                                effort="low",
                                services_affected=[name],
                                action_steps=["Verify plan is unused", "Delete the App Service Plan from portal/CLI"]
                            )
                        )
                        
            # AWS specific heuristics (conceptual mappings)
            elif provider == "aws":
                if res_type == "aws::ec2::volume":
                    if props.get("status") == "available":
                        unattached_disks.append(name)
                elif res_type == "aws::ec2::eip":
                    if not props.get("associationId"):
                        idle_ips.append(name)
        except Exception:
            pass

    # Aggregate unattached disk savings
    if unattached_disks:
        optimizations.append(
            CostOptimization(
                id=f"unattached_disks_{provider}",
                title=f"Delete {len(unattached_disks)} Unattached Disks",
                description="Disks accrue costs even when not attached to any running VM.",
                category=SavingsCategory.STORAGE_TIERING,
                estimated_savings="100% of unattached disk costs",
                effort="low",
                services_affected=unattached_disks,
                action_steps=["Snapshot if data backup is required", "Delete orphan disks"]
            )
        )

    # Aggregate idle IP savings
    if idle_ips:
        optimizations.append(
            CostOptimization(
                id=f"idle_ips_{provider}",
                title=f"Release {len(idle_ips)} Unassociated Public IPs",
                description="Cloud providers charge hourly rates for reserved public IP addresses not attached to running interfaces.",
                category=SavingsCategory.RIGHT_SIZING,
                estimated_savings="~$3-4/month per IP",
                effort="low",
                services_affected=idle_ips,
                action_steps=["Release IPs back to the cloud provider pool"]
            )
        )
        
    by_category = {}
    for cat in SavingsCategory:
        by_category[cat.value] = [asdict(o) for o in optimizations if o.category == cat]
        
    no_commitment = [o for o in optimizations if not getattr(o, "requires_commitment", False)]
    
    return {
        "total_optimizations": len(optimizations),
        "quick_wins": len(no_commitment),
        "optimizations": [asdict(o) for o in optimizations],
        "by_category": by_category,
        "scanned_resources": len(resources),
        "provider": provider
    }

