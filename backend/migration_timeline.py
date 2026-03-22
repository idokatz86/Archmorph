"""
Migration Timeline Generator — Issue #231

Auto-generates a phased migration timeline from analysis results with
dependency ordering (topological sort), parallel workstreams, estimated
durations, and risk scoring.

Seven migration phases:
    1. Assessment & Planning
    2. Foundation (networking, identity)
    3. Data Migration (databases, storage)
    4. Compute Migration (VMs, containers, serverless)
    5. Application Migration (app services, APIs)
    6. Cutover & Validation
    7. Optimization & Decommission

Usage::

    from migration_timeline import generate_timeline

    timeline = generate_timeline(analysis)
    md = render_timeline_markdown(timeline)
    csv = render_timeline_csv(timeline)
"""

from __future__ import annotations

import csv
import io
import logging
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Phase definitions
# ─────────────────────────────────────────────────────────────

PHASES = [
    {
        "order": 1,
        "id": "assessment_planning",
        "name": "Assessment & Planning",
        "description": "Inventory existing resources, map dependencies, define migration scope and success criteria.",
    },
    {
        "order": 2,
        "id": "foundation",
        "name": "Foundation",
        "description": "Establish Azure landing zone: networking, identity, security baselines, and monitoring foundations.",
    },
    {
        "order": 3,
        "id": "data_migration",
        "name": "Data Migration",
        "description": "Migrate databases and storage with replication, validation, and minimal-downtime cutover.",
    },
    {
        "order": 4,
        "id": "compute_migration",
        "name": "Compute Migration",
        "description": "Migrate VMs, containers, and serverless workloads to Azure equivalents.",
    },
    {
        "order": 5,
        "id": "application_migration",
        "name": "Application Migration",
        "description": "Migrate application services, APIs, integration layers, and AI/ML workloads.",
    },
    {
        "order": 6,
        "id": "cutover_validation",
        "name": "Cutover & Validation",
        "description": "Switch production traffic, validate end-to-end functionality, and run smoke tests.",
    },
    {
        "order": 7,
        "id": "optimization_decommission",
        "name": "Optimization & Decommission",
        "description": "Right-size resources, enable cost management, set up alerts, decommission source infrastructure.",
    },
]


# ─────────────────────────────────────────────────────────────
# Category → phase mapping
# ─────────────────────────────────────────────────────────────

CATEGORY_TO_PHASE: Dict[str, str] = {
    # Foundation
    "Networking": "foundation",
    "Security": "foundation",
    "Zero Trust": "foundation",
    # Data
    "Database": "data_migration",
    "Storage": "data_migration",
    "Data Governance": "data_migration",
    # Compute
    "Compute": "compute_migration",
    # Application
    "Integration": "application_migration",
    "AI/ML": "application_migration",
    "Analytics": "application_migration",
    "Media": "application_migration",
    "IoT": "application_migration",
    "Business": "application_migration",
    # Observability goes to foundation (monitoring setup early)
    "Observability": "foundation",
    "Management": "foundation",
    "DevTools": "optimization_decommission",
    "Migration": "assessment_planning",
    "Hybrid": "foundation",
    "Edge": "compute_migration",
}

# Fallback phase for unknown categories
DEFAULT_PHASE = "application_migration"


# ─────────────────────────────────────────────────────────────
# Service dependency graph (source services)
# ─────────────────────────────────────────────────────────────
# Key = service, Values = set of services that MUST be migrated first.

SERVICE_DEPENDENCIES: Dict[str, List[str]] = {
    # VMs depend on networking + identity
    "EC2": ["VPC", "IAM"],
    "Compute Engine": ["VPC", "Cloud IAM"],
    # Containers depend on networking
    "ECS": ["VPC", "IAM", "ECR"],
    "EKS": ["VPC", "IAM", "ECR"],
    "Fargate": ["VPC", "IAM"],
    "GKE": ["VPC", "Cloud IAM"],
    # Serverless depends on identity
    "Lambda": ["IAM"],
    "Cloud Functions": ["Cloud IAM"],
    # App services depend on networking + databases
    "Elastic Beanstalk": ["VPC", "RDS"],
    "App Runner": ["IAM"],
    # Databases depend on networking + security
    "RDS": ["VPC", "KMS"],
    "Aurora": ["VPC", "KMS"],
    "DynamoDB": ["IAM", "KMS"],
    "Cloud SQL": ["VPC", "Cloud KMS"],
    "Cloud Spanner": ["Cloud IAM"],
    "DocumentDB": ["VPC", "KMS"],
    "ElastiCache": ["VPC"],
    "Redshift": ["VPC", "KMS"],
    "Neptune": ["VPC"],
    # Storage depends on identity + encryption
    "S3": ["IAM", "KMS"],
    "Cloud Storage": ["Cloud IAM", "Cloud KMS"],
    "EFS": ["VPC"],
    # API layer depends on compute + auth
    "API Gateway": ["Lambda", "IAM", "Cognito"],
    # Messaging depends on identity
    "SQS": ["IAM"],
    "SNS": ["IAM"],
    "Kinesis": ["IAM"],
    "EventBridge": ["IAM"],
    # Monitoring (no hard deps, but logically after infra)
    "CloudWatch": ["IAM"],
    # CDN depends on origin
    "CloudFront": ["S3"],
    # Step Functions depend on targets
    "Step Functions": ["Lambda", "IAM"],
}


# ─────────────────────────────────────────────────────────────
# Complexity → duration mapping (hours)
# ─────────────────────────────────────────────────────────────

COMPLEXITY_DURATION: Dict[str, Dict[str, Any]] = {
    "simple": {"min_hours": 4, "max_hours": 8, "label": "Simple (stateless)"},
    "medium": {"min_hours": 8, "max_hours": 24, "label": "Medium (config-heavy)"},
    "complex": {"min_hours": 24, "max_hours": 80, "label": "Complex (stateful/database)"},
    "critical": {"min_hours": 40, "max_hours": 120, "label": "Critical (custom networking)"},
}

# Category-based complexity classification
CATEGORY_COMPLEXITY: Dict[str, str] = {
    "Storage": "simple",
    "Observability": "simple",
    "Management": "simple",
    "DevTools": "simple",
    "Migration": "simple",
    "Compute": "medium",
    "Integration": "medium",
    "Business": "medium",
    "Media": "medium",
    "Networking": "critical",
    "Security": "complex",
    "Zero Trust": "complex",
    "Database": "complex",
    "Data Governance": "complex",
    "AI/ML": "complex",
    "Analytics": "complex",
    "IoT": "complex",
    "Hybrid": "critical",
    "Edge": "critical",
}

# Per-service overrides
SERVICE_COMPLEXITY_OVERRIDE: Dict[str, str] = {
    "S3": "simple",
    "Cloud Storage": "simple",
    "Route 53": "simple",
    "Cloud DNS": "simple",
    "CloudFront": "simple",
    "SNS": "simple",
    "SES": "simple",
    "CloudWatch": "simple",
    "Managed Grafana": "simple",
    "EC2": "medium",
    "ECS": "medium",
    "EKS": "medium",
    "Fargate": "medium",
    "Lambda": "medium",
    "SQS": "medium",
    "Elastic Beanstalk": "medium",
    "Batch": "medium",
    "RDS": "complex",
    "Aurora": "complex",
    "DynamoDB": "complex",
    "Redshift": "complex",
    "Neptune": "complex",
    "ElastiCache": "complex",
    "Cognito": "complex",
    "IAM": "complex",
    "SageMaker": "complex",
    "VPC": "critical",
    "Direct Connect": "critical",
    "Transit Gateway": "critical",
    "Outposts": "critical",
    "IoT Core": "complex",
}

# Services considered high-risk
HIGH_RISK_SERVICES = {
    "RDS", "Aurora", "DynamoDB", "DocumentDB", "Redshift", "Neptune",
    "ElastiCache", "Cloud SQL", "Cloud Spanner", "Firestore", "BigQuery",
    "VPC", "Direct Connect", "Transit Gateway", "Outposts",
    "IAM", "Cognito", "KMS",
    "SageMaker", "IoT Core", "IoT Greengrass",
}


# ─────────────────────────────────────────────────────────────
# Core timeline generation
# ─────────────────────────────────────────────────────────────

def _classify_complexity(source_service: str, category: str) -> str:
    """Return complexity tier for a service."""
    if source_service in SERVICE_COMPLEXITY_OVERRIDE:
        return SERVICE_COMPLEXITY_OVERRIDE[source_service]
    return CATEGORY_COMPLEXITY.get(category, "medium")


def _estimate_hours(complexity: str) -> Dict[str, int]:
    """Return min/max hours for a complexity tier."""
    spec = COMPLEXITY_DURATION.get(complexity, COMPLEXITY_DURATION["medium"])
    return {"min_hours": spec["min_hours"], "max_hours": spec["max_hours"]}


def _build_dependency_order(services: List[str]) -> List[str]:
    """Topologically sort services based on SERVICE_DEPENDENCIES.

    Only considers dependencies that are present in the services list.
    Services without dependencies come first. Falls back to stable
    insertion order on cycles (Kahn's algorithm drops cycle members
    to the end rather than failing).
    """
    service_set = set(services)

    # Build adjacency list (only edges where both nodes are in the set)
    in_degree: Dict[str, int] = {s: 0 for s in services}
    adj: Dict[str, List[str]] = defaultdict(list)

    for svc in services:
        deps = SERVICE_DEPENDENCIES.get(svc, [])
        for dep in deps:
            if dep in service_set:
                adj[dep].append(svc)
                in_degree[svc] += 1

    # Kahn's algorithm
    queue: deque[str] = deque(s for s in services if in_degree[s] == 0)
    result: List[str] = []

    while queue:
        node = queue.popleft()
        result.append(node)
        for neighbor in adj[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # Append any remaining (cycle members) in original order
    remaining = [s for s in services if s not in set(result)]
    result.extend(remaining)

    return result


def _identify_parallel_groups(
    phase_services: List[Dict[str, Any]],
) -> List[List[Dict[str, Any]]]:
    """Group services within a phase into parallel workstreams.

    Two services can run in parallel if neither depends on the other.
    Uses a greedy algorithm: walk the topologically sorted list and
    start a new group whenever a dependency on a previous-group
    service is encountered.
    """
    if not phase_services:
        return []

    service_names = [s["source_service"] for s in phase_services]
    service_set = set(service_names)
    name_to_entry = {s["source_service"]: s for s in phase_services}

    groups: List[List[Dict[str, Any]]] = []
    current_group: List[Dict[str, Any]] = []
    placed: set = set()

    for svc_name in service_names:
        deps = SERVICE_DEPENDENCIES.get(svc_name, [])
        relevant_deps = [d for d in deps if d in service_set]

        # If this service depends on something in the CURRENT group, start new group
        if any(d in {s["source_service"] for s in current_group} for d in relevant_deps):
            if current_group:
                groups.append(current_group)
            current_group = [name_to_entry[svc_name]]
        else:
            current_group.append(name_to_entry[svc_name])

        placed.add(svc_name)

    if current_group:
        groups.append(current_group)

    return groups


def generate_timeline(
    analysis: Dict[str, Any],
    project_name: Optional[str] = None,
    hours_per_day: int = 8,
) -> Dict[str, Any]:
    """Generate a phased migration timeline from analysis results.

    Args:
        analysis: Analysis dict with ``mappings`` list.
        project_name: Optional project name for the timeline title.
        hours_per_day: Working hours per day (default 8).

    Returns:
        Full timeline dict ready for JSON serialization.
    """
    mappings = analysis.get("mappings", [])
    source_cloud = analysis.get("source_cloud", "AWS")
    timeline_id = f"tl-{uuid.uuid4().hex[:8]}"

    # ── Build per-service entries ──
    service_entries: List[Dict[str, Any]] = []
    for m in mappings:
        source = m.get("source_service", m.get("aws", ""))
        azure = m.get("azure_service", m.get("azure", ""))
        category = m.get("category", "Unknown")
        confidence = m.get("confidence", 0.85)

        complexity = _classify_complexity(source, category)
        hours = _estimate_hours(complexity)
        phase_id = CATEGORY_TO_PHASE.get(category, DEFAULT_PHASE)
        is_high_risk = source in HIGH_RISK_SERVICES

        service_entries.append({
            "source_service": source,
            "azure_service": azure,
            "category": category,
            "confidence": confidence,
            "complexity": complexity,
            "estimated_hours": hours,
            "phase_id": phase_id,
            "high_risk": is_high_risk,
            "dependencies": [
                d for d in SERVICE_DEPENDENCIES.get(source, [])
                if d in {e.get("source_service", e.get("aws", "")) for e in mappings}
            ],
        })

    # ── Assign services to phases & sort within each phase ──
    phase_buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for entry in service_entries:
        phase_buckets[entry["phase_id"]].append(entry)

    # Topologically sort services within each phase
    for phase_id, entries in phase_buckets.items():
        names = [e["source_service"] for e in entries]
        sorted_names = _build_dependency_order(names)
        name_to_entry = {e["source_service"]: e for e in entries}
        phase_buckets[phase_id] = [name_to_entry[n] for n in sorted_names]

    # ── Build phase objects ──
    phases: List[Dict[str, Any]] = []
    total_min_hours = 0
    total_max_hours = 0
    total_high_risk = 0

    for phase_def in PHASES:
        pid = phase_def["id"]
        entries = phase_buckets.get(pid, [])

        # Assessment & Cutover & Optimization always have baseline hours
        baseline_hours = {"min_hours": 0, "max_hours": 0}
        if pid == "assessment_planning":
            baseline_hours = {"min_hours": 16, "max_hours": 40}
        elif pid == "cutover_validation":
            baseline_hours = {"min_hours": 8, "max_hours": 24}
        elif pid == "optimization_decommission":
            baseline_hours = {"min_hours": 8, "max_hours": 24}

        phase_min = baseline_hours["min_hours"] + sum(
            e["estimated_hours"]["min_hours"] for e in entries
        )
        phase_max = baseline_hours["max_hours"] + sum(
            e["estimated_hours"]["max_hours"] for e in entries
        )
        phase_risk_count = sum(1 for e in entries if e["high_risk"])

        parallel_groups = _identify_parallel_groups(entries)

        phases.append({
            "order": phase_def["order"],
            "id": pid,
            "name": phase_def["name"],
            "description": phase_def["description"],
            "services": entries,
            "service_count": len(entries),
            "parallel_workstreams": parallel_groups,
            "workstream_count": len(parallel_groups),
            "estimated_hours": {"min": phase_min, "max": phase_max},
            "estimated_days": {
                "min": max(1, round(phase_min / hours_per_day)),
                "max": max(1, round(phase_max / hours_per_day)),
            },
            "high_risk_count": phase_risk_count,
        })

        total_min_hours += phase_min
        total_max_hours += phase_max
        total_high_risk += phase_risk_count

    # ── Summary ──
    complexity_dist = defaultdict(int)
    for e in service_entries:
        complexity_dist[e["complexity"]] += 1

    risk_level = "low"
    if total_high_risk >= 5:
        risk_level = "critical"
    elif total_high_risk >= 3:
        risk_level = "high"
    elif total_high_risk >= 1:
        risk_level = "medium"

    timeline = {
        "id": timeline_id,
        "title": project_name or f"{source_cloud} to Azure Migration Timeline",
        "source_cloud": source_cloud,
        "target_cloud": "Azure",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "total_services": len(service_entries),
        "total_phases": len(PHASES),
        "estimated_hours": {"min": total_min_hours, "max": total_max_hours},
        "estimated_days": {
            "min": max(1, round(total_min_hours / hours_per_day)),
            "max": max(1, round(total_max_hours / hours_per_day)),
        },
        "risk_level": risk_level,
        "high_risk_services": total_high_risk,
        "complexity_distribution": dict(complexity_dist),
        "phases": phases,
    }

    logger.info(
        "Generated timeline %s: %d services, %d phases, %d-%d hours",
        timeline_id,
        len(service_entries),
        len(PHASES),
        total_min_hours,
        total_max_hours,
    )

    return timeline


# ─────────────────────────────────────────────────────────────
# Export: Markdown
# ─────────────────────────────────────────────────────────────

def render_timeline_markdown(timeline: Dict[str, Any]) -> str:
    """Render the timeline as a human-readable Markdown document."""
    lines: List[str] = []
    est = timeline["estimated_hours"]
    days = timeline["estimated_days"]

    lines.append(f"# {timeline['title']}")
    lines.append("")
    lines.append(f"**Timeline ID:** {timeline['id']}")
    lines.append(f"**Source Cloud:** {timeline['source_cloud']}")
    lines.append(f"**Target Cloud:** {timeline['target_cloud']}")
    lines.append(f"**Total Services:** {timeline['total_services']}")
    lines.append(f"**Estimated Duration:** {days['min']}-{days['max']} working days ({est['min']}-{est['max']} hours)")
    lines.append(f"**Risk Level:** {timeline['risk_level'].upper()}")
    lines.append(f"**Generated:** {timeline['created_at'][:10]}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Phase summary table
    lines.append("## Phase Summary")
    lines.append("")
    lines.append("| # | Phase | Services | Hours (min-max) | Days (min-max) | Workstreams | High Risk |")
    lines.append("|---|-------|----------|-----------------|----------------|-------------|-----------|")

    for phase in timeline["phases"]:
        h = phase["estimated_hours"]
        d = phase["estimated_days"]
        lines.append(
            f"| {phase['order']} | {phase['name']} | {phase['service_count']} "
            f"| {h['min']}-{h['max']}h | {d['min']}-{d['max']}d "
            f"| {phase['workstream_count']} | {phase['high_risk_count']} |"
        )

    lines.append("")
    lines.append("---")
    lines.append("")

    # Detailed phases
    for phase in timeline["phases"]:
        lines.append(f"## Phase {phase['order']}: {phase['name']}")
        lines.append("")
        lines.append(f"_{phase['description']}_")
        lines.append("")
        h = phase["estimated_hours"]
        d = phase["estimated_days"]
        lines.append(f"**Duration:** {d['min']}-{d['max']} days ({h['min']}-{h['max']} hours)")
        lines.append("")

        if not phase["services"]:
            lines.append("_No specific services in this phase (baseline tasks only)._")
            lines.append("")
            continue

        # Workstreams
        for ws_idx, workstream in enumerate(phase["parallel_workstreams"], 1):
            if phase["workstream_count"] > 1:
                lines.append(f"### Workstream {ws_idx} (parallel)")
                lines.append("")

            for svc in workstream:
                risk_flag = " :warning:" if svc["high_risk"] else ""
                lines.append(f"- **{svc['source_service']}** → {svc['azure_service']}{risk_flag}")
                lines.append(f"  - Complexity: {svc['complexity']}")
                lines.append(f"  - Estimated: {svc['estimated_hours']['min_hours']}-{svc['estimated_hours']['max_hours']}h")
                if svc["dependencies"]:
                    lines.append(f"  - Depends on: {', '.join(svc['dependencies'])}")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Export: CSV
# ─────────────────────────────────────────────────────────────

def render_timeline_csv(timeline: Dict[str, Any]) -> str:
    """Render the timeline as CSV for project management import."""
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Phase #",
        "Phase",
        "Source Service",
        "Azure Service",
        "Category",
        "Complexity",
        "Min Hours",
        "Max Hours",
        "High Risk",
        "Dependencies",
        "Workstream",
    ])

    for phase in timeline["phases"]:
        if not phase["services"]:
            # Write a row for the phase baseline
            writer.writerow([
                phase["order"],
                phase["name"],
                "",
                "",
                "",
                "",
                phase["estimated_hours"]["min"],
                phase["estimated_hours"]["max"],
                "",
                "",
                "",
            ])
            continue

        for ws_idx, workstream in enumerate(phase["parallel_workstreams"], 1):
            for svc in workstream:
                writer.writerow([
                    phase["order"],
                    phase["name"],
                    svc["source_service"],
                    svc["azure_service"],
                    svc["category"],
                    svc["complexity"],
                    svc["estimated_hours"]["min_hours"],
                    svc["estimated_hours"]["max_hours"],
                    "Yes" if svc["high_risk"] else "No",
                    "; ".join(svc["dependencies"]),
                    ws_idx,
                ])

    return output.getvalue()
