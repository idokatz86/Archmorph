# Gate B: Evidence-first migration workbench

**Status:** Planning design; direction and three sections reviewed by the user on 2026-11-24.

**Scope:** AWS/GCP architecture planning for migration to Azure.
**Authorization boundary:** This document does not authorize product-code changes, cloud provisioning, production access, deployment, or decommissioning.

## Context and decision

The approved direction is an **evidence-first migration workbench**, evolving the existing application instead of replacing it with a general autonomous agent. The product should transform an AWS or GCP architecture diagram into a reviewable Azure migration package, with explicit provenance, assumptions, and validation status. The primary output is a decision-support artifact and pull request, not a deployment into a customer's subscription.

This direction fits the Phase 0 defaults—free/open source, a $150 monthly Azure cap, limited weekly engineering time, artifacts/PRs only—and responds to the Phase 1 findings: live analysis quality and retention are unverified, the current CI full-spine path is deterministic, and generated IaC errors are advisory. See [orientation](00_ORIENTATION.md), [audit](01_AUDIT.md), and [landscape](02_LANDSCAPE.md).

## Proposed architecture

Keep the current React frontend and FastAPI backend. Add a typed architecture graph as the shared internal contract for all downstream operations. The graph records source provider, observed nodes and relationships, catalog mappings, model inferences, customer answers, and review state. Evidence should be attached to the relevant graph elements: upload location or detected label, catalog entry and version, model/version, confidence, user change, and validation result.

The target remains Azure. Provider-neutral normalization is only an internal representation; it does not broaden the product to arbitrary source/target pairs. Catalog matching should be provider-aware and deterministic where possible. Model calls should be bounded to diagram interpretation, unresolved mapping suggestions, and narrative drafting. They must not silently overwrite observed facts or user decisions.

Costs, migration guidance, diagrams, HLD, and Terraform/Bicep drafts should all derive from the same graph snapshot. This avoids separate model calls inventing inconsistent topologies. The existing Azure OpenAI integration remains the initial runtime; do not introduce a new agent framework or AI Gateway unless a measured need justifies the cost and operational complexity.

## Workflow and component responsibilities

1. **Ingest:** authenticate the user, validate file type and size, create a run ID, and return explicit unsupported-input errors.
2. **Extract:** generate a provisional graph of observed services and edges. Keep extraction confidence distinct from mapping confidence.
3. **Map:** resolve source services against a versioned catalog. Model-generated alternatives remain suggestions and identify why catalog matching was unavailable or ambiguous.
4. **Clarify:** ask targeted questions for missing migration constraints. Store user answers separately from system defaults and inferred values.
5. **Validate graph:** check schema, provider, node/edge consistency, required decisions, and unresolved items. A partial graph can produce a draft, but never a complete/validated label.
6. **Estimate and generate:** compute directional costs from explicit region/SKU/quantity assumptions and dated price evidence; render architecture views and HLD; generate IaC from the same graph.
7. **Validate artifacts:** run Terraform/Bicep formatting and compiler checks plus policy checks. Preserve diagnostics. Do not execute generated code or call deployment APIs.
8. **Export:** package the graph snapshot, customer decisions, assumptions, evidence, cost rows, artifacts, and validation report into reviewable files and a pull request.

## Data flow, failure handling, and trust

Treat uploads, catalog text, model output, and tool descriptions as untrusted. Validate schemas and parameters at every boundary, escape rendered content, and keep IaC as inert text. Model or pricing-service failures must produce visible degraded/error states; do not substitute a success-shaped fallback or imply that unavailable evidence was verified.

Each export should be traceable to a versioned graph and record catalog version, model/deployment, pricing source and timestamp, user changes, and validation results. Use the existing managed identity for Azure-hosted model access and least-privilege permissions. If Azure MCP lookups are later added, expose only selected read-only tools with confirmation still enabled. Keep customer-subscription writes, deployment, rollback, and credential collection out of scope.

Store only data required for the session and generated artifact. Do not publish a specific retention or purge promise until backend deletion and user-visible receipt behavior are tested end to end. Establish per-run model/token/time limits and account for Azure usage; do not assume Copilot build-time credits cover application runtime costs.

## Evaluation and quality gates

Create a legally approved, held-out scenario set covering AWS-only, GCP-only, mixed, ambiguous, unsupported, and low-quality diagrams. Include known node/edge expectations, provider-aware mapping answers, user constraints, expected cost assumptions, and required output properties. Keep some scenarios outside ordinary prompt examples and fixture tests to reduce test overfitting.

Measure:

- service and relationship extraction precision/recall;
- provider-aware mapping accuracy and confidence calibration;
- evidence/provenance completeness and user-change preservation;
- cost arithmetic and agreement with the cited price inputs;
- HLD factual review against the graph and constraints;
- Terraform/Bicep formatting, compilation, and policy results;
- export integrity, accessibility, and data lifecycle behavior.

Compare end-to-end results with the current product baseline and qualified human migration review. Model-as-judge scores can supplement, not replace, objective checks and expert acceptance. Keep fast deterministic API tests, add regressions for known errors, and separately run real toolchain checks and budget-capped model evaluations. Production smoke evidence and content-quality evidence must remain distinct.

## Alternatives considered

| Direction | Why it was not selected as the initial product |
|---|---|
| IaC-first generator | It can produce more immediately tangible code, but inherits the input-accuracy problem and overlaps with Azure's deployment tooling. Compiler validity is not proof of correct topology, price, security, or deployability. |
| Autonomous multi-agent migration agent | It adds model calls, state, permissions, tool governance, and operational risk while conflicting with the no-customer-subscription-mutation constraint and budget. It is not required for the deterministic extract/map/validate/export workflow. |

## Non-goals and deferred capabilities

- No deployment, rollback, subscription scanning, or customer credential vault.
- No migration to a new agent framework, MCP toolchain, or multi-provider model gateway without a separate costed decision.
- No general provider-to-provider translation beyond AWS/GCP-to-Azure.
- No revival of retired RAG, Agent PaaS, SSO/org, gallery, collaboration, or drift surfaces solely because code exists.
- No claim that an artifact is production-ready merely because it renders or passes syntax checks.

## Gate C readiness checklist

Before any product coding is authorized, a separate Gate C decision should require:

1. Explicit acceptance thresholds for the scenario set and baseline comparison.
2. A reviewed graph schema and evidence/provenance rules, including the GCP confidence fix.
3. Confirmed Azure budget alerts and a model usage cap consistent with the $150/month limit.
4. Verified data retention and purge behavior, with a privacy-reviewed customer disclosure.
5. A scoped implementation plan, file ownership, test commands, rollback plan, and reviewable PR boundary.
6. Explicit confirmation that no customer-subscription deployment or destructive action is included.

Gate D remains separate: no legacy teardown or other destructive action without the exact required phrase, `APPROVE DECOMMISSION`.
