# Phase 0: Orientation and safety net

**Checked:** 2026-11-23
**Mode:** Read-only inventory, except for this planning document and the isolated `rebirth/plan` worktree. No Azure resource, DNS, billing, identity, GitHub secret, or production data was changed.

## Executive status

Archmorph is a public MIT-licensed repository at version 4.3.0 and a live site at `archmorphai.com`. The live site says it translates between any cloud providers, while the actual upload flow and repository describe AWS/GCP to Azure. The product is free and the README explicitly labels the product as preview/stabilization with Beta and Scaffold capabilities.

The Azure CLI is authenticated to the sandbox specified in the prompt. The current Archmorph deployment is present in that sandbox: 61 related resources were identified across the application, Terraform-state, and Container Apps-managed resource groups. The existing Archmorph monthly budget is $2,500 with a 100% alert, not the requested $150 cap with 50% and 80% alerts. No budget or resource changes were made.

The built-in AWS sample could not be analyzed. The site returned HTTP 401 and required sign-in. Its data-lifecycle receipt simultaneously showed pending upload/expiry, unavailable retention and audit details, and backend artifacts marked present. The displayed two-hour retention statement is therefore not verified by this run. No customer diagram was uploaded, and the sample was not purged.

GitHub CLI authentication is active, but the signed-in user's AI-credit usage endpoint returned HTTP 404. The Copilot plan, included allowance, current usage, enabled models, and account-level billing settings remain unverified. These are explicit open items, not inferred facts.

## Repository and product facts

| Item | Finding | Evidence |
|---|---|---|
| Repository | `idokatz86/Archmorph`, public, MIT, default branch `main` | GitHub repository metadata and local `origin` |
| Version | 4.3.0 in `VERSION`, `package.json`, README badge, and live-site footer | Local files and site |
| Product positioning | Free AWS/GCP-to-Azure migration workbench; claims diagram analysis, confidence-scored mappings, guided questions, IaC/HLD/report exports, Architecture Package, and cost estimates | [README.md](../../README.md), public site |
| Maturity | README calls the product preview/stabilization and marks capabilities Live, Beta, Scaffold, and Planned | [README.md](../../README.md) |
| Scope discrepancy | Site footer says “Translate Between Any Cloud Providers”; the upload UI says AWS/GCP diagrams and the README says AWS/GCP to Azure | Public site and README |
| Upload/data disclosure | PNG/JPG/SVG/PDF/Draw.io/Visio, up to 10 MB; UI claims analysis-only processing, two-hour server retention, browser session storage, and an available purge option | Public site |
| Sample test | AWS Classic Web App sample failed with “Authentication required. Please sign in to analyze.” The receipt showed metadata unavailable and backend artifacts present | Live-site run on 2026-11-23 |
| Local tree | 1,384 tracked files. The opened checkout is on `fix/primary-provider-registration-disabled`, four commits ahead and one behind `origin/main`; existing untracked files were left untouched | Local Git metadata |
| Planning branch | An isolated worktree was created on `rebirth/plan` from the opened checkout's committed HEAD, `66ea350`. It does not carry the original worktree's untracked files | Local Git metadata |

The repository's existing `.env` file is ignored by Git. Its contents were not read. No secret values were read or copied. The original checkout also contains pre-existing untracked `.azure`, `.copilot`, fixture, and documentation paths; these were not modified.

## External environment inventory

### Azure

- The active Azure CLI subscription matched the sandbox configured by the prompt. The subscription and tenant identifiers are intentionally omitted from this public-repository document.
- The sandbox contains 12 resource groups and 121 resources in total.
- 61 Archmorph-related resources were found: 57 in the application resource group, 2 in the Terraform-state resource group, and 2 in a Container Apps-managed resource group. No resource IDs are recorded here.
- Observed resource types include Container Apps and environments, Container Apps jobs and managed certificates, Static Web Apps, Container Registry, PostgreSQL Flexible Server, Redis, Azure OpenAI, Key Vault, Storage, Log Analytics, Application Insights, Communication Services and Email, managed identity, DNS zones and records, domain registration, private endpoints/DNS, virtual networks, network security groups, load balancer, and public IP.
- The Archmorph DNS zone has apex, `api`, and `www` records, including TXT records. Two managed certificates and an Azure domain registration were observed. Record targets and resource IDs are omitted from this public document.
- One Entra application registration with the display name `archmorph-github-actions` was found. Its credentials and federated-credential configuration were not inspected.
- One Archmorph Key Vault was found. Soft delete was reported enabled; purge-protection status was not established. Listing secret metadata was denied. No secret values were requested.
- The `ArchmorphSpend` monthly budget is $2,500 and has a 100% notification threshold. No $150 Archmorph budget with both 50% and 80% notifications was found. Existing budgets were not changed.

### GitHub and connected services

- GitHub CLI is authenticated with an active account. The personal AI-credit usage endpoint for November 2026 returned HTTP 404. This does not establish whether the account is billed through an organization or whether the token lacks access.
- The repository has 51 Actions secret names configured. Values were not accessed. Exact secret names are omitted from this public report. A separate inventory of secret consumers and rotation dependencies is still needed before the decommission plan.
- Repository documentation describes PostHog analytics and GitHub issue integration. Azure resources independently confirm use of Azure monitoring and Communication Services. PostHog's live account and other third-party account settings were not verified.
- No GitHub billing or budget settings were changed.

## Copilot billing and model facts

The GitHub CLI identity is active, but the following account-specific facts could not be retrieved: Copilot plan, included monthly AI-credit allowance, credits used this cycle, enabled models, and additional-usage budget. The user's current signed-in CLI account is the assumed billing account, as specified by the prompt's default.

Official GitHub billing documentation checked on 2026-11-23 states that 1 AI credit equals $0.01 USD and lists individual-plan monthly totals of 1,500 credits for Pro, 7,000 for Pro+, and 20,000 for Max. The actual plan is unknown. The current per-model token rates and release status are published in GitHub's [models and pricing table](https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing); rates are model- and, for some models, context-tier-specific.

GitHub's [Copilot Fusion documentation](https://docs.github.com/copilot/concepts/models/copilot-fusion) lists VS Code, Copilot CLI, the Copilot app, JetBrains, and Copilot in the cloud on GitHub.com as generally available surfaces. It reports a 30% paid-plan Fusion discount through 2026-11-30 and a separate 10% paid-plan auto-selection discount in Copilot Chat and the cloud agent. The documentation's exact applicability of Fusion to the cloud coding agent has not been independently confirmed.

GitHub's current budget wording is **Bundled AI credits budget**, set to `$0 USD`, with **Stop usage when budget limit is reached** enabled. This setting has not been changed.

## Assumptions from Section 9

No answers were available in-session. Per the prompt, these defaults are recorded as assumptions:

1. Target AWS and GCP workloads to Azure only.
2. Primary user: cloud architects planning a real migration.
3. Keep the product free and open source.
4. Plan around four hours per week, a $150 monthly Azure cap, and only the included GitHub AI-credit allowance with no paid extra usage.
5. Use the currently signed-in GitHub CLI account, subject to billing verification.
6. Assume no legacy user data or usage history should be preserved. This has not been verified against production storage.
7. Recommend a repository strategy after comparing alternatives.
8. Stop at verified artifacts and a pull request; do not deploy into a user's subscription.
9. Prefer early legacy teardown after explicit approval, with a placeholder page.
10. Preserve the Archmorph name and domain; no other non-negotiable was provided.

## Open items and required access

1. Confirm the GitHub Copilot plan, allowance, November usage, enabled models, and account-level additional-usage budget from the correct billing account. The CLI's user AI-credit endpoint returned 404; use the signed-in account's billing settings or the organization's billing administrator if organization-billed.
2. Set or confirm the requested $150 monthly Azure budget and 50%/80% alerts. Do not change the existing $2,500 budget without approval.
3. Obtain read-only access to Key Vault metadata if the exact secret-name inventory is required. Do not retrieve secret values.
4. Verify the app registration's federated credentials and permissions, CI/CD connections, domain registrar, and third-party analytics from their owning consoles.
5. Verify the actual server-side data-retention and purge behavior. The live sample's receipt did not establish it. The sample artifact was left for the displayed two-hour retention window because destructive actions are gated.
6. Sign-in is required to exercise analysis samples. No credentials were provided, so live output quality and end-to-end behavior remain unverified.

## Safety record

No Azure command was run until the active subscription was checked. All Azure queries were read-only and performed against the specified sandbox. No resource creation/deletion, DNS change, budget change, credential rotation, repository rewrite, or purge was performed. No cloud coding task is running.
