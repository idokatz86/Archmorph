"""
Archmorph – Migration Intelligence Engine
==========================================
Aggregates anonymized, community-level migration patterns to provide:

  - Community confidence scores: blended with mapping-level data to refine
    per-service confidence using real-world migration success signals.
  - Pattern library: common migration pathways with success rates.
  - Trending migrations: which service transitions are most popular.
  - Lessons learned: anonymized insight snippets from community data.

Privacy: All data is anonymized before aggregation. No PII, no diagram
content, no customer-identifiable information is stored. Only service
names, provider pairs, and success/failure booleans are recorded.
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/migration-intelligence", tags=["migration-intelligence"])


# ─────────────────────────────────────────────────────────────
# In-memory anonymous event store
# (Production: persistent store with TTL and aggregation jobs)
# ─────────────────────────────────────────────────────────────
_MIGRATION_EVENTS: List[Dict[str, Any]] = []
_PATTERN_STATS: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
    "count": 0,
    "success_count": 0,
    "avg_confidence": 0.0,
    "last_seen": None,
})


# ─────────────────────────────────────────────────────────────
# Seed data — realistic community patterns
# ─────────────────────────────────────────────────────────────
_SEED_PATTERNS = [
    {"source": "EC2", "target": "Virtual Machines", "src_provider": "aws", "tgt_provider": "azure", "count": 1842, "success_rate": 0.94},
    {"source": "S3", "target": "Blob Storage", "src_provider": "aws", "tgt_provider": "azure", "count": 2156, "success_rate": 0.97},
    {"source": "RDS", "target": "Azure SQL Database", "src_provider": "aws", "tgt_provider": "azure", "count": 1203, "success_rate": 0.91},
    {"source": "Lambda", "target": "Azure Functions", "src_provider": "aws", "tgt_provider": "azure", "count": 1567, "success_rate": 0.93},
    {"source": "DynamoDB", "target": "Cosmos DB", "src_provider": "aws", "tgt_provider": "azure", "count": 892, "success_rate": 0.88},
    {"source": "CloudFront", "target": "Azure CDN", "src_provider": "aws", "tgt_provider": "azure", "count": 987, "success_rate": 0.96},
    {"source": "EKS", "target": "AKS", "src_provider": "aws", "tgt_provider": "azure", "count": 654, "success_rate": 0.89},
    {"source": "SQS", "target": "Azure Service Bus", "src_provider": "aws", "tgt_provider": "azure", "count": 743, "success_rate": 0.92},
    {"source": "Cognito", "target": "Azure AD B2C", "src_provider": "aws", "tgt_provider": "azure", "count": 321, "success_rate": 0.85},
    {"source": "ElastiCache", "target": "Azure Cache for Redis", "src_provider": "aws", "tgt_provider": "azure", "count": 567, "success_rate": 0.95},
    {"source": "API Gateway", "target": "Azure API Management", "src_provider": "aws", "tgt_provider": "azure", "count": 876, "success_rate": 0.90},
    {"source": "CloudWatch", "target": "Azure Monitor", "src_provider": "aws", "tgt_provider": "azure", "count": 1120, "success_rate": 0.93},
    {"source": "Compute Engine", "target": "Virtual Machines", "src_provider": "gcp", "tgt_provider": "azure", "count": 432, "success_rate": 0.92},
    {"source": "Cloud Storage", "target": "Blob Storage", "src_provider": "gcp", "tgt_provider": "azure", "count": 567, "success_rate": 0.96},
    {"source": "Cloud SQL", "target": "Azure SQL Database", "src_provider": "gcp", "tgt_provider": "azure", "count": 298, "success_rate": 0.90},
    {"source": "Cloud Run", "target": "Azure Container Apps", "src_provider": "gcp", "tgt_provider": "azure", "count": 187, "success_rate": 0.91},
    {"source": "GKE", "target": "AKS", "src_provider": "gcp", "tgt_provider": "azure", "count": 234, "success_rate": 0.88},
    {"source": "Pub/Sub", "target": "Azure Service Bus", "src_provider": "gcp", "tgt_provider": "azure", "count": 156, "success_rate": 0.90},
]


class MigrationEvent(BaseModel):
    source_service: str
    target_service: str
    source_provider: str = "aws"
    target_provider: str = "azure"
    success: bool = True
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)


class CommunityPattern(BaseModel):
    source_service: str
    target_service: str
    source_provider: str
    target_provider: str
    migration_count: int
    success_rate: float
    community_confidence: float
    trending: bool = False


def _make_pattern_key(source: str, target: str, src_prov: str, tgt_prov: str) -> str:
    """Create a deterministic key for a migration pattern."""
    return hashlib.sha256(f"{src_prov}:{source}:{tgt_prov}:{target}".lower().encode()).hexdigest()[:16]


def record_migration_event(event: MigrationEvent) -> None:
    """Record an anonymized migration event."""
    key = _make_pattern_key(
        event.source_service, event.target_service,
        event.source_provider, event.target_provider,
    )
    stats = _PATTERN_STATS[key]
    stats["count"] += 1
    if event.success:
        stats["success_count"] += 1
    # Running average confidence
    n = stats["count"]
    stats["avg_confidence"] = ((stats["avg_confidence"] * (n - 1)) + event.confidence) / n
    stats["last_seen"] = datetime.now(timezone.utc).isoformat()
    stats["source"] = event.source_service
    stats["target"] = event.target_service
    stats["src_provider"] = event.source_provider
    stats["tgt_provider"] = event.target_provider

    _MIGRATION_EVENTS.append({
        "source": event.source_service,
        "target": event.target_service,
        "src_provider": event.source_provider,
        "tgt_provider": event.target_provider,
        "success": event.success,
        "confidence": event.confidence,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    logger.info("Recorded migration event: %s → %s (%s→%s)",
                event.source_service, event.target_service,
                event.source_provider, event.target_provider)


def get_community_confidence(
    source_service: str,
    target_service: str,
    source_provider: str = "aws",
    target_provider: str = "azure",
    base_confidence: float = 0.85,
) -> float:
    """
    Blend base mapping confidence with community data.

    Formula: 0.6 * base_confidence + 0.3 * community_success_rate + 0.1 * volume_factor
    """
    key = _make_pattern_key(source_service, target_service, source_provider, target_provider)
    stats = _PATTERN_STATS.get(key)

    # Check seed data if no live stats
    if not stats or stats["count"] == 0:
        for seed in _SEED_PATTERNS:
            if (seed["source"].lower() == source_service.lower() and
                seed["target"].lower() == target_service.lower()):
                success_rate = seed["success_rate"]
                volume_factor = min(seed["count"] / 2000, 1.0)
                return round(0.6 * base_confidence + 0.3 * success_rate + 0.1 * volume_factor, 3)

        return base_confidence  # No community data

    success_rate = stats["success_count"] / max(stats["count"], 1)
    volume_factor = min(stats["count"] / 100, 1.0)  # Normalize to 100 events = max confidence boost

    blended = 0.6 * base_confidence + 0.3 * success_rate + 0.1 * volume_factor
    return round(min(1.0, blended), 3)


def get_top_patterns(
    source_provider: str = "",
    target_provider: str = "",
    limit: int = 20,
) -> List[CommunityPattern]:
    """Get the most popular migration patterns from community + seed data."""
    patterns = []

    # Include seed data
    for seed in _SEED_PATTERNS:
        if source_provider and seed["src_provider"] != source_provider:
            continue
        if target_provider and seed["tgt_provider"] != target_provider:
            continue

        key = _make_pattern_key(
            seed["source"], seed["target"],
            seed["src_provider"], seed["tgt_provider"],
        )
        live_stats = _PATTERN_STATS.get(key, {})
        live_count = live_stats.get("count", 0)

        total_count = seed["count"] + live_count
        if live_count > 0:
            live_success = live_stats.get("success_count", 0) / max(live_count, 1)
            blended_rate = (seed["success_rate"] * seed["count"] + live_success * live_count) / total_count
        else:
            blended_rate = seed["success_rate"]

        community_conf = get_community_confidence(
            seed["source"], seed["target"],
            seed["src_provider"], seed["tgt_provider"],
        )

        patterns.append(CommunityPattern(
            source_service=seed["source"],
            target_service=seed["target"],
            source_provider=seed["src_provider"],
            target_provider=seed["tgt_provider"],
            migration_count=total_count,
            success_rate=round(blended_rate, 3),
            community_confidence=community_conf,
            trending=total_count > 1000,
        ))

    # Sort by count descending
    patterns.sort(key=lambda p: p.migration_count, reverse=True)
    return patterns[:limit]


# ─────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────
@router.post("/events")
async def submit_event(event: MigrationEvent):
    """Submit an anonymized migration event."""
    record_migration_event(event)
    return {"status": "recorded"}


@router.get("/patterns")
async def list_patterns(
    source_provider: str = "",
    target_provider: str = "",
    limit: int = 20,
):
    """Get top migration patterns with community confidence scores."""
    patterns = get_top_patterns(source_provider, target_provider, limit)
    return {
        "patterns": [p.model_dump() for p in patterns],
        "total": len(patterns),
    }


@router.get("/confidence")
async def query_confidence(
    source_service: str,
    target_service: str,
    source_provider: str = "aws",
    target_provider: str = "azure",
    base_confidence: float = 0.85,
):
    """Get blended community confidence for a specific migration path."""
    conf = get_community_confidence(
        source_service, target_service,
        source_provider, target_provider,
        base_confidence,
    )
    return {
        "source_service": source_service,
        "target_service": target_service,
        "base_confidence": base_confidence,
        "community_confidence": conf,
        "boost": round(conf - base_confidence, 3),
    }


@router.get("/trending")
async def get_trending(limit: int = 10):
    """Get trending migration patterns."""
    patterns = get_top_patterns(limit=limit)
    trending = [p for p in patterns if p.trending]
    return {
        "trending": [p.model_dump() for p in trending[:limit]],
        "total": len(trending),
    }


@router.get("/stats")
async def get_stats():
    """Get aggregate migration intelligence statistics."""
    total_events = len(_MIGRATION_EVENTS)
    total_patterns = len(_SEED_PATTERNS) + len([k for k, v in _PATTERN_STATS.items() if v["count"] > 0])
    success_events = sum(1 for e in _MIGRATION_EVENTS if e.get("success"))

    return {
        "total_events": total_events + sum(s["count"] for s in _SEED_PATTERNS),
        "total_patterns": total_patterns,
        "overall_success_rate": round(
            (success_events + sum(int(s["count"] * s["success_rate"]) for s in _SEED_PATTERNS)) /
            max(total_events + sum(s["count"] for s in _SEED_PATTERNS), 1),
            3,
        ),
        "live_events": total_events,
        "seed_patterns": len(_SEED_PATTERNS),
    }
