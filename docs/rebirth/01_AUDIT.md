# Phase 1: Forensic audit

**Checked:** 2026-11-23

**Scope:** Read-only review of the isolated `rebirth/plan` worktree, repository documentation and tests, selected GitHub issues/workflows, and the public site. No product, cloud, identity, billing, DNS, or customer-data changes were made.

## Executive disposition

Archmorph has a working, tested AWS/GCP-to-Azure migration workflow, but the evidence supports “preview/stabilization,” not a production-ready migration platform. Its best-supported value is turning a selected or uploaded architecture into reviewable mappings, guided constraints, draft IaC/HLD/cost artifacts, and export files. Neither the live sample nor the current CI smoke proves real-world analysis accuracy: the live sample stopped at authentication, and CI substitutes deterministic fixtures for model output.

The current site says “Translate Between Any Cloud Providers,” while the README and upload flow define AWS/GCP-to-Azure. The README calls v4.3.0 a preview, says the Azure Landing Zone diagram remains Beta, and records the GA/release gates as superseded. GitHub has no v4.3.0 release or tag. A production Architecture Package smoke workflow exists, but its latest listed runs are from 2026-05-03; the newer full-spine workflow is a local test deployment with deterministic CI data.

**Recommendation for Gate A:** preserve the core migration-workbench intent, but do not treat the current model output, generated IaC, cost estimate, or deployment surfaces as verified production decisions. No product code should be changed until the user approves the next gate.

## Capability and maturity inventory

| Capability | Evidence-backed state | Important boundary | Disposition |
|---|---|---|---|
| Diagram upload, sample selection, and service extraction | Implemented in the core path; file validation and analysis routes have focused tests. | Live AWS sample returned HTTP 401 during this audit. CI returns a fixed sample analysis, not a model interpretation of the image. | Carry forward; require authenticated real-diagram evaluation. |
| AWS/GCP-to-Azure service mapping | Curated cross-cloud catalog, model-assisted mapping, confidence and evidence fields are implemented. Catalog entries include review dates. | No current held-out accuracy/calibration report against real diagrams. A provider-blind provenance lookup creates incorrect or incomplete GCP catalog attribution (see findings). | Carry forward with provider-aware evidence and dated source references. |
| Guided questions and customer intent | Deterministic question rules and answer persistence exist; README documents 32 questions across 8 categories. Full-spine contract tests cover answer flow. | A passing API contract does not establish that questions capture enough information for a safe migration plan. | Carry forward; validate against architecture scenarios and expert review. |
| IaC generation | Terraform and Bicep generation, static checks, security scanning, optional compiler validation, and fallback templates exist. CI installs Terraform/Bicep and enables CLI validation in a dedicated job. | The generator returns code even when validation finds errors; it appends errors/warnings as comments. CI's full-spine path uses fixed IaC fixtures, while CLI checks establish syntax/format properties, not deployment correctness or policy compliance. | Reimagine as a gated draft pipeline; never imply validated/deployable solely from generated output. |
| HLD, reports, and classic exports | HLD and report endpoints and multiple export formats are implemented and covered by artifact/contract tests. | CI mode supplies a deterministic HLD; tests do not establish factual completeness, safe sizing, or correctness for a customer's workload. | Carry forward as reviewable artifacts with assumptions and source evidence. |
| Architecture Package / Azure Landing Zone target and DR diagrams | HTML/SVG package and target/DR topology renderers are implemented; the smoke validates output structure and expected labels. | README marks the Azure Landing Zone target diagram Beta and says the formal GA and release promotion gates were superseded. CI smoke uses deterministic analysis, not an accepted migration design. | Carry forward only as a review artifact; keep Beta until architecture-level acceptance evidence exists. |
| Cost estimates | Azure Retail Prices API integration, cache, aliases, fallback prices, cost assumptions, and export paths exist. | The implementation selects the first non-zero match among up to five API results or falls back to a built-in monthly estimate. These are directional estimates, not workload-specific bills; results do not consistently expose a direct per-meter source URL. | Carry forward as an estimate; ground each row in SKU, usage, region, assumptions, and source. |
| Migration timeline | Seven phases, a hard-coded source-service dependency graph, parallel groups, effort ranges, and export formats are implemented. | Durations and risks are rule-based estimates, not a dependency-validated run plan. | Reimagine as a customer-reviewed plan; do not present hours as committed forecasts. |
| Scanner, deploy engine, credential vault | README labels these Scaffold. Preview/execute routes and service code exist. | `MOCK_AZURE_CLI` defaults to mocked commands; preview counts are placeholders, and job status/log streaming/rollback endpoints contain stubs. The deploy feature flag does not make these surfaces production-ready. | Keep disabled/scaffolded; do not expose as completed capability. |
| Collaboration, replay, gallery, Terraform state import, drift, multi-cloud cost | Code and UI exist at varying maturity; README labels these Beta. | No evidence in this audit establishes the full production support, operational ownership, or customer outcomes for these adjacent surfaces. | Defer from the MVP unless a validated customer need justifies them. |
| MCP gateway and former RAG/Agent PaaS/identity experiments | An MCP gateway is present in the repository architecture. README says RAG/Agent PaaS and some SSO/org/profile routes were retired from the active API. | Presence in the repository is not proof of a supported customer-facing runtime. | Reuse the gateway selectively; do not revive retired surfaces by default. |

## Material findings

1. **GCP confidence provenance is provider-blind.** [`confidence_provenance.py`](../../backend/confidence_provenance.py) looks up catalog confidence by comparing the source only to each entry's `aws` field, although [`services/mappings.py`](../../backend/services/mappings.py) includes `gcp` mappings. When no AWS-key match exists, the output reports zero catalog confidence and weights only the GPT component; it can also match an identically named AWS service rather than the GCP source. This affects the explanation/provenance record, not necessarily the base mapping itself. It needs a provider-aware fix and GCP-specific tests before confidence explanations are treated as evidence.

2. **IaC validation is advisory, not a release gate.** [`iac_generator.py`](../../backend/iac_generator.py) explicitly returns generated code with inline validation errors. The CI toolchain job can catch formatting and compiler diagnostics for its fixtures, but the current end-to-end smoke bypasses model generation and IaC CLI validation. There is no verified plan/what-if and policy pass for a real generated migration.

3. **The model-selection report overstates what its data supports.** [`model_bench_2026_05.md`](../eval/model_bench_2026_05.md) reports wins based on a small synthetic dry-run corpus (8 tasks across 6 workloads; several model/workload cells have only 1–2 samples). The report itself says the committed numbers are synthetic. The later benchmark plan in [`model_bench.py`](../../backend/eval/model_bench.py) keeps production routing unchanged pending live quality, cost, latency, throttling, safety, and rollback gates. The runtime defaults remain `gpt-4.1` with `gpt-4o` fallback in [`openai_client.py`](../../backend/openai_client.py). No benchmark compares the complete Archmorph workflow with a current coding agent or an expert baseline. The report's reference to issue #603 as a model rollout is stale: current #603 is a customer-facing documentation task.

4. **Full-spine CI proves contracts, not model quality.** The [`live-export-full-spine-smoke.yml`](../../.github/workflows/live-export-full-spine-smoke.yml) workflow starts the app locally in `test` mode with `ARCHMORPH_CI_SMOKE_MODE=1`. [`ci_smoke.py`](../../backend/ci_smoke.py) substitutes fixed analysis, HLD, and IaC data. This usefully checks route wiring and artifact formats, but does not exercise real vision, model mapping, or production-quality IaC. A separate CI job installs Terraform and Bicep and enables CLI validation, which is positive syntax/format evidence but not a safety or cloud-deployment guarantee.

5. **Current release evidence is limited.** The GitHub release list and exact `v4.3.0` tag lookup are empty. The README says the original GA gate and Beta-to-Live promotion were closed as superseded. The latest listed Production Architecture Package Smoke runs succeeded on 2026-05-03; they predate this audit by more than six months. The live sample still could not be exercised without sign-in.

6. **Data lifecycle claims remain unverified.** The live sample receipt showed retention/audit details unavailable and backend artifacts present; see [Phase 0](00_ORIENTATION.md) and the [data-lifecycle documentation](../security/data-lifecycle-trust-receipts.md). The displayed two-hour retention claim is not sufficient evidence of server-side deletion. No sample purge or other destructive action was performed.

## Test and repository evidence

- Targeted backend tests for analysis, mapping, IaC, pricing, HLD, and export completed successfully using the repository Python 3.13 environment. An initial run with system Python 3.9 failed during import because the project uses Python 3.10+ syntax; retrying with the repository environment passed. Optional external-tool checks were not enabled in that local run.
- CI has a dedicated Terraform/Bicep validation job that installs the tools and sets `ARCHMORPH_RUN_IAC_VALIDATE_TOOLS=1` plus `ARCHMORPH_ENABLE_TERRAFORM_CLI_VALIDATION=1`.
- The GitHub security workflow covers static analysis and dependency/container scanning, and the repository has extensive unit/contract tests. Those are meaningful engineering controls, not evidence that the migration recommendations are correct.
- Four open issues were listed during the audit: mappings quarterly review (#1313), trusted Azure migration decision workbench (#1128), API/artifact/state/repository coherence (#1235), and alert-recipient verification (#1334). The visible open PR list was primarily dependency updates. Open/closed issue state is not treated as an acceptance signal.

## Carry forward, reimagine, defer

**Carry forward:** the AWS/GCP-to-Azure focus, guided capture of migration constraints, human-reviewable exports, catalog freshness controls, security scanning, testable API boundaries, accessibility, and strict customer-free positioning.

**Reimagine:** make a typed architecture graph with evidence/provenance the source of truth; separate observed facts from inferred mappings and user assumptions; expose exact catalog/document/pricing evidence; and gate IaC on compiler, policy, and environment-specific preview results. Benchmark end-to-end outputs on held-out architectures, with objective metrics and expert review, not only synthetic LLM-judge scores.

**Defer or retire from the first release:** live scanner, deployment/rollback, credential vault, general-purpose multi-agent execution, gallery, collaboration, and other surfaces that do not directly improve the verified migration workflow. Keep those routes feature-gated and label them accurately.

## Gate A status

Phase 0 orientation and this static audit are complete. Live analysis quality, server-side retention/purge, exact Copilot plan/allowance, and some external identity/secret metadata remain blocked or unknown. The safe next action is a user review of the audit and landscape; no design-stage implementation, cloud provisioning, or decommissioning has started.
