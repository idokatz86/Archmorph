# Archmorph Event Taxonomy — v1.0.0

**Status:** Sprint 0 of the Archmorph Retention Initiative (E6).
**Owner:** PM Master (canonical), Backend Master (emit), Frontend Master (emit).
**Source of truth:** [`backend/retention.py`](../backend/retention.py) — `CANONICAL_EVENTS`.

---

## Why this exists

The retention initiative ships measurement before any feature change.
Every product surface that wants to count toward Day-7 return rate, magic-link
claim rate, or any downstream KPI must emit one of the canonical events below.

A new event name must NOT be invented ad-hoc. To add an event, append it to
`CANONICAL_EVENTS` in `backend/retention.py` and update this document in the
same PR. The contract test enforces that the in-code dictionary equals the
table below.

---

## Canonical events

| Event | Emitter | Trigger | Notes |
|---|---|---|---|
| `page_view` | Frontend | User loaded any SPA page | Already emitted via `/api/analytics/events`. |
| `upload_started` | Frontend | User initiated a diagram upload | Fires on first byte of upload, not on completion. |
| `analysis_complete` | Backend | Vision analysis finished and mappings rendered | Bound to the analysis result session id. |
| `questions_answered` | Frontend | User completed the guided migration questions | Submit-once event; do not refire on edits. |
| `iac_generated` | Backend | IaC generation finished and artifact is available | Per format (Terraform / Bicep / CloudFormation). |
| `export_completed` | Frontend | User downloaded an artifact (IaC, HLD, report) | Do NOT fire on preview opens. |
| `account_claimed` | Backend | Anonymous user claimed an account via magic-link | E1 dependency — wired in Sprint 2. |
| `project_returned` | Backend | User returned to a previously-created project | E1 dependency — wired in Sprint 1/2. |

---

## Day-7 return rate definition

- **Cohort day D** = the UTC date on which an anonymous identifier was first
  observed (server-issued cookie via `record_visit_from_request`).
- **Day-7 returned** = the same anonymous identifier observed again on
  `D + 7 ± window_days` (default ±1, i.e. days 6 / 7 / 8).
- **Day-7 return rate** for cohort `D` = `|returned| / |cohort|`.
- A cohort is **complete** when `today >= D + 8`. The admin baseline view
  aggregates only complete cohorts.

The KPI target (CTO directive) is **>= 35% within 90 days of E1–E4 ship**.

---

## Privacy posture

- The anon identifier is a **server-issued random UUID** stored in a
  first-party HttpOnly cookie. Never client-generated.
- The cookie value is **never persisted server-side**. Only its
  HMAC-SHA256(salt, value) hash is stored.
- No IP, no User-Agent, no headers, no email — none — are attached to a
  retention record.
- `DNT: 1` and `Sec-GPC: 1` headers cause recording to be skipped.
- The whole subsystem is gated by `RETENTION_TRACKING_ENABLED=true`. Off by
  default; flipped on once CISO sign-off lands and the privacy notice is
  updated.
- Aggregate-only output. There is no per-user retention API.

---

## Admin endpoints

All require `Authorization: Bearer <admin-jwt>`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/admin/retention/day7` | Single-cohort Day-7 result. |
| GET | `/api/admin/retention/baseline` | Rolling N-day baseline with trend. |
| GET | `/api/admin/retention/taxonomy` | This taxonomy as JSON. |

All are mirrored at `/api/v1/...` by the v1 aggregator.

---

## Versioning

Bump the version on this page and on the `version` field returned by
`/api/admin/retention/taxonomy` whenever an event is added, removed, or
renamed. Renames are breaking changes.
