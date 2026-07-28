terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "= 4.75.0"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.13"
    }
  }

  # Separate state: Phase A can never plan or mutate the live Container App.
  # Backend inventory is supplied only through private CI/operator settings.
  backend "azurerm" {
    use_azuread_auth = true
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

data "azurerm_container_app_environment" "runtime" {
  name                = var.container_app_environment_name
  resource_group_name = var.resource_group_name
}

data "azurerm_container_registry" "runtime" {
  name                = var.container_registry_name
  resource_group_name = var.resource_group_name
}

data "azurerm_key_vault" "runtime" {
  name                = var.key_vault_name
  resource_group_name = var.resource_group_name
}

locals {
  database_secret_uri   = "${trimsuffix(data.azurerm_key_vault.runtime.vault_uri, "/")}/secrets/${var.database_secret_name}"
  database_secret_scope = "${data.azurerm_key_vault.runtime.id}/secrets/${var.database_secret_name}"
  key_vault_rbac_mode   = data.azurerm_key_vault.runtime.rbac_authorization_enabled
  tags = {
    project     = "archmorph"
    environment = var.environment
    managed_by  = "terraform"
    component   = "database-migration-bootstrap"
  }
}

resource "azurerm_user_assigned_identity" "database_migration" {
  name                = var.migration_identity_name
  resource_group_name = var.resource_group_name
  location            = data.azurerm_container_app_environment.runtime.location
  tags                = local.tags
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                            = data.azurerm_container_registry.runtime.id
  role_definition_name             = "AcrPull"
  principal_id                     = azurerm_user_assigned_identity.database_migration.principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "database_secret_reader" {
  count = local.key_vault_rbac_mode ? 1 : 0

  scope                            = local.database_secret_scope
  role_definition_name             = "Key Vault Secrets User"
  principal_id                     = azurerm_user_assigned_identity.database_migration.principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

# Access-policy mode cannot scope permissions to one secret. Keep this fallback
# to Get only and migrate reviewed production vaults to RBAC mode before the
# next hardening rollout.
resource "azurerm_key_vault_access_policy" "database_secret_reader" {
  count = local.key_vault_rbac_mode ? 0 : 1

  key_vault_id = data.azurerm_key_vault.runtime.id
  tenant_id    = data.azurerm_key_vault.runtime.tenant_id
  object_id    = azurerm_user_assigned_identity.database_migration.principal_id

  secret_permissions = ["Get"]
}

resource "time_sleep" "rbac_propagation" {
  create_duration = var.rbac_propagation_wait

  depends_on = [
    azurerm_role_assignment.acr_pull,
    azurerm_role_assignment.database_secret_reader,
    azurerm_key_vault_access_policy.database_secret_reader,
  ]
}

resource "azurerm_container_app_job" "database_migration" {
  name                         = var.migration_job_name
  location                     = data.azurerm_container_app_environment.runtime.location
  resource_group_name          = var.resource_group_name
  container_app_environment_id = data.azurerm_container_app_environment.runtime.id
  replica_timeout_in_seconds   = 900
  replica_retry_limit          = 0
  workload_profile_name        = var.workload_profile_name
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.database_migration.id]
  }

  registry {
    server   = data.azurerm_container_registry.runtime.login_server
    identity = azurerm_user_assigned_identity.database_migration.id
  }

  secret {
    name                = "db-connection"
    key_vault_secret_id = local.database_secret_uri
    identity            = azurerm_user_assigned_identity.database_migration.id
  }

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name    = "migrate"
      image   = var.migration_image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["python", "run_migrations.py"]
      args    = ["--expect-head", var.expected_alembic_head]

      env {
        name        = "DATABASE_URL"
        secret_name = "db-connection"
      }

      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.database_migration.client_id
      }

      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }

      env {
        name  = "MIGRATION_IMAGE_REFERENCE"
        value = var.migration_image
      }

      env {
        name  = "EXPECTED_ALEMBIC_HEAD"
        value = var.expected_alembic_head
      }
    }
  }

  depends_on = [time_sleep.rbac_propagation]
}
