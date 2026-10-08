# Release monitoring prerequisite plan

**Status: proposed; awaiting owner approval. No monitoring apply is authorized.**

This is a scoped implementation and validation plan, not an executed Terraform
plan. Production deployment remains paused until the required monitoring is
provisioned and independently attested.

## Verified starting point

- Release [37728767374](https://github.com/idokatz86/Archmorph/actions/runs/37728767374)
  passed private image builds, scans, attestations, environment alignment, and
  lossless migration plan/state integrity.
- Migration bootstrap applied one new manual Job, with zero updates or destroys.
  The Job is provisioned in the existing live app environment, but has no
  executions. The application still routes entirely to its previous revision.
- The immediate post-bootstrap CLI issue is a separate small fix:
  `az keyvault show` requires name/resource-group selectors, not `--ids`.
  The supported live metadata query confirms the migration identity's Get policy.
- The next gate requires four scheduled-query alerts and a critical action group.
  Resource inventory found none of these. An unrelated Application Insights
  Smart Detection group exists and must not be repurposed without approval.
- All six required release-monitoring output values are absent from the captured
  primary Terraform state.
- An existing Application Insights component is workspace-based, linked to an
  existing Log Analytics workspace. Reuse those resources; do not create a second
  telemetry pipeline or change ingestion/retention as part of this work.
- Current production Terraform apply requires approved infrastructure hardening
  and Key Vault RBAC mode. The live vault is in access-policy mode, and those
  apply-enabling variables are absent. Turning them on would be a separate
  security migration, not a monitoring-only fix.

Concrete resource identifiers and notification addresses stay in private
deployment configuration, not this document.

## Exact monitoring scope

Use the existing definitions in [infra/main.tf](../../infra/main.tf) and the
[canonical alert specifications](../../infra/monitoring/migration-alert-specs.json).
Do not invent alternative queries or weaken
[the applied-alert verifier](../../scripts/verify_migration_alerts.py).

| Role | Signal / aggregation | Evaluation | Window | Threshold |
|---|---|---|---|---|
| Migration failure | `migration_failed` count | 5 minutes | 15 minutes | Greater than 0 |
| Migration timeout | `migration_timed_out` count | 5 minutes | 15 minutes | Greater than 0 |
| Missing evidence | Started executions without success evidence | 5 minutes | 30 minutes | Greater than 0 |
| Customer degraded | `bridge_customer_degraded` count | 1 minute | 5 minutes | Greater than 0 |

All four are enabled severity-1 rules, use the exact application/owner predicates
in the canonical specification, and reference the same approved critical action
group. Failing periods remain 1 of 1 and aggregation remains Maximum.

Create one dedicated action group with the approved on-call email or distribution
list and common alert schema enabled. Confirm ownership and delivery with the
recipient; the presence of `ALERT_EMAIL` alone does not prove a monitored mailbox.
Do not add webhook, SMS, voice, automation, or production-changing actions.

## Implementation options

### A. Isolated release-monitoring state (recommended)

Extract only the four rules and critical action group into a small, explicitly
owned monitoring Terraform root. Read the existing Application Insights component
and workspace through data sources. Use the existing private state-storage
service with a dedicated state identity; do not provision a new account or expose
the backend publicly.

Preserve the canonical resource definitions/specification rather than maintaining
two diverging copies. Reconcile the primary root's declarations and any other
references to the critical group so no resource can be managed by two states.
First verify the five intended addresses are absent from primary state; if any
already exist, use a separately reviewed non-destructive state transition/import.

Update the release gate to read the six outputs from the explicit monitoring
state and retain exact live-resource attestation against the canonical spec.
Do not fallback to arbitrary "latest" outputs, silently skip the gate, or leave
the primary root able to recreate conflicting resources later.

This requires a reviewed code/configuration PR but avoids enabling unrelated
Key Vault, networking, database, or application changes merely to install alerts.

### B. Reconcile and apply the existing primary root

This preserves the current output-reading location, but it is acceptable only if
the full saved plan is demonstrably monitoring-only and the existing apply
prerequisites are satisfied without broad changes.

Given the live estate's drift and current hardening/RBAC prerequisites, this is
not the default choice. Do not use `terraform -target`, edit remote state by hand,
disable guard checks, or enable hardening flags merely to force a narrow apply.
If the plan proposes unrelated mutations, stop and obtain a separate approval.

## Proposed execution and approval gates

1. **Confirm owner inputs (no mutation).**
   - Approve option A or B.
   - Confirm existing telemetry resource identity, private state ownership,
     intended on-call recipient, notification-test window, and cost ceiling.
   - Confirm the existing private runner and OIDC identity can read telemetry
     metadata and manage only the approved monitoring scope. Any new role grant
     requires a separately reviewed least-privilege assignment.

2. **Implement the scoped PR and deterministic tests.**
   - Reuse the four definitions and one action-group contract.
   - Test that the plan rejects deletes/replacements, new telemetry resources,
     application/network/identity changes, unexpected receivers, and extra rules.
   - Preserve the existing canonical query/severity/scope/threshold verifier.
   - Keep deployment blocked until every output and applied rule verifies.

3. **Produce the actual saved Terraform plan, without apply.**
   - Run from the approved private-network runner against explicit state.
   - Pin the source SHA and provider lock; retain plan hash and state identities.
   - Encrypt any plan/state evidence using the existing reviewed artifact pattern.
   - For an empty monitoring state, expected managed changes are exactly five
     creates: four alerts and one action group. Existing telemetry is read-only.
   - Reconcile the linked Application Insights component's actual name instead
     of allowing the old primary naming pattern to create a duplicate.
   - Stop on any unexpected state ownership or resource mutation.

4. **Present evidence for explicit apply approval.**
   Approval must name the exact code SHA, plan hash, five-resource change set,
   telemetry scope, recipient, incremental cost estimate, and notification test.
   A request to prepare this plan is not approval to apply it.

5. **Apply only the approved saved plan.**
   - Use the existing production environment boundary and private rollout
     coordination lease/checkpoints.
   - Reverify plan, provider lock, lineage/serial, and source identity immediately
     before applying.
   - Do not touch application traffic, run a database migration, modify secrets,
     change Key Vault authorization, or open public network access.

6. **Attest and test before resuming a release.**
   - Read applied rule metadata through Azure ARM and run the existing verifier.
   - Confirm action-group receivers and perform an approved notification test.
   - Confirm canonical KQL compiles at the selected Application Insights scope
     and returns the expected columns from the actual telemetry pipeline.
   - Use synthetic, non-customer execution markers during the approved test window;
     prove failure, timeout, missing evidence, and degraded signals reach on-call.
     Do not trigger a real migration or customer incident to test alerts.
   - Check the missing-evidence rule's behavior during a normally running
     migration as well as missing terminal evidence. Any query-semantic change
     requires its own reviewed spec/verifier update, not an unreported adjustment.
   - Retain successful attestation and delivery evidence, then request resumption
     of the normal application release and its post-deployment checks.

## Required output contract

All values must name the exact applied resources:

- `migration_failure_alert_id`
- `migration_timeout_alert_id`
- `migration_missing_evidence_alert_id`
- `bridge_customer_degraded_alert_id`
- `application_insights_resource_id`
- `critical_action_group_id`

Read these from their single authoritative Terraform owner. An output is not
proof that an alert is enabled, has the right query/scope, or delivers a message;
the release verifier and notification evidence remain mandatory.

## Cost and operational constraints

Incremental footprint: four log-query rules (three five-minute and one one-minute
evaluation) plus one email action group; reuse the existing telemetry services.
Alert evaluations, log queries, ingestion, and notifications can be billable.
No price quote or cost approval has been obtained. Estimate the actual regional
increment with current Azure Monitor pricing and confirm the owner's ceiling
before apply. Do not change retention, sampling, or tier to hide the cost.

The existing release runner is ephemeral and deregisters after a job. Runner
availability must be verified before plan/apply, without converting it to an
unrestricted persistent public-repository runner. An idle VM's running cost must
not be confused with monitoring cost.

## Rollback and stop conditions

Application production remains unchanged while monitoring is prepared. If
monitoring provisioning or delivery verification fails, leave application release
blocked. Repair only the scoped resources through a new reviewed plan; do not
delete telemetry, disable private networking, bypass attestation, or resume
migration because some alerts exist.

Restoring the previous Terraform configuration is not permission to destroy newly
created monitors. Any removal or receiver change needs explicit review. Retain
diagnostic evidence without storing tokens, connection strings, state contents,
or customer payloads in public artifacts.

## Approval checklist

- [ ] Owner approves implementation option and single state owner.
- [ ] On-call recipient and notification-test window confirmed.
- [ ] Runtime telemetry resource and KQL scope verified.
- [ ] Scoped OIDC permissions and private runner availability confirmed.
- [ ] Actual saved plan reviewed: five expected creates, no unrelated mutations.
- [ ] Incremental cost estimate accepted.
- [ ] Explicit approval granted for that exact saved-plan apply.
- [ ] Applied resources, all six outputs, live attestation, and notification tests pass.
- [ ] Application release resumption separately authorized.
