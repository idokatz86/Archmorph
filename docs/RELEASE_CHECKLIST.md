# Archmorph Release Checklist

Use this checklist before promoting a build to production or enabling scaffolded capabilities for a tenant.

## 1. Branch And Version

- Release branch is `main` for production. Archmorph does not maintain a separate staging environment.
- `frontend/src/constants.js` contains the intended `APP_VERSION`.
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
- `alembic-migration-smoke`: PostgreSQL plus pgvector migration cycle covering heads, offline upgrade SQL generation, upgrade to head, downgrade to base, and re-upgrade.
- `frontend-build`: ESLint, Vitest, Vite build, frontend SBOM, Grype.
- `upload-sarif`: SARIF upload attempted for available scans.
- `deploy-backend`: ACR build, Trivy container gate, deployment secret validation, metrics storage managed-identity/RBAC preflight, Container Apps blue-green deploy, green revision refresh smoke, production health verify.
- `deploy-frontend`: Static Web Apps deployment from the tested artifact.
- `post-deploy-smoke`: deployed frontend, routed frontend URLs, API health, and OpenAPI schema checks.

The supporting workflows should also be green or explicitly reviewed:

- `Security Scanning`
- `Backend Performance K6 Tests`
- `Playwright Tests`
- `E2E Health Monitoring`

Generated artifact validation coverage is tracked in the [Generated Artifact Validation Matrix](GENERATED_ARTIFACT_VALIDATION_MATRIX.md). Review that matrix when a release changes Architecture Package, diagram, IaC, HLD, cost, or OpenAPI output behavior.

## 4. Manual Smoke Checks

After deployment, verify:

- Frontend root loads without console-blocking errors.
- `/#translator` opens the translator workflow.
- `/#playground` opens the sample playground.
- `${API_URL}/health` passes `scripts/health_gate.sh`: status must be `healthy`, scheduled jobs must be fresh, and Redis must report either `ok` or `disabled_optional`. `missing_required` is release-blocking.
- The green backend revision must successfully run `/api/service-updates/storage-preflight` and `/api/service-updates/run-now` with `X-API-Key: ADMIN_KEY` before traffic shift; this validates `ARCHMORPH_API_KEY`, `AZURE_STORAGE_ACCOUNT_URL`, and the managed-identity Blob Storage read/write/list path.
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
- Prefer the `rollback.yml` workflow for backend rollback. It activates a known-good Container Apps revision, shifts traffic, and verifies authenticated `/api/health`.
- Container Apps keeps the prior blue revision for fast traffic shift.
- Use direct `az containerapp` traffic commands only as the fallback path documented in the runbook.
- If frontend release is bad, redeploy the previous Static Web Apps artifact or revert and let CI/CD redeploy.
- Do not use `terraform destroy` or `azd down` as normal rollback; they are disaster teardown commands.
- After rollback, run `post-deploy-smoke` or `E2E Health Monitoring` manually.

## 7. Evidence To Keep

- Git commit SHA.
- GitHub Actions run URL.
- Smoke-test output summary and Architecture Package smoke artifact manifest.
- Enabled feature flags and tenant scope.
- Any known optional dependency warnings accepted for release, including the Redis `disabled_optional` mode when `checks.redis_readiness.require_redis=false` and `checks.redis_readiness.scale_blocked=false`. Required `degraded`, `unhealthy`, `missing_required`, or `scale_blocked=true` production health is release-blocking.
