# Archmorph Checkov Policies

This directory contains project-owned Checkov policies for checked-in Azure Terraform.

The CI job runs only `CKV_ARCHMORPH_*` checks so policy-as-code can block newly introduced infrastructure regressions without turning this PR into a broad remediation of every upstream Checkov advisory.

| Check | Scope | Blocks |
| --- | --- | --- |
| `CKV_ARCHMORPH_1` | Taggable Azure resources | Missing `project`, `environment`, or `managed_by` baseline tags |
| `CKV_ARCHMORPH_2` | `azurerm_postgresql_flexible_server` | Missing or enabled public network access |
| `CKV_ARCHMORPH_3` | `azurerm_storage_account` | Missing or disabled infrastructure encryption |

Run locally from the repository root:

```bash
python -m pip install checkov
checkov --quiet --framework terraform --directory infra --external-checks-dir infra/policies/checkov --check CKV_ARCHMORPH_1,CKV_ARCHMORPH_2,CKV_ARCHMORPH_3
```