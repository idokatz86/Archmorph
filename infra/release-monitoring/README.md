# Isolated release monitoring

**Plan only. No infrastructure apply or application rollout is authorized by the
planning workflow.**

This root is the single Terraform owner of four migration/bridge scheduled-query
rules and the dedicated critical email action group. It consumes the unchanged
[canonical alert specification](../monitoring/migration-alert-specs.json) and
reads metadata for existing Application Insights and Log Analytics resources.
It does not retrieve instrumentation keys, create a workspace, or modify IAM,
networking, Key Vault, database, application settings, or traffic.

## Scope and ownership

Expected first plan: **five creates, zero updates, zero deletes**.

| Role | Evaluation / window | Severity |
|---|---|---|
| Migration failure | 5 minutes / 15 minutes | 1 |
| Migration timeout | 5 minutes / 15 minutes | 1 |
| Missing success evidence | 5 minutes / 30 minutes | 1 |
| Customer degraded bridge | 1 minute / 5 minutes | 1 |

All query predicates, aggregation, threshold zero, failing periods, and
notification bindings come from the reviewed contract. Query validation remains
enabled. There are no dimension splits or additional notification receivers.
Alert action-group IDs are constructed from the existing verified resource-group
scope and the managed group's fixed name, retaining Terraform's resource
dependency. This makes membership concrete in the initial plan instead of
accepting an unknown provider-generated ID. Unknown or additional group bindings
remain approval-blocking.

The primary root no longer manages these five resources. Its
[non-destructive ownership declarations](../release-monitoring-ownership.tf)
prevent deletion of an existing deployment's monitors; unrelated primary alerts
read the critical group as a data source. The initial-plan verifier refuses to
continue if primary state or live inventory already contains these monitors.
That case requires a separate reviewed state-transfer/import plan, never dual
ownership, silent adoption, `terraform -target`, or hand-edited state.

The monitoring backend reuses the existing private migration-state
account/container but requires a distinct `MONITORING_TFSTATE_KEY`. This is a
separate state identity, not a new storage or IAM boundary. Its key must not
collide with either existing state. Do not create a public backend or use
storage-account keys/SAS.
Terraform's Azure backend initializes an empty state blob during planning. A
retry keeps the same key and must prove a version-4, serial-zero state with no
resources, outputs, or check results. Any managed history/content blocks initial
planning and requires separate adoption review. The monitoring lineage/digest is
captured and must remain unchanged throughout the plan; keys are never rotated
or deleted to bypass this check.

## Planning procedure

1. Merge reviewed planning support only after its tests pass. The application
   rollout remains separately paused.
2. Configure the three monitoring settings documented in
   [SECRETS.md](../../.github/SECRETS.md). Use the existing owner-approved
   `ALERT_EMAIL`; do not print or copy it into source files.
3. Restore the existing private-network ephemeral runner if necessary, without
   creating new infrastructure or widening permissions.
4. Dispatch [Release monitoring plan](../../.github/workflows/release-monitoring-plan.yml)
   on protected `main`, supplying the exact reviewed `source_sha`.
5. The workflow validates telemetry linkage, requires absence of existing
   monitoring ownership, initializes the isolated backend, validates the root,
   and saves a real Terraform binary plan.
6. [The verifier](../../scripts/verify_release_monitoring.py) allows only the five
   intended creates, exact receiver, canonical alert fields, known security
   values, and six output identities. It rejects updates, replacements, missing
   resources, extra receivers/dimensions, provisioners, and unrelated reads.
   Primary, migration, and pristine monitoring state are re-read; all three
   lossless identities must be unchanged during planning.
7. The plan, logs, metadata, provider lock, canonical spec, and private state
   evidence are retained only in an encrypted seven-day artifact. The existing
   AES-256-CBC/PBKDF2 review-bundle convention is retained; the encrypted artifact
   hash is published separately in the run summary. This workflow does not
   implement an automatic decrypt/apply path. Plaintext evidence is removed.
8. Present the exact source, plan SHA-256, encrypted artifact SHA-256, provider
   lock, five-resource diff, state identities, recipient source, and cost before
   requesting explicit saved-plan apply approval.

There is no apply input or apply job. A future apply implementation must validate
the approved immutable artifact/hash, exact source and provider lock, current
state, and rollout ownership. Plan success is not permission to apply it.

## Release output contract

After a separately approved apply, the deployment gate reads only this root's:

- `migration_failure_alert_id`
- `migration_timeout_alert_id`
- `migration_missing_evidence_alert_id`
- `bridge_customer_degraded_alert_id`
- `application_insights_resource_id`
- `critical_action_group_id`

Missing outputs remain release-blocking. The existing
[applied-resource attestation](../../scripts/verify_migration_alerts.py) still
compares enabled state, severity, scopes, queries, timing, aggregation, thresholds,
and action-group IDs against the canonical specification. There is no fallback
to stale primary outputs or automatically discovered unrelated alert IDs.

## Cost estimate and remaining approval gates

The Azure Retail Prices API returned the following West Europe USD consumption
meters during the October 2026 review:

- Five-minute system-log rule: $1.50 per month, three rules = $4.50.
- One-minute system-log rule: $3.00 per month, one rule = $3.00.
- **Base alert estimate: $7.50/month**, for these non-dimension-split rules.
- The email meter lists a zero-price tier through 1,000 units and $0.00002 per
  email thereafter. Allowance availability is billing-scope dependent.

Source: [Azure Monitor pricing](https://azure.microsoft.com/pricing/details/monitor/)
and [Azure Retail Prices API](https://prices.azure.com/api/retail/prices).
This excludes existing telemetry ingestion/retention, taxes, discounts, and
temporary runner compute. It is not a cost ceiling or an apply approval.

A live aggregate-only query probe returned `RemoteServerFault`; query execution
at the selected telemetry scope is **not yet verified**. Do not claim that a
successful Terraform plan proves alert execution or delivery. Before apply,
confirm current pricing, approved notification recipient, query compilation,
and the test window. After apply, verify exact live resource metadata and approved
synthetic notifications without using customer data or starting a real migration.

The missing-evidence query is retained without semantic changes. Validate its
behavior for a normal in-progress migration as well as missing terminal evidence;
any refinement requires a separately reviewed canonical-spec change.
