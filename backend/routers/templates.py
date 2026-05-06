"""
Architecture template gallery routes.

Templates are curated starting points backed by deterministic analysis sessions so
the translator can open them without a user-uploaded diagram.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from error_envelope import ArchmorphException
from export_capabilities import attach_export_capability
from routers.samples import build_sample_analysis
from routers.shared import SESSION_STORE, generate_session_id, limiter
from usage_metrics import record_funnel_step

router = APIRouter()

TEMPLATES: list[dict] = [
    {
        "id": "aws-hub-spoke",
        "sample_id": "aws-hub-spoke",
        "title": "AWS Hub & Spoke Landing Zone",
        "description": "Centralized inspection, hybrid connectivity, and isolated shared-service and production spokes.",
        "category": "enterprise",
        "difficulty": "advanced",
        "source_provider": "aws",
        "services": ["Transit Gateway", "VPN Gateway", "Network Firewall", "Direct Connect", "EKS", "Aurora"],
        "tags": ["landing-zone", "networking", "hybrid", "inspection"],
    },
    {
        "id": "aws-iaas-web",
        "sample_id": "aws-iaas",
        "title": "AWS IaaS Web Stack",
        "description": "VPC, load-balanced EC2 web/app tier, block storage, S3 backups, RDS, and CloudWatch monitoring.",
        "category": "web",
        "difficulty": "intermediate",
        "source_provider": "aws",
        "services": ["VPC", "ELB", "EC2", "EBS", "S3", "RDS", "CloudWatch"],
        "tags": ["web", "iaas", "database", "monitoring"],
    },
    {
        "id": "gcp-iaas-web",
        "sample_id": "gcp-iaas",
        "title": "GCP IaaS Web Stack",
        "description": "Custom VPC, managed instance groups, global load balancing, persistent disks, Cloud SQL, and Cloud Monitoring.",
        "category": "web",
        "difficulty": "intermediate",
        "source_provider": "gcp",
        "services": ["VPC", "Cloud Load Balancing", "Compute Engine", "Persistent Disk", "Cloud SQL"],
        "tags": ["web", "iaas", "managed-instance-groups", "sql"],
    },
    {
        "id": "aws-eks-platform",
        "sample_id": "aws-eks",
        "title": "AWS Container Platform",
        "description": "EKS cluster with ingress, private registry, shared storage, Redis cache, and audit controls.",
        "category": "containers",
        "difficulty": "advanced",
        "source_provider": "aws",
        "services": ["EKS", "ECR", "Fargate", "EFS", "ElastiCache", "CloudTrail"],
        "tags": ["kubernetes", "containers", "registry", "audit"],
    },
    {
        "id": "gcp-gke-platform",
        "sample_id": "gcp-gke",
        "title": "GCP Container Platform",
        "description": "GKE Autopilot with Cloud Run services, Pub/Sub messaging, Firestore, Memorystore, and Security Command Center.",
        "category": "containers",
        "difficulty": "advanced",
        "source_provider": "gcp",
        "services": ["GKE", "Cloud Run", "Artifact Registry", "Pub/Sub", "Firestore", "Memorystore"],
        "tags": ["kubernetes", "serverless", "messaging", "nosql"],
    },
]


def _categories() -> list[dict]:
    categories = [
        ("all", "All Templates"),
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
    """Browse curated architecture templates."""
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
    """Get one curated architecture template."""
    template = next((item for item in TEMPLATES if item["id"] == template_id), None)
    if not template:
        raise ArchmorphException(404, f"Template '{template_id}' not found")
    return _public_template(template)


@router.post("/api/templates/{template_id}/analyze")
@limiter.limit("5/minute")
async def analyze_template(request: Request, template_id: str):
    """Create a translator-ready deterministic analysis for a template."""
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
            "is_template": True,
            "is_sample": False,
        }
    )
    SESSION_STORE[diagram_id] = analysis
    record_funnel_step(diagram_id, "template_analyze")
    return attach_export_capability(analysis, diagram_id)