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
  "feature_gaps": ["notable gaps between source and target"],
  "dependencies": ["other Azure services typically needed"]
}

Rules:
- confidence must reflect realistic feature parity (0.6-0.95 range usually)
- If no good Azure equivalent exists, set confidence < 0.5 and explain in notes
- Consider the surrounding architecture context when suggesting alternatives
- Return ONLY the JSON object, no markdown fencing
"""


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
        return {
            "source_service": source_service,
            "source_provider": source_provider,
            "azure_service": existing.get("azure", ""),
            "confidence": existing.get("confidence", 0.9),
            "category": existing.get("category", ""),
            "notes": existing.get("notes", ""),
            "source": "catalogue",
            "review_status": "approved",
        }

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
        "review_status": "pending" if suggestion.get("confidence", 0.5) < 0.7 else "auto_approved",
    }

    # Queue low-confidence for review
    if auto_queue_review and result["confidence"] < 0.7:
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

    logger.info(
        "Suggestion %s %s by %s",
        suggestion_id,
        decision,
        reviewer,
    )
    return suggestion


def get_review_stats() -> Dict[str, Any]:
    """Return review queue statistics."""
    with _review_lock:
        items = list(_review_queue.values())

    total = len(items)
    pending = sum(1 for i in items if not i.get("reviewed"))
    approved = sum(1 for i in items if i.get("decision") == "approved")
    rejected = sum(1 for i in items if i.get("decision") == "rejected")

    avg_confidence = 0.0
    if items:
        avg_confidence = sum(i.get("confidence", 0) for i in items) / len(items)

    return {
        "total": total,
        "pending": pending,
        "approved": approved,
        "rejected": rejected,
        "avg_confidence": round(avg_confidence, 3),
    }
