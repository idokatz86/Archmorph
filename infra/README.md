# Archmorph Infrastructure

This directory contains the checked-in Terraform configuration for the Azure-hosted Archmorph stack. It is validated in CI with `terraform init -backend=false`, `terraform fmt -check`, `terraform validate`, and Archmorph-owned Checkov policy checks; live plans and state operations remain operator-run tasks.

## Topology ownership

| Component | Terraform owner | Configuration contract |
| --- | --- | --- |
| Resource group, Container Apps, Container Registry, PostgreSQL, Redis, monitoring, and primary Blob Storage | `infra/main.tf` | Region, names, and overrides come from reviewed variables and private deployment settings |
| Azure OpenAI account and model deployments | `infra/main.tf` | Region/model changes require a reviewed import, quota check, and rollback plan |
| Metrics storage container | `infra/main.tf` | Uses the Terraform-managed primary storage account and managed-identity RBAC |
| Terraform remote state | Partial `azurerm` backend blocks | Resource group, account, container, and key come from private CI/operator configuration |
| Migration Job bootstrap | `infra/migration-bootstrap` | Separate state owns only the dedicated identity, secret-scoped/AcrPull RBAC, propagation wait, and manual Job |

## Two-phase application rollout

Production rollout is intentionally split across two Terraform state files:

1. **Phase A — migration bootstrap:** `infra/migration-bootstrap` reads existing
  Container Apps environment, ACR, Key Vault, and versionless database-secret
  metadata. It creates a dedicated user-assigned identity, `AcrPull`, Key Vault
  Secrets User scoped to the single database Secret, a propagation wait, and one
  manual-trigger Job pinned to the reviewed image digest and exact Alembic head.
  The Secret URI is constructed from Key Vault metadata; Terraform never reads
  or stores the `DATABASE_URL` value.
  This root has no `azurerm_container_app`, ingress, traffic, or probe resource,
  so a failed bootstrap or migration cannot mutate the live app revision.
2. **Phase B — application revision:** after one Job execution succeeds at the
  exact head, CI clones the current app template, adds the new immutable digest,
  `/readyz`, and schema range metadata, smokes the zero-traffic revision, then
  shifts traffic. The previous revision remains the rollback candidate.

Never use `terraform -target` for Phase A. CI performs `init`, `validate`, a full
saved `plan`, then applies that exact plan under the shared production rollout
concurrency group. A pre-existing migration Job is explicitly adopted into the
separate state before plan; repeated deployments then converge idempotently.
Concurrent Job executions are rejected before bootstrap and again before start.
CI also reads the primary state and refuses bootstrap when that state still owns
the Job. Apply the primary root's reviewed `removed { destroy = false }` change
first; a resource must never be managed by both states.

Private deployment configuration must supply a distinct
`MIGRATION_TFSTATE_KEY`, migration Job/identity names, Key Vault name, database
Secret name, and existing prerequisite names. Do not publish their concrete
values. On failure, leave production traffic and probes unchanged, inspect the
Phase A plan/Job execution evidence, fix forward, and rerun. No live apply is
required for local validation.

## Partial backend initialization

Never commit live backend inventory. Configure `TFSTATE_RESOURCE_GROUP`, `TFSTATE_STORAGE_ACCOUNT`, `TFSTATE_CONTAINER`, `TFSTATE_KEY`, and a distinct `TFSTATE_STAGING_KEY` as private GitHub repository secrets or operator-local environment values. Use the validated wrapper:

```bash
python3 scripts/init_terraform_backend.py --environment production
python3 scripts/init_terraform_backend.py --environment staging
```

The wrapper refuses missing settings and rejects a staging key that equals the production key; environment state must never share a key.

## No-break state guardrails

Live inventory, imported-resource IDs, and migration history belong in private operator notes, Terraform state, and approved change records—not this repository. Before any state-changing operation:

1. Confirm the intended target from private deployment configuration and current traffic evidence.
2. Run `terraform state pull > backup.tfstate` and retain the backup outside the repository.
3. Generate and review a locked binary plan; reject unrelated creates, replacements, or destroys.
4. Import existing resources only after verifying the exact IDs from the Azure control plane.
5. Keep rollback resources available until the approved zero-traffic window passes.
6. Apply only from the environment-gated workflow or an approved operator session.

The `Terraform Production` workflow fails when private backend settings or legacy-name overrides are absent. Do not replace those checks with source-code defaults. For import/adoption guidance, use role-based placeholders such as `<resource-group>`, `<container-app>`, `<storage-account>`, and `<redis-cache>`.

## Sweden Central One-Region Migration Guardrails

Issue #783 tracks the plan to move Archmorph toward a single `swedencentral` regional footprint. This is a parallel-build migration, not an in-place edit of `location` or `openai_location` against the current state.

- Runbook: [../docs/infra/sweden-central-migration-plan.md](../docs/infra/sweden-central-migration-plan.md)
- Readiness report template: [../docs/infra/sweden-central-readiness-report.md](../docs/infra/sweden-central-readiness-report.md)
- Example variables for a future isolated stack: [sweden-central.example.tfvars](sweden-central.example.tfvars)

Before any Sweden Central plan or apply:

1. Use a separate backend key, Terraform workspace, or environment folder from the current West Europe state.
2. Validate Sweden Central service/SKU availability for Container Apps, Static Web Apps, ACR, PostgreSQL, Redis, Storage, Key Vault, Log Analytics, Application Insights, networking, DNS, and monitoring.
3. Validate Azure OpenAI / Foundry model availability and quota for `gpt-4.1`, `gpt-4o`, and any benchmark candidates before changing AI routing.
4. Keep West Europe and East US rollback paths live until Sweden Central passes dark launch, traffic shift, soak, and rollback drills.
5. Treat old-region deletion as a separate reviewed destroy plan after zero-traffic evidence.

## Front Door Origin Lock Contract

Production backend traffic is expected to arrive through the Archmorph-owned Azure Front Door profile, not directly at the Container App FQDN.

- Terraform sets the Front Door origin `origin_host_header` to the owned endpoint hostname (`azurerm_cdn_frontdoor_endpoint.api[0].host_name`).
- The Container App receives `TRUSTED_FRONT_DOOR_FDID` from `azurerm_cdn_frontdoor_profile.main[0].resource_guid` and `TRUSTED_FRONT_DOOR_HOSTS` from the Front Door endpoint hostname.
- Runtime middleware enforces that production requests (except `/healthz` platform liveness probes) carry the matching `X-Azure-FDID` header and a trusted host value before the app serves the request.
- These values are deployment identifiers. Keep their concrete values in Terraform state or private CI/operator settings; smoke tests should consume outputs without publishing them.

For operator verification after Terraform changes, inspect:

```bash
cd infra
terraform output front_door_api_hostname
terraform output front_door_profile_resource_guid
terraform output backend_url
```

Use the Front Door hostname (or the production custom domain that routes through it) for successful smoke traffic, and use `backend_url` only to confirm the direct origin is blocked.

## Local Validation

Run these commands when editing files under `infra/`:

```bash
cd infra
find . -path './.terraform' -prune -o -name '*.tf' -print0 | xargs -0 terraform fmt -check
for dir in . staging dr observability migration-bootstrap; do
  terraform -chdir="$dir" init -backend=false -input=false -lockfile=readonly
  terraform -chdir="$dir" validate -no-color
done
```

These commands do not connect to the configured remote backend and do not mutate Azure resources.

### Terraform provider lock policy

Commit `.terraform.lock.hcl` for every checked-in Terraform root (`infra/`, `infra/staging`, `infra/dr`, `infra/observability`) and run init in CI with `-lockfile=readonly`. This keeps provider selections reviewable in PRs and fails validation if a workflow would mutate lockfiles unexpectedly.

Run the project-owned policy-as-code gate from the repository root before changing Azure Terraform resources:

```bash
python -m pip install checkov
checkov --quiet --framework terraform --directory infra --external-checks-dir infra/policies/checkov --check CKV_ARCHMORPH_1,CKV_ARCHMORPH_2,CKV_ARCHMORPH_3
```

The policy gate enforces baseline tags on taggable Azure resources, blocks PostgreSQL Flexible Server public network access, and requires Storage infrastructure encryption. It intentionally runs only `CKV_ARCHMORPH_*` checks so CI catches project-defined guardrails without mixing unrelated upstream Checkov advisories into this gate.
