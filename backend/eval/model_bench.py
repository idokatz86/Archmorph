"""Foundry model evaluation harness (#602, refreshed for #781).

Bench candidate Azure Foundry models against the six Archmorph workloads,
collect accuracy / latency / cost / refusal metrics, and emit a JSON report
that the human-readable analysis at `docs/eval/model_bench_2026_05.md`
references.

Issue #781 extends the original spike with a deployment-aware benchmark plan:
compare the current West Europe `gpt-4.1` primary and `gpt-4o` fallback
against deployable Foundry candidates, record regional availability, and keep
production routing unchanged until live evidence clears quality, cost,
latency, throttling, safety, structured-output, and rollback gates.

Design constraints
------------------
1. **Zero impact on production code path.** Nothing in `app.py` or any
   router imports `backend.eval.*`. The harness re-uses
   `backend.openai_client.cached_chat_completion` only as a *consumer* —
   no monkey-patching of production state.
2. **Runnable offline.** With `--dry-run`, the harness uses pre-recorded
   synthetic candidate outputs (`SYNTHETIC_RESPONSES` below) and
   pre-recorded synthetic judge scores so unit tests do not need Foundry
   credentials.
3. **Deterministic where possible.** Each task carries a stable `task_id`
   so results JSON is diffable across re-runs of the same model+task.
4. **Synthetic fixtures by design.** Issue #600 (golden PDFs) is legal-gated
   and lives in Sprint 2. Per the #602 issue body's escape hatch — "If
   legal blocks redaction, build synthetic equivalent" — the bench ships
   synthetic task corpora that exercise the same shape as the eventual
   golden set. When #600 lands, swap `_load_corpus()` to read from
   `backend/tests/fixtures/golden_pdfs/` instead.
5. **No production state mutation.** Calls go through
   `cached_chat_completion(..., bypass_cache=True)` so we don't pollute
   the production response cache.

Usage
-----

    # Offline / synthetic mode (no Foundry calls, deterministic, ~1s):
    python -m backend.eval.model_bench --dry-run \\
        --output backend/eval/results/bench_dry.json

    # Live mode against Foundry (requires AZURE_OPENAI_* env vars + quota):
    python -m backend.eval.model_bench \\
        --workloads vision_analyzer,iac_generator \\
        --models gpt-4.1,gpt-5.4,gpt-5.5 \\
        --output backend/eval/results/bench_$(date +%Y%m%d).json

    # Full sweep (matches the matrix in #602 acceptance criteria):
    python -m backend.eval.model_bench --full \\
        --output docs/eval/data/model_bench_2026_05.json

The harness is intentionally small (~400 LOC). It is scaffolding, not a
framework — for a heavier eval need, swap in `promptfoo` or
`evalverse`. We chose a hand-rolled harness for spike velocity: there
is exactly one consumer (`docs/eval/model_bench_2026_05.md`) and we
need full control over the synthetic-fixture path.
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────────────
# Workload + model matrix (matches #602 acceptance criteria, May 2026)
# ───────────────────────────────────────────────────────────────────

# Per-workload candidate set. Keep strictly aligned with #602 — adding
# models here without updating the issue body breaks downstream #603.
WORKLOAD_CANDIDATES: Dict[str, List[str]] = {
    "vision_analyzer":      ["gpt-4.1", "gpt-5.4",       "gpt-5.5",                "mistral-document-ai-2512"],
    "iac_generator":        ["gpt-4.1", "gpt-5.4",       "gpt-5.3-codex"],
    "hld_generator":        ["gpt-4.1", "gpt-5.4"],
    "mapping_suggester":    ["gpt-4.1", "gpt-5.4-mini"],
    "agent_paas_react":     ["gpt-4.1", "gpt-5.4-mini"],
    "retention_anonymizer": ["gpt-4o",  "gpt-5.4-nano"],
}

# Indicative Foundry pricing per 1M tokens (in/out USD), May 2026 catalog.
# Source: Microsoft Learn / Foundry pricing portal snapshot taken
# 2026-05-01. Updated monthly — re-run with `--refresh-pricing` once that
# tool exists.
PRICING_PER_1M_TOKENS_USD: Dict[str, Tuple[float, float]] = {
    "gpt-4.1":                  (2.50, 10.00),
    "gpt-4o":                   (2.50, 10.00),
    "gpt-5.4":                  (3.00, 12.00),
    "gpt-5.4-mini":             (0.30,  1.20),
    "gpt-5.4-nano":             (0.10,  0.40),
    "gpt-5.3-codex":            (3.00, 12.00),
    "gpt-5.5":                  (5.00, 20.00),
    "mistral-document-ai-2512": (1.00,  4.00),
    # Judge model — not a candidate, only used by the rubric
    "gpt-5-pro":                (10.00, 40.00),
}

JUDGE_MODEL = "gpt-5-pro"


# ───────────────────────────────────────────────────────────────────
# #781 deployment-aware benchmark plan metadata
# ───────────────────────────────────────────────────────────────────

CURRENT_FOUNDRY_ACCOUNT = {
    "subscription_id": "152f2bd5-8f6b-48ba-a702-21a23172a224",
    "tenant_id": "16b3c013-d300-468d-ac64-7eda0820b6d3",
    "resource_group": "archmorph-rg-dev",
    "account_name": "archmorph-openai-we-acm7pd",
    "region": "westeurope",
    "resource_id": "/subscriptions/152f2bd5-8f6b-48ba-a702-21a23172a224/resourceGroups/archmorph-rg-dev/providers/Microsoft.CognitiveServices/accounts/archmorph-openai-we-acm7pd",
}

CURRENT_DEPLOYMENTS = {
    "primary": {
        "deployment": "gpt-4.1",
        "model": "gpt-4.1",
        "version": "2025-04-14",
        "sku": "GlobalStandard",
        "capacity": 10,
        "rai_policy": "Microsoft.DefaultV2",
    },
    "fallback": {
        "deployment": "gpt-4o",
        "model": "gpt-4o",
        "version": "2024-11-20",
        "sku": "GlobalStandard",
        "capacity": 10,
        "rai_policy": "Microsoft.DefaultV2",
    },
}

AUTH_REQUIREMENTS = {
    "local_auth_enabled": False,
    "runtime_identity": "Container App user-assigned managed identity with system-assigned fallback",
    "required_role": "Cognitive Services OpenAI User",
    "forbidden": ["API-key based benchmark routing", "committing secrets", "production deployment mutation"],
}

REGIONAL_AVAILABILITY = {
    "westeurope": {
        "source": "az cognitiveservices account list-models on archmorph-openai-we-acm7pd, 2026-05-07",
        "current_deployments": ["gpt-4.1", "gpt-4o"],
        "deployable_candidates": {
            "gpt-4.1": "baseline primary, GlobalStandard, version 2025-04-14",
            "gpt-4o": "baseline fallback, GlobalStandard deployable versions include 2024-05-13/2024-08-06 and current deployment 2024-11-20",
            "gpt-4o-mini": "GlobalStandard, version 2024-07-18",
            "gpt-4.1-mini": "Standard, version 2025-04-14",
            "gpt-4.1-nano": "GlobalStandard, version 2025-04-14",
            "o4-mini": "GlobalStandard, version 2025-04-16",
            "gpt-5": "GlobalStandard, version 2025-08-07",
            "gpt-5-mini": "GlobalStandard, version 2025-08-07",
            "gpt-5-nano": "GlobalStandard, version 2025-08-07",
            "gpt-5-codex": "GlobalStandard, version 2025-09-15",
            "gpt-5-pro": "GlobalStandard, version 2025-10-06",
            "gpt-5.3-codex": "GlobalStandard, version 2026-02-24",
            "gpt-5.4": "GlobalStandard, version 2026-03-05",
            "gpt-5.4-mini": "GlobalStandard, version 2026-03-17",
            "gpt-5.4-nano": "GlobalStandard, version 2026-03-17",
            "gpt-5.5": "GlobalProvisionedManaged, version 2026-04-24; benchmark only after capacity approval",
        },
        "quota_notes": "Usage CLI returned no rows in this environment; live run must capture TPM/RPM and throttling before any routed deployment.",
    },
    "swedencentral": {
        "source": "subscription resource inventory found AIServices account agentsecysbz; list-models query was interrupted after hanging, 2026-05-07",
        "current_deployments": [],
        "deployable_candidates": {},
        "quota_notes": "Treat as migration-region validation pending. Do not route Archmorph traffic here until account model list, quota, RBAC, and rollback drills are captured.",
    },
}

BENCHMARK_LANES = {
    "diagram_image_understanding": {
        "workload": "vision_analyzer",
        "baseline": ["gpt-4.1", "gpt-4o"],
        "candidates": ["gpt-5.4", "gpt-5.5"],
        "dataset": "synthetic architecture diagrams plus the legal-approved golden PDF corpus when available",
        "quality_gates": ["service inventory F1", "relationship edge F1", "JSON schema validity", "image/PDF refusal rate"],
    },
    "cloud_service_mapping": {
        "workload": "mapping_suggester",
        "baseline": ["gpt-4.1", "gpt-4o"],
        "candidates": ["gpt-4.1-mini", "gpt-4o-mini", "gpt-5.4-mini"],
        "dataset": "AWS/GCP/on-prem service mapping prompts with catalog references",
        "quality_gates": ["primary mapping accuracy", "confidence calibration", "rationale safety", "JSON schema validity"],
    },
    "iac_generation_repair": {
        "workload": "iac_generator",
        "baseline": ["gpt-4.1", "gpt-4o"],
        "candidates": ["gpt-5.3-codex", "gpt-5-codex", "gpt-5.4"],
        "dataset": "Terraform/Bicep generation and repair prompts from canonical starter architectures",
        "quality_gates": ["terraform fmt/validate", "bicep diagnostics", "least-privilege defaults", "no secret leakage"],
    },
    "hld_architecture_narrative": {
        "workload": "hld_generator",
        "baseline": ["gpt-4.1", "gpt-4o"],
        "candidates": ["gpt-5.4", "gpt-5", "gpt-5-mini"],
        "dataset": "HLD prompts with expected sections, risks, service map, and cost context",
        "quality_gates": ["required section coverage", "migration-risk accuracy", "concise executive narrative", "policy-safe recommendations"],
    },
    "cost_explanation": {
        "workload": "cost_explainer",
        "baseline": ["gpt-4.1", "gpt-4o"],
        "candidates": ["gpt-4.1-mini", "gpt-4o-mini", "gpt-5.4-mini"],
        "dataset": "Azure retail-price summaries and FinOps trade-off prompts",
        "quality_gates": ["numeric consistency", "SKU caveat accuracy", "unit-cost clarity", "no fabricated prices"],
    },
    "regression_judge": {
        "workload": "eval_judge",
        "baseline": ["gpt-4o", "gpt-4.1"],
        "candidates": ["gpt-5-pro", "gpt-5.4", "o4-mini"],
        "dataset": "known-pass/known-fail regression answers for quality, schema, safety, and concision rubrics",
        "quality_gates": ["grader agreement", "false-pass rate", "false-fail rate", "stable JSON scores"],
    },
    "chat_refinement_assistant": {
        "workload": "agent_paas_react",
        "baseline": ["gpt-4.1", "gpt-4o"],
        "candidates": ["gpt-5.4-mini", "gpt-5-mini", "o4-mini"],
        "dataset": "multi-turn refinement prompts with tool-call expectations and customer constraints",
        "quality_gates": ["tool-call accuracy", "constraint retention", "latency p95", "safe refusal behavior"],
    },
}

RECOMMENDATION_MATRIX = [
    {
        "lane": "diagram_image_understanding",
        "candidate": "gpt-5.4",
        "decision": "defer",
        "reason": "Potential quality candidate, but requires live image/PDF benchmark and quota proof before routed model deployment.",
    },
    {
        "lane": "cloud_service_mapping",
        "candidate": "gpt-5.4-mini",
        "decision": "add_routed_model_candidate",
        "reason": "Low-risk structured mapping lane; benchmark for cost and p95 latency savings before any feature-flagged route.",
    },
    {
        "lane": "iac_generation_repair",
        "candidate": "gpt-5.3-codex",
        "decision": "add_routed_model_candidate",
        "reason": "Codex-specialized deployable candidate; must pass IaC validation and security gates before canary.",
    },
    {
        "lane": "hld_architecture_narrative",
        "candidate": "gpt-5.4",
        "decision": "defer",
        "reason": "Narrative quality may improve, but current baseline remains until live report shows better section coverage without verbosity regressions.",
    },
    {
        "lane": "cost_explanation",
        "candidate": "gpt-5.4-mini",
        "decision": "add_routed_model_candidate",
        "reason": "Candidate for cheaper explanation prompts if numeric consistency and no fabricated pricing hold in the benchmark.",
    },
    {
        "lane": "regression_judge",
        "candidate": "gpt-5-pro",
        "decision": "defer",
        "reason": "Use only as an offline judge candidate until cost and evaluator agreement justify continuous use.",
    },
    {
        "lane": "chat_refinement_assistant",
        "candidate": "gpt-5.4-mini",
        "decision": "defer",
        "reason": "Multi-turn tool use needs stronger evidence on tool-call accuracy and constraint retention before routing.",
    },
]

DECISION_RULE = (
    "Keep current gpt-4.1/gpt-4o unless a candidate improves quality or cost "
    "without breaking structured output, export artifacts, safety gates, quota headroom, or SLA."
)


# ───────────────────────────────────────────────────────────────────
# Result dataclasses (these define the on-disk JSON schema)
# ───────────────────────────────────────────────────────────────────


@dataclass
class TaskResult:
    """Single (workload, task, model) measurement."""

    workload: str
    task_id: str
    model: str
    latency_seconds: float
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    refusal: bool
    accuracy: float
    completeness: float
    schema_validity: float
    safety: float
    concision: float
    error: Optional[str] = None
    candidate_excerpt: str = ""  # first 200 chars only — full output is huge


@dataclass
class WorkloadSummary:
    """Per (workload, model) aggregate."""

    workload: str
    model: str
    n_tasks: int
    p50_latency_s: float
    p95_latency_s: float
    mean_cost_usd: float
    refusal_rate: float
    mean_accuracy: float
    mean_completeness: float
    mean_schema_validity: float
    mean_safety: float
    mean_concision: float
    composite_score: float  # weighted blend, see _composite()


@dataclass
class BenchReport:
    """Full bench output — written to disk as JSON."""

    started_at: str
    finished_at: str
    dry_run: bool
    workloads_run: List[str]
    models_seen: List[str]
    judge_model: str
    n_tasks_total: int
    n_results: int
    task_results: List[TaskResult] = field(default_factory=list)
    summaries: List[WorkloadSummary] = field(default_factory=list)


# ───────────────────────────────────────────────────────────────────
# Synthetic task corpus
# ───────────────────────────────────────────────────────────────────
# Each task carries: task_id, system + user prompts, and a reference
# output the judge will compare against. When #600 lands, swap to load
# from `backend/tests/fixtures/golden_pdfs/`.

CORPUS: Dict[str, List[Dict[str, Any]]] = {
    "vision_analyzer": [
        {
            "task_id": "vis_aws_typical",
            "system": "You are an Azure migration analyst. Extract a structured service inventory from the architecture description below. Output JSON: {services:[{name,provider,layer}], edges:[{from,to,protocol}]}.",
            "user": "Architecture: An AWS VPC contains an ALB fronting an EKS cluster running 3 microservices (orders, billing, notifications). Services persist to RDS PostgreSQL Multi-AZ. Static assets in S3, served via CloudFront. CloudWatch + X-Ray for observability.",
            "reference": {
                "services": [
                    {"name": "ALB",        "provider": "aws", "layer": "ingress"},
                    {"name": "EKS",        "provider": "aws", "layer": "compute"},
                    {"name": "RDS",        "provider": "aws", "layer": "data"},
                    {"name": "S3",         "provider": "aws", "layer": "storage"},
                    {"name": "CloudFront", "provider": "aws", "layer": "cdn"},
                    {"name": "CloudWatch", "provider": "aws", "layer": "observability"},
                    {"name": "X-Ray",      "provider": "aws", "layer": "observability"},
                ],
                "edges": [
                    {"from": "CloudFront", "to": "S3",  "protocol": "https"},
                    {"from": "ALB",        "to": "EKS", "protocol": "https"},
                    {"from": "EKS",        "to": "RDS", "protocol": "tcp/5432"},
                ],
            },
        },
        {
            "task_id": "vis_gcp_typical",
            "system": "You are an Azure migration analyst. Extract a structured service inventory from the architecture description below. Output JSON.",
            "user": "Architecture: A GCP project runs GKE behind a Cloud Load Balancer, with Cloud SQL PostgreSQL HA, Cloud Storage for media, Cloud CDN, and Cloud Logging.",
            "reference": {
                "services": [
                    {"name": "Cloud Load Balancer", "provider": "gcp", "layer": "ingress"},
                    {"name": "GKE",                 "provider": "gcp", "layer": "compute"},
                    {"name": "Cloud SQL",           "provider": "gcp", "layer": "data"},
                    {"name": "Cloud Storage",       "provider": "gcp", "layer": "storage"},
                    {"name": "Cloud CDN",           "provider": "gcp", "layer": "cdn"},
                    {"name": "Cloud Logging",       "provider": "gcp", "layer": "observability"},
                ],
                "edges": [
                    {"from": "Cloud Load Balancer", "to": "GKE",       "protocol": "https"},
                    {"from": "GKE",                 "to": "Cloud SQL", "protocol": "tcp/5432"},
                ],
            },
        },
    ],
    "iac_generator": [
        {
            "task_id": "iac_aks_minimal",
            "system": "You are an Azure infrastructure engineer. Emit a single self-contained Terraform file for the requested resources. Use azurerm provider ~> 4.60. Do not invent resource group names.",
            "user": "Generate Terraform for: 1 AKS cluster (system pool 3 nodes Standard_D4s_v5), 1 Azure SQL Database (vCore Gen5 GP, 4 vCores), 1 Azure Front Door Standard, all in a resource group called rg-archmorph-prod-eastus2.",
            "reference": "terraform { required_providers { azurerm = { source = \"hashicorp/azurerm\" version = \"~> 4.60\" } } }\nprovider \"azurerm\" { features {} }\nresource \"azurerm_resource_group\" \"rg\" { name = \"rg-archmorph-prod-eastus2\" location = \"eastus2\" }\nresource \"azurerm_kubernetes_cluster\" \"aks\" { name = \"aks-archmorph\" location = azurerm_resource_group.rg.location resource_group_name = azurerm_resource_group.rg.name dns_prefix = \"aks-archmorph\" default_node_pool { name = \"system\" node_count = 3 vm_size = \"Standard_D4s_v5\" } identity { type = \"SystemAssigned\" } }\n# (azurerm_mssql_server, azurerm_mssql_database, azurerm_cdn_frontdoor_profile follow…)",
        },
    ],
    "hld_generator": [
        {
            "task_id": "hld_simple_3tier",
            "system": "You are an Azure architect. Produce a Markdown High-Level Design with sections: Overview, Service Map, Networking, Security, Cost, Risks.",
            "user": "Source: AWS 3-tier app (ALB → ECS Fargate → RDS PG). Target: Azure equivalents. Audience: customer architecture review board.",
            "reference": "# High-Level Design\n## Overview\nMigration of AWS 3-tier app to Azure-native equivalents.\n## Service Map\n| Source | Target | Confidence |\n|---|---|---|\n| ALB | Application Gateway | high |\n| ECS Fargate | Container Apps | high |\n| RDS PostgreSQL | PostgreSQL Flexible Server | high |\n## Networking\nVNet with 3 subnets (ingress, app, data). NSG on app subnet locks down to ingress subnet only.\n## Security\nManaged Identity for App→DB. Key Vault for secrets. Private Endpoints for PG.\n## Cost\nIndicative monthly: $400–800.\n## Risks\nALB→AppGw L7 rule reauthoring; PG version pin.",
        },
    ],
    "mapping_suggester": [
        {
            "task_id": "map_lambda",
            "system": "You map a single source service to its Azure equivalents. Output JSON: {primary, alternatives:[{name,confidence,rationale}]}.",
            "user": "AWS Lambda",
            "reference": {
                "primary": "Azure Functions",
                "alternatives": [
                    {"name": "Azure Container Apps", "confidence": "medium", "rationale": "When workload exceeds 10-min execution or needs custom runtimes"},
                    {"name": "Azure Logic Apps",     "confidence": "low",    "rationale": "Workflow-oriented, not a 1:1 fit"},
                ],
            },
        },
        {
            "task_id": "map_dynamodb",
            "system": "You map a single source service to its Azure equivalents. Output JSON.",
            "user": "AWS DynamoDB",
            "reference": {
                "primary": "Azure Cosmos DB (NoSQL API)",
                "alternatives": [
                    {"name": "Azure Cosmos DB for PostgreSQL", "confidence": "low", "rationale": "Only when relational features required"},
                ],
            },
        },
    ],
    "agent_paas_react": [
        {
            "task_id": "agent_simple_lookup",
            "system": "You are an Archmorph PaaS agent. Use the `lookup_mapping(source_service)` tool to answer. Reply only after the tool call returns. Output JSON: {tool_calls:[{name,args}], final_answer}.",
            "user": "What's the Azure equivalent of AWS S3?",
            "reference": {
                "tool_calls": [{"name": "lookup_mapping", "args": {"source_service": "S3"}}],
                "final_answer": "Azure Blob Storage",
            },
        },
    ],
    "retention_anonymizer": [
        {
            "task_id": "anon_basic_event",
            "system": "Anonymize the event payload. Replace any name/email/IP with stable hashed tokens. Preserve event_type, timestamp, and counts.",
            "user": '{"event_type":"login","timestamp":"2026-05-01T10:00:00Z","user":{"email":"alice@example.com","name":"Alice Smith","ip":"203.0.113.42"},"count":1}',
            "reference": {
                "event_type": "login",
                "timestamp":  "2026-05-01T10:00:00Z",
                "user": {"email": "<HASH:email>", "name": "<HASH:name>", "ip": "<HASH:ip>"},
                "count": 1,
            },
        },
    ],
}


# ───────────────────────────────────────────────────────────────────
# Synthetic responses (drive --dry-run; calibrated per model)
# ───────────────────────────────────────────────────────────────────
# Keyed on (model, task_id) → fixed response. These are based on
# small-N pilot runs we did against Foundry preview deployments and
# are NOT live measurements — they are calibrated stand-ins so the
# harness produces stable numbers in CI without consuming quota.
# When live runs replace these, the structure is unchanged.

SYNTHETIC_RESPONSES: Dict[Tuple[str, str], Dict[str, Any]] = {
    # Pattern: each model + task entry yields the same dict shape:
    #   {"latency_s": float, "tokens_in": int, "tokens_out": int,
    #    "scores": {"accuracy", "completeness", "schema_validity",
    #               "safety", "concision"}, "refusal": bool}
    #
    # These numbers reflect the verdict in `model_bench_2026_05.md`.
    # Adjust together with that doc — both are versioned in the same
    # commit on purpose.

    # Vision analyzer ────────────────────────────────────────────
    ("gpt-4.1",                  "vis_aws_typical"): {"latency_s": 1.83, "tokens_in": 180, "tokens_out": 220, "scores": {"accuracy": 0.86, "completeness": 0.90, "schema_validity": 1.00, "safety": 1.00, "concision": 0.85}, "refusal": False},
    ("gpt-5.4",                  "vis_aws_typical"): {"latency_s": 1.21, "tokens_in": 180, "tokens_out": 210, "scores": {"accuracy": 0.93, "completeness": 0.95, "schema_validity": 1.00, "safety": 1.00, "concision": 0.92}, "refusal": False},
    ("gpt-5.5",                  "vis_aws_typical"): {"latency_s": 2.40, "tokens_in": 180, "tokens_out": 250, "scores": {"accuracy": 0.96, "completeness": 0.97, "schema_validity": 1.00, "safety": 1.00, "concision": 0.88}, "refusal": False},
    ("mistral-document-ai-2512", "vis_aws_typical"): {"latency_s": 0.95, "tokens_in": 180, "tokens_out": 190, "scores": {"accuracy": 0.91, "completeness": 0.92, "schema_validity": 1.00, "safety": 1.00, "concision": 0.94}, "refusal": False},

    ("gpt-4.1",                  "vis_gcp_typical"): {"latency_s": 1.78, "tokens_in": 160, "tokens_out": 200, "scores": {"accuracy": 0.84, "completeness": 0.88, "schema_validity": 1.00, "safety": 1.00, "concision": 0.86}, "refusal": False},
    ("gpt-5.4",                  "vis_gcp_typical"): {"latency_s": 1.18, "tokens_in": 160, "tokens_out": 195, "scores": {"accuracy": 0.92, "completeness": 0.94, "schema_validity": 1.00, "safety": 1.00, "concision": 0.91}, "refusal": False},
    ("gpt-5.5",                  "vis_gcp_typical"): {"latency_s": 2.35, "tokens_in": 160, "tokens_out": 230, "scores": {"accuracy": 0.95, "completeness": 0.96, "schema_validity": 1.00, "safety": 1.00, "concision": 0.87}, "refusal": False},
    ("mistral-document-ai-2512", "vis_gcp_typical"): {"latency_s": 0.92, "tokens_in": 160, "tokens_out": 180, "scores": {"accuracy": 0.90, "completeness": 0.91, "schema_validity": 1.00, "safety": 1.00, "concision": 0.93}, "refusal": False},

    # IaC generator ──────────────────────────────────────────────
    ("gpt-4.1",        "iac_aks_minimal"): {"latency_s": 3.10, "tokens_in": 220, "tokens_out": 720, "scores": {"accuracy": 0.78, "completeness": 0.80, "schema_validity": 0.90, "safety": 0.95, "concision": 0.82}, "refusal": False},
    ("gpt-5.4",        "iac_aks_minimal"): {"latency_s": 2.20, "tokens_in": 220, "tokens_out": 700, "scores": {"accuracy": 0.88, "completeness": 0.90, "schema_validity": 0.95, "safety": 1.00, "concision": 0.88}, "refusal": False},
    ("gpt-5.3-codex",  "iac_aks_minimal"): {"latency_s": 1.85, "tokens_in": 220, "tokens_out": 680, "scores": {"accuracy": 0.94, "completeness": 0.94, "schema_validity": 1.00, "safety": 1.00, "concision": 0.92}, "refusal": False},

    # HLD generator ──────────────────────────────────────────────
    ("gpt-4.1",  "hld_simple_3tier"): {"latency_s": 4.20, "tokens_in": 260, "tokens_out": 980, "scores": {"accuracy": 0.85, "completeness": 0.88, "schema_validity": 0.92, "safety": 1.00, "concision": 0.80}, "refusal": False},
    ("gpt-5.4",  "hld_simple_3tier"): {"latency_s": 2.95, "tokens_in": 260, "tokens_out": 920, "scores": {"accuracy": 0.92, "completeness": 0.94, "schema_validity": 0.95, "safety": 1.00, "concision": 0.88}, "refusal": False},

    # Mapping suggester ──────────────────────────────────────────
    ("gpt-4.1",      "map_lambda"):   {"latency_s": 0.88, "tokens_in": 80, "tokens_out": 110, "scores": {"accuracy": 0.92, "completeness": 0.90, "schema_validity": 1.00, "safety": 1.00, "concision": 0.95}, "refusal": False},
    ("gpt-5.4-mini", "map_lambda"):   {"latency_s": 0.42, "tokens_in": 80, "tokens_out": 105, "scores": {"accuracy": 0.93, "completeness": 0.92, "schema_validity": 1.00, "safety": 1.00, "concision": 0.96}, "refusal": False},
    ("gpt-4.1",      "map_dynamodb"): {"latency_s": 0.85, "tokens_in": 80, "tokens_out": 115, "scores": {"accuracy": 0.90, "completeness": 0.88, "schema_validity": 1.00, "safety": 1.00, "concision": 0.94}, "refusal": False},
    ("gpt-5.4-mini", "map_dynamodb"): {"latency_s": 0.40, "tokens_in": 80, "tokens_out": 100, "scores": {"accuracy": 0.92, "completeness": 0.90, "schema_validity": 1.00, "safety": 1.00, "concision": 0.96}, "refusal": False},

    # Agent ReAct ────────────────────────────────────────────────
    ("gpt-4.1",      "agent_simple_lookup"): {"latency_s": 1.10, "tokens_in": 140, "tokens_out": 160, "scores": {"accuracy": 0.94, "completeness": 0.92, "schema_validity": 0.98, "safety": 1.00, "concision": 0.90}, "refusal": False},
    ("gpt-5.4-mini", "agent_simple_lookup"): {"latency_s": 0.55, "tokens_in": 140, "tokens_out": 150, "scores": {"accuracy": 0.95, "completeness": 0.93, "schema_validity": 0.98, "safety": 1.00, "concision": 0.93}, "refusal": False},

    # Retention anonymizer ──────────────────────────────────────
    ("gpt-4o",       "anon_basic_event"): {"latency_s": 0.68, "tokens_in": 100, "tokens_out": 120, "scores": {"accuracy": 0.96, "completeness": 0.96, "schema_validity": 1.00, "safety": 1.00, "concision": 0.97}, "refusal": False},
    ("gpt-5.4-nano", "anon_basic_event"): {"latency_s": 0.31, "tokens_in": 100, "tokens_out": 115, "scores": {"accuracy": 0.96, "completeness": 0.96, "schema_validity": 1.00, "safety": 1.00, "concision": 0.97}, "refusal": False},
}


# ───────────────────────────────────────────────────────────────────
# Bench machinery
# ───────────────────────────────────────────────────────────────────


def _composite(s: Dict[str, float]) -> float:
    """Weighted composite: accuracy 40%, completeness 25%, schema 15%,
    safety 15%, concision 5%. Tuned so a model that produces malformed
    JSON (schema_validity=0) cannot win on raw accuracy alone."""
    return round(
        0.40 * s["accuracy"]
        + 0.25 * s["completeness"]
        + 0.15 * s["schema_validity"]
        + 0.15 * s["safety"]
        + 0.05 * s["concision"],
        3,
    )


def _cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    if model not in PRICING_PER_1M_TOKENS_USD:
        return 0.0
    cin, cout = PRICING_PER_1M_TOKENS_USD[model]
    return round((tokens_in / 1_000_000) * cin + (tokens_out / 1_000_000) * cout, 6)


def _run_single(workload: str, task: Dict[str, Any], model: str, *, dry_run: bool) -> TaskResult:
    """Execute one (workload, task, model) measurement."""
    task_id = task["task_id"]

    if dry_run:
        rec = SYNTHETIC_RESPONSES.get((model, task_id))
        if rec is None:
            return TaskResult(
                workload=workload, task_id=task_id, model=model,
                latency_seconds=0.0, prompt_tokens=0, completion_tokens=0,
                cost_usd=0.0, refusal=False,
                accuracy=0.0, completeness=0.0, schema_validity=0.0,
                safety=0.0, concision=0.0,
                error=f"no synthetic record for ({model}, {task_id})",
            )
        s = rec["scores"]
        return TaskResult(
            workload=workload, task_id=task_id, model=model,
            latency_seconds=rec["latency_s"],
            prompt_tokens=rec["tokens_in"],
            completion_tokens=rec["tokens_out"],
            cost_usd=_cost_usd(model, rec["tokens_in"], rec["tokens_out"]),
            refusal=rec["refusal"],
            accuracy=s["accuracy"], completeness=s["completeness"],
            schema_validity=s["schema_validity"], safety=s["safety"],
            concision=s["concision"],
            candidate_excerpt="[synthetic]",
        )

    # ── live mode ───────────────────────────────────────────────
    # Defer heavy import until live mode actually runs — keeps
    # import-time impact at zero for offline tests.
    try:
        from openai_client import cached_chat_completion  # type: ignore
    except ImportError as exc:
        return TaskResult(
            workload=workload, task_id=task_id, model=model,
            latency_seconds=0.0, prompt_tokens=0, completion_tokens=0,
            cost_usd=0.0, refusal=False,
            accuracy=0.0, completeness=0.0, schema_validity=0.0,
            safety=0.0, concision=0.0,
            error=f"openai_client unavailable: {exc}",
        )

    messages = [
        {"role": "system", "content": task["system"]},
        {"role": "user",   "content": task["user"]},
    ]
    started = time.perf_counter()
    try:
        resp = cached_chat_completion(
            messages, model=model, temperature=0.0, bypass_cache=True,
        )
    except Exception as exc:  # noqa: BLE001 — bench, want every error to propagate to the row
        return TaskResult(
            workload=workload, task_id=task_id, model=model,
            latency_seconds=time.perf_counter() - started,
            prompt_tokens=0, completion_tokens=0, cost_usd=0.0,
            refusal=False,
            accuracy=0.0, completeness=0.0, schema_validity=0.0,
            safety=0.0, concision=0.0,
            error=f"{type(exc).__name__}: {exc}",
        )

    latency = time.perf_counter() - started
    usage = getattr(resp, "usage", None)
    pt = getattr(usage, "prompt_tokens", 0) if usage else 0
    ct = getattr(usage, "completion_tokens", 0) if usage else 0
    candidate = (resp.choices[0].message.content or "") if resp.choices else ""

    # Judge call
    scores, refusal = _judge(workload, task["reference"], candidate, dry_run=False)

    return TaskResult(
        workload=workload, task_id=task_id, model=model,
        latency_seconds=round(latency, 3),
        prompt_tokens=pt, completion_tokens=ct,
        cost_usd=_cost_usd(model, pt, ct),
        refusal=refusal,
        accuracy=scores["accuracy"], completeness=scores["completeness"],
        schema_validity=scores["schema_validity"], safety=scores["safety"],
        concision=scores["concision"],
        candidate_excerpt=candidate[:200],
    )


def _judge(workload: str, reference: Any, candidate: str, *, dry_run: bool) -> Tuple[Dict[str, float], bool]:
    """Rubric-grade a candidate response against a known-good reference.

    In dry-run mode this is never called — synthetic scores come straight
    from `SYNTHETIC_RESPONSES`. In live mode we ask `gpt-5-pro` to grade
    using the prompt at `judge_prompt.txt`.
    """
    if dry_run:
        # not used — synthetic path returns scores directly
        return ({"accuracy": 1.0, "completeness": 1.0, "schema_validity": 1.0, "safety": 1.0, "concision": 1.0}, False)

    try:
        from openai_client import cached_chat_completion  # type: ignore
    except ImportError:
        return ({"accuracy": 0.0, "completeness": 0.0, "schema_validity": 0.0, "safety": 0.0, "concision": 0.0}, False)

    judge_prompt_path = Path(__file__).parent / "judge_prompt.txt"
    judge_system = judge_prompt_path.read_text(encoding="utf-8")
    judge_user = (
        f"## Workload\n{workload}\n\n"
        f"## Reference (known-good)\n{json.dumps(reference, indent=2) if not isinstance(reference, str) else reference}\n\n"
        f"## Candidate\n{candidate}\n"
    )

    try:
        resp = cached_chat_completion(
            [{"role": "system", "content": judge_system}, {"role": "user", "content": judge_user}],
            model=JUDGE_MODEL, temperature=0.0, bypass_cache=True,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "").strip()
        parsed = json.loads(raw)
        return (
            {
                "accuracy":         float(parsed.get("accuracy", 0.0)),
                "completeness":     float(parsed.get("completeness", 0.0)),
                "schema_validity":  float(parsed.get("schema_validity", 0.0)),
                "safety":           float(parsed.get("safety", 0.0)),
                "concision":        float(parsed.get("concision", 0.0)),
            },
            bool(parsed.get("refusal", False)),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("judge call failed: %s", exc)
        return ({"accuracy": 0.0, "completeness": 0.0, "schema_validity": 0.0, "safety": 0.0, "concision": 0.0}, False)


def _summarize(results: List[TaskResult]) -> List[WorkloadSummary]:
    """Aggregate per (workload, model)."""
    grouped: Dict[Tuple[str, str], List[TaskResult]] = {}
    for r in results:
        grouped.setdefault((r.workload, r.model), []).append(r)

    out: List[WorkloadSummary] = []
    for (wl, mdl), rs in sorted(grouped.items()):
        latencies = [r.latency_seconds for r in rs if not r.error]
        if not latencies:
            continue
        scores_mean = {
            "accuracy":        statistics.mean(r.accuracy for r in rs),
            "completeness":    statistics.mean(r.completeness for r in rs),
            "schema_validity": statistics.mean(r.schema_validity for r in rs),
            "safety":          statistics.mean(r.safety for r in rs),
            "concision":       statistics.mean(r.concision for r in rs),
        }
        out.append(WorkloadSummary(
            workload=wl, model=mdl, n_tasks=len(rs),
            p50_latency_s=round(statistics.median(latencies), 3),
            p95_latency_s=round(_percentile(latencies, 0.95), 3),
            mean_cost_usd=round(statistics.mean(r.cost_usd for r in rs), 6),
            refusal_rate=round(sum(1 for r in rs if r.refusal) / len(rs), 3),
            mean_accuracy=round(scores_mean["accuracy"], 3),
            mean_completeness=round(scores_mean["completeness"], 3),
            mean_schema_validity=round(scores_mean["schema_validity"], 3),
            mean_safety=round(scores_mean["safety"], 3),
            mean_concision=round(scores_mean["concision"], 3),
            composite_score=_composite(scores_mean),
        ))
    return out


def _percentile(values: List[float], p: float) -> float:
    """Inclusive linear-interp percentile, p in [0,1]. Adequate for n>=2."""
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    s = sorted(values)
    k = (len(s) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def build_benchmark_plan() -> Dict[str, Any]:
    """Return the #781 deployment-aware benchmark plan.

    This is intentionally static and offline-friendly. The live benchmark can
    attach measured result files later, but the candidate set, auth posture,
    regional evidence, and decision rule should be reviewable in CI without
    touching Azure resources.
    """
    return {
        "issue": 781,
        "generated_for_date": "2026-05-07",
        "current_account": CURRENT_FOUNDRY_ACCOUNT,
        "current_deployments": CURRENT_DEPLOYMENTS,
        "auth_requirements": AUTH_REQUIREMENTS,
        "regional_availability": REGIONAL_AVAILABILITY,
        "benchmark_lanes": BENCHMARK_LANES,
        "recommendation_matrix": RECOMMENDATION_MATRIX,
        "decision_rule": DECISION_RULE,
        "production_routing_change": False,
        "minimum_required_lanes": 5,
    }


def run_bench(
    workloads: Optional[List[str]] = None,
    models_filter: Optional[List[str]] = None,
    *,
    dry_run: bool = False,
) -> BenchReport:
    """Execute the bench across the requested (workload, model) cells."""
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    selected = workloads or list(WORKLOAD_CANDIDATES.keys())

    results: List[TaskResult] = []
    models_seen: set[str] = set()
    n_total = 0

    for wl in selected:
        if wl not in WORKLOAD_CANDIDATES:
            logger.warning("unknown workload %s, skipping", wl)
            continue
        candidates = WORKLOAD_CANDIDATES[wl]
        if models_filter:
            candidates = [m for m in candidates if m in models_filter]
        tasks = CORPUS.get(wl, [])
        for task in tasks:
            n_total += len(candidates)
            for model in candidates:
                models_seen.add(model)
                results.append(_run_single(wl, task, model, dry_run=dry_run))

    return BenchReport(
        started_at=started,
        finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        dry_run=dry_run,
        workloads_run=selected,
        models_seen=sorted(models_seen),
        judge_model=JUDGE_MODEL,
        n_tasks_total=n_total,
        n_results=len(results),
        task_results=results,
        summaries=_summarize(results),
    )


def _report_to_json(report: BenchReport) -> str:
    return json.dumps({
        "started_at":     report.started_at,
        "finished_at":    report.finished_at,
        "dry_run":        report.dry_run,
        "benchmark_plan": build_benchmark_plan(),
        "workloads_run":  report.workloads_run,
        "models_seen":    report.models_seen,
        "judge_model":    report.judge_model,
        "n_tasks_total":  report.n_tasks_total,
        "n_results":      report.n_results,
        "task_results":   [asdict(r) for r in report.task_results],
        "summaries":      [asdict(s) for s in report.summaries],
    }, indent=2, sort_keys=True)


def _parse_cli(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="model_bench", description=__doc__.split("\n", 1)[0])
    p.add_argument("--dry-run", action="store_true", help="Use synthetic responses; no Foundry calls.")
    p.add_argument("--full", action="store_true", help="Run the full matrix in #602 acceptance criteria.")
    p.add_argument("--plan", action="store_true", help="Emit the #781 benchmark plan only; no model calls.")
    p.add_argument("--workloads", default=None,
                   help=f"Comma-separated subset of: {','.join(WORKLOAD_CANDIDATES)}")
    p.add_argument("--models", default=None,
                   help="Comma-separated subset of model names to evaluate.")
    p.add_argument("--output", default="-", help="Output file path or '-' for stdout.")
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_cli(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.full and (args.workloads or args.models):
        logger.error("--full is incompatible with --workloads / --models")
        return 2

    if args.plan:
        payload = json.dumps(build_benchmark_plan(), indent=2, sort_keys=True)
        if args.output == "-":
            print(payload)
        else:
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(payload, encoding="utf-8")
            logger.info("wrote benchmark plan: %s", out)
        return 0

    workloads = list(WORKLOAD_CANDIDATES) if args.full else (
        [w.strip() for w in args.workloads.split(",")] if args.workloads else None
    )
    models_filter = [m.strip() for m in args.models.split(",")] if args.models else None

    report = run_bench(workloads=workloads, models_filter=models_filter, dry_run=args.dry_run)
    payload = _report_to_json(report)

    if args.output == "-":
        print(payload)
    else:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
        logger.info("wrote bench report: %s (%d results)", out, len(report.task_results))

    # Quick console verdict so dry-run is useful without opening the file
    if args.verbose or args.output != "-":
        print("\nWorkload               Model                          n   p50(s)  p95(s)  $/call    refuse  composite", file=sys.stderr)
        print("─" * 110, file=sys.stderr)
        for s in report.summaries:
            print(
                f"{s.workload:<22} {s.model:<30} {s.n_tasks:>3}  "
                f"{s.p50_latency_s:>6.3f}  {s.p95_latency_s:>6.3f}  "
                f"{s.mean_cost_usd:>8.6f}  {s.refusal_rate:>6.2%}  {s.composite_score:>6.3f}",
                file=sys.stderr,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
