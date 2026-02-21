"""
Archmorph Migration Runbook Generator
Generates step-by-step migration guides based on architectural analysis
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class MigrationPhase(str, Enum):
    ASSESSMENT = "assessment"
    PLANNING = "planning"
    PREPARATION = "preparation"
    MIGRATION = "migration"
    VALIDATION = "validation"
    CUTOVER = "cutover"
    POST_MIGRATION = "post_migration"


class TaskPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


@dataclass
class MigrationTask:
    """Individual migration task."""
    id: str
    title: str
    description: str
    phase: MigrationPhase
    priority: TaskPriority
    estimated_hours: float
    dependencies: List[str] = field(default_factory=list)
    azure_services: List[str] = field(default_factory=list)
    commands: List[str] = field(default_factory=list)
    validation_steps: List[str] = field(default_factory=list)
    rollback_steps: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.NOT_STARTED
    owner: Optional[str] = None
    notes: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "phase": self.phase.value,
            "priority": self.priority.value,
            "estimated_hours": self.estimated_hours,
            "dependencies": self.dependencies,
            "azure_services": self.azure_services,
            "commands": self.commands,
            "validation_steps": self.validation_steps,
            "rollback_steps": self.rollback_steps,
            "risks": self.risks,
            "status": self.status.value,
            "owner": self.owner,
            "notes": self.notes,
        }


@dataclass
class MigrationRunbook:
    """Complete migration runbook."""
    id: str
    diagram_id: str
    title: str
    source_cloud: str
    target_cloud: str = "Azure"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tasks: List[MigrationTask] = field(default_factory=list)
    estimated_duration_days: int = 0
    risk_level: str = "medium"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "diagram_id": self.diagram_id,
            "title": self.title,
            "source_cloud": self.source_cloud,
            "target_cloud": self.target_cloud,
            "created_at": self.created_at.isoformat(),
            "tasks": [t.to_dict() for t in self.tasks],
            "estimated_duration_days": self.estimated_duration_days,
            "risk_level": self.risk_level,
            "summary": self.get_summary(),
        }
    
    def get_summary(self) -> Dict[str, Any]:
        """Get runbook summary statistics."""
        total_hours = sum(t.estimated_hours for t in self.tasks)
        return {
            "total_tasks": len(self.tasks),
            "by_phase": {
                phase.value: len([t for t in self.tasks if t.phase == phase])
                for phase in MigrationPhase
            },
            "by_priority": {
                priority.value: len([t for t in self.tasks if t.priority == priority])
                for priority in TaskPriority
            },
            "by_status": {
                status.value: len([t for t in self.tasks if t.status == status])
                for status in TaskStatus
            },
            "total_estimated_hours": total_hours,
            "estimated_days": round(total_hours / 8, 1),  # 8 hours per day
        }


# ─────────────────────────────────────────────────────────────
# Task Templates by Service Category
# ─────────────────────────────────────────────────────────────
COMPUTE_MIGRATION_TASKS = [
    {
        "title": "Inventory existing compute resources",
        "description": "Document all EC2/Compute Engine instances, their configurations, and dependencies",
        "phase": MigrationPhase.ASSESSMENT,
        "priority": TaskPriority.CRITICAL,
        "estimated_hours": 4,
        "validation_steps": ["All instances documented", "Instance sizes recorded", "OS versions noted"],
    },
    {
        "title": "Create Azure VM SKU mapping",
        "description": "Map source instance types to equivalent Azure VM sizes",
        "phase": MigrationPhase.PLANNING,
        "priority": TaskPriority.HIGH,
        "estimated_hours": 2,
        "azure_services": ["Virtual Machines"],
    },
    {
        "title": "Set up Azure Site Recovery",
        "description": "Configure ASR for VM replication if using lift-and-shift approach",
        "phase": MigrationPhase.PREPARATION,
        "priority": TaskPriority.HIGH,
        "estimated_hours": 8,
        "azure_services": ["Azure Site Recovery", "Recovery Services Vault"],
        "commands": [
            "az backup vault create --name <vault-name> --resource-group <rg>",
            "az site-recovery vault create --name <vault-name> --resource-group <rg>",
        ],
    },
    {
        "title": "Migrate VM workloads",
        "description": "Execute VM migration using Azure Migrate or ASR",
        "phase": MigrationPhase.MIGRATION,
        "priority": TaskPriority.CRITICAL,
        "estimated_hours": 16,
        "azure_services": ["Azure Migrate", "Virtual Machines"],
        "risks": ["Network connectivity changes", "DNS updates required"],
        "rollback_steps": ["Failback to source VMs", "Restore network configuration"],
    },
]

DATABASE_MIGRATION_TASKS = [
    {
        "title": "Database assessment and compatibility check",
        "description": "Run Azure Database Migration Assessment to identify compatibility issues",
        "phase": MigrationPhase.ASSESSMENT,
        "priority": TaskPriority.CRITICAL,
        "estimated_hours": 4,
        "azure_services": ["Azure Database Migration Service"],
        "validation_steps": ["Assessment report generated", "Compatibility issues documented"],
    },
    {
        "title": "Create target database instances",
        "description": "Provision Azure SQL, PostgreSQL, or MySQL Flexible Server instances",
        "phase": MigrationPhase.PREPARATION,
        "priority": TaskPriority.HIGH,
        "estimated_hours": 4,
        "azure_services": ["Azure SQL Database", "Azure Database for PostgreSQL", "Azure Database for MySQL"],
        "commands": [
            "az postgres flexible-server create --name <name> --resource-group <rg>",
            "az sql db create --name <name> --server <server> --resource-group <rg>",
        ],
    },
    {
        "title": "Configure ongoing replication",
        "description": "Set up continuous data sync between source and target databases",
        "phase": MigrationPhase.PREPARATION,
        "priority": TaskPriority.CRITICAL,
        "estimated_hours": 8,
        "azure_services": ["Azure Database Migration Service"],
        "risks": ["Data inconsistency during migration", "Schema drift"],
    },
    {
        "title": "Execute database cutover",
        "description": "Stop replication and switch applications to Azure databases",
        "phase": MigrationPhase.CUTOVER,
        "priority": TaskPriority.CRITICAL,
        "estimated_hours": 4,
        "validation_steps": [
            "Data integrity verified",
            "All records match source count",
            "Application connections tested",
        ],
        "rollback_steps": ["Revert connection strings", "Resume source database operations"],
    },
]

STORAGE_MIGRATION_TASKS = [
    {
        "title": "Inventory storage resources",
        "description": "Document all S3 buckets/GCS buckets, sizes, access patterns, and lifecycle policies",
        "phase": MigrationPhase.ASSESSMENT,
        "priority": TaskPriority.HIGH,
        "estimated_hours": 3,
    },
    {
        "title": "Create Azure Storage accounts",
        "description": "Provision storage accounts with appropriate redundancy and access tiers",
        "phase": MigrationPhase.PREPARATION,
        "priority": TaskPriority.HIGH,
        "estimated_hours": 2,
        "azure_services": ["Azure Blob Storage", "Azure Files"],
        "commands": [
            "az storage account create --name <name> --resource-group <rg> --sku Standard_LRS",
            "az storage container create --name <container> --account-name <account>",
        ],
    },
    {
        "title": "Migrate data using AzCopy",
        "description": "Transfer data from source to Azure using AzCopy for high-speed migration",
        "phase": MigrationPhase.MIGRATION,
        "priority": TaskPriority.HIGH,
        "estimated_hours": 24,  # Depends on data size
        "azure_services": ["Azure Blob Storage"],
        "commands": [
            "azcopy copy 's3://bucket' 'https://<account>.blob.core.windows.net/container' --recursive",
        ],
        "validation_steps": ["File count matches", "Checksums verified", "Access patterns work"],
    },
]

NETWORKING_MIGRATION_TASKS = [
    {
        "title": "Design Azure network topology",
        "description": "Design VNets, subnets, NSGs, and peering to match source architecture",
        "phase": MigrationPhase.PLANNING,
        "priority": TaskPriority.CRITICAL,
        "estimated_hours": 8,
        "azure_services": ["Virtual Network", "Network Security Groups"],
    },
    {
        "title": "Set up VPN or ExpressRoute",
        "description": "Configure hybrid connectivity between source and Azure during migration",
        "phase": MigrationPhase.PREPARATION,
        "priority": TaskPriority.HIGH,
        "estimated_hours": 8,
        "azure_services": ["VPN Gateway", "ExpressRoute"],
        "commands": [
            "az network vnet-gateway create --name <name> --resource-group <rg> --vnet <vnet>",
        ],
    },
    {
        "title": "Configure DNS migration",
        "description": "Set up Azure DNS and plan DNS cutover strategy",
        "phase": MigrationPhase.PREPARATION,
        "priority": TaskPriority.HIGH,
        "estimated_hours": 4,
        "azure_services": ["Azure DNS", "Private DNS Zones"],
    },
]

SECURITY_MIGRATION_TASKS = [
    {
        "title": "Map IAM policies to Azure RBAC",
        "description": "Translate source IAM roles/policies to Azure RBAC roles",
        "phase": MigrationPhase.PLANNING,
        "priority": TaskPriority.CRITICAL,
        "estimated_hours": 8,
        "azure_services": ["Azure AD", "Role-Based Access Control"],
    },
    {
        "title": "Migrate secrets to Azure Key Vault",
        "description": "Transfer secrets, keys, and certificates to Azure Key Vault",
        "phase": MigrationPhase.PREPARATION,
        "priority": TaskPriority.CRITICAL,
        "estimated_hours": 4,
        "azure_services": ["Azure Key Vault"],
        "commands": [
            "az keyvault create --name <name> --resource-group <rg>",
            "az keyvault secret set --vault-name <vault> --name <secret> --value <value>",
        ],
    },
    {
        "title": "Enable security monitoring",
        "description": "Configure Microsoft Defender for Cloud and security monitoring",
        "phase": MigrationPhase.POST_MIGRATION,
        "priority": TaskPriority.HIGH,
        "estimated_hours": 4,
        "azure_services": ["Microsoft Defender for Cloud", "Azure Sentinel"],
    },
]

MONITORING_MIGRATION_TASKS = [
    {
        "title": "Set up Azure Monitor",
        "description": "Configure Log Analytics workspace and Azure Monitor for all migrated resources",
        "phase": MigrationPhase.PREPARATION,
        "priority": TaskPriority.HIGH,
        "estimated_hours": 4,
        "azure_services": ["Azure Monitor", "Log Analytics"],
        "commands": [
            "az monitor log-analytics workspace create --name <name> --resource-group <rg>",
        ],
    },
    {
        "title": "Configure Application Insights",
        "description": "Set up APM for application monitoring and distributed tracing",
        "phase": MigrationPhase.POST_MIGRATION,
        "priority": TaskPriority.MEDIUM,
        "estimated_hours": 4,
        "azure_services": ["Application Insights"],
    },
    {
        "title": "Create alerting rules",
        "description": "Configure alerts for critical metrics and error conditions",
        "phase": MigrationPhase.POST_MIGRATION,
        "priority": TaskPriority.HIGH,
        "estimated_hours": 4,
        "azure_services": ["Azure Monitor Alerts"],
    },
]


# ─────────────────────────────────────────────────────────────
# Runbook Generator
# ─────────────────────────────────────────────────────────────
def _detect_service_categories(mappings: List[Dict[str, Any]]) -> Dict[str, bool]:
    """Detect which service categories are present in the architecture."""
    categories = {
        "compute": False,
        "database": False,
        "storage": False,
        "networking": False,
        "security": False,
        "monitoring": False,
        "containers": False,
        "serverless": False,
        "messaging": False,
        "ai_ml": False,
    }
    
    category_keywords = {
        "compute": ["EC2", "VM", "Compute", "Instance", "Virtual Machine"],
        "database": ["RDS", "Database", "SQL", "PostgreSQL", "MySQL", "Cosmos", "DynamoDB", "Firestore", "BigQuery"],
        "storage": ["S3", "Blob", "Storage", "GCS", "Cloud Storage", "File"],
        "networking": ["VPC", "VNet", "Network", "Load Balancer", "CDN", "CloudFront", "DNS", "Route 53"],
        "security": ["IAM", "Key Vault", "KMS", "Secrets", "WAF", "Firewall", "Security"],
        "monitoring": ["CloudWatch", "Monitor", "Insights", "Logging", "Metrics"],
        "containers": ["ECS", "EKS", "GKE", "AKS", "Container", "Kubernetes", "Docker"],
        "serverless": ["Lambda", "Functions", "Cloud Functions", "App Service"],
        "messaging": ["SQS", "SNS", "Pub/Sub", "Event", "Queue", "Service Bus", "Event Grid"],
        "ai_ml": ["SageMaker", "AI Platform", "OpenAI", "Cognitive", "ML", "Machine Learning"],
    }
    
    for mapping in mappings:
        source = mapping.get("source_service", "").lower()
        azure = mapping.get("azure_service", "").lower()
        combined = f"{source} {azure}"
        
        for category, keywords in category_keywords.items():
            if any(kw.lower() in combined for kw in keywords):
                categories[category] = True
    
    return categories


def _calculate_risk_level(mappings: List[Dict[str, Any]], categories: Dict[str, bool]) -> str:
    """Calculate overall migration risk level."""
    risk_score = 0
    
    # High risk factors
    if categories.get("database"):
        risk_score += 3
    if categories.get("containers"):
        risk_score += 2
    if categories.get("networking"):
        risk_score += 2
    if categories.get("ai_ml"):
        risk_score += 2
    
    # Check for low confidence mappings
    low_confidence_count = sum(1 for m in mappings if m.get("confidence", 0) < 0.6)
    if low_confidence_count > 3:
        risk_score += 3
    elif low_confidence_count > 0:
        risk_score += 1
    
    # Service count factor
    if len(mappings) > 20:
        risk_score += 2
    elif len(mappings) > 10:
        risk_score += 1
    
    if risk_score >= 8:
        return "critical"
    elif risk_score >= 5:
        return "high"
    elif risk_score >= 3:
        return "medium"
    return "low"


def generate_migration_runbook(
    diagram_id: str,
    analysis: Dict[str, Any],
    project_name: Optional[str] = None,
) -> MigrationRunbook:
    """Generate a comprehensive migration runbook based on architecture analysis."""
    
    mappings = analysis.get("mappings", [])
    source_cloud = analysis.get("source_cloud", "AWS")
    
    # Detect service categories
    categories = _detect_service_categories(mappings)
    risk_level = _calculate_risk_level(mappings, categories)
    
    # Generate runbook
    import uuid
    runbook_id = f"rb-{uuid.uuid4().hex[:8]}"
    
    title = project_name or f"{source_cloud} to Azure Migration Runbook"
    
    runbook = MigrationRunbook(
        id=runbook_id,
        diagram_id=diagram_id,
        title=title,
        source_cloud=source_cloud,
        risk_level=risk_level,
    )
    
    task_id = 1
    
    # Always include assessment tasks
    runbook.tasks.append(MigrationTask(
        id=f"task-{task_id}",
        title="Initial migration assessment",
        description="Document current architecture, identify dependencies, and define migration scope",
        phase=MigrationPhase.ASSESSMENT,
        priority=TaskPriority.CRITICAL,
        estimated_hours=8,
        validation_steps=[
            "All services documented",
            "Dependencies mapped",
            "Migration scope defined",
            "Timeline agreed upon",
        ],
    ))
    task_id += 1
    
    # Add category-specific tasks
    if categories["compute"]:
        for template in COMPUTE_MIGRATION_TASKS:
            runbook.tasks.append(MigrationTask(
                id=f"task-{task_id}",
                **template,
            ))
            task_id += 1
    
    if categories["database"]:
        for template in DATABASE_MIGRATION_TASKS:
            runbook.tasks.append(MigrationTask(
                id=f"task-{task_id}",
                **template,
            ))
            task_id += 1
    
    if categories["storage"]:
        for template in STORAGE_MIGRATION_TASKS:
            runbook.tasks.append(MigrationTask(
                id=f"task-{task_id}",
                **template,
            ))
            task_id += 1
    
    if categories["networking"]:
        for template in NETWORKING_MIGRATION_TASKS:
            runbook.tasks.append(MigrationTask(
                id=f"task-{task_id}",
                **template,
            ))
            task_id += 1
    
    # Always include security tasks
    for template in SECURITY_MIGRATION_TASKS:
        runbook.tasks.append(MigrationTask(
            id=f"task-{task_id}",
            **template,
        ))
        task_id += 1
    
    # Always include monitoring tasks
    for template in MONITORING_MIGRATION_TASKS:
        runbook.tasks.append(MigrationTask(
            id=f"task-{task_id}",
            **template,
        ))
        task_id += 1
    
    # Add final validation task
    runbook.tasks.append(MigrationTask(
        id=f"task-{task_id}",
        title="Final migration validation",
        description="Comprehensive validation of all migrated services and decommission planning",
        phase=MigrationPhase.POST_MIGRATION,
        priority=TaskPriority.CRITICAL,
        estimated_hours=8,
        validation_steps=[
            "All services operational",
            "Performance baseline established",
            "Security audit completed",
            "Documentation updated",
            "Team training completed",
            "Source decommission scheduled",
        ],
    ))
    
    # Calculate estimated duration
    total_hours = sum(t.estimated_hours for t in runbook.tasks)
    runbook.estimated_duration_days = round(total_hours / 8)  # 8 hours per day
    
    logger.info(
        "Generated runbook %s with %d tasks, estimated %d days",
        runbook_id, len(runbook.tasks), runbook.estimated_duration_days
    )
    
    return runbook


def render_runbook_markdown(runbook: MigrationRunbook) -> str:
    """Render runbook as Markdown document."""
    lines = [
        f"# {runbook.title}",
        "",
        f"**Runbook ID:** {runbook.id}",
        f"**Source Cloud:** {runbook.source_cloud}",
        f"**Target Cloud:** {runbook.target_cloud}",
        f"**Risk Level:** {runbook.risk_level.upper()}",
        f"**Estimated Duration:** {runbook.estimated_duration_days} days",
        f"**Created:** {runbook.created_at.strftime('%Y-%m-%d')}",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
        f"This runbook outlines the migration of your {runbook.source_cloud} architecture to Azure.",
        f"It contains **{len(runbook.tasks)} tasks** across {len(set(t.phase for t in runbook.tasks))} phases.",
        "",
    ]
    
    # Summary table
    summary = runbook.get_summary()
    lines.extend([
        "### Task Summary",
        "",
        "| Phase | Tasks | Hours |",
        "|-------|-------|-------|",
    ])
    
    for phase in MigrationPhase:
        phase_tasks = [t for t in runbook.tasks if t.phase == phase]
        if phase_tasks:
            hours = sum(t.estimated_hours for t in phase_tasks)
            lines.append(f"| {phase.value.replace('_', ' ').title()} | {len(phase_tasks)} | {hours}h |")
    
    lines.extend(["", "---", ""])
    
    # Tasks by phase
    for phase in MigrationPhase:
        phase_tasks = [t for t in runbook.tasks if t.phase == phase]
        if not phase_tasks:
            continue
        
        lines.extend([
            f"## Phase: {phase.value.replace('_', ' ').title()}",
            "",
        ])
        
        for task in phase_tasks:
            priority_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
            lines.extend([
                f"### {task.id}: {task.title}",
                "",
                f"**Priority:** {priority_emoji.get(task.priority.value, '')} {task.priority.value.upper()}",
                f"**Estimated Time:** {task.estimated_hours} hours",
                f"**Status:** {task.status.value.replace('_', ' ').title()}",
                "",
                task.description,
                "",
            ])
            
            if task.azure_services:
                lines.append(f"**Azure Services:** {', '.join(task.azure_services)}")
                lines.append("")
            
            if task.commands:
                lines.extend(["**Commands:**", "```bash"])
                lines.extend(task.commands)
                lines.extend(["```", ""])
            
            if task.validation_steps:
                lines.append("**Validation Checklist:**")
                for step in task.validation_steps:
                    lines.append(f"- [ ] {step}")
                lines.append("")
            
            if task.risks:
                lines.append("**Risks:**")
                for risk in task.risks:
                    lines.append(f"- ⚠️ {risk}")
                lines.append("")
            
            if task.rollback_steps:
                lines.append("**Rollback Steps:**")
                for step in task.rollback_steps:
                    lines.append(f"1. {step}")
                lines.append("")
            
            lines.append("---")
            lines.append("")
    
    return "\n".join(lines)
