# CTO Authorization — E2 Multi-Cloud Beta Contractor Funding

**Decision date:** April 30, 2026
**Decision owner:** CTO
**Initiative:** Retention Initiative / E2 Multi-Cloud Beta
**Authorization type:** Capacity expansion (contractor)
**Classification:** Internal — confidential
**Status:** APPROVED — execute immediately

---

## Decision

Authorize **two contract backend engineers** to join the E2 multi-cloud Beta workstream for **Sprints 1–4 (≈ 6 weeks)** of the Retention Initiative.

This authorization removes the single critical-path risk surfaced by the Scrum Master in the April 30 re-plan: that three sequential CISO/Legal sign-off gates plus a +2-engineer capacity gap would otherwise force GCP out of the 90-day window and reduce E2 GA to Azure + AWS only.

**Outcome bought with this authorization:** GCP stays in the 90-day window. E2 ships GA across all three clouds (Azure + AWS + GCP) in Sprint 6.

---

## Scope

### What contractors will work on

| Sprint | AWS pair | GCP pair |
|---|---|---|
| 1 | Provider abstraction refactor + AWS connector skeleton | GCP design spike + WIF prototype |
| 2 | AWS connector implementation (cross-account IAM + external ID) | GCP connector implementation (Workload Identity Federation) |
| 3 | AWS Beta gate hardening; cross-cloud test matrix | GCP connector implementation continued |
| 4 | AWS Beta hardening; per-cloud parity for `#233` dep graph + `#234` cost drill-down | GCP Beta gate hardening; cross-cloud test matrix |

### What contractors will NOT work on

- No write paths. Read-only enforcement at SDK + policy layer is non-negotiable.
- No production credential handling; sandbox accounts only.
- No customer-facing UI. Frontend changes route through Frontend Master.
- No solo work on auth model design — pair with the internal Cloud Master lead at every auth decision point.

---

## Constraints (non-negotiable)

1. **Read-only guardrail** — connectors must be incapable of `Create*`, `Update*`, `Delete*`, `Put*`, `Set*` operations at the SDK layer AND blocked again at the policy layer. Two-layer enforcement is mandatory.
2. **Zero long-lived credentials** — no static access keys, no JSON service-account files. AWS via cross-account IAM role + external ID; GCP via Workload Identity Federation; secrets never written to env, logs, or telemetry.
3. **Pair with internal lead** — every auth-related decision must be made jointly with the internal Cloud Master backend lead. Contractors do not unilaterally land auth-related PRs.
4. **NDA + background check** before workspace access is provisioned.
5. **Sandbox-only access** — dedicated AWS account and GCP project for QA fixtures. No access to production tenants, customer data, or shared corporate identity perimeter.
6. **Hard end-date Sprint 4 close.** No extension absent written CTO sign-off and a new authorization memo.

---

## Selection criteria

Required:
- 5+ years backend Python (FastAPI or equivalent async framework).
- Production experience with both AWS IAM (cross-account roles, external ID) AND GCP IAM (WIF, identity pools, identity providers). Single-cloud generalists do not qualify for this engagement.
- Demonstrated track record on read-only / least-privilege scanner or observability tooling — not generic "AWS/GCP experience."
- Clear sample of prior pair-work with internal teams; no lone-wolf profiles.

Preferred:
- Prior experience with Azure connector parity (since Azure connector is the reference pattern).
- Prior CISO/Legal sign-off cycle experience — knows what artifacts gates require.

Disqualifying:
- Anyone who proposes long-lived credentials or "we'll fix the read-only enforcement later."
- Anyone unwilling to pair on auth decisions.

---

## Reporting and governance

| Function | Owner |
|---|---|
| Day-to-day technical lead | Cloud Master |
| Sprint accountability | Scrum Master |
| Escalation path | CTO |
| Security gate authority | CISO Master (per-cloud sign-off) |
| Legal gate authority | Legal/Privacy lead (per-cloud sign-off) |
| Cadence | Daily standup with internal Cloud Master pair; weekly Scrum Master sync; bi-weekly CTO check-in |

The contractors do **not** sit on the architecture review board, do **not** make build-vs-buy decisions, and do **not** speak for Archmorph externally.

---

## Off-ramp

This authorization auto-expires at the end of Sprint 4. Three off-ramp scenarios:

1. **Plan succeeds (E2 on track at end of Sprint 4):** contractors offboard. Internal team carries Sprint 5–6 hardening.
2. **Plan slips on one cloud only:** CTO decides whether to extend one pair (single new authorization memo) or drop the slipping cloud to Phase-2.
3. **Plan slips on both clouds:** CTO scope-cut decision — Azure + AWS only, GCP defers to Phase-2. Contractors offboard at Sprint 4 regardless.

There is no automatic renewal. Silence does not equal extension.

---

## Sourcing path

Cloud Master is authorized to begin sourcing immediately via:
- Existing trusted contractor network (preferred — faster onboarding, known security posture).
- Vetted contractor agencies with defense / regulated-industry track record (acceptable fallback).
- Marketplace platforms (last resort — only with extra reference-check rigor).

Target time-to-start: contractors paired and productive by **Sprint 1 Day 3**. If sourcing slips past Sprint 1 Week 1, escalate to CTO same day — every day of slip compresses GCP gate margin.

---

## Acceptance criteria for this authorization

This memo is considered satisfied when:

- [ ] Both contractors signed and onboarded by Sprint 1 Day 3.
- [ ] Sandbox AWS account and GCP project provisioned by Sprint 1 Day 5.
- [ ] First AWS connector commit lands by Sprint 1 Day 7, paired with internal lead.
- [ ] First GCP design spike committed by Sprint 1 Day 7.
- [ ] CISO Sprint 1 Week 1 threat-model session attended by both contractors.
- [ ] Zero auth-related PRs land without internal pair sign-off through end of Sprint 4.
- [ ] Both contractors offboarded cleanly at end of Sprint 4 unless explicitly re-authorized.

---

## Companion documents

- [RETENTION_CISO_THREAT_MODEL_BRIEF.md](RETENTION_CISO_THREAT_MODEL_BRIEF.md) — Sprint 1 Week 1 CISO session brief
- [EVENT_TAXONOMY.md](EVENT_TAXONOMY.md) — E6 retention telemetry (Sprint 0, shipped)

---

**Signed:** CTO
**Date:** April 30, 2026
