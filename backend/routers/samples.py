from error_envelope import ArchmorphException
"""
Sample Diagrams routes — onboarding samples with mock analysis.
"""

from fastapi import APIRouter, Request
import uuid

from routers.shared import SESSION_STORE, limiter
from services import CROSS_CLOUD_MAPPINGS
from usage_metrics import record_funnel_step

router = APIRouter()


# Each sample defines zones with services.  The analyze endpoint
# builds data that matches the *real* vision-analysis output so
# that the questions / apply-answers / export / IaC pipelines
# work end-to-end without special-casing.

SAMPLE_DIAGRAMS = [
    {
        "id": "aws-iaas",
        "name": "AWS IaaS — VMs, VPC & Storage",
        "description": "Classic IaaS: VPC with public/private subnets, EC2 Auto Scaling behind an ALB, EBS volumes, S3 backups, and CloudWatch monitoring",
        "provider": "aws",
        "zones": [
            {
                "name": "Networking",
                "services": [
                    {"name": "VPC", "role": "Isolated virtual network with public and private subnets"},
                    {"name": "ELB", "role": "Application Load Balancer for HTTP/HTTPS traffic distribution"},
                    {"name": "VPN", "role": "Site-to-site VPN for hybrid connectivity"},
                    {"name": "Route 53", "role": "DNS resolution and health-check routing"},
                ],
            },
            {
                "name": "Compute",
                "services": [
                    {"name": "EC2", "role": "Auto Scaling group of web/app server instances"},
                    {"name": "EC2 Auto Scaling", "role": "Horizontal scaling based on CPU utilization"},
                ],
            },
            {
                "name": "Storage & Database",
                "services": [
                    {"name": "EBS", "role": "Block storage volumes attached to EC2 instances"},
                    {"name": "S3", "role": "Object storage for backups and static assets"},
                    {"name": "RDS", "role": "Multi-AZ PostgreSQL relational database"},
                ],
            },
            {
                "name": "Monitoring & Security",
                "services": [
                    {"name": "CloudWatch", "role": "Metrics, logs, and alarms"},
                    {"name": "IAM", "role": "Identity and access management policies"},
                    {"name": "KMS", "role": "Encryption key management for EBS and S3"},
                ],
            },
        ],
        "complexity": "medium",
    },
    {
        "id": "gcp-iaas",
        "name": "GCP IaaS — VMs, VPC & Cloud SQL",
        "description": "GCP IaaS stack: custom VPC, Compute Engine MIGs behind a load balancer, Persistent Disks, Cloud SQL, and Cloud Monitoring",
        "provider": "gcp",
        "zones": [
            {
                "name": "Networking",
                "services": [
                    {"name": "VPC", "role": "Custom-mode VPC with regional subnets"},
                    {"name": "Cloud Load Balancing", "role": "Global HTTP(S) load balancer with health checks"},
                    {"name": "Cloud VPN", "role": "Encrypted tunnel for on-premises connectivity"},
                    {"name": "Cloud DNS", "role": "Managed DNS with DNSSEC support"},
                ],
            },
            {
                "name": "Compute",
                "services": [
                    {"name": "Compute Engine", "role": "Managed Instance Groups running web/app tier"},
                    {"name": "Managed Instance Groups", "role": "Autoscaler for horizontal scaling"},
                ],
            },
            {
                "name": "Storage & Database",
                "services": [
                    {"name": "Persistent Disk", "role": "SSD block storage attached to VMs"},
                    {"name": "Cloud Storage", "role": "Object storage for backups and media"},
                    {"name": "Cloud SQL", "role": "Managed PostgreSQL with high availability"},
                ],
            },
            {
                "name": "Monitoring & Security",
                "services": [
                    {"name": "Cloud Monitoring", "role": "Infrastructure and application metrics"},
                    {"name": "Cloud IAM", "role": "Identity and access management"},
                    {"name": "Cloud KMS", "role": "Encryption key management"},
                ],
            },
        ],
        "complexity": "medium",
    },
    {
        "id": "aws-eks",
        "name": "AWS Containers — EKS & ECR",
        "description": "Container platform: EKS cluster with Fargate, ECR registry, EFS shared storage, ElastiCache, and CloudTrail audit",
        "provider": "aws",
        "zones": [
            {
                "name": "Networking",
                "services": [
                    {"name": "VPC", "role": "Cluster VPC with private node subnets"},
                    {"name": "ELB", "role": "Network Load Balancer for Kubernetes ingress"},
                    {"name": "PrivateLink", "role": "Private endpoints for AWS services"},
                ],
            },
            {
                "name": "Compute",
                "services": [
                    {"name": "EKS", "role": "Managed Kubernetes control plane"},
                    {"name": "Fargate", "role": "Serverless pod execution environment"},
                    {"name": "ECR", "role": "Private container image registry"},
                ],
            },
            {
                "name": "Data",
                "services": [
                    {"name": "EFS", "role": "Shared NFS file storage for pods"},
                    {"name": "ElastiCache", "role": "Redis session store and cache layer"},
                    {"name": "RDS", "role": "Aurora PostgreSQL database"},
                ],
            },
            {
                "name": "Security & Audit",
                "services": [
                    {"name": "IAM", "role": "IRSA roles for pod-level permissions"},
                    {"name": "Secrets Manager", "role": "Secrets injection via CSI driver"},
                    {"name": "CloudTrail", "role": "API audit logging"},
                ],
            },
        ],
        "complexity": "complex",
    },
    {
        "id": "gcp-gke",
        "name": "GCP Containers — GKE & Pub/Sub",
        "description": "GKE Autopilot with Cloud Run sidecars, Pub/Sub event bus, Firestore, Memorystore, and Security Command Center",
        "provider": "gcp",
        "zones": [
            {
                "name": "Networking",
                "services": [
                    {"name": "VPC", "role": "Shared VPC with private GKE subnets"},
                    {"name": "Cloud Load Balancing", "role": "Ingress controller with managed certificates"},
                    {"name": "Private Service Connect", "role": "Private connectivity to GCP APIs"},
                ],
            },
            {
                "name": "Compute",
                "services": [
                    {"name": "GKE", "role": "Autopilot Kubernetes cluster"},
                    {"name": "Cloud Run", "role": "Event-driven microservices"},
                    {"name": "Artifact Registry", "role": "Container and package registry"},
                ],
            },
            {
                "name": "Data & Messaging",
                "services": [
                    {"name": "Pub/Sub", "role": "Asynchronous event bus between services"},
                    {"name": "Firestore", "role": "NoSQL document database"},
                    {"name": "Memorystore", "role": "Managed Redis for caching"},
                ],
            },
            {
                "name": "Security",
                "services": [
                    {"name": "Cloud IAM", "role": "Workload Identity for pods"},
                    {"name": "Secret Manager", "role": "Application secrets management"},
                    {"name": "Security Command Center", "role": "Threat detection and compliance"},
                ],
            },
        ],
        "complexity": "complex",
    },
]


@router.get("/api/samples")
async def list_sample_diagrams():
    """List available sample diagrams for onboarding."""
    return {"samples": [
        {"id": s["id"], "name": s["name"], "description": s["description"],
         "provider": s["provider"], "complexity": s["complexity"]}
        for s in SAMPLE_DIAGRAMS
    ]}


from ai_suggestion import build_mapping_deep_dive

def build_sample_analysis(sample_id: str, diagram_id: str) -> dict:
    """Build a deterministic analysis dict for a sample diagram.

    Extracted so that expired sample sessions can be transparently
    recreated by any downstream endpoint (apply-answers, export, etc.).
    Returns the analysis dict or ``None`` if *sample_id* is unknown.
    """
    sample = next((s for s in SAMPLE_DIAGRAMS if s["id"] == sample_id), None)
    if not sample:
        return None

    mappings = []
    zones_with_services = []
    provider_key = "aws" if sample["provider"] == "aws" else "gcp"

    for zone_idx, zone_def in enumerate(sample["zones"], start=1):
        zone_services = []
        for svc in zone_def["services"]:
            svc_name = svc["name"]
            role = svc.get("role", "")

            mapping = next(
                (m for m in CROSS_CLOUD_MAPPINGS
                 if svc_name.lower() == m.get(provider_key, "").lower()
                 or svc_name.lower() in m.get(provider_key, "").lower()),
                None
            )

            azure_svc = mapping["azure"] if mapping else f"Azure {svc_name}"
            base_conf = mapping["confidence"] if mapping else 0.80
            confidence = round(min(1.0, base_conf * 0.7 + 0.85 * 0.3), 2)
            notes_text = mapping.get("notes", "Suggested equivalent") if mapping else "Suggested equivalent"
            _category = mapping.get("category", "General") if mapping else "General"

            # Build confidence explanation for transparency
            if mapping:
                conf_explanation = [
                    f"Curated mapping confidence: {int(base_conf * 100)}% — {notes_text}",
                    "Sample diagram detection confidence: 85% (pre-verified sample)",
                    f"Blended score: 70% mapping ({int(base_conf * 100)}%) + 30% detection (85%) = {int(confidence * 100)}%",
                ]
            else:
                conf_explanation = [
                    f"No curated mapping found for {svc_name} — base mapping score set to 80%",
                    "Sample diagram detection confidence: 85% (pre-verified sample)",
                    "Manual review recommended to confirm best target service",
                ]

            mapping_entry = {
                "source_service": svc_name,
                "source_provider": sample["provider"],
                "azure_service": azure_svc,
                "confidence": confidence,
                "confidence_explanation": conf_explanation,
                "notes": f"Zone {zone_idx} \u2013 {zone_def['name']}: {role}. {notes_text}".strip()
            }
            deep_dive = build_mapping_deep_dive(mapping_entry, svc_name)
            mapping_entry.update(deep_dive)

            if not mapping_entry.get("strengths"):
                mapping_entry["strengths"] = [f"Native integration mapped directly from {sample['provider'].upper()}"]
            if not mapping_entry.get("limitations"):
                mapping_entry["limitations"] = [f"Feature parity mismatch might require config adjustments in Azure {azure_svc}"]
            if not mapping_entry.get("migration_notes"):
                mapping_entry["migration_notes"] = [f"AWS usually migrates to Azure {azure_svc} with minimal refactoring." if sample['provider'] == 'aws' else f"GCP has differing networking topologies, test {azure_svc} routes."]
            
            mappings.append(mapping_entry)

            zone_services.append({
                "source": svc_name,
                "source_provider": sample["provider"],
                "azure": azure_svc,
                "confidence": confidence,
            })

        zones_with_services.append({
            "id": zone_idx,
            "name": zone_def["name"],
            "services": zone_services,
        })

    high = len([m for m in mappings if m["confidence"] >= 0.90])
    medium = len([m for m in mappings if 0.80 <= m["confidence"] < 0.90])
    low = len([m for m in mappings if m["confidence"] < 0.80])
    avg = round(sum(m["confidence"] for m in mappings) / max(len(mappings), 1), 2)

    return {
        "diagram_id": diagram_id,
        "diagram_type": sample["name"],
        "source_provider": sample["provider"],
        "target_provider": "azure",
        "architecture_patterns": [],
        "services_detected": len(mappings),
        "zones": zones_with_services,
        "mappings": mappings,
        "warnings": [],
        "service_connections": [],
        "confidence_summary": {
            "high": high,
            "medium": medium,
            "low": low,
            "average": avg,
            "methodology": (
                "Each confidence score is calculated by blending two factors: "
                "(1) a curated mapping confidence from our verified cross-cloud service database (weighted 70%), "
                "reflecting how closely the source and target services match in features and capabilities; and "
                "(2) a detection confidence (weighted 30%), representing identification certainty. "
                "Sample diagrams use a fixed 85% detection confidence since services are pre-verified."
            ),
        },
        "is_sample": True,
    }


import re as _re  # noqa: E402

# Pattern: "sample-<sample_id>-<hex6>"
_SAMPLE_ID_RE = _re.compile(r"^sample-(.+)-[0-9a-f]{6}$")


def get_or_recreate_session(diagram_id: str):
    """Return the session for *diagram_id*, auto-recreating sample sessions.

    For sample diagrams (IDs like ``sample-aws-iaas-0af138``) the analysis
    is deterministic, so we silently rebuild it when the in-memory store
    has evicted or lost the entry (e.g. after a container restart).

    Returns ``None`` only for non-sample diagrams that are genuinely missing.
    """
    session = SESSION_STORE.get(diagram_id)
    if session is not None:
        return session

    m = _SAMPLE_ID_RE.match(diagram_id)
    if not m:
        return None  # not a sample — genuinely missing

    sample_id = m.group(1)
    analysis = build_sample_analysis(sample_id, diagram_id)
    if analysis is None:
        return None  # unknown sample name

    SESSION_STORE[diagram_id] = analysis
    return analysis


@router.post("/api/samples/{sample_id}/analyze")
@limiter.limit("5/minute")
async def analyze_sample_diagram(request: Request, sample_id: str):
    """Generate a mock analysis for a sample diagram.

    The returned structure mirrors the real vision-analysis output so that
    every downstream endpoint (questions, apply-answers, export, IaC,
    HLD, cost-estimate) works without special-casing.
    """
    diagram_id = f"sample-{sample_id}-{uuid.uuid4().hex[:6]}"
    analysis = build_sample_analysis(sample_id, diagram_id)
    if analysis is None:
        raise ArchmorphException(404, f"Sample '{sample_id}' not found")

    SESSION_STORE[diagram_id] = analysis
    record_funnel_step(diagram_id, "analyze")

    return analysis
