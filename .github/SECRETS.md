# Required GitHub Secrets

This document lists all GitHub Secrets required for the CI/CD workflows to function properly.

## CI/CD Workflow Secrets

These secrets are required in `.github/workflows/ci.yml`:

| Secret Name | Description | Example Value |
|-------------|-------------|---------------|
| `AZURE_SUBSCRIPTION_ID` | Azure subscription ID | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `AZURE_TENANT_ID` | Azure AD tenant ID | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `AZURE_CLIENT_ID` | Service principal or managed identity client ID for OIDC | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `AZURE_RESOURCE_GROUP` | Azure resource group name | `archmorph-rg-dev` |
| `ACR_NAME` | Azure Container Registry name | `myacrname` |
| `ACR_LOGIN_SERVER` | ACR login server URL | `myacrname.azurecr.io` |
| `CONTAINER_APP_NAME` | Azure Container Apps name | `archmorph-api` |
| `CONTAINER_APP_ENV` | Container Apps Environment name | `archmorph-cae-dev` |
| `ADMIN_KEY` | Backend admin/API key used by deploy smoke to authenticate service catalog refresh | (strong random secret) |
| `SWA_NAME` | Static Web App name | `archmorph-frontend` |
| `API_URL` | Backend API URL (with `/api` suffix) | `https://your-app.azurecontainerapps.io/api` |
| `SWA_DEPLOYMENT_TOKEN` | Static Web App deployment token | (from Azure Portal) |

## Monitoring Workflow Secrets

These secrets are required in `.github/workflows/monitoring.yml`:

| Secret Name | Description | Example Value |
|-------------|-------------|---------------|
| `API_URL` | Backend API URL | `https://your-app.azurecontainerapps.io/api` |
| `FRONTEND_URL` | Frontend Static Web App URL | `https://your-swa.azurestaticapps.net` |

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
   - Organization: `your-org`
   - Repository: `your-repo`
   - Entity type: `Branch` or `Pull Request`
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

- Never commit secrets to the repository
- Use OIDC authentication instead of service principal secrets when possible
- Rotate secrets periodically
- Use production GitHub environment secrets; Archmorph does not maintain a separate staging environment
- Backend Container Apps deployments require `ARCHMORPH_API_KEY` and `ARCHMORPH_ADMIN_KEY` to reference the `ADMIN_KEY` secret in the deployed revision.
- The `archmorphmetrics` storage account must keep shared-key access disabled; backend storage access is expected to use `AZURE_STORAGE_ACCOUNT_URL` plus the Container App system-assigned managed identity with `Storage Blob Data Contributor`.
- `AZURE_CLIENT_ID` is for GitHub Actions OIDC. Do not set it in the backend Container App to select storage identity; use `AZURE_STORAGE_MANAGED_IDENTITY_CLIENT_ID` only when a user-assigned storage identity is intentionally attached.
- The deploy smoke calls `/api/service-updates/storage-preflight` before traffic shift to prove the deployed revision can write, read, list, and delete service-catalog blobs through managed identity.
- The `SWA_DEPLOYMENT_TOKEN` is sensitive - regenerate if compromised
