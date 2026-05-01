# CISO Threat-Model Session Brief — Sprint 1 Week 1

**Initiative:** Retention Initiative / E2 Multi-Cloud Beta
**Session type:** Batched threat model — Azure refresh + AWS new + GCP new
**Why batched:** Three sequential CISO/Legal gates over 4 sprints serialize and break the plan. Front-loading all three threat models into one session lets Legal review run in parallel rather than sequentially. This is the single calendar reservation that makes the 90-day window feasible.
**Owner:** CTO (sponsor) → CISO Master (chair)
**Classification:** Internal — confidential
**Status:** Calendar reservation in progress

---

## Logistics

| Field | Value |
|---|---|
| Target window | Week of May 4–8, 2026 (Sprint 1 Week 1) |
| Length | 3 hours, single session |
| Format | In-person preferred; hybrid acceptable; recording opt-in only |
| Pre-read deadline | 48 hours before session |
| Output deadline | Threat model + three signed sign-off gate templates within 5 business days of session |

If the session cannot land in Sprint 1 Week 1, escalate to CTO the same day. Every day of slip compresses Sprint 3 AWS Beta gate margin.

---

## Required attendees (no proxies — these names sign artifacts)

| Role | Why required |
|---|---|
| **CISO Master** | Chair. Owns final security sign-off authority per cloud. |
| **Cloud Master** | Owns connector implementation. Primary technical interface to CISO across all three clouds. |
| **Internal backend lead (Cloud team)** | Designs auth implementation; pairs with contractors on every auth decision. |
| **Legal / Privacy lead** | Owns final legal sign-off authority per cloud. Must be in the room to scope the gate templates, not asked to retroactively review. |
| **IT / Identity admin** | Owns sandbox account procurement, federated trust setup, and corporate-identity perimeter decisions. |

## Optional attendees

| Role | Why optional |
|---|---|
| Two E2 contract backend engineers | Strongly preferred to attend if onboarded. Catches auth model surprises before they land in PRs. Mandatory if onboarded by session date. |
| Frontend Master | Optional; surfaces if any threat model finding affects cloud-picker UX or per-cloud badging. |
| QA lead | Optional; helpful for sandbox fixture and per-cloud test matrix decisions. |

---

## Pre-reads (sent 48 hours in advance)

1. **Existing Azure connector design** — reference pattern. Auth model: Managed Identity. Rate limits, telemetry redaction, error handling already production-validated.
2. **Proposed AWS auth model** — cross-account IAM role assumption with external ID. Role-trust policy draft. No long-lived access keys anywhere in the design.
3. **Proposed GCP auth model** — Workload Identity Federation. Identity pool + provider design. Federated trust draft. No JSON service account files anywhere.
4. **Read-only enforcement design** — two-layer enforcement: SDK-level (verbs blocked: `Create*`, `Update*`, `Delete*`, `Put*`, `Set*`) AND policy-level (IAM policy / GCP IAM role permissions explicitly read-only). Both layers required, not redundant.
5. **Archmorph data classification doc** — what data classes the connectors will touch, what classification tier each falls under, what redaction rules apply to telemetry.
6. **EVENT_TAXONOMY.md** — Sprint 0 deliverable, retention telemetry definitions. Confirms what connector activity gets recorded for analytics, what gets redacted, what never leaves the customer environment.
7. **Contractor authorization memo** — `RETENTION_E2_CONTRACTOR_AUTHORIZATION.md`. Constraints, pair-work requirements, sandbox-only access.

---

## Agenda (3 hours)

### Block 1 — Read-only enforcement model (30 min)

- Confirm two-layer enforcement is the required posture (SDK + policy).
- Walk the SDK-level verb-block implementation across all three clouds.
- Walk the policy-level least-privilege role/permission set per cloud.
- Define the test that proves a connector cannot mutate state — what does "proven read-only" mean as an artifact CISO will sign?
- **Decision required:** sign-off artifact format for read-only enforcement (one model, applies to all three clouds).

### Block 2 — AWS auth model deep dive (40 min)

- Cross-account IAM role assumption mechanics.
- External ID generation, rotation policy, storage location.
- Role trust policy review — who is the trusted principal, what conditions are required?
- Threat model: confused deputy, stale external ID, customer trust-policy drift, role assumption from non-Archmorph principals.
- Telemetry: what's logged, what's redacted, where logs land, retention window.
- **Decision required:** AWS Beta sign-off gate template — what artifacts CISO + Legal need to sign at Sprint 3 to clear AWS for Beta GA.

### Block 3 — GCP auth model deep dive (40 min)

- Workload Identity Federation setup — identity pool, provider, federated trust.
- Federated trust scope: which Google Cloud services, which projects, which roles.
- Threat model: federated trust scope drift, identity pool compromise, provider misconfiguration, cross-project privilege escalation.
- Telemetry: same redaction model as AWS — confirm parity.
- **Decision required:** GCP Beta sign-off gate template — what artifacts CISO + Legal need to sign at Sprint 4 to clear GCP for Beta GA.

### Block 4 — Azure refresh (20 min)

- Confirm existing Managed Identity threat model is still current (no architecture changes since v2.x).
- Identify any Sprint 1–6 changes that would invalidate the existing model.
- **Decision required:** Azure GA sign-off gate template — confirm or update. Will be retroactively applied at Sprint 5.

### Block 5 — Cross-cutting concerns (30 min)

- **Secret hygiene:** confirm zero long-lived credentials across all three clouds. Sweep for places secrets could leak: env vars, logs, telemetry, error messages, support tooling, debug endpoints.
- **Telemetry redaction:** unified redaction policy across all three clouds. Confirm `EVENT_TAXONOMY.md` events do not carry cloud-resource identifiers, customer principal names, or anything classifiable as PII / customer data.
- **Audit trail:** what audit events the connector emits, where they go, who reviews them, retention window.
- **Incident response:** what happens if a connector is compromised or a customer's trust policy is misconfigured? Kill-switch design? Per-customer revocation?
- **Decision required:** unified cross-cutting policy doc, applies to all three clouds.

### Block 6 — Sandbox + procurement (20 min)

- IT-owned dedicated AWS account for QA fixtures.
- IT-owned dedicated GCP project for QA fixtures.
- Federated trust setup between sandbox accounts and Archmorph dev tenants.
- IT runbook for sandbox provisioning, rotation, and decommissioning.
- **Decision required:** procurement ticket + IT runbook owner + target completion date (Sprint 1 Day 5).

---

## Decisions to leave the room with

| # | Decision | Owner | Required by |
|---|---|---|---|
| 1 | Read-only enforcement sign-off artifact format | CISO | End of session |
| 2 | AWS Beta gate template (artifact list) | CISO + Legal | End of session |
| 3 | GCP Beta gate template (artifact list) | CISO + Legal | End of session |
| 4 | Azure GA gate template (confirm or update) | CISO + Legal | End of session |
| 5 | Cross-cutting policy doc owner + draft due date | CISO | End of session |
| 6 | Sandbox procurement ticket + IT runbook owner | IT lead | End of session |
| 7 | Threat model document owner + due date (target: 5 business days) | Cloud Master | End of session |

If decisions 1–4 do not leave the room, the 90-day window is at risk. Escalate to CTO same day.

---

## Outputs (deliverables within 5 business days of session)

1. **Signed threat model document** — covers all three clouds, two-layer read-only enforcement, cross-cutting concerns. Signed by CISO and Cloud Master.
2. **Three sign-off gate templates** — AWS Beta (Sprint 3), GCP Beta (Sprint 4), Azure GA (Sprint 5). Each template lists exact artifacts CISO + Legal need to clear the gate.
3. **Cross-cutting policy doc** — unified secret hygiene, telemetry redaction, audit trail, incident response. Applies to all three clouds.
4. **Sandbox procurement ticket** — filed with IT, due Sprint 1 Day 5.
5. **IT runbook** — sandbox provisioning, rotation, decommissioning. Owned by IT lead.

---

## Risks if this session does not happen on time

| Risk | Impact |
|---|---|
| Slip into Sprint 1 Week 2 | Sprint 3 AWS gate margin compressed. Recoverable. |
| Slip into Sprint 2 | AWS gate at risk. Either AWS slips to Sprint 4 (collapses with GCP gate — high risk) OR scope-cut required. |
| Sequential gate review (no batched session) | GCP slips to Phase-2. E2 ships Azure + AWS only. User override partially defeated. |
| Legal/Privacy not in the room | Gate templates retroactively rebuilt by Legal — historically adds 1–2 sprints per cloud. 90-day window broken. |

---

## Companion documents

- [RETENTION_E2_CONTRACTOR_AUTHORIZATION.md](RETENTION_E2_CONTRACTOR_AUTHORIZATION.md) — funding decision for the +2 backend engineers
- [EVENT_TAXONOMY.md](EVENT_TAXONOMY.md) — E6 retention telemetry, Sprint 0 (shipped)
- [SECURITY_ASSESSMENT.md](SECURITY_ASSESSMENT.md) — current security posture baseline

---

**Sponsor:** CTO
**Chair:** CISO Master
**Brief drafted:** April 30, 2026
**Status:** Awaiting calendar lock — week of May 4–8, 2026
