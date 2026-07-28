# Archmorph Rollback Runbook

Use this runbook when a production release causes user-visible errors, failed health gates, broken Architecture Package output, or a release-blocking regression after traffic shift. The target drill time is under 10 minutes from decision to verified rollback.

## Scope

This is a rollback guide for production recovery. It is not a disaster teardown guide.

Do not use `terraform destroy` or `azd down` for normal rollback. Those commands remove infrastructure and can prolong an incident. Use revision traffic rollback, image pinning, frontend artifact redeploy, or a revert-driven release instead.

## Prerequisites

- GitHub Actions access to run the manual rollback workflow.
- Azure RBAC for the production subscription and resource group.
- GitHub secrets present: `AZURE_SUBSCRIPTION_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_RESOURCE_GROUP`, `CONTAINER_APP_NAME`, `API_URL`, `ACR_NAME`, and `ACR_LOGIN_SERVER`, plus `ARCHMORPH_API_KEY` or `ADMIN_KEY` for authenticated health verification.
- Azure CLI authenticated if using the manual fallback.
- Release evidence for the signed bridge revision, frontend artifact, Git SHA, immutable image digest, declared schema range, and exact traffic manifest.

## Decision Points

Start rollback when any of these are true:

- `/api/health` is not `healthy` after deploy stabilization.
- Scheduled job freshness, Redis readiness, database connectivity, or OpenAPI schema checks fail in production.
- The core live path cannot upload, analyze, ask guided questions, export Architecture Package HTML/SVG, generate IaC/HLD, or estimate cost.
- Error rate or latency exceeds the active SLO burn-rate alert and fix-forward is not clearly faster.
- Security, auth, or data-boundary behavior changes unexpectedly.

Abort rollback and escalate if:

- No previous healthy backend revision exists.
- The last known good revision requires a database schema that is no longer compatible.
- Azure Container Apps refuses revision activation or traffic shift.
- Health stays unhealthy after shifting traffic.
- The suspected fault is shared infrastructure, database, secrets, storage, or Azure OpenAI regional availability rather than the application revision.

## Backend Rollback: GitHub Workflow

Prefer the `Manual Rollback` workflow in `.github/workflows/rollback.yml`.

1. Open GitHub Actions and choose `Manual Rollback`.
2. Enter the successful `release_run_id` containing `backend-release-evidence`.
  The workflow verifies the HMAC-signed bridge manifest and refuses list-order,
  creation-time, or active-state target selection.
3. The workflow always shifts 100% to the signed bridge; partial rollback is not supported.
4. Run the workflow. The `rollback` job is bound to the GitHub `production` Environment, so GitHub will pause before Azure login and traffic movement until required reviewers approve the deployment (or an authorized emergency bypass is used under repository policy).
5. For emergency rollback, page the designated production environment approver immediately. If GitHub Actions or environment approval is unavailable, use the Azure CLI fallback below and record why the protected workflow could not be used.
6. Confirm the workflow compares the target revision's
  `APP_SCHEMA_MIN_REVISION` / `APP_SCHEMA_MAX_REVISION` metadata and queries its
  `/api/schema-compatibility` endpoint **before any traffic change**. An inactive
  target may be started at zero traffic solely for this preflight.
7. Only after compatibility succeeds, confirm the workflow activates the target,
  shifts traffic, verifies readiness/schema metadata, and proves normal API
  requests return retryable read-only 503.
8. If routed verification fails, confirm exact pre-rollback weights are restored
  and verified before the workflow fails.
9. Capture the workflow URL, target revision, image digest, schema range/current
  revision, approval/bypass evidence, and health output in release evidence.

The workflow normalizes `API_URL`, calls `/api/health`, sends `X-API-Key` from `ARCHMORPH_API_KEY` with `ADMIN_KEY` fallback when present, and uses the production Environment OIDC subject so Azure trust is scoped to approved production runs instead of branch name alone.

## Backend Rollback: Azure CLI Fallback

Use this only if the workflow is unavailable.

Set context:

```bash
az account set --subscription "$AZURE_SUBSCRIPTION_ID"
```

Retrieve and verify the signed bridge manifest from successful release evidence.
Use its explicit revision/image pair. List revisions only to confirm that target
still exists; never derive a target by selecting the first or second active row:

The first migration `014` rollout creates this bridge from the exact current
immutable release image plus a schema/readiness/read-only overlay. The old
production revision is never promoted merely because it was active.

The bridge is a safe rollback target, not normal steady state: it serves
`/healthz`, `/readyz`, and `/api/schema-compatibility` only. Other requests return
retryable 503 to prevent schema-013 writes. After bridge rollback, fix forward to
a final schema-compatible revision before resuming normal customer operations.

```bash
az containerapp revision list \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name "$CONTAINER_APP_NAME" \
  --query "[].{name:name,active:properties.active,traffic:properties.trafficWeight,created:properties.createdTime,image:properties.template.containers[0].image}" \
  --output table
```

Before activation, read the target's schema metadata and call its zero-traffic
preflight endpoint. If the retained target is inactive, the workflow may activate
it with zero traffic only so the endpoint can start; on incompatibility it
deactivates that revision again. Stop if metadata is absent, the endpoint is
unavailable, or the current revision is outside the declared accepted range. Do
**not** change traffic before compatibility succeeds.

Activate the compatible target revision:

```bash
az containerapp revision activate \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name "$CONTAINER_APP_NAME" \
  --revision "$TARGET_REVISION"
```

Shift traffic:

```bash
az containerapp ingress traffic set \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name "$CONTAINER_APP_NAME" \
  --revision-weight "$TARGET_REVISION=100"
```

Verify health:

```bash
BASE="${API_URL%/}"
BASE="${BASE%/api}"
curl -fsS \
  -H "X-API-Key: ${ARCHMORPH_API_KEY:-$ADMIN_KEY}" \
  "${BASE}/api/health" | jq .
```

Expected bridge rollback result: readiness is 200, schema compatibility is
`compatible` with `release_role=bridge`, and normal API requests return retryable
503. This is degraded safe recovery pending a final fix-forward.

## ACR Image Pinning

Keep release evidence for the exact backend image used by each revision. Prefer immutable digests over mutable tags when investigating or restoring a known good image.

Find image metadata from revisions:

```bash
az containerapp revision list \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name "$CONTAINER_APP_NAME" \
  --query "[].{revision:name,image:properties.template.containers[0].image}" \
  --output table
```

Resolve or inspect ACR digests when needed:

```bash
az acr repository show-manifests \
  --name "$ACR_NAME" \
  --repository archmorph-api \
  --orderby time_desc \
  --output table
```

If a new hotfix deployment is required, pin the target image by digest in the deployment evidence and avoid reusing ambiguous tags as the rollback source of truth.

## Frontend Rollback

Static Web Apps does not have the same revision traffic model as Container Apps.
CI downloads the prior successful `frontend-dist` before deployment and restores
it automatically when routed verification fails. For manual recovery:

For the first bridge rollout, a prior complete artifact may not exist. In that
case frontend failure blocks the release without a speculative restore; the
routed bridge remains compatible with the previous frontend until a verified
frontend artifact succeeds.

- Redeploy the previously tested Static Web Apps artifact from the successful CI/CD run.
- Revert the bad frontend commit and let CI/CD publish the recovered artifact.
- If the bad behavior is controlled by a feature flag, disable the flag first when that restores the live path faster than redeploy.

After frontend rollback, verify:

- Root page loads.
- `/#translator` and `/#playground` load.
- Upload or sample analysis reaches results.
- Architecture Package HTML/SVG export buttons still work for a sample.

## Database And Alembic Caveats

Application rollback should not automatically downgrade the production database.

Archmorph uses expand/contract application compatibility across a bounded
rollback window:

- Each image exposes `minimum_revision`, `maximum_revision`, and explicit
  `accepted_revisions` at `/api/schema-compatibility`.
- The deployment workflow stores the same minimum/maximum values in the
  Container Apps revision environment metadata.
- Migration `014` retains `tenant_rehome_aliases` and `tenant_rehome_audit`.
  Resolved exact-scope analysis aliases remain read-through compatible through
  the current `014` application rollback window so a compatible previous app can
  follow retained identities without reversing the rewrite. Future migration
  heads are incompatible by default until this contract and its tests change.
- Quarantined, ambiguous, or foreign-scope aliases remain fail-closed. The alias
  mapping is evidence, not authority to guess a provider or tenant.
- Contract cleanup that removes alias read-through is a later migration and must
  occur only after the rollback window and retained revision expiry.

The migration evidence preserves what changed and where retained rows moved. It
does **not** mean a downgrade can reconstruct deleted, merged, or deduplicated
identities. Migration `014` therefore refuses downgrade whenever tenant rewrite
alias/audit evidence exists; only an unused empty schema can participate in the
automated Alembic downgrade cycle. Never claim that destructive identity
rewrites are reversible.

Run Alembic downgrade only when all of these are true:

- The migration is explicitly reversible and data-safe.
- The downgrade has been tested against a copy or staging-equivalent snapshot.
- Product and data owners accept any data loss or shape change.
- The rollback target cannot run safely with the current schema.

Default posture: keep the database at the current schema, roll the application
back only to a preflight-compatible revision, or fix forward with a compatible
image/new migration. If no retained revision accepts the current schema, do not
change traffic; deploy a forward-fix revision that declares and proves support.

The manual rollback workflow and both Terraform production plan/apply jobs share
`production-backend-rollout` concurrency with backend deploys. They cannot race
bootstrap, migration, green smoke, or traffic movement. A preflight failure exits
before traffic mutation; a post-shift failure restores the exact prior manifest.

## Migration alert ownership

Platform Engineering owns `archmorph-migration-job-failure` and
`archmorph-migration-missing-evidence`. Both notify the critical action group.
Failure, timeout, cancellation, or absence of
`ARCHMORPH_MIGRATION_EVIDENCE=` blocks rollout. Fix forward; never auto-downgrade.
The alert queries use secret-free Application Insights lifecycle events rather
than relying on provider-specific Container Apps Job log columns.

CI now runs an Alembic smoke against PostgreSQL plus pgvector: heads, offline upgrade SQL generation, upgrade to head, downgrade to base, and re-upgrade. A migration that cannot complete this cycle must not be promoted.

## Health And Smoke Verification

After backend or frontend rollback, run at least one automated smoke:

```bash
scripts/health_gate.sh "$API_URL" --strict-freshness
```

Also verify:

- `/api/health` returns `healthy` with authenticated access.
- `/api/openapi.json` loads and reports Archmorph API.
- Service catalog freshness is current or has a documented accepted reason.
- Architecture Package smoke passes for a sample or known customer-safe fixture.
- GitHub Actions `post-deploy-smoke` or `E2E Health Monitoring` is green.
- If you have the direct Container App origin, verify forged SWA headers are rejected there and on the public API edge:

```bash
FORGED_PRINCIPAL="$(python - <<'PY'
import base64, json
print(base64.b64encode(json.dumps({
    "identityProvider": "aad",
    "userId": "smoke-user",
    "userDetails": "smoke@example.com",
    "userRoles": ["authenticated"],
    "claims": [],
}).encode("utf-8")).decode("ascii"))
PY
)"

curl -sS -o /tmp/direct-origin-swa.json -w "%{http_code}\n" \
  -H "x-ms-client-principal: ${FORGED_PRINCIPAL}" \
  "${DIRECT_ORIGIN_URL%/}/api/auth/me"

curl -sS -o /tmp/public-edge-swa.json -w "%{http_code}\n" \
  -H "x-ms-client-principal: ${FORGED_PRINCIPAL}" \
  "${API_URL%/api}/api/auth/me"
```

Both requests must stay unauthenticated (`401` with `UNTRUSTED_SWA_PRINCIPAL`, or a documented anonymous response if the trust gate is intentionally relaxed outside production). Do not set `TRUST_SWA_PRINCIPAL_HEADER=true` unless the backend is exclusively reachable through a validated SWA-linked ingress.

## Sub-10-Minute Drill

Use this checklist for quarterly operator drills:

1. Identify the release run containing the signed known-good bridge manifest.
2. Run `Manual Rollback` with that release run ID.
3. Confirm traffic is `100` percent on the rollback revision.
4. Verify bridge readiness/schema metadata and retryable read-only 503 behavior.
5. Verify frontend root, translator, playground, and one Architecture Package export.
6. Record elapsed time, workflow URL, target revision, image digest, and any manual steps.

A drill passes when traffic is restored and health verified in under 10 minutes without using infrastructure teardown commands.
