"""
Starter architecture routes.

Starters are curated AWS/GCP source architectures backed by deterministic
analysis sessions so they can activate the Workbench and serve as regression
coverage for canonical translation outputs.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from error_envelope import ArchmorphException
from export_capabilities import attach_export_capability
from routers.samples import build_sample_analysis
from routers.shared import SESSION_STORE, generate_session_id, limiter
from usage_metrics import record_funnel_step

router = APIRouter()

STARTER_DELIVERABLES = ["Analysis", "IaC", "HLD", "Cost Estimate", "Export Package"]

TEMPLATES: list[dict] = [
    {
        "id": "aws-hub-spoke",
        "sample_id": "aws-hub-spoke",
        "title": "AWS Hub & Spoke Landing Zone",
        "description": "Centralized inspection, hybrid connectivity, and isolated shared-service and production spokes.",
        "category": "enterprise",
        "complexity": "advanced",
        "difficulty": "advanced",
        "source_provider": "aws",
        "services": ["Transit Gateway", "VPN Gateway", "Network Firewall", "Direct Connect", "EKS", "Aurora"],
        "tags": ["landing-zone", "networking", "hybrid", "inspection"],
        "assumptions": ["Azure landing zone pattern", "Centralized inspection", "Hub-spoke network topology"],
        "available_deliverables": STARTER_DELIVERABLES,
        "expected_outputs": ["Hub-spoke Azure network design", "Terraform-ready landing zone baseline", "Cost and migration planning package"],
        "regression_profile": {"id": "golden-aws-hub-spoke", "coverage": "golden", "manual_check": True},
    },
    {
        "id": "aws-iaas-web",
        "sample_id": "aws-iaas",
        "title": "AWS IaaS Web Stack",
        "description": "VPC, load-balanced EC2 web/app tier, block storage, S3 backups, RDS, and CloudWatch monitoring.",
        "category": "web",
        "complexity": "intermediate",
        "difficulty": "intermediate",
        "source_provider": "aws",
        "services": ["VPC", "ELB", "EC2", "EBS", "S3", "RDS", "CloudWatch"],
        "tags": ["web", "iaas", "database", "monitoring"],
        "assumptions": ["Lift-and-modernize web workload", "Managed Azure database target", "Observable app tier"],
        "available_deliverables": STARTER_DELIVERABLES,
        "expected_outputs": ["Azure VM/App Gateway mapping", "Bicep or Terraform IaC", "HLD with monitoring and backup guidance"],
        "regression_profile": {"id": "golden-aws-iaas-web", "coverage": "golden", "manual_check": True},
    },
    {
        "id": "gcp-iaas-web",
        "sample_id": "gcp-iaas",
        "title": "GCP IaaS Web Stack",
        "description": "Custom VPC, managed instance groups, global load balancing, persistent disks, Cloud SQL, and Cloud Monitoring.",
        "category": "web",
        "complexity": "intermediate",
        "difficulty": "intermediate",
        "source_provider": "gcp",
        "services": ["VPC", "Cloud Load Balancing", "Compute Engine", "Persistent Disk", "Cloud SQL"],
        "tags": ["web", "iaas", "managed-instance-groups", "sql"],
        "assumptions": ["Regional web workload", "Managed Azure SQL target", "Global ingress mapped to Azure front door pattern"],
        "available_deliverables": STARTER_DELIVERABLES,
        "expected_outputs": ["Azure compute and database translation", "Network and ingress HLD", "Cost estimate baseline"],
        "regression_profile": {"id": "golden-gcp-iaas-web", "coverage": "golden", "manual_check": True},
    },
    {
        "id": "aws-eks-platform",
        "sample_id": "aws-eks",
        "title": "AWS Container Platform",
        "description": "EKS cluster with ingress, private registry, shared storage, Redis cache, and audit controls.",
        "category": "containers",
        "complexity": "advanced",
        "difficulty": "advanced",
        "source_provider": "aws",
        "services": ["EKS", "ECR", "Fargate", "EFS", "ElastiCache", "CloudTrail"],
        "tags": ["kubernetes", "containers", "registry", "audit"],
        "assumptions": ["AKS target architecture", "Private registry and shared storage", "Audit controls retained"],
        "available_deliverables": STARTER_DELIVERABLES,
        "expected_outputs": ["AKS platform translation", "Container registry and cache mapping", "Security and audit HLD"],
        "regression_profile": {"id": "golden-aws-eks-platform", "coverage": "golden", "manual_check": True},
    },
    {
        "id": "gcp-gke-platform",
        "sample_id": "gcp-gke",
        "title": "GCP Container Platform",
        "description": "GKE Autopilot with Cloud Run services, Pub/Sub messaging, Firestore, Memorystore, and Security Command Center.",
        "category": "containers",
        "complexity": "advanced",
        "difficulty": "advanced",
        "source_provider": "gcp",
        "services": ["GKE", "Cloud Run", "Artifact Registry", "Pub/Sub", "Firestore", "Memorystore"],
        "tags": ["kubernetes", "serverless", "messaging", "nosql"],
        "assumptions": ["AKS plus Azure Container Apps evaluation", "Event-driven services retained", "Managed data services mapped to Azure"],
        "available_deliverables": STARTER_DELIVERABLES,
        "expected_outputs": ["AKS/ACA decision baseline", "Messaging and data service translation", "Regression-ready export package"],
        "regression_profile": {"id": "golden-gcp-gke-platform", "coverage": "golden", "manual_check": True},
    },
]


def _categories() -> list[dict]:
    categories = [
        ("all", "All Starters"),
        ("web", "Web & APIs"),
        ("containers", "Containers"),
        ("enterprise", "Enterprise"),
    ]
    return [
        {
            "id": category_id,
            "label": label,
            "count": len(TEMPLATES) if category_id == "all" else sum(1 for template in TEMPLATES if template["category"] == category_id),
        }
        for category_id, label in categories
    ]


def _public_template(template: dict) -> dict:
    return {key: value for key, value in template.items() if key != "sample_id"}


@router.get("/api/templates")
async def list_templates(category: str = "all", source_provider: str = ""):
    """Browse curated starter architectures."""
    filtered = TEMPLATES
    if category != "all":
        filtered = [template for template in filtered if template["category"] == category]
    if source_provider:
        filtered = [template for template in filtered if template["source_provider"] == source_provider]
    return {
        "templates": [_public_template(template) for template in filtered],
        "categories": _categories(),
        "total": len(filtered),
    }


@router.get("/api/templates/{template_id}")
async def get_template(template_id: str):
    """Get one curated starter architecture."""
    template = next((item for item in TEMPLATES if item["id"] == template_id), None)
    if not template:
        raise ArchmorphException(404, f"Template '{template_id}' not found")
    return _public_template(template)


@router.post("/api/templates/{template_id}/analyze")
@limiter.limit("5/minute")
async def analyze_template(request: Request, template_id: str):
    """Create a Workbench-ready deterministic analysis for a starter."""
    template = next((item for item in TEMPLATES if item["id"] == template_id), None)
    if not template:
        raise ArchmorphException(404, f"Template '{template_id}' not found")

    diagram_id = generate_session_id(f"template-{template_id}")
    analysis = build_sample_analysis(template["sample_id"], diagram_id)
    if analysis is None:
        raise ArchmorphException(404, f"Template '{template_id}' analysis source not found")

    analysis.update(
        {
            "diagram_type": template["title"],
            "template_id": template_id,
            "template_title": template["title"],
            "starter_metadata": _public_template(template),
            "is_template": True,
            "is_starter": True,
            "is_sample": False,
        }
    )
    SESSION_STORE[diagram_id] = analysis
    record_funnel_step(diagram_id, "template_analyze")
    return attach_export_capability(analysis, diagram_id)