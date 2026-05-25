# Roadmap: Trusted Azure Migration Decision Workbench

**Epic:** [#1128](https://github.com/idokatz86/Archmorph/issues/1128)
**Status:** In Progress — do not close until child themes are materially delivered
**Last updated:** 2026-05-25

---

## North Star

Turn an imperfect AWS/GCP architecture artifact into a **review-ready Azure migration decision package in under 15 minutes**.

## Strategic Bet

Archmorph becomes a **trusted Azure migration decision workbench**, not just an AI output generator.

---

## Proven Spine (Pre-Condition)

The following capabilities are already live and form the production spine this roadmap builds on:

- ✅ Authenticated SWA Google browser session
- ✅ Backend session exchange
- ✅ PDF upload
- ✅ Async analysis
- ✅ Azure service mapping
- ✅ User-owned result attribution
- ✅ Draw.io export via bearer session + export capability
- ✅ Healthy ACA/SWA production deployment

---

## Child Roadmap Themes

### Delivery Waves

Waves are sequenced by dependency. Each wave should reach Definition of Ready before coding begins.

---

#### Wave 0 — Production Release Gate ✅

| Issue | Title | Status |
|-------|-------|--------|
| [#1132](https://github.com/idokatz86/Archmorph/issues/1132) | Make authenticated production browser E2E a release gate | ✅ Closed/Completed |

**Summary:** The authenticated production browser E2E now runs as a post-deploy gate and scheduled synthetic (≥ every 4 hours). It covers SWA sign-in/session bridge, PDF/sample upload, async analysis completion, user-owned result attribution, Draw.io export using bearer session + export capability, and production health evidence. Failure blocks release or opens a P0 issue with screenshots, responses, revision SHA, and correlation IDs.

---

#### Wave 1 — Queue/Admission Controls and Richer Progress Semantics

| Issue | Title | Status | Shipped slice |
|-------|-------|--------|---------------|
| [#988](https://github.com/idokatz86/Archmorph/issues/988) | Production performance, quota, and memory guardrails for AI/export paths | 🔄 Open | — |
| [#1136](https://github.com/idokatz86/Archmorph/issues/1136) | Improve analysis progress semantics and queue/admission control | 🔄 Open | [PR #1156](https://github.com/idokatz86/Archmorph/pull/1156) ✅ shipped |

**Shipped via [PR #1156](https://github.com/idokatz86/Archmorph/pull/1156) (2026-05-25):**
- Explicit async analysis phases exposed in job status: `preprocessing → classifying → waiting_for_model → analyzing → validating → mapping → saving`
- `phase`, `updated_at`, elapsed, queue-wait, and running timing fields added to job status payloads
- Queue observability metrics: queued jobs count, active workers, oldest queued age, queued p95 age
- Visible progress heartbeats while SSE streams are idle

**Remaining for full closure of Wave 1:**
- #988: bounded per-worker OpenAI admission + Retry-After-aware retries, upload/session/cache memory accounting, cost/token observability for direct vision calls
- #1136: per-tenant/per-user limits for expensive analysis work; no silent UI gap longer than 6 seconds; queue age + OpenAI 429/timeout rate observable

**Wave 1 is required before Wave 2** (durable workspaces need reliable job state and admission control).

---

#### Wave 2 — Durable Workspaces + Trust/Evidence Layer

| Issue | Title | Status |
|-------|-------|--------|
| [#1133](https://github.com/idokatz86/Archmorph/issues/1133) | Introduce durable workspaces, analysis versions, and artifact records | 🔄 Open |
| [#1130](https://github.com/idokatz86/Archmorph/issues/1130) | Add trust and evidence layer for AI service mappings | 🔄 Open |

**#1133 Durable Workspaces** introduces customer-visible product records: Workspace, SourceAsset, Analysis, AnalysisVersion, Artifact, Decision/Risk, Audit/Event. Redis/hot stores remain for short-lived session/streaming; customer work persists in durable storage. Users can reopen saved analyses after browser refresh or session expiry.

**#1130 Trust/Evidence Layer** makes every AI mapping defensible: detection confidence, Azure mapping rationale, alternatives considered, known gaps, catalog/model freshness, and user override/confirmation status. Low-confidence mappings are flagged for review. Exports include a methodology/limitations section.

**Wave 2 is required before Wave 3** (the architect review queue and migration package need durable workspaces and defensible mapping evidence as their inputs).

---

#### Wave 3 — Architect Review Queue + Migration Package as Hero Outcome

| Issue | Title | Status |
|-------|-------|--------|
| [#1131](https://github.com/idokatz86/Archmorph/issues/1131) | Add Architect Review Queue for assumptions, risks, and low-confidence mappings | 🔄 Open |
| [#1129](https://github.com/idokatz86/Archmorph/issues/1129) | Make Migration Package the primary product outcome | 🔄 Open |

**#1131 Architect Review Queue** buckets: Assumptions, Low-confidence mappings, Architecture gaps, Cost/pricing warnings, Security/compliance concerns. Disposition actions: Accept, Edit, Mark as risk, Exclude from export. Deliverables are gated until required review items are accepted or explicitly retained as risks.

**#1129 Migration Package** becomes the hero output: Executive summary, source architecture inventory, Azure target mappings, source/target architecture diagrams, assumptions and unresolved decisions, risks/gaps/limitations, cost assumptions, IaC/HLD appendix, methodology and confidence notes. Individual exports remain available but secondary.

**Wave 3 is required before Wave 4** (data lifecycle receipt needs a concrete package to refer to; shareable snapshots need a completed package).

---

#### Wave 4 — Visible Data Lifecycle, Audit, and Trust Receipts + Role-Based Snapshots

| Issue | Title | Status | Shipped slice |
|-------|-------|--------|---------------|
| [#1135](https://github.com/idokatz86/Archmorph/issues/1135) | Add visible data lifecycle controls and trust receipt | 🔄 Open | [PR #1157](https://github.com/idokatz86/Archmorph/pull/1157) ✅ shipped |
| [#1134](https://github.com/idokatz86/Archmorph/issues/1134) | Add role-based shareable migration package snapshots | 🔄 Open | — |

**Shipped via [PR #1157](https://github.com/idokatz86/Archmorph/pull/1157) (2026-05-25):**
- Backend trust receipt builder attached to upload, restore, sync/async analysis completion, and purge responses
- Data lifecycle receipt panel replacing the purge-only workbench banner: shows retention class, export capability expiry, AI processing disclosure, backend artifact status, purge status, audit/security log boundary
- Purge confirmation visible after workbench reset; receipt downloadable as JSON
- Retention classes, receipt schema, purge semantics, and audit-log boundary documented

**Remaining for full closure of Wave 4:**
- #1135: full integration of receipt into Migration Package; orphaned artifact count metric
- #1134: expiring share snapshots, role-scoped views (Executive/Architect/DevOps/Security/FinOps), audited access, revocable links, visually distinct customer-private vs public-sample states

**Wave 4 is required before Wave 5** (enterprise readiness track needs durable audit/evidence controls).

---

#### Wave 5 — Enterprise Cloud Readiness Track

| Issue | Title | Status |
|-------|-------|--------|
| [#1137](https://github.com/idokatz86/Archmorph/issues/1137) | Build enterprise cloud readiness track: private ingress, DR, tenant isolation, evidence | 🔄 Open |

**#1137** covers: Front Door-only public ingress / private backend origin, regional DR plan and Azure OpenAI failover posture, tenant isolation model and per-tenant quotas, dependency SLO dashboard, release annotations in telemetry, and compliance/security evidence pack.

---

## Full Dependency Order

```
Wave 0 (#1132 ✅)
    ↓
Wave 1 (#988 🔄, #1136 🔄 — partial PR #1156 ✅)
    ↓
Wave 2 (#1133 🔄, #1130 🔄)
    ↓
Wave 3 (#1131 🔄, #1129 🔄)
    ↓
Wave 4 (#1135 🔄 — partial PR #1157 ✅, #1134 🔄)
    ↓
Wave 5 (#1137 🔄)
```

---

## Success Metrics

| Metric | Target | Notes |
|--------|--------|-------|
| Upload → analysis completion rate | Baseline first | Blocked by Wave 1 |
| Analysis → package export rate | Baseline first | Blocked by Wave 3 |
| Package save/share rate | > 0 | Blocked by Wave 4 |
| Day-7 saved workspace return rate | > 0 | Blocked by Wave 2 |
| Low-confidence mapping resolution rate | > 50% | Blocked by Wave 2/3 |
| Browser synthetic pass rate | ≥ 99% | #1132 ✅ delivered gate |
| Production E2E failure MTTR | < 2 h | #1132 ✅ delivered alerting |

---

## Governance Notes

- **Do not close this epic** unless all wave themes are materially delivered or explicitly superseded by newer issues.
- **Each child issue must reach Definition of Ready** (acceptance criteria clear, design agreed, no undiscovered blockers) before coding begins.
- **Do not duplicate** implementation work already assigned to child issues; coordinate through child issue comment threads.
- Shipped partial slices (PRs #1156, #1157) advance the relevant child issues but do not close them — full closure requires the remaining acceptance criteria to be met.
