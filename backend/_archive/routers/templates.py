"""
Architecture Template Gallery
============================
Pre-built cloud architecture templates for common patterns.
Users can browse, preview, and use these as starting points.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/templates", tags=["templates"])

# ─────────────────────────────────────────────────────────────
# Template catalog — each entry is a common architecture pattern
# with metadata and a pre-built analysis snapshot that can seed
# the DiagramTranslator.
# ─────────────────────────────────────────────────────────────
TEMPLATES: list[dict] = [
    {
        "id": "three-tier-web",
        "title": "3-Tier Web Application",
        "description": "Classic web architecture with load balancer, application servers, and managed database. Ideal for traditional web apps, CMS, and e-commerce platforms.",
        "category": "web",
        "difficulty": "beginner",
        "source_provider": "aws",
        "services": ["ALB", "EC2", "RDS", "ElastiCache", "S3", "CloudFront"],
        "tags": ["web", "load-balancer", "database", "caching"],
        "icon": "globe",
        "estimated_monthly_cost": "$150 – $500",
    },
    {
        "id": "serverless-api",
        "title": "Serverless REST API",
        "description": "Event-driven API using managed functions, API gateway, and NoSQL database. Zero server management with auto-scaling from zero to millions of requests.",
        "category": "serverless",
        "difficulty": "beginner",
        "source_provider": "aws",
        "services": ["API Gateway", "Lambda", "DynamoDB", "Cognito", "CloudWatch"],
        "tags": ["serverless", "api", "nosql", "event-driven"],
        "icon": "zap",
        "estimated_monthly_cost": "$10 – $200",
    },
    {
        "id": "microservices-k8s",
        "title": "Microservices on Kubernetes",
        "description": "Container-orchestrated microservices with service mesh, centralized logging, and auto-scaling. For teams adopting cloud-native patterns.",
        "category": "containers",
        "difficulty": "advanced",
        "source_provider": "aws",
        "services": ["EKS", "ECR", "ALB", "RDS", "ElastiCache", "CloudWatch", "SQS"],
        "tags": ["kubernetes", "containers", "microservices", "service-mesh"],
        "icon": "boxes",
        "estimated_monthly_cost": "$500 – $2,000",
    },
    {
        "id": "data-pipeline",
        "title": "Real-Time Data Pipeline",
        "description": "Stream ingestion, transformation, and analytics pipeline. Process millions of events per second with real-time dashboards and alerts.",
        "category": "data",
        "difficulty": "intermediate",
        "source_provider": "aws",
        "services": ["Kinesis", "Lambda", "S3", "Glue", "Redshift", "QuickSight"],
        "tags": ["data", "streaming", "analytics", "etl"],
        "icon": "activity",
        "estimated_monthly_cost": "$300 – $1,500",
    },
    {
        "id": "ml-platform",
        "title": "ML Training & Inference",
        "description": "End-to-end machine learning platform with model training, experiment tracking, and real-time inference endpoints.",
        "category": "ai-ml",
        "difficulty": "advanced",
        "source_provider": "aws",
        "services": ["SageMaker", "S3", "ECR", "Lambda", "API Gateway", "CloudWatch"],
        "tags": ["machine-learning", "ai", "inference", "training"],
        "icon": "brain",
        "estimated_monthly_cost": "$500 – $5,000",
    },
    {
        "id": "static-site-cdn",
        "title": "Static Site with CDN",
        "description": "JAMstack architecture with global CDN, serverless functions for dynamic content, and CI/CD pipeline. Lightning-fast pages worldwide.",
        "category": "web",
        "difficulty": "beginner",
        "source_provider": "aws",
        "services": ["S3", "CloudFront", "Route 53", "Lambda@Edge", "ACM"],
        "tags": ["static-site", "cdn", "jamstack", "edge"],
        "icon": "globe2",
        "estimated_monthly_cost": "$5 – $50",
    },
    {
        "id": "event-driven-saga",
        "title": "Event-Driven Architecture",
        "description": "Loosely coupled services communicating through an event bus with dead-letter queues, retries, and saga orchestration for distributed transactions.",
        "category": "serverless",
        "difficulty": "intermediate",
        "source_provider": "aws",
        "services": ["EventBridge", "SQS", "SNS", "Lambda", "Step Functions", "DynamoDB"],
        "tags": ["event-driven", "saga", "messaging", "orchestration"],
        "icon": "workflow",
        "estimated_monthly_cost": "$50 – $300",
    },
    {
        "id": "multi-region-ha",
        "title": "Multi-Region High Availability",
        "description": "Active-active multi-region deployment with global load balancing, cross-region replication, and automated failover. 99.99% uptime target.",
        "category": "enterprise",
        "difficulty": "advanced",
        "source_provider": "aws",
        "services": ["Route 53", "ALB", "EC2", "Aurora Global", "S3", "CloudFront", "WAF"],
        "tags": ["multi-region", "high-availability", "disaster-recovery", "failover"],
        "icon": "shield",
        "estimated_monthly_cost": "$2,000 – $10,000",
    },
    {
        "id": "iot-platform",
        "title": "IoT Data Platform",
        "description": "Device management, telemetry ingestion, real-time processing, and device twin for IoT fleet management at scale.",
        "category": "iot",
        "difficulty": "intermediate",
        "source_provider": "aws",
        "services": ["IoT Core", "IoT Analytics", "Kinesis", "Lambda", "DynamoDB", "S3"],
        "tags": ["iot", "devices", "telemetry", "edge"],
        "icon": "cpu",
        "estimated_monthly_cost": "$200 – $1,000",
    },
    {
        "id": "gcp-web-app",
        "title": "GCP Web Application",
        "description": "Google Cloud based web app with Cloud Run, Cloud SQL, and Memorystore. Fully managed with auto-scaling.",
        "category": "web",
        "difficulty": "beginner",
        "source_provider": "gcp",
        "services": ["Cloud Run", "Cloud SQL", "Memorystore", "Cloud CDN", "Cloud Storage"],
        "tags": ["gcp", "web", "serverless", "managed"],
        "icon": "globe",
        "estimated_monthly_cost": "$100 – $400",
    },
]

CATEGORIES = [
    {"id": "all", "label": "All Templates", "count": len(TEMPLATES)},
    {"id": "web", "label": "Web & APIs", "count": sum(1 for t in TEMPLATES if t["category"] == "web")},
    {"id": "serverless", "label": "Serverless", "count": sum(1 for t in TEMPLATES if t["category"] == "serverless")},
    {"id": "containers", "label": "Containers", "count": sum(1 for t in TEMPLATES if t["category"] == "containers")},
    {"id": "data", "label": "Data & Analytics", "count": sum(1 for t in TEMPLATES if t["category"] == "data")},
    {"id": "ai-ml", "label": "AI / ML", "count": sum(1 for t in TEMPLATES if t["category"] == "ai-ml")},
    {"id": "enterprise", "label": "Enterprise", "count": sum(1 for t in TEMPLATES if t["category"] == "enterprise")},
    {"id": "iot", "label": "IoT", "count": sum(1 for t in TEMPLATES if t["category"] == "iot")},
]


@router.get("")
async def list_templates(category: str = "all", source_provider: str = ""):
    """Browse available architecture templates."""
    filtered = TEMPLATES
    if category != "all":
        filtered = [t for t in filtered if t["category"] == category]
    if source_provider:
        filtered = [t for t in filtered if t["source_provider"] == source_provider]
    return {"templates": filtered, "categories": CATEGORIES, "total": len(filtered)}


@router.get("/{template_id}")
async def get_template(template_id: str):
    """Get a specific template with full details."""
    for t in TEMPLATES:
        if t["id"] == template_id:
            return t
    return {"error": "Template not found"}, 404
