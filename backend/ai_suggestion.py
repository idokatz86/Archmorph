"""AI Cross-Cloud Mapping Auto-Suggestion (Issue #153).

Uses GPT-4o to suggest Azure equivalents for unknown / low-confidence
source-cloud services, with dependency-graph-aware reasoning.
Integrates with the existing CROSS_CLOUD_MAPPINGS catalogue and
provides an admin review queue for human-in-the-loop vetting.
"""

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.mappings import CROSS_CLOUD_MAPPINGS
from openai_client import (
    get_openai_client,
    AZURE_OPENAI_DEPLOYMENT,
    openai_retry,
    handle_openai_error,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# In-memory admin review queue (replaced by DB in prod)
# ─────────────────────────────────────────────────────────
_review_queue: Dict[str, Dict[str, Any]] = {}  # suggestion_id → suggestion
_review_lock = threading.Lock()

# ─────────────────────────────────────────────────────────
# Learning feedback store — approved/rejected decisions
# used as few-shot examples for future GPT suggestions
# ─────────────────────────────────────────────────────────
_feedback_store: List[Dict[str, Any]] = []  # chronologically ordered
_feedback_lock = threading.Lock()
_AUTO_APPROVE_THRESHOLD = 0.9  # confidence > this → auto-approved

# Known catalogue lookup for fast matching
_KNOWN_AWS: Dict[str, Dict[str, Any]] = {}
_KNOWN_GCP: Dict[str, Dict[str, Any]] = {}

for m in CROSS_CLOUD_MAPPINGS:
    if m.get("aws"):
        _KNOWN_AWS[m["aws"].lower()] = m
    if m.get("gcp"):
        _KNOWN_GCP[m["gcp"].lower()] = m


# ─────────────────────────────────────────────────────────
# Catalogue lookup (fast path)
# ─────────────────────────────────────────────────────────
def lookup_mapping(
    source_service: str,
    source_provider: str = "aws",
) -> Optional[Dict[str, Any]]:
    """Check if a service already exists in the curated catalogue.

    Returns the mapping dict if found, None otherwise.
    """
    key = source_service.strip().lower()
    if source_provider.lower() in ("aws", "amazon"):
        return _KNOWN_AWS.get(key)
    if source_provider.lower() in ("gcp", "google"):
        return _KNOWN_GCP.get(key)
    return None


# ─────────────────────────────────────────────────────────
# GPT-4o AI suggestion
# ─────────────────────────────────────────────────────────
_SUGGESTION_SYSTEM_PROMPT = """You are an expert cloud architect specialising in cross-cloud migrations.
Given a source cloud service (AWS or GCP), suggest the best Azure equivalent.

Return a JSON object with these exact fields:
{
  "azure_service": "Name of the Azure service",
  "confidence": 0.0 to 1.0,
  "category": "Compute|Storage|Database|Networking|Security|AI/ML|Analytics|DevOps|Integration|Management",
  "notes": "Brief migration guidance (max 150 chars)",
  "alternatives": ["other Azure options if any"],
  "migration_effort": "low|medium|high",
  "feature_gaps": ["If any feature gaps exist, explain the mismatch in detail and provide an official Microsoft Learn or Azure docs link for reference"],
  "dependencies": ["other Azure services typically needed"]
}

Rules:
- confidence must reflect realistic feature parity (0.6-0.95 range usually)
- When there is a Feature parity mismatch or a feature gap, explicitly explain what the mismatch is within feature_gaps, and supply a link to official documentation (e.g. Microsoft Learn) explaining the limitation or alternative.
- If no good Azure equivalent exists, set confidence < 0.5 and explain in notes
- Consider the surrounding architecture context when suggesting alternatives
- Return ONLY the JSON object, no markdown fencing
"""


def _build_few_shot_examples(source_provider: str, max_examples: int = 5) -> str:
    """Build few-shot examples from approved feedback for the GPT prompt."""
    examples = []
    with _feedback_lock:
        approved = [
            fb for fb in _feedback_store
            if fb.get("decision") == "approved"
            and fb.get("source_provider", "").lower() == source_provider.lower()
        ]
    # Take most recent approved entries
    for fb in approved[-max_examples:]:
        examples.append(
            f'  {{"source": "{fb.get("source_service", "")}", '
            f'"azure_service": "{fb.get("azure_service", "")}", '
            f'"confidence": {fb.get("confidence", 0.8)}, '
            f'"category": "{fb.get("category", "")}"}}'
        )
    # Also pull a few from the known catalogue
    known = _KNOWN_AWS if source_provider.lower() in ("aws", "amazon") else _KNOWN_GCP
    for key, m in list(known.items())[:max(0, max_examples - len(examples))]:
        examples.append(
            f'  {{"source": "{key}", '
            f'"azure_service": "{m.get("azure", "")}", '
            f'"confidence": {m.get("confidence", 0.9)}, '
            f'"category": "{m.get("category", "")}"}}'
        )
    if not examples:
        return ""
    return (
        "\n\nHere are verified mappings for reference:\n"
        + "\n".join(examples)
    )


def _record_feedback(suggestion: Dict[str, Any], decision: str, reviewer: str) -> None:
    """Record an approved/rejected decision for learning feedback."""
    entry = {
        "source_service": suggestion.get("source_service", ""),
        "source_provider": suggestion.get("source_provider", ""),
        "azure_service": suggestion.get("azure_service", ""),
        "confidence": suggestion.get("confidence", 0),
        "category": suggestion.get("category", ""),
        "decision": decision,
        "reviewer": reviewer,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    with _feedback_lock:
        _feedback_store.append(entry)
    logger.info("Recorded feedback: %s → %s (%s)", entry["source_service"], entry["azure_service"], decision)


def _build_confidence_factors(suggestion: Dict[str, Any], source_service: str) -> list:
    """Build human-readable confidence factor breakdown (#353).

    Returns a list of dicts, each with:
      - factor: str (name of the signal)
      - weight: float (0-1)
      - signal: str ("positive" | "negative" | "neutral")
      - explanation: str (plain-language explanation)
    """
    confidence = float(suggestion.get("confidence", 0.5))
    factors = []

    # 1. Catalog match — did we find it in the service catalog?
    if suggestion.get("source") == "catalog" or confidence >= 0.9:
        factors.append({
            "factor": "catalog_match",
            "weight": 0.35,
            "signal": "positive",
            "explanation": f"'{source_service}' has a direct match in the Archmorph service catalog.",
        })
    else:
        factors.append({
            "factor": "catalog_match",
            "weight": 0.35,
            "signal": "negative",
            "explanation": f"'{source_service}' was not found in the catalog; AI inference was used.",
        })

    # 2. Feature parity
    gaps = suggestion.get("feature_gaps", [])
    if not gaps:
        factors.append({
            "factor": "feature_parity",
            "weight": 0.25,
            "signal": "positive",
            "explanation": "No significant feature gaps detected between source and target service.",
        })
    else:
        factors.append({
            "factor": "feature_parity",
            "weight": 0.25,
            "signal": "negative",
            "explanation": f"{len(gaps)} feature gap(s) identified: {', '.join(gaps[:3])}.",
        })

    # 3. Migration effort
    effort = suggestion.get("migration_effort", "medium")
    if effort == "low":
        factors.append({
            "factor": "migration_effort",
            "weight": 0.20,
            "signal": "positive",
            "explanation": "Low migration effort — near drop-in replacement.",
        })
    elif effort == "high":
        factors.append({
            "factor": "migration_effort",
            "weight": 0.20,
            "signal": "negative",
            "explanation": "High migration effort — significant rearchitecture required.",
        })
    else:
        factors.append({
            "factor": "migration_effort",
            "weight": 0.20,
            "signal": "neutral",
            "explanation": "Moderate migration effort — some adaptation needed.",
        })

    # 4. Alternatives available
    alts = suggestion.get("alternatives", [])
    if len(alts) >= 2:
        factors.append({
            "factor": "alternatives_available",
            "weight": 0.10,
            "signal": "neutral",
            "explanation": f"{len(alts)} alternative Azure services considered; best match selected.",
        })
    else:
        factors.append({
            "factor": "alternatives_available",
            "weight": 0.10,
            "signal": "positive",
            "explanation": "Strong single-best match with few viable alternatives.",
        })

    # 5. Confidence threshold summary
    if confidence >= 0.85:
        level, label = "positive", "High"
    elif confidence >= 0.6:
        level, label = "neutral", "Medium"
    else:
        level, label = "negative", "Low"
    factors.append({
        "factor": "overall_assessment",
        "weight": 0.10,
        "signal": level,
        "explanation": f"{label} confidence ({confidence:.0%}). "
                       + ("Mapping is reliable for production use." if confidence >= 0.85
                          else "Consider reviewing before finalizing." if confidence >= 0.6
                          else "Manual review strongly recommended."),
    })

    return factors


# ─────────────────────────────────────────────────────────
# Per-mapping strengths, limitations & migration notes (#404)
# ─────────────────────────────────────────────────────────
# Curated knowledge base of Azure-specific limitations and strengths
# keyed by lowercase Azure service name fragments.
_SERVICE_KNOWLEDGE_BASE: Dict[str, Dict[str, Any]] = {
    "virtual machines": {
        "strengths": [
            {"factor": "Broad VM family selection", "detail": "60+ VM series covering general purpose, compute, memory, storage, GPU and HPC workloads.", "severity": "positive"},
            {"factor": "Hybrid benefit", "detail": "Azure Hybrid Benefit allows reuse of Windows Server / SQL Server licenses for up to 85% savings.", "severity": "positive"},
            {"factor": "Availability Zones", "detail": "99.99% SLA with VMs spread across 3 availability zones.", "severity": "positive"},
        ],
        "limitations": [
            {"factor": "Nested virtualisation", "detail": "Nested Hyper-V is only supported on Dv3/Ev3 or newer series.", "severity": "low", "doc_link": "https://learn.microsoft.com/en-us/azure/virtual-machines/acu"},
            {"factor": "Live migration during maintenance", "detail": "Memory-preserving live migration is not guaranteed for all VM sizes.", "severity": "medium", "doc_link": "https://learn.microsoft.com/en-us/azure/virtual-machines/maintenance-and-updates"},
        ],
        "migration_notes": [
            {"area": "config", "note": "AMI → Managed Image or Azure Compute Gallery conversion required.", "effort": "medium"},
            {"area": "networking", "note": "Security groups → NSG rule translation (stateful in both, but syntax differs).", "effort": "low"},
        ],
    },
    "kubernetes": {
        "strengths": [
            {"factor": "Managed Kubernetes", "detail": "AKS provides free control plane, integrated Azure AD RBAC, and auto-upgrade channels.", "severity": "positive"},
            {"factor": "KEDA autoscaling", "detail": "Native event-driven autoscaling with KEDA built into AKS.", "severity": "positive"},
        ],
        "limitations": [
            {"factor": "IAM to Azure RBAC", "detail": "AWS IAM roles for service accounts → Azure Workload Identity Federation migration required.", "severity": "high", "doc_link": "https://learn.microsoft.com/en-us/azure/aks/workload-identity-overview"},
            {"factor": "Node pool limits", "detail": "AKS supports max 5,000 nodes per cluster (vs EKS 5,000) but 100 nodes per pool by default.", "severity": "medium", "doc_link": "https://learn.microsoft.com/en-us/azure/aks/quotas-skus-regions"},
        ],
        "migration_notes": [
            {"area": "code", "note": "Kubernetes manifests are portable; Helm charts work directly.", "effort": "low"},
            {"area": "config", "note": "aws-load-balancer-controller annotations → Azure-specific ingress annotations.", "effort": "medium"},
            {"area": "data", "note": "Persistent volumes: EBS CSI → Azure Disk CSI driver (no data migration needed for stateless).", "effort": "low"},
        ],
    },
    "lambda": {
        "strengths": [
            {"factor": "Consumption billing", "detail": "Azure Functions Consumption plan: pay only for execution time, first 1M requests free.", "severity": "positive"},
            {"factor": "Durable Functions", "detail": "Built-in orchestration patterns (fan-out, chaining, human interaction) not natively available in Lambda.", "severity": "positive"},
        ],
        "limitations": [
            {"factor": "Timeout limits", "detail": "Consumption plan max timeout is 10 minutes (Lambda allows 15 min). Use Premium plan for longer.", "severity": "medium", "doc_link": "https://learn.microsoft.com/en-us/azure/azure-functions/functions-scale"},
            {"factor": "Cold start", "detail": "Consumption plan cold starts can be 1-3s; Premium plan offers pre-warmed instances.", "severity": "medium", "doc_link": "https://learn.microsoft.com/en-us/azure/azure-functions/functions-premium-plan"},
            {"factor": "Layer equivalence", "detail": "Lambda Layers have no direct equivalent; use custom Docker images or NuGet/npm packages.", "severity": "low", "doc_link": "https://learn.microsoft.com/en-us/azure/azure-functions/functions-custom-handlers"},
        ],
        "migration_notes": [
            {"area": "code", "note": "Handler signature differs: Lambda handler(event, context) → Azure Function trigger bindings.", "effort": "medium"},
            {"area": "config", "note": "API Gateway + Lambda → Azure Functions HTTP trigger or Azure API Management.", "effort": "medium"},
        ],
    },
    "functions": {
        "strengths": [
            {"factor": "Consumption billing", "detail": "Pay-per-execution with generous free tier (1M requests/month).", "severity": "positive"},
            {"factor": "Durable orchestration", "detail": "Durable Functions for complex workflows with automatic state management.", "severity": "positive"},
        ],
        "limitations": [
            {"factor": "Timeout limits", "detail": "Consumption plan: 10 min max. Premium/Dedicated plans: configurable up to unlimited.", "severity": "medium", "doc_link": "https://learn.microsoft.com/en-us/azure/azure-functions/functions-scale"},
        ],
        "migration_notes": [
            {"area": "code", "note": "Cloud Functions HTTP trigger → Azure Functions HTTP trigger; signature adaptation needed.", "effort": "medium"},
        ],
    },
    "s3": {
        "strengths": [
            {"factor": "Tiered storage", "detail": "Hot/Cool/Cold/Archive tiers with lifecycle management for cost optimisation.", "severity": "positive"},
            {"factor": "Azure Data Lake", "detail": "Blob Storage supports hierarchical namespace (ADLS Gen2) for big data analytics.", "severity": "positive"},
        ],
        "limitations": [
            {"factor": "Object lock", "detail": "Immutable storage policies differ from S3 Object Lock (compliance vs legal hold modes).", "severity": "low", "doc_link": "https://learn.microsoft.com/en-us/azure/storage/blobs/immutable-storage-overview"},
            {"factor": "Request rate", "detail": "Blob Storage: 20,000 requests/sec per storage account (S3: 5,500 PUT per prefix).", "severity": "low", "doc_link": "https://learn.microsoft.com/en-us/azure/storage/common/scalability-targets-standard-account"},
        ],
        "migration_notes": [
            {"area": "data", "note": "Use AzCopy or Azure Data Box for large-scale S3 → Blob migration.", "effort": "low"},
            {"area": "config", "note": "S3 bucket policies → Azure RBAC + Blob access policies.", "effort": "medium"},
        ],
    },
    "rds": {
        "strengths": [
            {"factor": "Managed database", "detail": "Azure SQL/PostgreSQL Flex offers built-in HA, automated backups, and intelligent tuning.", "severity": "positive"},
            {"factor": "Serverless tier", "detail": "Azure SQL Serverless auto-pauses and auto-scales, ideal for intermittent workloads.", "severity": "positive"},
        ],
        "limitations": [
            {"factor": "Engine compatibility", "detail": "RDS Oracle/MariaDB: no native Azure equivalent; use Azure SQL or VM-hosted DB.", "severity": "high", "doc_link": "https://learn.microsoft.com/en-us/azure/azure-sql/migration-guides/"},
            {"factor": "Read replicas", "detail": "Azure SQL read replicas are limited to same region for Hyperscale tier.", "severity": "medium", "doc_link": "https://learn.microsoft.com/en-us/azure/azure-sql/database/read-scale-out"},
        ],
        "migration_notes": [
            {"area": "data", "note": "Use Azure Database Migration Service (DMS) for schema + data migration.", "effort": "medium"},
            {"area": "config", "note": "Parameter groups → Azure server parameters; connection string format change.", "effort": "low"},
        ],
    },
    "cosmos": {
        "strengths": [
            {"factor": "Multi-model", "detail": "Supports SQL, MongoDB, Cassandra, Gremlin, and Table APIs natively.", "severity": "positive"},
            {"factor": "Global distribution", "detail": "Turnkey multi-region writes with 5 consistency levels.", "severity": "positive"},
        ],
        "limitations": [
            {"factor": "RU pricing model", "detail": "Request Unit (RU) based pricing can be complex to predict; use capacity calculator.", "severity": "medium", "doc_link": "https://learn.microsoft.com/en-us/azure/cosmos-db/request-units"},
            {"factor": "Document size", "detail": "Max document size is 2 MB (DynamoDB: 400 KB but with item collections).", "severity": "low", "doc_link": "https://learn.microsoft.com/en-us/azure/cosmos-db/concepts-limits"},
        ],
        "migration_notes": [
            {"area": "data", "note": "DynamoDB → Cosmos DB SQL API migration using Azure Data Factory or custom ETL.", "effort": "high"},
            {"area": "code", "note": "DynamoDB SDK calls → Cosmos DB SDK; query syntax differs significantly for SQL API.", "effort": "high"},
        ],
    },
    "sql": {
        "strengths": [
            {"factor": "Intelligent performance", "detail": "Automatic tuning, intelligent insights, and query performance recommendations.", "severity": "positive"},
            {"factor": "Elastic pools", "detail": "Share resources across multiple databases for cost efficiency.", "severity": "positive"},
        ],
        "limitations": [
            {"factor": "Cross-database queries", "detail": "Cross-database queries require Elastic Query (limited) or Synapse Link.", "severity": "medium", "doc_link": "https://learn.microsoft.com/en-us/azure/azure-sql/database/elastic-query-overview"},
        ],
        "migration_notes": [
            {"area": "data", "note": "Use Database Migration Service for online migration with minimal downtime.", "effort": "medium"},
        ],
    },
    "redis": {
        "strengths": [
            {"factor": "Managed service", "detail": "Azure Cache for Redis with clustering, geo-replication, and data persistence.", "severity": "positive"},
        ],
        "limitations": [
            {"factor": "Lua scripting", "detail": "Complex Lua scripts may need adaptation; check command compatibility.", "severity": "low", "doc_link": "https://learn.microsoft.com/en-us/azure/azure-cache-for-redis/cache-lua-scripting"},
        ],
        "migration_notes": [
            {"area": "data", "note": "Use RDB export/import or RIOT tool for data migration.", "effort": "low"},
        ],
    },
    "load balancer": {
        "strengths": [
            {"factor": "Layer 4 & 7 options", "detail": "Azure Load Balancer (L4) + Application Gateway (L7) + Front Door (global L7).", "severity": "positive"},
        ],
        "limitations": [
            {"factor": "Feature mapping", "detail": "ALB → Application Gateway; NLB → Azure LB; one-to-one but config differs.", "severity": "medium", "doc_link": "https://learn.microsoft.com/en-us/azure/architecture/guide/technology-choices/load-balancing-overview"},
        ],
        "migration_notes": [
            {"area": "config", "note": "Target groups → Backend pools; listener rules → routing rules.", "effort": "medium"},
        ],
    },
    "cloudfront": {
        "strengths": [
            {"factor": "Azure Front Door", "detail": "Global load balancing + CDN + WAF in a single service.", "severity": "positive"},
        ],
        "limitations": [
            {"factor": "Lambda@Edge", "detail": "CloudFront Functions/Lambda@Edge → Azure Front Door Rules Engine (less flexible).", "severity": "medium", "doc_link": "https://learn.microsoft.com/en-us/azure/frontdoor/front-door-rules-engine"},
        ],
        "migration_notes": [
            {"area": "config", "note": "CloudFront distributions → Front Door profiles; origin and routing reconfiguration.", "effort": "medium"},
        ],
    },
    "sqs": {
        "strengths": [
            {"factor": "Azure Service Bus", "detail": "Enterprise messaging with sessions, dead-letter, and scheduled delivery.", "severity": "positive"},
        ],
        "limitations": [
            {"factor": "FIFO guarantees", "detail": "Service Bus sessions provide ordering but differ from SQS FIFO group-level ordering.", "severity": "medium", "doc_link": "https://learn.microsoft.com/en-us/azure/service-bus-messaging/message-sessions"},
        ],
        "migration_notes": [
            {"area": "code", "note": "SQS SDK → Service Bus SDK; message format and receipt handle semantics differ.", "effort": "medium"},
        ],
    },
    "sns": {
        "strengths": [
            {"factor": "Event Grid", "detail": "Azure Event Grid provides event-driven pub/sub with filtering and dead-letter.", "severity": "positive"},
        ],
        "limitations": [
            {"factor": "SMS/push", "detail": "SNS SMS/push → Azure Notification Hubs (separate service) or Communication Services.", "severity": "medium", "doc_link": "https://learn.microsoft.com/en-us/azure/notification-hubs/"},
        ],
        "migration_notes": [
            {"area": "code", "note": "SNS topic subscriptions → Event Grid subscriptions; different filtering syntax.", "effort": "medium"},
        ],
    },
    "vpc": {
        "strengths": [
            {"factor": "VNet", "detail": "Azure Virtual Network with subnet delegation, service endpoints, and Private Link.", "severity": "positive"},
        ],
        "limitations": [
            {"factor": "CIDR flexibility", "detail": "VNet address space can be modified after creation but subnets cannot overlap.", "severity": "low", "doc_link": "https://learn.microsoft.com/en-us/azure/virtual-network/manage-virtual-network"},
        ],
        "migration_notes": [
            {"area": "networking", "note": "VPC subnets → VNet subnets; NAT Gateway and route tables need reconfiguration.", "effort": "medium"},
        ],
    },
    "app service": {
        "strengths": [
            {"factor": "Fully managed PaaS", "detail": "Built-in CI/CD, custom domains, SSL, and autoscale with zero infrastructure management.", "severity": "positive"},
            {"factor": "Deployment slots", "detail": "Blue-green deployments with traffic splitting built into the platform.", "severity": "positive"},
        ],
        "limitations": [
            {"factor": "Runtime restrictions", "detail": "Consumption-tier App Service has limited outbound IP control and sandbox restrictions.", "severity": "low", "doc_link": "https://learn.microsoft.com/en-us/azure/app-service/overview-patch-os-runtime"},
        ],
        "migration_notes": [
            {"area": "config", "note": "Elastic Beanstalk/App Runner → App Service; Procfile → startup command.", "effort": "low"},
        ],
    },
    "container apps": {
        "strengths": [
            {"factor": "Serverless containers", "detail": "Scale to zero, Dapr integration, and KEDA-based autoscaling.", "severity": "positive"},
            {"factor": "Revision management", "detail": "Built-in traffic splitting for canary/blue-green deployments.", "severity": "positive"},
        ],
        "limitations": [
            {"factor": "GPU support", "detail": "Container Apps GPU workloads require dedicated plan (preview).", "severity": "medium", "doc_link": "https://learn.microsoft.com/en-us/azure/container-apps/gpu-overview"},
        ],
        "migration_notes": [
            {"area": "config", "note": "ECS task definitions → Container Apps YAML manifests; port and env var mapping.", "effort": "medium"},
        ],
    },
}


def _lookup_service_knowledge(azure_service: str) -> Dict[str, Any]:
    """Look up curated knowledge for an Azure service. Returns strengths, limitations, migration notes."""
    svc_lower = azure_service.lower()
    for key, knowledge in _SERVICE_KNOWLEDGE_BASE.items():
        if key in svc_lower or svc_lower in key:
            return knowledge
    # Generic fallback
    return {
        "strengths": [
            {"factor": "Managed Azure service", "detail": f"{azure_service} is a fully managed Azure service with SLA guarantees.", "severity": "positive"},
        ],
        "limitations": [],
        "migration_notes": [
            {"area": "config", "note": "Configuration format and SDK calls will differ from the source provider.", "effort": "medium"},
        ],
    }


def build_mapping_deep_dive(suggestion: Dict[str, Any], source_service: str) -> Dict[str, Any]:
    """Build structured strengths, limitations, and migration notes for a mapping (#404).

    Returns dict with:
      - strengths: list of {factor, detail, severity}
      - limitations: list of {factor, detail, severity, doc_link}
      - migration_notes: list of {area, note, effort}
    """
    azure_service = suggestion.get("azure_service", "")
    knowledge = _lookup_service_knowledge(azure_service)

    strengths = list(knowledge.get("strengths", []))
    limitations = list(knowledge.get("limitations", []))
    migration_notes = list(knowledge.get("migration_notes", []))

    # Supplement from GPT suggestion data
    gaps = suggestion.get("feature_gaps", [])
    for gap in gaps:
        if not any(lim["factor"].lower() == gap.lower() for lim in limitations):
            limitations.append({
                "factor": gap,
                "detail": f"Feature gap identified during AI analysis: {gap}.",
                "severity": "medium",
                "doc_link": "",
            })

    # Add effort-based migration note if not already present
    effort = suggestion.get("migration_effort", "medium")
    deps = suggestion.get("dependencies", [])
    if deps and not any(n["area"] == "dependencies" for n in migration_notes):
        migration_notes.append({
            "area": "dependencies",
            "note": f"Requires additional Azure services: {', '.join(deps[:4])}.",
            "effort": effort,
        })

    return {
        "strengths": strengths,
        "limitations": limitations,
        "migration_notes": migration_notes,
    }


@openai_retry
def _call_gpt_suggest(
    source_service: str,
    source_provider: str,
    context_services: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Call GPT-4o for a mapping suggestion."""
    client = get_openai_client()

    user_content = f"Source provider: {source_provider}\nSource service: {source_service}"
    if context_services:
        user_content += f"\nOther services in the architecture: {', '.join(context_services[:20])}"

    # Inject few-shot examples from approved feedback + catalogue
    few_shot = _build_few_shot_examples(source_provider)
    if few_shot:
        user_content += few_shot

    response = client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": _SUGGESTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.2,
        max_tokens=500,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or "{}"
    return json.loads(raw)


def suggest_mapping(
    source_service: str,
    source_provider: str = "aws",
    context_services: Optional[List[str]] = None,
    auto_queue_review: bool = True,
) -> Dict[str, Any]:
    """Suggest an Azure mapping for a source cloud service.

    1. Fast path — check curated catalogue first.
    2. Slow path — call GPT-4o for AI suggestion.
    3. If confidence < 0.7, automatically queue for admin review.

    Parameters
    ----------
    source_service : str
        Name of the source cloud service (e.g. "Kinesis Data Streams").
    source_provider : str
        "aws" or "gcp".
    context_services : list, optional
        Other services in the architecture for contextual suggestion.
    auto_queue_review : bool
        If True, low-confidence suggestions are queued for review.

    Returns
    -------
    dict
        Suggestion with azure_service, confidence, category, notes, etc.
    """
    # Fast path — catalogue hit
    existing = lookup_mapping(source_service, source_provider)
    if existing:
        result = {
            "source_service": source_service,
            "source_provider": source_provider,
            "azure_service": existing.get("azure", ""),
            "confidence": existing.get("confidence", 0.9),
            "category": existing.get("category", ""),
            "notes": existing.get("notes", ""),
            "source": "catalogue",
            "review_status": "approved",
        }
        # Add deep-dive data for catalogue matches too (#404)
        result["confidence_factors"] = _build_confidence_factors(result, source_service)
        result.update(build_mapping_deep_dive(result, source_service))
        return result

    # Slow path — GPT-4o
    try:
        suggestion = _call_gpt_suggest(source_service, source_provider, context_services)
    except Exception as exc:
        err = handle_openai_error(exc, "AI mapping suggestion")
        logger.error("AI suggestion failed for %s: %s", source_service, err)
        return {
            "source_service": source_service,
            "source_provider": source_provider,
            "azure_service": "Unknown",
            "confidence": 0.0,
            "category": "Unknown",
            "notes": f"AI suggestion unavailable: {err}",
            "source": "error",
            "review_status": "failed",
        }

    result = {
        "source_service": source_service,
        "source_provider": source_provider,
        "azure_service": suggestion.get("azure_service", "Unknown"),
        "confidence": min(max(float(suggestion.get("confidence", 0.5)), 0.0), 1.0),
        "category": suggestion.get("category", "Unknown"),
        "notes": suggestion.get("notes", ""),
        "alternatives": suggestion.get("alternatives", []),
        "migration_effort": suggestion.get("migration_effort", "medium"),
        "feature_gaps": suggestion.get("feature_gaps", []),
        "dependencies": suggestion.get("dependencies", []),
        "source": "ai",
        "review_status": "pending" if float(suggestion.get("confidence", 0.5)) < _AUTO_APPROVE_THRESHOLD else "auto_approved",
        # ── Confidence explainability (#353) ──
        "confidence_factors": _build_confidence_factors(suggestion, source_service),
        # ── Deep-dive strengths/limitations/migration notes (#404) ──
        **build_mapping_deep_dive(suggestion, source_service),
    }

    # Queue for review unless auto-approved (confidence >= 0.9)
    if auto_queue_review and result["confidence"] < _AUTO_APPROVE_THRESHOLD:
        _enqueue_review(result)

    return result


def suggest_batch(
    services: List[Dict[str, str]],
    source_provider: str = "aws",
) -> List[Dict[str, Any]]:
    """Suggest mappings for multiple services.

    Parameters
    ----------
    services : list
        Each item: {"name": "ServiceName"} or {"source_service": "ServiceName"}
    source_provider : str
        Source cloud provider.

    Returns
    -------
    list
        List of suggestion dicts.
    """
    all_names = [s.get("name") or s.get("source_service", "") for s in services]
    results = []
    for svc in services:
        name = svc.get("name") or svc.get("source_service", "")
        if not name:
            continue
        context = [n for n in all_names if n != name]
        results.append(suggest_mapping(name, source_provider, context))
    return results


# ─────────────────────────────────────────────────────────
# Dependency graph inference
# ─────────────────────────────────────────────────────────
COMMON_DEPENDENCIES: Dict[str, List[str]] = {
    "Virtual Machines": ["Virtual Network", "Managed Disks", "Network Security Groups"],
    "AKS": ["Virtual Network", "Container Registry", "Azure Monitor"],
    "Azure Functions": ["Storage Account", "Application Insights", "Key Vault"],
    "App Service": ["Application Insights", "Key Vault", "Virtual Network"],
    "SQL Database": ["Virtual Network", "Key Vault", "Azure Monitor"],
    "Cosmos DB": ["Virtual Network", "Key Vault", "Azure Monitor"],
    "API Management": ["Virtual Network", "Application Insights", "Key Vault"],
    "Container Apps": ["Virtual Network", "Container Registry", "Log Analytics"],
    "Azure Front Door": ["Web Application Firewall", "Azure DNS"],
    "Event Hubs": ["Storage Account", "Azure Monitor"],
    "Service Bus": ["Azure Monitor", "Key Vault"],
    "Blob Storage": ["Key Vault", "Azure Monitor", "CDN"],
    "Cache for Redis": ["Virtual Network", "Azure Monitor"],
}


def build_dependency_graph(
    mappings: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build a dependency graph from a list of Azure service mappings.

    Returns
    -------
    dict
        nodes: list of service entries with id, label, category
        edges: list of {source, target, type} dependency links
        missing_dependencies: Azure services implied but not in the mapping set
    """
    nodes = []
    edges = []
    mapped_services = set()

    for i, m in enumerate(mappings):
        azure = m.get("azure_service") or m.get("azure", "")
        if not azure:
            continue
        node_id = f"svc-{i}"
        nodes.append({
            "id": node_id,
            "label": azure,
            "source_service": m.get("source_service", ""),
            "category": m.get("category", ""),
            "confidence": m.get("confidence", 0),
        })
        mapped_services.add(azure)

    # Build edges from common dependencies
    azure_to_id = {n["label"]: n["id"] for n in nodes}
    implied_deps = set()

    for node in nodes:
        deps = COMMON_DEPENDENCIES.get(node["label"], [])
        for dep in deps:
            if dep in azure_to_id:
                edges.append({
                    "source": node["id"],
                    "target": azure_to_id[dep],
                    "type": "depends_on",
                })
            else:
                implied_deps.add(dep)

    return {
        "nodes": nodes,
        "edges": edges,
        "missing_dependencies": sorted(implied_deps - mapped_services),
        "total_services": len(nodes),
        "total_connections": len(edges),
    }


# ─────────────────────────────────────────────────────────
# Admin review queue
# ─────────────────────────────────────────────────────────
def _enqueue_review(suggestion: Dict[str, Any]) -> str:
    """Add a suggestion to the admin review queue."""
    suggestion_id = str(uuid.uuid4())
    with _review_lock:
        _review_queue[suggestion_id] = {
            **suggestion,
            "suggestion_id": suggestion_id,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "reviewed": False,
            "reviewer": None,
            "decision": None,
        }
    logger.info(
        "Queued suggestion %s for review: %s → %s (%.2f)",
        suggestion_id,
        suggestion.get("source_service"),
        suggestion.get("azure_service"),
        suggestion.get("confidence", 0),
    )
    return suggestion_id


def get_review_queue(
    status: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Get pending review items.

    Parameters
    ----------
    status : str, optional
        Filter by review status ("pending", "approved", "rejected").
    limit : int
        Max items to return.
    """
    with _review_lock:
        items = list(_review_queue.values())

    if status == "pending":
        items = [i for i in items if not i.get("reviewed")]
    elif status == "approved":
        items = [i for i in items if i.get("decision") == "approved"]
    elif status == "rejected":
        items = [i for i in items if i.get("decision") == "rejected"]

    # Sort newest first
    items.sort(key=lambda x: x.get("submitted_at", ""), reverse=True)
    return items[:limit]


def review_suggestion(
    suggestion_id: str,
    decision: str,
    reviewer: str,
    override_azure_service: Optional[str] = None,
    override_confidence: Optional[float] = None,
    notes: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Approve or reject a suggestion.

    Parameters
    ----------
    suggestion_id : str
        ID of the suggestion to review.
    decision : str
        "approved" or "rejected".
    reviewer : str
        Reviewer identifier.
    override_azure_service : str, optional
        Override the AI-suggested Azure service.
    override_confidence : float, optional
        Override the confidence score.
    notes : str, optional
        Reviewer notes.

    Returns
    -------
    dict or None
        Updated suggestion, or None if not found.
    """
    with _review_lock:
        suggestion = _review_queue.get(suggestion_id)
        if not suggestion:
            return None

        suggestion["reviewed"] = True
        suggestion["decision"] = decision
        suggestion["reviewer"] = reviewer
        suggestion["reviewed_at"] = datetime.now(timezone.utc).isoformat()

        if override_azure_service:
            suggestion["azure_service"] = override_azure_service
        if override_confidence is not None:
            suggestion["confidence"] = override_confidence
        if notes:
            suggestion["reviewer_notes"] = notes

    # Record feedback for learning
    _record_feedback(suggestion, decision, reviewer)

    logger.info(
        "Suggestion %s %s by %s",
        suggestion_id,
        decision,
        reviewer,
    )
    return suggestion


def get_review_stats() -> Dict[str, Any]:
    """Return review queue statistics with accuracy metrics."""
    with _review_lock:
        items = list(_review_queue.values())

    total = len(items)
    pending = sum(1 for i in items if not i.get("reviewed"))
    approved = sum(1 for i in items if i.get("decision") == "approved")
    rejected = sum(1 for i in items if i.get("decision") == "rejected")
    reviewed = approved + rejected

    avg_confidence = 0.0
    if items:
        avg_confidence = sum(i.get("confidence", 0) for i in items) / len(items)

    approval_rate = round(approved / reviewed, 3) if reviewed > 0 else 0.0

    with _feedback_lock:
        feedback_total = len(_feedback_store)

    return {
        "total": total,
        "pending": pending,
        "approved": approved,
        "rejected": rejected,
        "reviewed": reviewed,
        "approval_rate": approval_rate,
        "avg_confidence": round(avg_confidence, 3),
        "auto_approve_threshold": _AUTO_APPROVE_THRESHOLD,
        "feedback_entries": feedback_total,
    }


def get_suggestion_history(
    limit: int = 100,
    decision_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return history of all suggestions with decisions.

    Parameters
    ----------
    limit : int
        Max items to return.
    decision_filter : str, optional
        Filter by decision ("approved", "rejected", "auto_approved", "pending").
    """
    with _review_lock:
        items = list(_review_queue.values())

    if decision_filter == "auto_approved":
        items = [i for i in items if i.get("review_status") == "auto_approved"]
    elif decision_filter == "approved":
        items = [i for i in items if i.get("decision") == "approved"]
    elif decision_filter == "rejected":
        items = [i for i in items if i.get("decision") == "rejected"]
    elif decision_filter == "pending":
        items = [i for i in items if not i.get("reviewed")]

    items.sort(key=lambda x: x.get("submitted_at", ""), reverse=True)
    return items[:limit]
