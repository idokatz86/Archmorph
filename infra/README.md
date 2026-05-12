# Archmorph Infrastructure

This directory contains the checked-in Terraform configuration for the Azure-hosted Archmorph stack. It is validated in CI with `terraform init -backend=false`, `terraform fmt -check`, `terraform validate`, and Archmorph-owned Checkov policy checks; live plans and state operations remain operator-run tasks.

## Current Topology

| Component | Terraform owner | Region note |
| --- | --- | --- |
| Resource group, Container Apps, Container Registry, PostgreSQL, Redis, Application Insights, Log Analytics, and primary Blob Storage | `infra/main.tf` | `var.location`, default `westeurope` |
| Azure OpenAI account and model deployments | `infra/main.tf` | Live traffic uses West Europe account `archmorph-openai-we-acm7pd` with `gpt-4.1` primary and `gpt-4o` fallback; Terraform now targets `var.openai_location = westeurope`, but #608 import/state sync must run before apply |
| Metrics storage container `metrics` | `infra/main.tf` (`azurerm_storage_container.metrics`) | Uses the same Terraform-managed primary Blob storage account as the app runtime |
| Terraform remote state storage | Bootstrap command comments in `infra/main.tf` | `archmorph-tfstate-rg` / `archmorphtfstate`, `westeurope` |

## No-Break State Sync Guardrails

Issue #608 tracks bringing Terraform state back in line with the consolidated Azure estate. The #607 live traffic cutover to West Europe is complete, but the East US account remains online for rollback and the live West Europe account still needs to be adopted into Terraform state. The following operations must stay manual and change-window controlled:

- `terraform plan` against the live dev workspace
- `terraform import`
- `terraform state rm`
- `terraform apply`
- Any Azure CLI command that creates, updates, deletes, or moves resources

Before any state-changing operation:

1. Confirm production traffic is still using the West Europe OpenAI account and App Insights shows no East US dependency traffic in the verification window.
2. Run `terraform state pull > backup.tfstate` and keep the backup outside the repository.
3. Capture `terraform plan -lock=false` output and verify there is no unrelated drift.
4. Import `archmorph-openai-we-acm7pd` and its `gpt-4.1` / `gpt-4o` deployments into the Terraform resources before changing or removing the East US state entry.
5. Keep the East US account alive until at least 24 hours of zero traffic is verified.
6. Apply only from an approved operator session with rollback notes and smoke checks ready.

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
- The values above are identifiers, not secrets. They are safe to use in smoke tests that prove direct Container App access is rejected while Front Door-routed traffic succeeds.

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
for dir in . staging dr observability; do
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
