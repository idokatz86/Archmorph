# Archmorph Infrastructure

This directory contains the checked-in Terraform configuration for the Azure-hosted Archmorph stack. It is validated in CI with `terraform init -backend=false`, `terraform fmt -check`, and `terraform validate`; live plans and state operations remain operator-run tasks.

## Current Topology

| Component | Terraform owner | Region note |
| --- | --- | --- |
| Resource group, Container Apps, Container Registry, PostgreSQL, Redis, Application Insights, Log Analytics, and primary Blob Storage | `infra/main.tf` | `var.location`, default `westeurope` |
| Azure OpenAI account and model deployments | `infra/main.tf` | `var.openai_location`, currently `eastus` until #607 cutover and #608 state sync finish |
| Metrics storage account `archmorphmetrics` | `.github/workflows/ci.yml` | Workflow-owned for current deployment smoke/runtime metrics path; do not alter inline region or SKU without a Terraform import or replacement plan |
| Terraform remote state storage | Bootstrap command comments in `infra/main.tf` | `archmorph-tfstate-rg` / `archmorphtfstate`, `westeurope` |

## No-Break State Sync Guardrails

Issue #608 tracks bringing Terraform state back in line with the consolidated Azure estate. The safe repo-only work is validation and documentation. The following operations must stay manual and change-window controlled:

- `terraform plan` against the live dev workspace
- `terraform import`
- `terraform state rm`
- `terraform apply`
- Any Azure CLI command that creates, updates, deletes, or moves resources

Before any state-changing operation:

1. Confirm #607 has completed and traffic is using the West Europe OpenAI account.
2. Run `terraform state pull > backup.tfstate` and keep the backup outside the repository.
3. Capture `terraform plan -lock=false` output and verify there is no unrelated drift.
4. Prefer importing the existing West Europe OpenAI account into state and removing the retired East US state entry over destroy/recreate.
5. Apply only from an approved operator session with rollback notes and smoke checks ready.

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