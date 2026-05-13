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
- Release evidence for the last known good backend revision, frontend artifact, Git SHA, and container image tag or digest.

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
2. Enter the target `revision_name` when known. Leave it empty to select the previous active revision automatically.
3. Keep `traffic_percentage` at `100` for a full rollback unless doing a controlled partial shift.
4. Run the workflow. The `rollback` job is bound to the GitHub `production` Environment, so GitHub will pause before Azure login and traffic movement until required reviewers approve the deployment (or an authorized emergency bypass is used under repository policy).
5. For emergency rollback, page the designated production environment approver immediately. If GitHub Actions or environment approval is unavailable, use the Azure CLI fallback below and record why the protected workflow could not be used.
6. Confirm the workflow activates the target revision, shifts traffic, and verifies authenticated `${API_URL}/api/health`.
7. Capture the workflow URL, target revision, version, approval/bypass evidence, and health output in release evidence.

The workflow normalizes `API_URL`, calls `/api/health`, sends `X-API-Key` from `ARCHMORPH_API_KEY` with `ADMIN_KEY` fallback when present, and uses the production Environment OIDC subject so Azure trust is scoped to approved production runs instead of branch name alone.

## Backend Rollback: Azure CLI Fallback

Use this only if the workflow is unavailable.

Set context:

```bash
az account set --subscription "$AZURE_SUBSCRIPTION_ID"
```

List revisions and identify the last known good target:

```bash
az containerapp revision list \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name "$CONTAINER_APP_NAME" \
  --query "[].{name:name,active:properties.active,traffic:properties.trafficWeight,created:properties.createdTime,image:properties.template.containers[0].image}" \
  --output table
```

Activate the target revision:

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

Expected result: `.status == "healthy"`, scheduled jobs are fresh or intentionally disabled, Redis is `ok` or accepted as `disabled_optional`, and version/SHA match the intended rollback target.

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

Static Web Apps does not have the same revision traffic model as Container Apps. Use one of these paths:

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

Run Alembic downgrade only when all of these are true:

- The migration is explicitly reversible and data-safe.
- The downgrade has been tested against a copy or staging-equivalent snapshot.
- Product and data owners accept any data loss or shape change.
- The rollback target cannot run safely with the current schema.

Default posture: keep the database at the current schema, roll the application back to a compatible revision, and fix forward with a new migration when needed.

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

## Sub-10-Minute Drill

Use this checklist for quarterly operator drills:

1. Identify current bad revision and previous known good revision.
2. Run `Manual Rollback` workflow with the target revision.
3. Confirm traffic is `100` percent on the rollback revision.
4. Verify authenticated `/api/health` and release version/SHA.
5. Verify frontend root, translator, playground, and one Architecture Package export.
6. Record elapsed time, workflow URL, target revision, image digest, and any manual steps.

A drill passes when traffic is restored and health verified in under 10 minutes without using infrastructure teardown commands.
