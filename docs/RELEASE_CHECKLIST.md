# Archmorph Release Checklist

Use this checklist before promoting a build to production or enabling scaffolded capabilities for a tenant.

## 1. Branch And Version

- Release branch is `main` for production. Archmorph does not maintain a separate staging environment.
- Root [VERSION](../VERSION) contains the intended stable semantic version.
- `python3 scripts/sync_version.py --check` confirms backend, frontend, package, badge, PRD, OpenAPI, diagram, and changelog version signals match it.
- `python3 scripts/lint_public_metadata.py` confirms public files contain placeholders rather than environment inventory.
- [CHANGELOG.md](../CHANGELOG.md) has an `[Unreleased]` entry describing the release.
- Documentation reflects the actual feature maturity: `Live`, `Beta`, `Scaffold`, or `Planned`.

## 2. Required GitHub Secrets

All secrets must be stored in GitHub Actions secrets or environment secrets. Do not commit values in source files, `.env`, `terraform.tfvars`, workflow logs, or documentation examples.

Core deployment secrets:

- `API_URL`
- `FRONTEND_URL`
- `SWA_DEPLOYMENT_TOKEN`
- `AZURE_SUBSCRIPTION_ID`
- `AZURE_TENANT_ID`
- `AZURE_CLIENT_ID`
- `AZURE_RESOURCE_GROUP`
- `ACR_NAME`
- `ACR_LOGIN_SERVER`
- `CONTAINER_APP_NAME`
- `CONTAINER_APP_ENV`
- `MIGRATION_JOB_NAME`
- `MIGRATION_IDENTITY_NAME`
- `MIGRATION_KEY_VAULT_NAME`
- `MIGRATION_DATABASE_SECRET_NAME`
- `MIGRATION_TFSTATE_KEY`
- `RELEASE_MANIFEST_HMAC_KEY` — at least 32 bytes; signs bridge evidence
- `APPLICATIONINSIGHTS_CONNECTION_STRING` — provides the instrumentation key for secret-free migration lifecycle evidence

Required production repository variables before any Terraform apply:

- `TF_ENABLE_PRODUCTION_INFRA_HARDENING=true`
- `TF_KEY_VAULT_RBAC_AUTHORIZATION_ENABLED=true`
- `TF_BACKEND_CONTAINER_IMAGE`
- `ARCHMORPH_API_KEY`
- `ADMIN_KEY`

Application secrets:

- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_ENDPOINT`
- `ACS_CONNECTION_STRING`
- `ACS_SENDER_EMAIL`
- `LOG_ANALYTICS_WORKSPACE_ID`
- `DATABASE_URL` — PostgreSQL connection string for production
- `REDIS_HOST` or `REDIS_URL` — Redis-backed session/cache store for scaled deployments
- `VISION_CACHE_MAXSIZE` — maximum vision analysis cache entries; default `500`
- `VISION_CACHE_TTL_SECONDS` — vision analysis cache TTL; default `3600`
- `CONTAINER_APP_REPLICA_COUNT` or `CONTAINER_APP_MIN_REPLICAS` — declare intentional multi-replica runtime to the health gate

Production guard env vars:

- `ENFORCE_POSTGRES=true`
- `REQUIRE_REDIS=true`

## 3. Required Quality Gates

Before production promotion, run the local production-parity guard mode at least once after configuration changes:

```bash
docker compose -f docker-compose.yml -f docker-compose.parity.yml up --build
```

The backend must start with PostgreSQL, Redis, `ENFORCE_POSTGRES=true`, and `REQUIRE_REDIS=true`; the admin release gate should report no database/session blockers.

The `CI/CD` workflow must pass before release:

- `backend-tests`: Ruff, pytest, coverage threshold, OpenAPI export, committed OpenAPI contract snapshot check, backend SBOM, Grype.
- `alembic-migration-smoke`: PostgreSQL plus pgvector structural migration checks covering heads, offline upgrade SQL generation, and an **empty-schema-only** `014 -> 013 -> 014` compatibility cycle. This is not evidence that production data can be downgraded; populated revision `014` is protected by refusal tests and uses fix-forward/bridge recovery.
- `frontend-build`: ESLint, Vitest, Vite build, frontend SBOM, Grype.
- `upload-sarif`: SARIF upload attempted for available scans.
- `deploy-backend`: Terraform validation/policy dependencies; exact traffic capture; schema `013`/`014` bridge and signed immutable manifest; authorization-mode-aware Key Vault grant; same-identity secret/`SELECT 1`/schema preflight; exact-head migration; zero-traffic final smoke; exact restoration trap; production health verify.
- `deploy-frontend`: runs only after backend success, deploys the tested artifact, verifies routed pages, and restores the prior successful artifact on failure.
	On the first bridge rollout only, no previous complete artifact contract may
	exist; failure remains release-blocking and the bridge keeps the API compatible
	with the prior frontend instead of attempting an unverified rollback.
- `post-deploy-smoke`: deployed frontend, routed frontend URLs, API health, and OpenAPI schema checks.

The supporting workflows should also be green or explicitly reviewed:

- `Security Scanning`
- `Backend Performance K6 Tests`
- `Playwright Tests`
- `Live Export Full-Spine Smoke` (required for PRs that touch Live export/IaC/HLD/cost/auth-capability/frontend export surfaces)
- `E2E Health Monitoring`

Generated artifact validation coverage is tracked in the [Generated Artifact Validation Matrix](GENERATED_ARTIFACT_VALIDATION_MATRIX.md). Review that matrix when a release changes Architecture Package, diagram, IaC, HLD, cost, or OpenAPI output behavior.

## 4. Manual Smoke Checks

After deployment, verify:

- Frontend root loads without console-blocking errors.
- `/#translator` opens the translator workflow.
- `/#playground` opens the sample playground.
- `${API_URL}/health` passes `scripts/health_gate.sh`: status must be `healthy`, scheduled jobs must be fresh, and Redis must report either `ok` or `disabled_optional`. `missing_required` is release-blocking.
- The green backend revision must successfully run `/api/service-updates/storage-preflight` and `/api/service-updates/run-now` with `X-API-Key: ARCHMORPH_API_KEY` before traffic shift; this validates API authentication, `AZURE_STORAGE_ACCOUNT_URL`, and the managed-identity Blob Storage read/write/list path.
- Confirm the bridge was directly verified and routed on schema `013` before
	migration. Its signed manifest must name an explicit revision, immutable image,
	source SHA, and accepted schemas `013`/`014`. For the first rollout, confirm
	the bridge base is the exact current immutable release image. The overlay
	adapts readiness for 013/014, exposes only liveness/readiness/schema metadata,
	and returns retryable 503 for feature/data requests.
- Confirm the same-identity migration preflight succeeded with
	`--preflight-only --expect-current 013` before Alembic ran.
- Confirm final green stayed at exactly zero traffic until direct smoke passed
	and the exact pre-shift manifest is retained for restoration.
- `${API_ROOT}/openapi.json` loads and reports `Archmorph API`.
- Run the [Production Architecture Package Smoke](PRODUCTION_SMOKE_ARCHITECTURE_PACKAGE.md) workflow with `strict_freshness=true`; retain the summary and artifact bundle for release evidence.
- Confirm each changed generated artifact has an owner, validation command or explicit gap note, fixture, release evidence location, and gap tracking entry in the [Generated Artifact Validation Matrix](GENERATED_ARTIFACT_VALIDATION_MATRIX.md).
- A sample diagram can complete analysis without requiring customer data.
- Export actions that are part of the live path still produce files: Architecture Package HTML, target SVG, DR SVG, HLD, cost CSV, IaC, and at least one classic diagram format.
- Drift baseline smoke: run the sample drift audit, accept/reject one non-green finding, and export the Markdown report.

## 5. Scaffolded Feature Gate

These flags default to disabled and require owner approval before enabling:

- `deploy_engine`
- `live_cloud_scanner`
- `enterprise_sso_scim`

Billing remains intentionally disabled/out of scope for this release.

Frontend opt-in flags use matching `VITE_FEATURE_FLAG_*` names, for example `VITE_FEATURE_FLAG_DEPLOY_ENGINE=true`.

Before enabling any scaffolded feature, confirm:

- Tenant-specific credentials and permissions are configured.
- Secrets are in GitHub/Azure secret stores, not source control.
- Rollback or disablement path is documented.
- Tests cover the enabled tenant path.
- Customer-facing copy clearly states preview/beta status when appropriate.
- Admin release gate shows the expected version/SHA metadata and required smoke checks before the flag is enabled.
- Admin release gate readiness has no database/session release blockers, or the blocker is explicitly accepted for a non-production environment.

## 6. Rollback

- Follow the [rollback runbook](runbooks/rollback.md) during production incidents; target a verified rollback in under 10 minutes.
- Prefer `rollback.yml` and supply the successful release run containing the
	signed bridge manifest. The workflow refuses arbitrary revisions, verifies the
	retained image/schema contract, shifts traffic, and verifies health.
- Never select the first active or previous-created revision after migration `014`.
- Use direct `az containerapp` traffic commands only as the fallback path documented in the runbook.
- If frontend release is bad, redeploy the previous Static Web Apps artifact or revert and let CI/CD redeploy.
- Do not use `terraform destroy` or `azd down` as normal rollback; they are disaster teardown commands.
- After rollback, run `post-deploy-smoke` or `E2E Health Monitoring` manually.

## 7. Evidence To Keep

- Git commit SHA.
- GitHub Actions run URL.
- Smoke-test output summary and Architecture Package smoke artifact manifest.
- Enabled feature flags and tenant scope.
- Signed bridge manifest plus exact blue and pre-shift traffic manifests.
- Migration preflight/migration execution names, immutable image, schema
	current/target values, statuses, and success evidence markers.
- Any known optional dependency warnings accepted for release, including the Redis `disabled_optional` mode when `checks.redis_readiness.require_redis=false` and `checks.redis_readiness.scale_blocked=false`. Required `degraded`, `unhealthy`, `missing_required`, or `scale_blocked=true` production health is release-blocking.
