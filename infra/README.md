# Archmorph Infrastructure

This directory contains the checked-in Terraform configuration for the Azure-hosted Archmorph stack. It is validated in CI with `terraform init -backend=false`, `terraform fmt -check`, and `terraform validate`; live plans and state operations remain operator-run tasks.

## Current Topology

| Component | Terraform owner | Region note |
| --- | --- | --- |
| Resource group, Container Apps, Container Registry, PostgreSQL, Redis, Application Insights, Log Analytics, and primary Blob Storage | `infra/main.tf` | `var.location`, default `westeurope` |
| Azure OpenAI account and model deployments | `infra/main.tf` | Live traffic uses West Europe account `archmorph-openai-we-acm7pd` with `gpt-4.1` primary and `gpt-4o` fallback; Terraform now targets `var.openai_location = westeurope`, but #608 import/state sync must run before apply |
| Metrics storage account `archmorphmetrics` | `.github/workflows/ci.yml` | Workflow-owned for current deployment smoke/runtime metrics path; do not alter inline region or SKU without a Terraform import or replacement plan |
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

## Local Validation

Run these commands when editing files under `infra/`:

```bash
cd infra
find . -path './.terraform' -prune -o -name '*.tf' -print0 | xargs -0 terraform fmt -check
for dir in . staging dr observability; do
	terraform -chdir="$dir" init -backend=false -input=false
	terraform -chdir="$dir" validate -no-color
done
```

These commands do not connect to the configured remote backend and do not mutate Azure resources.