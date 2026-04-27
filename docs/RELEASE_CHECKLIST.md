# Archmorph Release Checklist

Use this checklist before promoting a build to production or enabling scaffolded capabilities for a tenant.

## 1. Branch And Version

- Release branch is `main` for production or `staging` for pre-production.
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

Staging-only overrides, when used:

- `STAGING_RESOURCE_GROUP`
- `STAGING_CONTAINER_APP_NAME`

## 3. Required Quality Gates

The `CI/CD` workflow must pass before release:

- `backend-tests`: Ruff, pytest, coverage threshold, OpenAPI export, backend SBOM, Grype.
- `frontend-build`: ESLint, Vitest, Vite build, frontend SBOM, Grype.
- `upload-sarif`: SARIF upload attempted for available scans.
- `deploy-backend`: ACR build, Trivy container gate, Container Apps blue-green deploy, production health verify.
- `deploy-frontend`: Static Web Apps deployment from the tested artifact.
- `post-deploy-smoke`: deployed frontend, routed frontend URLs, API health, and OpenAPI schema checks.

The supporting workflows should also be green or explicitly reviewed:

- `Security Scanning`
- `Backend Performance K6 Tests`
- `Playwright Tests`
- `E2E Health Monitoring`

## 4. Manual Smoke Checks

After deployment, verify:

- Frontend root loads without console-blocking errors.
- `/#translator` opens the translator workflow.
- `/#playground` opens the sample playground.
- `${API_URL}/health` returns `healthy` or `degraded` with expected version metadata.
- `${API_ROOT}/openapi.json` loads and reports `Archmorph API`.
- A sample diagram can complete analysis without requiring production-only secrets.
- Export actions that are part of the live path still produce files.

## 5. Scaffolded Feature Gate

These flags default to disabled and require owner approval before enabling:

- `deploy_engine`
- `living_architecture_drift`
- `live_cloud_scanner`
- `enterprise_sso_scim`
- `stripe_billing`

Frontend opt-in flags use matching `VITE_FEATURE_FLAG_*` names, for example `VITE_FEATURE_FLAG_DEPLOY_ENGINE=true`.

Before enabling any scaffolded feature, confirm:

- Tenant-specific credentials and permissions are configured.
- Secrets are in GitHub/Azure secret stores, not source control.
- Rollback or disablement path is documented.
- Tests cover the enabled tenant path.
- Customer-facing copy clearly states preview/beta status when appropriate.

## 6. Rollback

- Prefer the `rollback.yml` workflow for backend rollback.
- Container Apps keeps the prior blue revision for fast traffic shift.
- If frontend release is bad, redeploy the previous Static Web Apps artifact or revert and let CI/CD redeploy.
- After rollback, run `post-deploy-smoke` or `E2E Health Monitoring` manually.

## 7. Evidence To Keep

- Git commit SHA.
- GitHub Actions run URL.
- Smoke-test output summary.
- Enabled feature flags and tenant scope.
- Any known degraded dependencies accepted for release.