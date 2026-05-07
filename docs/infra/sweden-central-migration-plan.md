# Sweden Central One-Region Migration Plan

> Issue: [#783](https://github.com/idokatz86/Archmorph/issues/783)
> Status: Planning artifact only
> Production impact: None. Do not apply this plan without an approved change window.

## Executive Decision

Migrate Archmorph to Sweden Central by building a parallel regional stack, validating it, shifting traffic gradually, and retiring old regions only after zero-traffic proof. Do not edit existing Terraform `location` or `openai_location` values and apply in place. Most Azure regional resources in this stack are ForceNew or operationally risky to move in place.

The current production-ready baseline remains West Europe for the application and Azure OpenAI. East US and West Europe resources must stay available as rollback paths until Sweden Central passes readiness, dark-launch, traffic-shift, soak, and rollback drills.

## Scope

In scope:

- Terraform migration strategy for a new Sweden Central stack.
- Availability and quota readiness gates.
- Readiness evidence checklist in [sweden-central-readiness-report.md](sweden-central-readiness-report.md).
- Data/configuration migration order.
- Managed identity, RBAC, and no-key-auth requirements.
- Dark launch, traffic shift, rollback, and old-region retirement gates.

Out of scope:

- Running `terraform apply`, `terraform import`, `terraform state rm`, or `terraform destroy`.
- Creating Azure resources from this plan.
- Changing live DNS, Front Door routes, OpenAI deployments, or production app settings.
- Decommissioning West Europe or East US resources.

## Current Terraform Region Shape

| Area | Current configuration | Migration implication |
| --- | --- | --- |
| Main Azure region | `var.location`, default `westeurope` in `infra/variables.tf`; operator tfvars may override it outside the repository | Create a separate Sweden Central stack or workspace; do not mutate the current state in place. |
| Azure OpenAI region | `var.openai_location`, default `westeurope` in `infra/variables.tf` | Validate Sweden Central model availability and quota before any AI cutover. App/data can move first if AI capacity is blocked. |
| Static Web Apps | Hardcoded `westeurope` in `infra/main.tf` | Must be parameterized or replaced during the parallel build plan. Treat as ForceNew. |
| Terraform remote state bootstrap | Commented bootstrap uses West Europe state RG/storage | Keep current state untouched; create a separate state key/workspace for Sweden Central. Do not reuse the current state key. |
| Front Door/WAF | Global services in `infra/main.tf` | Can front both old and new origins during migration; traffic shift must be explicit and reversible. |
| Regional dependencies | Container Apps, ACR, PostgreSQL Flexible Server, Redis, Storage, Key Vault, Log Analytics, Application Insights, VNet, subnets, private endpoints, NSGs | Build parallel resources in Sweden Central, validate diagnostics and private networking before traffic. |

## Readiness Gate 1: Inventory And Freeze

Before any Terraform preview:

- Export current resource inventory for all Archmorph resource groups.
- Pull Terraform state to an encrypted backup outside the repository.
- Capture current app settings, container image tags, secrets names, managed identities, role assignments, private endpoints, DNS records, diagnostic settings, alerts, dashboards, and Front Door origin/routing configuration.
- Freeze non-emergency infrastructure changes until the Sweden Central plan is approved or explicitly paused.
- Confirm which resources are Terraform-managed, workflow-owned, manually adopted, or pending import.
- Confirm the rollback region and exact production URL routing path.

Exit criteria:

- Inventory is reviewed by Cloud, Security, and product owner.
- State backup exists and has a restore owner.
- No unresolved drift blocks a no-apply plan.

## Readiness Gate 2: Sweden Central Service Availability

Validate Sweden Central support for every required service and SKU before building:

| Service family | Required validation |
| --- | --- |
| Resource groups and networking | VNet, delegated Container Apps subnet, database subnet, private endpoint subnet, NSGs, private DNS zones and links. |
| Container Apps | Managed environment support, workload profile/consumption support, ingress, revisions, health probes, managed identity, ACR pull. |
| Container Registry | SKU availability, geo/security policy, private pull posture, Defender/Trivy compatibility. |
| PostgreSQL Flexible Server | Version, SKU, storage, backup retention, zone/HA options, private networking, migration tooling. |
| Redis | SKU/capacity parity or accepted replacement path if unavailable. |
| Storage | Account kind/SKU, blob containers, RBAC, diagnostic logs, soft delete/retention, public access disabled. |
| Key Vault | SKU, purge protection, soft delete, private endpoint, access model, managed identity access. |
| Log Analytics and Application Insights | Region support, workspace-based App Insights, diagnostic sink compatibility, alert queries. |
| Static Web Apps | Region/SKU support or explicit alternative hosting choice. |
| Front Door and DNS | Global routing support, Sweden backend origin health, WAF policy reuse, rollback origin group. |
| Azure OpenAI / Foundry | `gpt-4.1`, `gpt-4o`, model versions, deployment SKU, quota, content filter policy, p95 latency, 429 rate. |

Exit criteria:

- A region availability table is attached to the change request and reflected in [sweden-central-readiness-report.md](sweden-central-readiness-report.md).
- Any unavailable service has an approved workaround or phase split.
- Azure OpenAI capacity is explicitly marked `ready`, `partial`, or `blocked`.

## Readiness Gate 3: Terraform Stack Isolation

The Sweden Central build must be isolated from the current West Europe state.

Required approach:

- Use a separate backend key, Terraform workspace, or environment folder for Sweden Central.
- Use a Sweden Central tfvars file based on [../../infra/sweden-central.example.tfvars](../../infra/sweden-central.example.tfvars).
- Use unique resource naming suffixes where Azure global names would collide.
- Parameterize hardcoded regional values before plan, especially Static Web Apps.
- Run `terraform fmt -check`, `terraform init -backend=false`, and `terraform validate` locally and in CI.
- Run a no-apply plan against the Sweden Central state and confirm it creates new resources only.

Forbidden approach:

- Do not change `infra/terraform.tfvars` from `westeurope` to `swedencentral` and apply against the current state.
- Do not remove or destroy West Europe/East US resources during the build PR.
- Do not import Sweden resources into the current West Europe state key unless the operator plan explicitly calls for it.

Exit criteria:

- Plan output shows only Sweden Central create operations for the new stack.
- No West Europe or East US destroy/replace appears in the plan.
- State isolation is documented in the change ticket.

## Readiness Gate 4: Data And Configuration Migration

Migration order:

1. Provision Sweden Central storage, Key Vault, PostgreSQL, Redis, monitoring, networking, and identities.
2. Restore or replicate PostgreSQL data into the Sweden Central server.
3. Copy storage blobs with checksums and retention settings.
4. Recreate secrets and app settings with Sweden Central endpoints only.
5. Confirm Container App identities have RBAC on Sweden resources and no accidental dependency on West Europe storage, Key Vault, OpenAI, or Log Analytics.
6. Validate service-catalog persistence, sessions, exports, package generation, and OpenAI health against Sweden endpoints.

Exit criteria:

- Database restore has row-count and application smoke validation.
- Storage copy has checksum or inventory parity evidence.
- App settings contain no old-region endpoint values except documented rollback references.

## Readiness Gate 5: AI Runtime Validation

AI movement is its own gate. If Sweden Central lacks model or quota parity, split migration into app/data first and AI later.

Required checks:

- `gpt-4.1` deployment availability, version, SKU, quota, content filter policy, and latency.
- `gpt-4o` fallback availability, version, SKU, quota, content filter policy, and latency.
- Candidate models from the Foundry benchmark plan only as optional benchmark lanes, not production routes.
- Managed identity access using `Cognitive Services OpenAI User`.
- Local auth disabled on Archmorph-owned OpenAI resources.
- No API keys in app settings or committed artifacts.
- Health response shows `openai=ok` against Sweden only.

Exit criteria:

- AI data-plane smoke tests pass with managed identity.
- 429/5xx/error behavior is within SLO under expected load.
- Rollback to West Europe OpenAI is documented and tested before live cutover.

## Dark Launch And Traffic Shift

Dark launch:

- Deploy Sweden Central backend and frontend with no user traffic.
- Run health, auth, storage, OpenAI, IaC generation, HLD export, architecture package export, service catalog, and Starter Architecture smoke tests.
- Confirm alerts, dashboards, logs, and dependency telemetry are live before traffic.

Traffic shift:

1. Add Sweden Central as a Front Door origin with zero or low traffic.
2. Shift 1% internal traffic or synthetic traffic and monitor for at least 30 minutes.
3. Shift 10% and monitor p95 latency, error rate, OpenAI dependency failures, storage errors, database errors, and export failures.
4. Shift 50% only after the 10% gate is clean.
5. Shift 100% and soak for at least 24 hours before old-region retirement planning.

Rollback trigger examples:

- API health fails or reports `openai`/`storage` degraded.
- p95 latency breaches SLO for two consecutive windows.
- Elevated 429/5xx from Azure OpenAI or PostgreSQL.
- Export/package generation fails above baseline.
- Alerting or diagnostics pipeline is unavailable.

Rollback action:

- Move Front Door origin weight back to West Europe.
- Restore old app settings only from reviewed rollback artifacts.
- Keep Sweden Central resources for diagnosis unless they are causing active harm.

## Old-Region Retirement

Retirement is a separate work item after successful 100% traffic soak.

Required evidence:

- Front Door, App Insights, OpenAI dependency logs, storage logs, and database metrics show zero production traffic to West Europe/East US for the approved window.
- Backups and exports are retained according to policy.
- Destroy plans are separate, reviewed, and scoped to old-region resources only.
- DNS TTL and rollback windows have expired.

Do not delete old-region OpenAI, database, storage, or Key Vault resources inside the initial migration PR.

## Validation Commands

Planning-only local validation:

```bash
cd infra
terraform fmt -check
terraform init -backend=false -input=false
terraform validate -no-color
```

Example no-apply preview for the future isolated Sweden stack:

```bash
cd infra
cp sweden-central.example.tfvars sweden-central.tfvars
terraform plan \
  -var-file=sweden-central.tfvars \
  -out=/tmp/archmorph-sweden-central.tfplan
```

Populate the operator-local `sweden-central.tfvars` with approved secret inputs before planning. Only run the preview above against an explicitly isolated backend/workspace. Do not run it against the current West Europe state key.

## Open Follow-Ups

- Parameterize hardcoded Static Web Apps region before any Sweden Central plan.
- Produce a region/SKU availability report from Azure quota and service availability tooling.
- Decide whether Sweden Central AI is required for day-one traffic or can follow app/data migration.
- Create a separate old-region retirement issue after successful Sweden Central soak.
