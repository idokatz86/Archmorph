# Sweden Central Readiness Report

> Issue: [#783](https://github.com/idokatz86/Archmorph/issues/783)
> Status: Operator validation required before any deployment
> Scope: Availability, quota, smoke, observability, rollback, and retirement gates for a future Sweden Central stack.

This report is the controlled evidence table for the Sweden Central migration. It intentionally contains no subscription IDs, tenant IDs, resource IDs, connection strings, API keys, or live secrets. Operators should attach raw Azure evidence to the private change record, not to this repository.

## Current Evidence Summary

| Gate | Current status | Required evidence before proceed |
| --- | --- | --- |
| Resource inventory and freeze | Not started | Exported inventory, state backup owner, app settings/secrets/RBAC/DNS/monitoring capture, drift review. |
| Sweden Central service/SKU availability | Not started | Availability and quota results for each required Azure service/SKU in `swedencentral`. |
| Azure OpenAI / Foundry availability | Not started | Model/version/SKU/quota evidence for `gpt-4.1`, `gpt-4o`, and any benchmark candidates. |
| Terraform stack isolation | Planned | Separate backend key/workspace/environment, plan proves Sweden Central creates only and no old-region destroy/replace. |
| Data/config migration | Not started | PostgreSQL restore parity, storage checksum/inventory parity, app settings contain only Sweden endpoints plus documented rollback refs. |
| Production-like smoke tests | Not started | Health, auth, storage, OpenAI, service catalog, IaC generation, HLD export, package export, and Starter Architecture smoke results. |
| Observability and alerts | Not started | App Insights, Log Analytics, diagnostics, Front Door/WAF logs, availability tests, action groups, and alert query validation. |
| Rollback drill | Not started | Front Door rollback to West Europe tested, rollback app settings reviewed, old-region paths still healthy. |
| Traffic shift | Not started | 1%, 10%, 50%, and 100% shift windows with p95/error/dependency evidence and no incident. |
| Old-region retirement | Blocked until soak | Separate issue and reviewed destroy plan after zero-traffic evidence. |

## Required Service/SKU Checks

| Service | Target region | Expected result | Evidence owner | Status |
| --- | --- | --- | --- | --- |
| Resource group | `swedencentral` | Supported | Cloud owner | Pending |
| Virtual Network, subnets, NSGs | `swedencentral` | Supported with required address plan | Cloud owner | Pending |
| Private endpoints and Private DNS | `swedencentral` | Supported for PostgreSQL, Key Vault, and any private dependency | Cloud owner | Pending |
| Azure Container Apps managed environment | `swedencentral` | Supported with required ingress, revisions, managed identity, and workload profile/consumption mode | Platform owner | Pending |
| Azure Container Registry | `swedencentral` | Supported SKU and secure pull posture | Platform owner | Pending |
| PostgreSQL Flexible Server | `swedencentral` | Supported version/SKU/storage/backup/private networking/HA posture | Data owner | Pending |
| Azure Cache for Redis | `swedencentral` | Supported capacity and SKU, or approved alternative | Platform owner | Pending |
| Storage account | `swedencentral` | Supported account kind/SKU, public access disabled, soft delete/retention enabled | Cloud owner | Pending |
| Key Vault | `swedencentral` | Supported with purge protection, soft delete, RBAC/private endpoint posture | Security owner | Pending |
| Log Analytics | `swedencentral` | Supported workspace and diagnostic sink | Observability owner | Pending |
| Application Insights | `swedencentral` | Supported workspace-based resource and web tests | Observability owner | Pending |
| Static Web Apps | `swedencentral` | Supported, or approved hosting alternative if unavailable | Frontend owner | Pending |
| Front Door and WAF | Global | Supports Sweden Central origin, health probes, and rollback origin group | Cloud owner | Pending |
| Azure OpenAI `gpt-4.1` | `swedencentral` | Required model version/SKU/quota/content filter available | AI owner | Pending |
| Azure OpenAI `gpt-4o` | `swedencentral` | Required fallback model version/SKU/quota/content filter available | AI owner | Pending |

## Terraform Plan Acceptance

A Sweden Central no-apply plan can proceed only when all of the following are true:

- Plan uses isolated state, not the current West Europe backend key.
- Plan creates Sweden Central resources only.
- Plan does not replace, destroy, or mutate current West Europe/East US resources.
- Static Web Apps region handling is parameterized or otherwise explicitly handled.
- Global resource name collisions are resolved with approved naming.
- Managed identity and RBAC are used for AI and storage access.
- No API keys, connection strings, resource IDs, subscription IDs, or tenant IDs are committed.

## Smoke Test Acceptance

Sweden Central dark launch can accept traffic only after these checks pass against Sweden dependencies:

- API health returns healthy.
- Health includes `openai=ok` and `storage=ok`.
- Authenticated user flow succeeds.
- Service catalog reads/writes persist.
- IaC generation succeeds.
- HLD export succeeds.
- Architecture package export succeeds.
- Starter Architecture smoke test succeeds.
- Azure OpenAI dependency latency and 429/5xx rate are within SLO.
- Application Insights and Log Analytics receive traces, dependencies, exceptions, and availability data.
- Alerts fire in a controlled test and notify the expected action group.

## Rollback Acceptance

Rollback is considered tested only when:

- Front Door can route 100% of traffic back to West Europe.
- West Europe API health remains healthy.
- West Europe OpenAI and storage health remain healthy.
- Reverted app settings are sourced from reviewed artifacts.
- Sweden Central resources remain available for diagnosis unless the incident commander approves shutdown.

## Retirement Acceptance

Old-region retirement is blocked until a separate issue confirms:

- 100% traffic has run on Sweden Central for the approved soak period.
- Front Door, App Insights, OpenAI dependency logs, storage logs, and database metrics show zero production traffic to West Europe/East US.
- Backups and legal/compliance retention are complete.
- Destroy plans are reviewed and scoped to old-region resources only.
- The rollback window has expired.
