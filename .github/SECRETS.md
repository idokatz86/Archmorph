# Required GitHub Secrets

This document lists all GitHub Secrets required for the CI/CD workflows to function properly.

This file must list secret names and placeholder formats only. Do not commit real secret values, API keys, tokens, tenant or subscription IDs, production resource names, private endpoints, or environment-specific URLs.

## CI/CD Workflow Secrets

These secrets are required in `.github/workflows/ci.yml`:

| Secret Name | Description | Placeholder / Format |
|-------------|-------------|---------------|
| `AZURE_SUBSCRIPTION_ID` | Azure subscription ID | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `AZURE_TENANT_ID` | Azure AD tenant ID | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `AZURE_CLIENT_ID` | Service principal or managed identity client ID for OIDC | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `AZURE_RESOURCE_GROUP` | Azure resource group name | `your-resource-group` |
| `ACR_NAME` | Azure Container Registry name | `myacrname` |
| `ACR_LOGIN_SERVER` | ACR login server URL | `myacrname.azurecr.io` |
| `CONTAINER_APP_NAME` | Azure Container Apps name | `your-container-app` |
| `CONTAINER_APP_ENV` | Container Apps Environment name | `your-container-app-env` |
| `ARCHMORPH_API_KEY` | Backend API key used by authenticated API health checks and service catalog refresh triggers | (strong random secret) |
| `ADMIN_KEY` | Backend admin key mapped to `ARCHMORPH_ADMIN_KEY` for admin-only operations, sessions, and deploy smoke fallback authentication | (strong random secret) |
| `JWT_SECRET` | Recommended dedicated backend JWT signing secret for production user/session tokens. If omitted, deploy falls back to `ADMIN_KEY`; a distinct strong random value is strongly recommended. | (strong random secret) |
| `SWA_NAME` | Static Web App name | `your-static-web-app` |
| `API_URL` | Backend API URL (with `/api` suffix) | `https://your-api.example.com/api` |
| `SWA_DEPLOYMENT_TOKEN` | Static Web App deployment token | (from Azure Portal) |

## Monitoring Workflow Secrets

These secrets are required in `.github/workflows/monitoring.yml`:

| Secret Name | Description | Placeholder / Format |
|-------------|-------------|---------------|
| `API_URL` | Backend API URL, including the required `/api` suffix | `https://your-api.example.com/api` |
| `FRONTEND_URL` | Frontend Static Web App URL | `https://your-swa.azurestaticapps.net` |

## Production Terraform Workflow Secrets

These secrets are required in `.github/workflows/terraform-prod.yml`:

| Secret Name | Description | Placeholder / Format |
|-------------|-------------|---------------|
| `TFPLAN_ARTIFACT_PASSPHRASE` | High-entropy passphrase used to encrypt reviewed binary Terraform plan artifacts before upload and decrypt them inside the approved production apply job. | (strong random secret) |

## E2E Test Environment Variables

When running E2E tests locally or in CI, set these environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `API_BASE` | Backend API base URL | `http://localhost:8000` |
| `ADMIN_KEY` | Admin API key for test endpoints | `test-admin-key` |

## How to Configure

### 1. Azure OIDC Setup (Recommended)

For secure authentication without storing credentials:

1. Create an Azure AD App Registration
2. Add federated credentials for GitHub Actions:
   - Organization: `idokatz86`
   - Repository: `Archmorph`
   - Entity type for production deploy/apply/rollback: `Environment`
   - Environment name: `production`
   - Subject: `repo:idokatz86/Archmorph:environment:production`
   - Do not scope production Azure access only to `repo:idokatz86/Archmorph:ref:refs/heads/main`; the production GitHub Environment approval gate must be part of the OIDC trust boundary.
3. Assign necessary roles to the service principal

### 2. GitHub Secrets Configuration

1. Go to your repository Settings → Secrets and variables → Actions
2. Click "New repository secret"
3. Add each secret from the tables above

### 3. Getting Secret Values

```bash
# Azure CLI commands to retrieve values

# Subscription ID
az account show --query id -o tsv

# Tenant ID  
az account show --query tenantId -o tsv

# ACR Login Server
az acr show --name YOUR_ACR_NAME --query loginServer -o tsv

# SWA Deployment Token
az staticwebapp secrets list --name YOUR_SWA_NAME --query properties.apiKey -o tsv
```

## Security Notes

- Never commit secrets, keys, tokens, connection strings, production resource names, private endpoints, or environment-specific URLs to the repository
- Use OIDC authentication instead of service principal secrets when possible
- Rotate secrets periodically
- Use production GitHub environment secrets; Archmorph does not maintain a separate staging environment
- Production Azure federated credentials should trust the GitHub Environment subject `repo:idokatz86/Archmorph:environment:production`.
- Backend Container Apps deployments require `ARCHMORPH_API_KEY` to reference the API key secret and `ARCHMORPH_ADMIN_KEY` to reference the admin-key secret in the deployed revision.
- Backend Container Apps deployments require `JWT_SECRET` in production/staging. The workflow maps repository secret `JWT_SECRET` into a Container App secret named `jwt-secret`; if the repository secret is absent, it uses `ADMIN_KEY` as a compatibility fallback.
- Production storage accounts must keep shared-key access disabled; backend storage access is expected to use `AZURE_STORAGE_ACCOUNT_URL` plus the Container App system-assigned managed identity with `Storage Blob Data Contributor`.
- `AZURE_CLIENT_ID` is for GitHub Actions OIDC. Do not set it in the backend Container App to select storage identity; use `AZURE_STORAGE_MANAGED_IDENTITY_CLIENT_ID` only when a user-assigned storage identity is intentionally attached.
- The deploy smoke calls `/api/service-updates/storage-preflight` before traffic shift to prove the deployed revision can write, read, list, and delete service-catalog blobs through managed identity.
- The `SWA_DEPLOYMENT_TOKEN` is sensitive - regenerate if compromised
