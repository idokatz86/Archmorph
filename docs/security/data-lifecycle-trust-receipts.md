# Data Lifecycle Trust Receipts

Archmorph treats uploaded architecture diagrams and derived analysis payloads as ephemeral customer content. The trust receipt is the customer-safe record of what the current analysis stored, when it expires, how export capability is scoped, and what remains after purge.

## Retention Classes

| Class | Scope | Default retention window | Purge behavior |
| --- | --- | ---: | --- |
| `ephemeral-analysis` | Uploaded bytes, analysis session payload, project diagram index, generated artifact capability state, queued analysis job state, and IaC chat state for a diagram | 2 hours | Deleted immediately by `DELETE /api/diagrams/{diagram_id}/purge` |
| `security-audit` | Operational metadata such as correlation ID, project ID, event type, and deletion outcome | 30 days | Retained after customer content purge |

The `security-audit` class must not contain uploaded diagram bytes, prompts, generated customer artifacts, API keys, bearer tokens, or export capability tokens.

## Receipt Schema

Every receipt uses `schema_version: 2026-05-25` and includes:

- `receipt_id`: generated opaque receipt identifier.
- `correlation_id`: customer-safe run identifier, currently the diagram ID.
- `diagram_id` and `project_id`: identifiers needed for support and audit correlation.
- `retention`: retention class, content TTL, uploaded timestamp, and expiry timestamp.
- `export_capability`: whether a one-time export capability was issued and its remaining TTL.
- `ai_processing`: processing purpose and model-training disclosure.
- `artifacts`: backend artifact presence or deletion status.
- `purge`: deletion status, server deletion confirmation, and the required client cache action.
- `audit_security_logs`: audit retention boundary and customer-content exclusion.

## Purge Semantics

The purge endpoint deletes server-side customer content for the current diagram: uploaded bytes, analysis session payload, project index membership, share records, export capabilities, async jobs/events, and IaC chat state. The response includes a purge receipt that confirms which artifact groups were deleted.

The purge receipt also reports `orphaned_artifact_count` and emits purge success/orphan detection metrics (`diagram_purge_succeeded` or `diagram_purge_with_orphans`) so support and security teams can monitor data-deletion outcomes.

The browser must clear the current diagram session cache after a successful purge. The required client cache targets are:

- `sessionStorage:archmorph_session_<diagram_id>`
- `sessionStorage:archmorph_img_<diagram_id>`
- `sessionStorage:archmorph_session`
- `sessionStorage:archmorph_active_diagram`
- `sessionStorage:archmorph_pending_upload_reauth`

The frontend keeps the purge receipt visible so the user can download it as JSON.

## Migration Package

`POST /api/diagrams/{diagram_id}/export-package` now includes `analysis/trust-receipt.json` so lifecycle disclosures can travel with exported migration handoff artifacts.

## Non-Goals For This Slice

This slice does not introduce durable workspace records, historical analysis versions, or long-lived artifact ledgers. Those belong to the durable workspace work tracked separately in #1133.