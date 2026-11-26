# Gate C — Scoped Implementation Plan

**Status:** Gate C approved; scoped implementation completed and locally verified on 2026-11-24. No cloud activity, deployment, or data-retention changes were made.

## Objective

Implement the approved evidence-first migration workbench as a review and decision-support product. A user should be able to trace detected architecture, proposed Azure mappings, cost assumptions, validation results, and exported artifacts back to their evidence. This work does not make an architecture deployable or guarantee that a migration is safe.

The existing analysis payload and `AnalysisVersion.snapshot` JSON are the compatibility baseline. Add a versioned, validated graph projection to that payload rather than introducing a new persistence store or SQL migration. Keep existing API fields and artifact workflows working while adding explicit provenance and status.

## Workstreams and order

| Order | Workstream | Scope and principal seams | Depends on |
|---|---|---|---|
| 0 | Characterization and compatibility | Add focused regression fixtures for current sync/async analysis, persistence/restore, cost estimate, IaC generation, and exports. Preserve legacy snapshots and response fields. Use [`AnalysisVersion`](../../backend/models/workspace.py) as the durable snapshot boundary; do not alter retention or upload handling. | Gate C approval |
| 1 | Graph contract and mapping provenance | Add a strict `architecture-graph/v1` model in `backend/architecture_graph.py`, built on [`StrictBaseModel`](../../backend/strict_models.py). Project only facts present in analysis: nodes carry source/target service and mapping evidence; edges are emitted only when detected, with valid node references. Adapt old snapshots without inventing edges. Fix provider-specific catalog confidence lookup in [`confidence_provenance.py`](../../backend/confidence_provenance.py); propagate the source provider rather than silently treating missing GCP data as AWS. Reuse [`mapping_evidence.py`](../../backend/mapping_evidence.py), which already provides mapping-level evidence and provider-aware catalog freshness. | 0 |
| 2 | Analysis integration and durable compatibility | Build and validate the graph after [`_normalize_analysis`](../../backend/routers/diagrams.py) and before existing persistence. Keep legacy `mappings`, `services_detected`, and other clients’ fields intact. Ensure graph, provider, run metadata, and evidence survive canonical snapshots, restore, and export. Use the existing JSON snapshot; add no database columns. | 1 |
| 3 | Cost evidence | Extend [`estimate_services_cost`](../../backend/services/azure_pricing.py) and the existing cost-estimate response with per-service source, SKU/meter, region, assumptions, and cache/freshness metadata. Distinguish a live Retail Prices API result from a built-in estimate; never imply API provenance when no live price was obtained. Update [`CostPanel.jsx`](../../frontend/src/components/DiagramTranslator/CostPanel.jsx) to surface the distinction and assumptions. | 0 |
| 4 | IaC validation status | Separate validation outcome from generated source in [`iac_generator.py`](../../backend/iac_generator.py). Preserve existing `code`, hash, ETag, and editable/downloadable draft behavior, but return and persist explicit pass/fail/warning metadata; output with validation errors must never be labeled validated. Keep status accurate across the diagram generation/chat routes and the project/cost generation call sites in `routers/iac_routes.py`, `routers/projects.py`, `routers/insights.py`, and `iac_chat.py`. Update the relevant translator UI, including [`ExportHub.jsx`](../../frontend/src/components/DiagramTranslator/ExportHub.jsx), to show draft/validated/blocked status without implying deployment approval. | 0 |
| 5 | Evidence-bearing exports | Extend [`architecture_package.py`](../../backend/architecture_package.py) and existing export routes to include a machine-readable manifest for graph schema version, source/target providers, mapping evidence, pricing assumptions/provenance, and IaC validation state. Keep generated content within existing size limits and export-capability authorization. | 2, 3, 4 |
| 6 | Evaluation and release | Run deterministic fixtures through the real analysis-to-export pipeline using mocked model/pricing/network boundaries. Update focused backend and frontend tests and the existing evaluation report; do not treat synthetic fixtures as proof of production model quality. | 1–5 |

The existing [`LiveArchitectureSchema`](../../backend/models/infrastructure.py) describes live scanner results and should not be repurposed as the migration graph contract. The existing [`AnalysisResult`](../../backend/routers/shared.py) is only a summary shape and is not sufficient to represent graph topology or evidence.

## Acceptance criteria

1. **Graph correctness:** Every graph validates against `architecture-graph/v1`; node IDs are unique, every edge endpoint exists, and absent/uncertain topology is represented as absent or explicitly unknown—not inferred. Existing snapshots without the graph remain readable.
2. **Provider provenance:** Focused AWS and GCP fixtures demonstrate that confidence lookup uses the matching provider catalog. Missing provider-specific catalog evidence remains unknown/low-confidence and is surfaced for review, not replaced with an AWS match.
3. **Cost truthfulness:** Each cost line identifies its price source and relevant SKU/meter, region, assumptions, and cache time when available. API failure or built-in estimates cannot be presented as a fresh API quote. Currency and estimate range remain explicit.
4. **Validation truthfulness:** An IaC artifact with any validator error is never marked validated. It remains clearly a draft/blocked artifact with errors visible; warnings remain distinguishable. Existing hash/ETag concurrency behavior and code editing/chat remain functional.
5. **Export traceability:** Architecture package outputs include the same graph/evidence and do not claim independent correctness, deployment readiness, or customer approval. Export authorization, bounds, and existing response fields remain intact.
6. **Test and cost boundaries:** New tests use synthetic fixtures and mocked external calls; no customer diagrams, live cloud resources, subscription credentials, paid model calls, or non-test Azure/GitHub resources are required. The targeted backend and frontend suites pass.

## Focused test plan

- Backend unit tests: graph schema/legacy adaptation and invalid endpoints; provider-specific confidence lookup; live/cached/built-in pricing provenance; IaC validator pass, warning, and error outcomes.
- Backend route tests: analysis payload persistence and restore; additive API response compatibility; generated IaC status remaining accurate after chat/edit; export manifest preservation and authorization.
- Frontend tests: mapping provenance/review indicators in `AnalysisResults.jsx` and `ResultsTable.jsx`; pricing source/assumptions in `CostPanel.test.jsx`; validation status and draft handling in `ExportHub.test.jsx`.
- Pipeline fixtures: representative synthetic AWS and GCP diagrams cover known mappings, unknown services, missing topology evidence, and validation failure. All fixtures must satisfy the measurable criteria above; do not set a claimed production-quality model score from this small corpus.

## Data, budget, and release prerequisites

- Do not change image upload, storage, retention, or purge behavior in this workstream. Before any production-facing release, resolve the previously recorded uncertainty about sample-image retention and purge behavior; do not upload customer diagrams until that lifecycle is verified and approved.
- Use only synthetic fixtures in tests and review. Preserve existing authentication, tenant/project membership, snapshot redaction, and export-capability checks.
- No cloud deployment, subscription access, resource provisioning, or additional paid model usage is part of this plan. Reconcile the existing Azure budget/alert configuration with the previously stated $150 monthly limit and 50%/80% alerts before any cloud activity; no budget settings are changed by this plan.
- Release only after a human review of sample evidence-bearing outputs and confirmation that no UI or export labels drafts as validated or deployment-ready. Roll back by reverting the implementation changes; no database migration or destructive data operation is planned.

## Gate C decision

Approval authorizes only the implementation scope above. Any expansion into automated deployment, credential/scanner functionality, customer-subscription changes, altered data retention, paid model evaluation, or infrastructure provisioning requires a separate explicit decision. Gate D destructive actions remain blocked unless the exact required phrase in the master prompt is provided.
