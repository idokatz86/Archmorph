terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.60"
    }
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2.8"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  features {
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
    key_vault {
      purge_soft_delete_on_destroy = true
    }
  }
  subscription_id = var.subscription_id
}

provider "azapi" {}

# ─────────────────────────────────────────────────────────────
# Random suffix for globally unique names
# ─────────────────────────────────────────────────────────────
resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

locals {
  name_suffix = random_string.suffix.result
  tags = {
    project     = "archmorph"
    environment = var.environment
    managed_by  = "terraform"
  }
}

# ─────────────────────────────────────────────────────────────
# Resource Group
# ─────────────────────────────────────────────────────────────
resource "azurerm_resource_group" "main" {
  name     = "archmorph-rg-${var.environment}"
  location = var.location
  tags     = local.tags
}

# ─────────────────────────────────────────────────────────────
# Log Analytics Workspace
# ─────────────────────────────────────────────────────────────
resource "azurerm_log_analytics_workspace" "main" {
  name                = "archmorph-logs-${local.name_suffix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

# ─────────────────────────────────────────────────────────────
# Storage Account (Blob Storage for diagrams & IaC files)
# ─────────────────────────────────────────────────────────────
resource "azurerm_storage_account" "main" {
  name                            = "archmorph${local.name_suffix}"
  resource_group_name             = azurerm_resource_group.main.name
  location                        = azurerm_resource_group.main.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  shared_access_key_enabled       = false  # Use RBAC instead of shared keys
  allow_nested_items_to_be_public = false
  public_network_access_enabled   = true   # Disable in prod with VNet integration
  https_traffic_only_enabled      = true
  infrastructure_encryption_enabled = true  # Double encryption at rest

  blob_properties {
    cors_rule {
      allowed_headers    = ["Content-Type", "Authorization"]
      allowed_methods    = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
      allowed_origins    = [var.frontend_url]
      exposed_headers    = ["ETag", "Content-Length"]
      max_age_in_seconds = 3600
    }
    delete_retention_policy {
      days = 7
    }
    container_delete_retention_policy {
      days = 7
    }
  }

  # Network rules - restrict in production
  network_rules {
    default_action             = var.environment == "prod" ? "Deny" : "Allow"
    bypass                     = ["AzureServices"]
    ip_rules                   = []  # Add trusted IPs in production
    virtual_network_subnet_ids = []
  }

  tags = local.tags
}

resource "azurerm_storage_container" "diagrams" {
  name                  = "diagrams"
  storage_account_id    = azurerm_storage_account.main.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "iac" {
  name                  = "generated-iac"
  storage_account_id    = azurerm_storage_account.main.id
  container_access_type = "private"
}

# ─────────────────────────────────────────────────────────────
# Azure Container Registry
# ─────────────────────────────────────────────────────────────
resource "azurerm_container_registry" "main" {
  name                          = "archmorph${local.name_suffix}"
  resource_group_name           = azurerm_resource_group.main.name
  location                      = azurerm_resource_group.main.location
  sku                           = var.environment == "prod" ? "Standard" : "Basic"
  admin_enabled                 = var.environment != "prod"  # Disable admin in production
  public_network_access_enabled = true
  zone_redundancy_enabled       = var.environment == "prod"
  anonymous_pull_enabled        = false
  data_endpoint_enabled         = var.environment == "prod"

  # Enable content trust in production
  trust_policy_enabled = var.environment == "prod"

  tags = local.tags
}

# ─────────────────────────────────────────────────────────────
# Azure Database for PostgreSQL Flexible Server
# ─────────────────────────────────────────────────────────────
resource "azurerm_postgresql_flexible_server" "main" {
  name                   = "archmorph-db-${local.name_suffix}"
  resource_group_name    = azurerm_resource_group.main.name
  location               = azurerm_resource_group.main.location
  version                = "15"
  administrator_login    = var.db_admin_username
  administrator_password = var.db_admin_password
  storage_mb             = 32768
  sku_name               = var.environment == "prod" ? "GP_Standard_D2s_v3" : "B_Standard_B1ms"
  zone                   = "1"
  backup_retention_days  = var.environment == "prod" ? 35 : 7
  geo_redundant_backup_enabled = var.environment == "prod"

  authentication {
    password_auth_enabled         = true
    active_directory_auth_enabled = var.environment == "prod"  # Enable AAD auth in prod
  }

  # Require SSL/TLS for all connections
  # Note: ssl_enforcement_enabled is not available - use connection string sslmode=require

  tags = local.tags
}

resource "azurerm_postgresql_flexible_server_database" "main" {
  name      = "archmorph"
  server_id = azurerm_postgresql_flexible_server.main.id
  collation = "en_US.utf8"
  charset   = "UTF8"
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_azure" {
  name             = "AllowAzureServices"
  server_id        = azurerm_postgresql_flexible_server.main.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

# ─────────────────────────────────────────────────────────────
# Key Vault (for secrets)
# ─────────────────────────────────────────────────────────────
data "azurerm_client_config" "current" {}

resource "azurerm_key_vault" "main" {
  name                       = "archmorph-kv-${local.name_suffix}"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days  = var.environment == "prod" ? 90 : 7
  purge_protection_enabled    = var.environment == "prod"  # Enable in production
  rbac_authorization_enabled  = var.environment == "prod"  # Use RBAC in production

  # Network ACLs - restrict in production
  network_acls {
    bypass                     = "AzureServices"
    default_action             = var.environment == "prod" ? "Deny" : "Allow"
    ip_rules                   = []
    virtual_network_subnet_ids = []
  }

  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = data.azurerm_client_config.current.object_id

    secret_permissions = [
      "Get", "List", "Set", "Delete", "Purge", "Backup", "Restore"
    ]
    key_permissions = [
      "Get", "List", "Create", "Delete", "Purge"
    ]
  }

  tags = local.tags
}

resource "azurerm_key_vault_secret" "db_connection" {
  name         = "db-connection-string"
  value        = "postgresql://${var.db_admin_username}:${var.db_admin_password}@${azurerm_postgresql_flexible_server.main.fqdn}:5432/archmorph?sslmode=require"
  key_vault_id = azurerm_key_vault.main.id
}

resource "azurerm_key_vault_secret" "storage_connection" {
  name         = "storage-connection-string"
  value        = azurerm_storage_account.main.primary_connection_string
  key_vault_id = azurerm_key_vault.main.id
}

# ─────────────────────────────────────────────────────────────
# Azure OpenAI Service
# ─────────────────────────────────────────────────────────────
resource "azurerm_cognitive_account" "openai" {
  name                  = "archmorph-openai-${local.name_suffix}"
  resource_group_name   = azurerm_resource_group.main.name
  location              = var.openai_location # OpenAI has limited regions
  kind                  = "OpenAI"
  sku_name              = "S0"
  custom_subdomain_name = "archmorph-openai-${local.name_suffix}"

  tags = local.tags
}

resource "azurerm_cognitive_deployment" "gpt4_vision" {
  name                 = "gpt-4o"
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = "gpt-4o"
    version = "2024-05-13"
  }

  sku {
    name     = "Standard"
    capacity = 10
  }
}

resource "azurerm_key_vault_secret" "openai_key" {
  name         = "openai-api-key"
  value        = azurerm_cognitive_account.openai.primary_access_key
  key_vault_id = azurerm_key_vault.main.id
}

# ─────────────────────────────────────────────────────────────
# Container Apps Environment
# ─────────────────────────────────────────────────────────────
resource "azurerm_container_app_environment" "main" {
  name                       = "archmorph-cae-${var.environment}"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = var.location  # West Europe (same as other resources)
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }

  tags = local.tags
}

# ─────────────────────────────────────────────────────────────
# Backend Container App
# ─────────────────────────────────────────────────────────────
resource "azurerm_container_app" "backend" {
  name                         = "archmorph-api"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  tags                         = local.tags

  # Managed identity for secure access to Azure resources
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.container_app.id]
  }

  registry {
    server               = azurerm_container_registry.main.login_server
    username             = azurerm_container_registry.main.admin_username
    password_secret_name = "acr-password"
  }

  secret {
    name  = "acr-password"
    value = azurerm_container_registry.main.admin_password
  }

  secret {
    name  = "db-connection"
    value = "postgresql://${var.db_admin_username}:${var.db_admin_password}@${azurerm_postgresql_flexible_server.main.fqdn}:5432/archmorph?sslmode=require"
  }

  # Storage uses RBAC (shared_access_key_enabled = false) — no connection string needed

  secret {
    name  = "openai-key"
    value = azurerm_cognitive_account.openai.primary_access_key
  }

  secret {
    name  = "appinsights-connection"
    value = azurerm_application_insights.main.connection_string
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "http"

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    min_replicas = 1
    max_replicas = var.environment == "prod" ? 10 : 3

    container {
      name   = "api"
      image  = "${azurerm_container_registry.main.login_server}/archmorph-api:latest"
      cpu    = var.environment == "prod" ? 1.0 : 0.5
      memory = var.environment == "prod" ? "2Gi" : "1Gi"

      env {
        name        = "DATABASE_URL"
        secret_name = "db-connection"
      }

      env {
        name  = "AZURE_STORAGE_ACCOUNT_URL"
        value = "https://${azurerm_storage_account.main.name}.blob.core.windows.net"
      }

      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.container_app.client_id
      }

      env {
        name        = "AZURE_OPENAI_API_KEY"
        secret_name = "openai-key"
      }

      env {
        name  = "AZURE_OPENAI_ENDPOINT"
        value = azurerm_cognitive_account.openai.endpoint
      }

      env {
        name  = "AZURE_OPENAI_DEPLOYMENT"
        value = azurerm_cognitive_deployment.gpt4_vision.name
      }

      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }

      env {
        name        = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        secret_name = "appinsights-connection"
      }

      liveness_probe {
        path              = "/api/health"
        port              = 8000
        transport         = "HTTP"
        initial_delay     = 10
        interval_seconds  = 30
        failure_count_threshold = 3
      }

      readiness_probe {
        path              = "/api/health"
        port              = 8000
        transport         = "HTTP"
        interval_seconds  = 10
        failure_count_threshold = 3
      }

      startup_probe {
        path              = "/api/health"
        port              = 8000
        transport         = "HTTP"
        interval_seconds  = 5
        failure_count_threshold = 10
      }
    }
  }
}

# ─────────────────────────────────────────────────────────────
# Static Web App (Frontend)
# ─────────────────────────────────────────────────────────────
resource "azurerm_static_web_app" "frontend" {
  name                = "archmorph-frontend"
  resource_group_name = azurerm_resource_group.main.name
  location            = "westeurope"
  sku_tier            = var.environment == "prod" ? "Standard" : "Free"
  sku_size            = var.environment == "prod" ? "Standard" : "Free"
  tags                = local.tags
}

# ─────────────────────────────────────────────────────────────
# User Assigned Managed Identity (for Container App)
# ─────────────────────────────────────────────────────────────
resource "azurerm_user_assigned_identity" "container_app" {
  name                = "archmorph-api-identity"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.tags
}

# Grant Container App identity access to Key Vault secrets
resource "azurerm_key_vault_access_policy" "container_app" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = azurerm_user_assigned_identity.container_app.principal_id

  secret_permissions = ["Get", "List"]
}

# Grant Container App identity access to Storage (Blob Data Contributor)
resource "azurerm_role_assignment" "container_app_storage" {
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.container_app.principal_id
}

# Grant Container App identity access to ACR (AcrPull)
resource "azurerm_role_assignment" "container_app_acr" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.container_app.principal_id
}

# ─────────────────────────────────────────────────────────────
# Diagnostic Settings (Security & Audit Logging)
# ─────────────────────────────────────────────────────────────
resource "azurerm_monitor_diagnostic_setting" "key_vault" {
  name                       = "keyvault-diagnostics"
  target_resource_id         = azurerm_key_vault.main.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  enabled_log {
    category = "AuditEvent"
  }
}

resource "azurerm_monitor_diagnostic_setting" "storage" {
  name                       = "storage-diagnostics"
  target_resource_id         = "${azurerm_storage_account.main.id}/blobServices/default"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  enabled_log {
    category = "StorageRead"
  }

  enabled_log {
    category = "StorageWrite"
  }

  enabled_log {
    category = "StorageDelete"
  }
}

resource "azurerm_monitor_diagnostic_setting" "postgresql" {
  name                       = "postgresql-diagnostics"
  target_resource_id         = azurerm_postgresql_flexible_server.main.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  enabled_log {
    category = "PostgreSQLLogs"
  }
}

resource "azurerm_monitor_diagnostic_setting" "openai" {
  name                       = "openai-diagnostics"
  target_resource_id         = azurerm_cognitive_account.openai.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  enabled_log {
    category = "Audit"
  }

  enabled_log {
    category = "RequestResponse"
  }
}

# ─────────────────────────────────────────────────────────────
# Application Insights (APM & Telemetry)
# ─────────────────────────────────────────────────────────────
resource "azurerm_application_insights" "main" {
  name                = "archmorph-insights-${local.name_suffix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  workspace_id        = azurerm_log_analytics_workspace.main.id
  application_type    = "web"
  retention_in_days   = 30
  sampling_percentage = var.environment == "prod" ? 50 : 100  # Sample 50% in prod to reduce costs
  
  # Enable distributed tracing
  disable_ip_masking = false  # GDPR compliance
  
  tags = local.tags
}

# ─────────────────────────────────────────────────────────────
# Azure Monitor Action Group (for alerts)
# ─────────────────────────────────────────────────────────────
resource "azurerm_monitor_action_group" "critical" {
  name                = "archmorph-critical-alerts"
  resource_group_name = azurerm_resource_group.main.name
  short_name          = "archcrit"
  
  email_receiver {
    name                    = "admin"
    email_address          = var.alert_email
    use_common_alert_schema = true
  }
  
  tags = local.tags
}

# ─────────────────────────────────────────────────────────────
# Azure Monitor Alerts
# ─────────────────────────────────────────────────────────────

# High Error Rate Alert
resource "azurerm_monitor_metric_alert" "high_error_rate" {
  name                = "archmorph-high-error-rate"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azurerm_application_insights.main.id]
  description         = "Alert when error rate exceeds 5%"
  severity            = 1
  frequency           = "PT5M"
  window_size         = "PT15M"
  
  criteria {
    metric_namespace = "microsoft.insights/components"
    metric_name      = "requests/failed"
    aggregation      = "Count"
    operator         = "GreaterThan"
    threshold        = 50
  }
  
  action {
    action_group_id = azurerm_monitor_action_group.critical.id
  }
  
  tags = local.tags
}

# High Response Time Alert
resource "azurerm_monitor_metric_alert" "high_response_time" {
  name                = "archmorph-high-response-time"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azurerm_application_insights.main.id]
  description         = "Alert when P95 response time exceeds 5s"
  severity            = 2
  frequency           = "PT5M"
  window_size         = "PT15M"
  
  criteria {
    metric_namespace = "microsoft.insights/components"
    metric_name      = "requests/duration"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = 5000  # 5 seconds in milliseconds
  }
  
  action {
    action_group_id = azurerm_monitor_action_group.critical.id
  }
  
  tags = local.tags
}

# Container App CPU Alert
resource "azurerm_monitor_metric_alert" "high_cpu" {
  name                = "archmorph-high-cpu"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azurerm_container_app.backend.id]
  description         = "Alert when CPU exceeds 80%"
  severity            = 2
  frequency           = "PT5M"
  window_size         = "PT15M"
  
  criteria {
    metric_namespace = "Microsoft.App/containerApps"
    metric_name      = "UsageNanoCores"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = 800000000  # 80% of 1 core in nanocores
  }
  
  action {
    action_group_id = azurerm_monitor_action_group.critical.id
  }
  
  tags = local.tags
}

# Database Connection Alert
resource "azurerm_monitor_metric_alert" "db_connections" {
  name                = "archmorph-db-connections"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azurerm_postgresql_flexible_server.main.id]
  description         = "Alert when database connections exceed 80%"
  severity            = 2
  frequency           = "PT5M"
  window_size         = "PT15M"
  
  criteria {
    metric_namespace = "Microsoft.DBforPostgreSQL/flexibleServers"
    metric_name      = "active_connections"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = 80  # Percent of max connections
  }
  
  action {
    action_group_id = azurerm_monitor_action_group.critical.id
  }
  
  tags = local.tags
}

# Storage Account Availability Alert
resource "azurerm_monitor_metric_alert" "storage_availability" {
  name                = "archmorph-storage-availability"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azurerm_storage_account.main.id]
  description         = "Alert when storage availability drops below 99%"
  severity            = 1
  frequency           = "PT5M"
  window_size         = "PT15M"
  
  criteria {
    metric_namespace = "Microsoft.Storage/storageAccounts"
    metric_name      = "Availability"
    aggregation      = "Average"
    operator         = "LessThan"
    threshold        = 99
  }
  
  action {
    action_group_id = azurerm_monitor_action_group.critical.id
  }
  
  tags = local.tags
}

# OpenAI Dependency Failure Alert (log-based)
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "openai_failures" {
  name                = "archmorph-openai-failures"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  description         = "Alert when OpenAI API calls fail repeatedly"
  severity            = 1
  enabled             = true
  scopes              = [azurerm_application_insights.main.id]

  evaluation_frequency = "PT5M"
  window_duration      = "PT15M"

  criteria {
    query = <<-KQL
      AppDependencies
      | where Type == "HTTP" and (Target has "openai" or Name has "openai")
      | where Success == false
      | summarize FailedCalls = count() by bin(TimeGenerated, 5m)
    KQL
    time_aggregation_method = "Count"
    operator                = "GreaterThan"
    threshold               = 10
    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.critical.id]
  }

  tags = local.tags
}

# Container App Restart Alert (log-based)
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "container_restarts" {
  name                = "archmorph-container-restarts"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  description         = "Alert when container app restarts unexpectedly"
  severity            = 2
  enabled             = true
  scopes              = [azurerm_log_analytics_workspace.main.id]

  evaluation_frequency = "PT5M"
  window_duration      = "PT15M"

  criteria {
    query = <<-KQL
      ContainerAppSystemLogs_CL
      | where ContainerAppName_s == "archmorph-api"
      | where Reason_s has_any ("BackOff", "CrashLoopBackOff", "OOMKilled", "Error")
      | summarize RestartEvents = count() by bin(TimeGenerated, 5m)
    KQL
    time_aggregation_method = "Count"
    operator                = "GreaterThan"
    threshold               = 3
    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.critical.id]
  }

  tags = local.tags
}

# Slow API Response Alert (P95 > 10s, log-based for endpoint detail)
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "slow_endpoints" {
  name                = "archmorph-slow-endpoints"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  description         = "Alert when any endpoint P95 exceeds 10 seconds"
  severity            = 3
  enabled             = true
  scopes              = [azurerm_application_insights.main.id]

  evaluation_frequency = "PT10M"
  window_duration      = "PT30M"

  criteria {
    query = <<-KQL
      AppRequests
      | where Name !has "health"
      | summarize P95 = percentile(DurationMs, 95), Count = count() by Name
      | where P95 > 10000 and Count > 5
    KQL
    time_aggregation_method = "Count"
    operator                = "GreaterThan"
    threshold               = 0
    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.critical.id]
  }

  tags = local.tags
}

# Exception Spike Alert
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "exception_spike" {
  name                = "archmorph-exception-spike"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  description         = "Alert when exception count spikes above normal"
  severity            = 2
  enabled             = true
  scopes              = [azurerm_application_insights.main.id]

  evaluation_frequency = "PT5M"
  window_duration      = "PT15M"

  criteria {
    query = <<-KQL
      AppExceptions
      | summarize ExceptionCount = count() by bin(TimeGenerated, 5m)
    KQL
    time_aggregation_method = "Count"
    operator                = "GreaterThan"
    threshold               = 25
    failing_periods {
      minimum_failing_periods_to_trigger_alert = 2
      number_of_evaluation_periods             = 3
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.critical.id]
  }

  tags = local.tags
}

# Application Insights Availability Test (Ping)
resource "azurerm_application_insights_standard_web_test" "health_check" {
  name                    = "archmorph-health-ping"
  resource_group_name     = azurerm_resource_group.main.name
  location                = azurerm_resource_group.main.location
  application_insights_id = azurerm_application_insights.main.id
  geo_locations           = ["emea-nl-ams-azr", "emea-gb-db3-azr", "emea-fr-pra-edge"]
  frequency               = 300  # Every 5 minutes
  timeout                 = 30   # 30 seconds
  enabled                 = true

  request {
    url = "https://${azurerm_container_app.backend.ingress[0].fqdn}/api/health"
  }

  validation_rules {
    expected_status_code = 200
    ssl_check_enabled    = true
  }

  tags = local.tags
}

# Availability alert tied to the web test
resource "azurerm_monitor_metric_alert" "availability_test" {
  name                = "archmorph-availability-test-alert"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azurerm_application_insights.main.id]
  description         = "Alert when health endpoint availability drops below 90%"
  severity            = 1
  frequency           = "PT5M"
  window_size         = "PT15M"

  criteria {
    metric_namespace = "microsoft.insights/components"
    metric_name      = "availabilityResults/availabilityPercentage"
    aggregation      = "Average"
    operator         = "LessThan"
    threshold        = 90
  }

  action {
    action_group_id = azurerm_monitor_action_group.critical.id
  }

  tags = local.tags
}

# ─────────────────────────────────────────────────────────────
# Log Analytics Saved Queries (for dashboards)
# ─────────────────────────────────────────────────────────────
resource "azurerm_log_analytics_saved_search" "error_logs" {
  name                       = "ArchmorphErrorLogs"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  category                   = "Archmorph"
  display_name              = "Error Logs"
  query                     = <<-QUERY
    AppExceptions
    | where TimeGenerated > ago(24h)
    | summarize count() by ExceptionType, bin(TimeGenerated, 1h)
    | order by TimeGenerated desc
  QUERY
  function_alias            = "ArchmorphErrors"
}

resource "azurerm_log_analytics_saved_search" "api_latency" {
  name                       = "ArchmorphApiLatency"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  category                   = "Archmorph"
  display_name              = "API Latency by Endpoint"
  query                     = <<-QUERY
    AppRequests
    | where TimeGenerated > ago(24h)
    | summarize 
        avg(DurationMs), 
        percentile(DurationMs, 95),
        percentile(DurationMs, 99),
        count()
      by Name, bin(TimeGenerated, 1h)
    | order by TimeGenerated desc
  QUERY
  function_alias            = "ArchmorphLatency"
}

resource "azurerm_log_analytics_saved_search" "user_analytics" {
  name                       = "ArchmorphUserAnalytics"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  category                   = "Archmorph"
  display_name              = "User Analytics"
  query                     = <<-QUERY
    AppRequests
    | where TimeGenerated > ago(7d)
    | where Name startswith "/api/diagrams"
    | summarize 
        Analyses = countif(Name contains "analyze"),
        Exports = countif(Name contains "export"),
        IaCGenerated = countif(Name contains "generate")
      by bin(TimeGenerated, 1d)
    | order by TimeGenerated desc
  QUERY
  function_alias            = "ArchmorphUserAnalytics"
}

resource "azurerm_log_analytics_saved_search" "dependency_health" {
  name                       = "ArchmorphDependencyHealth"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  category                   = "Archmorph"
  display_name              = "External Dependency Health"
  query                     = <<-QUERY
    AppDependencies
    | where TimeGenerated > ago(24h)
    | summarize
        Calls = count(),
        AvgDuration = round(avg(DurationMs), 1),
        FailRate = round(100.0 * countif(Success == false) / count(), 2)
      by Type, Target
    | order by Calls desc
  QUERY
  function_alias            = "ArchmorphDependencies"
}

resource "azurerm_log_analytics_saved_search" "openai_usage" {
  name                       = "ArchmorphOpenAIUsage"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  category                   = "Archmorph"
  display_name              = "OpenAI API Usage & Latency"
  query                     = <<-QUERY
    AppDependencies
    | where TimeGenerated > ago(24h)
    | where Type == "HTTP" and (Target has "openai" or Name has "openai")
    | summarize
        Calls = count(),
        AvgLatencySeconds = round(avg(DurationMs) / 1000, 2),
        P95LatencySeconds = round(percentile(DurationMs, 95) / 1000, 2),
        Failures = countif(Success == false)
      by bin(TimeGenerated, 1h)
    | order by TimeGenerated desc
  QUERY
  function_alias            = "ArchmorphOpenAI"
}

resource "azurerm_log_analytics_saved_search" "slow_requests" {
  name                       = "ArchmorphSlowRequests"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  category                   = "Archmorph"
  display_name              = "Slow Requests (>5s)"
  query                     = <<-QUERY
    AppRequests
    | where TimeGenerated > ago(24h)
    | where DurationMs > 5000
    | project TimeGenerated, Endpoint = Name, DurationSec = round(DurationMs / 1000, 1), ResultCode, ClientIP
    | order by DurationSec desc
    | take 50
  QUERY
  function_alias            = "ArchmorphSlowRequests"
}

resource "azurerm_log_analytics_saved_search" "security_events" {
  name                       = "ArchmorphSecurityEvents"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  category                   = "Archmorph"
  display_name              = "Security Events (401/403/429)"
  query                     = <<-QUERY
    AppRequests
    | where TimeGenerated > ago(24h)
    | where ResultCode in ("401", "403", "429")
    | summarize
        Count = count()
      by ResultCode, ClientIP, Name
    | order by Count desc
  QUERY
  function_alias            = "ArchmorphSecurityEvents"
}

resource "azurerm_log_analytics_saved_search" "container_errors" {
  name                       = "ArchmorphContainerErrors"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  category                   = "Archmorph"
  display_name              = "Container App Error Logs"
  query                     = <<-QUERY
    ContainerAppConsoleLogs_CL
    | where TimeGenerated > ago(24h)
    | where ContainerAppName_s == "archmorph-api"
    | where Log_s has_any ("error", "exception", "critical", "failed", "traceback")
    | project TimeGenerated, Log = Log_s
    | order by TimeGenerated desc
    | take 100
  QUERY
  function_alias            = "ArchmorphContainerErrors"
}

# ─────────────────────────────────────────────────────────────
# Azure Monitor Workbook (Comprehensive Operations Dashboard)
# ─────────────────────────────────────────────────────────────
resource "azurerm_application_insights_workbook" "dashboard" {
  name                = "archmorph-dashboard"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  display_name        = "Archmorph Operations Dashboard"
  source_id           = azurerm_application_insights.main.id
  category            = "workbook"
  
  data_json = jsonencode({
    version = "Notebook/1.0"
    items = [
      # ── Header ──
      {
        type = 1
        content = {
          json = "# 🏗️ Archmorph Operations Dashboard\nReal-time monitoring for the Archmorph architecture translation platform.\n\n---"
        }
        name = "header"
      },
      # ── Time Range Parameter ──
      {
        type = 9
        content = {
          version = "KqlParameterItem/1.0"
          parameters = [
            {
              id          = "time-range"
              version     = "KqlParameterItem/1.0"
              name        = "TimeRange"
              type        = 4
              isRequired  = true
              value       = { durationMs = 86400000 }
              typeSettings = {
                selectableValues = [
                  { durationMs = 3600000,   displayText = "Last 1 hour" },
                  { durationMs = 14400000,  displayText = "Last 4 hours" },
                  { durationMs = 43200000,  displayText = "Last 12 hours" },
                  { durationMs = 86400000,  displayText = "Last 24 hours" },
                  { durationMs = 259200000, displayText = "Last 3 days" },
                  { durationMs = 604800000, displayText = "Last 7 days" }
                ]
              }
            }
          ]
        }
        name = "parameters"
      },

      # ══════════════════════════════════════════════════════════
      # SECTION 1: Health Overview (KPIs)
      # ══════════════════════════════════════════════════════════
      {
        type = 1
        content = { json = "## 🟢 Health Overview" }
        name = "section-health"
      },
      # Availability / Success Rate
      {
        type = 3
        content = {
          version      = "KqlItem/1.0"
          query        = <<-KQL
            AppRequests
            | where TimeGenerated {TimeRange}
            | summarize
                TotalRequests = count(),
                SuccessfulRequests = countif(Success == true),
                FailedRequests = countif(Success == false)
            | extend AvailabilityPct = round(100.0 * SuccessfulRequests / TotalRequests, 2)
            | project AvailabilityPct, TotalRequests, SuccessfulRequests, FailedRequests
          KQL
          size         = 4
          title        = "Service Availability"
          queryType    = 0
          resourceType = "microsoft.insights/components"
          visualization = "tiles"
          tileSettings = {
            titleContent   = { columnMatch = "AvailabilityPct", formatter = 12, formatOptions = { palette = "greenRed" } }
            subtitleContent = { columnMatch = "TotalRequests" }
          }
        }
        name = "availability-tile"
      },
      # Avg / P95 / P99 Response Time tiles
      {
        type = 3
        content = {
          version      = "KqlItem/1.0"
          query        = <<-KQL
            AppRequests
            | where TimeGenerated {TimeRange}
            | summarize
                AvgDuration = round(avg(DurationMs), 1),
                P50 = round(percentile(DurationMs, 50), 1),
                P95 = round(percentile(DurationMs, 95), 1),
                P99 = round(percentile(DurationMs, 99), 1),
                Requests = count()
            | project
                ["Avg (ms)"] = AvgDuration,
                ["P50 (ms)"] = P50,
                ["P95 (ms)"] = P95,
                ["P99 (ms)"] = P99,
                ["Total Requests"] = Requests
          KQL
          size         = 4
          title        = "Response Time Summary"
          queryType    = 0
          resourceType = "microsoft.insights/components"
          visualization = "tiles"
        }
        name = "latency-tiles"
      },

      # ══════════════════════════════════════════════════════════
      # SECTION 2: Request Traffic & Performance
      # ══════════════════════════════════════════════════════════
      {
        type = 1
        content = { json = "## 📊 Request Traffic & Performance" }
        name = "section-traffic"
      },
      # Requests over time (success vs failure)
      {
        type = 3
        content = {
          version      = "KqlItem/1.0"
          query        = <<-KQL
            AppRequests
            | where TimeGenerated {TimeRange}
            | summarize
                Successful = countif(Success == true),
                Failed = countif(Success == false)
              by bin(TimeGenerated, {TimeRange:grain})
            | render timechart
          KQL
          size         = 0
          title        = "Requests Over Time (Success vs Failed)"
          queryType    = 0
          resourceType = "microsoft.insights/components"
          visualization = "timechart"
        }
        customWidth = "50"
        name = "requests-timechart"
      },
      # Response time percentiles over time
      {
        type = 3
        content = {
          version      = "KqlItem/1.0"
          query        = <<-KQL
            AppRequests
            | where TimeGenerated {TimeRange}
            | summarize
                P50 = percentile(DurationMs, 50),
                P95 = percentile(DurationMs, 95),
                P99 = percentile(DurationMs, 99)
              by bin(TimeGenerated, {TimeRange:grain})
            | render timechart
          KQL
          size         = 0
          title        = "Response Time Percentiles (ms)"
          queryType    = 0
          resourceType = "microsoft.insights/components"
          visualization = "timechart"
        }
        customWidth = "50"
        name = "latency-timechart"
      },
      # Response codes breakdown
      {
        type = 3
        content = {
          version      = "KqlItem/1.0"
          query        = <<-KQL
            AppRequests
            | where TimeGenerated {TimeRange}
            | extend StatusBucket = case(
                ResultCode startswith "2", "2xx Success",
                ResultCode startswith "3", "3xx Redirect",
                ResultCode startswith "4", "4xx Client Error",
                ResultCode startswith "5", "5xx Server Error",
                "Other")
            | summarize Count = count() by StatusBucket
            | order by StatusBucket asc
          KQL
          size         = 3
          title        = "HTTP Status Code Distribution"
          queryType    = 0
          resourceType = "microsoft.insights/components"
          visualization = "piechart"
        }
        customWidth = "33"
        name = "status-codes-pie"
      },
      # Top endpoints by volume
      {
        type = 3
        content = {
          version      = "KqlItem/1.0"
          query        = <<-KQL
            AppRequests
            | where TimeGenerated {TimeRange}
            | summarize
                Requests = count(),
                AvgDuration = round(avg(DurationMs), 1),
                P95Duration = round(percentile(DurationMs, 95), 1),
                ErrorRate = round(100.0 * countif(Success == false) / count(), 2)
              by Name
            | top 15 by Requests desc
            | project Endpoint = Name, Requests, ["Avg (ms)"] = AvgDuration, ["P95 (ms)"] = P95Duration, ["Error %"] = ErrorRate
          KQL
          size         = 1
          title        = "Top 15 Endpoints by Volume"
          queryType    = 0
          resourceType = "microsoft.insights/components"
          visualization = "table"
          gridSettings = {
            formatters = [
              { columnMatch = "Requests", formatter = 4, formatOptions = { palette = "blue" } },
              { columnMatch = "Error %", formatter = 18, formatOptions = { thresholdsOptions = "icons", thresholdsGrid = [
                { operator = ">=", thresholdValue = "5", representation = "4", text = "{0}%" },
                { operator = "Default", representation = "success", text = "{0}%" }
              ] } }
            ]
          }
        }
        customWidth = "67"
        name = "top-endpoints"
      },

      # ══════════════════════════════════════════════════════════
      # SECTION 3: Core Workflow Metrics
      # ══════════════════════════════════════════════════════════
      {
        type = 1
        content = { json = "## 🔄 Core Workflow Metrics\nArchitecture analysis → HLD generation → IaC generation → Export" }
        name = "section-workflow"
      },
      # Architecture Analysis pipeline
      {
        type = 3
        content = {
          version      = "KqlItem/1.0"
          query        = <<-KQL
            AppRequests
            | where TimeGenerated {TimeRange}
            | where Name has_any ("analyze", "generate-hld", "generate", "export", "terraform-preview")
            | extend Workflow = case(
                Name has "analyze", "1. Analyze",
                Name has "generate-hld", "2. HLD",
                Name has "generate" and not(Name has "hld"), "3. IaC Generate",
                Name has "export", "4. Export",
                Name has "terraform-preview", "5. TF Preview",
                "Other")
            | summarize
                Count = count(),
                AvgDuration = round(avg(DurationMs) / 1000, 1),
                SuccessRate = round(100.0 * countif(Success == true) / count(), 1)
              by Workflow
            | order by Workflow asc
            | project Workflow, Count, ["Avg (s)"] = AvgDuration, ["Success %"] = SuccessRate
          KQL
          size         = 1
          title        = "Workflow Pipeline Stats"
          queryType    = 0
          resourceType = "microsoft.insights/components"
          visualization = "table"
        }
        customWidth = "50"
        name = "workflow-table"
      },
      # Workflow volume over time
      {
        type = 3
        content = {
          version      = "KqlItem/1.0"
          query        = <<-KQL
            AppRequests
            | where TimeGenerated {TimeRange}
            | where Name has_any ("analyze", "generate-hld", "generate", "export")
            | extend Step = case(
                Name has "analyze", "Analyze",
                Name has "generate-hld", "HLD",
                Name has "generate", "IaC",
                Name has "export", "Export",
                "Other")
            | summarize Count = count() by Step, bin(TimeGenerated, {TimeRange:grain})
            | render timechart
          KQL
          size         = 0
          title        = "Workflow Steps Over Time"
          queryType    = 0
          resourceType = "microsoft.insights/components"
          visualization = "timechart"
        }
        customWidth = "50"
        name = "workflow-timechart"
      },

      # ══════════════════════════════════════════════════════════
      # SECTION 4: Errors & Exceptions
      # ══════════════════════════════════════════════════════════
      {
        type = 1
        content = { json = "## 🔴 Errors & Exceptions" }
        name = "section-errors"
      },
      # Error rate over time
      {
        type = 3
        content = {
          version      = "KqlItem/1.0"
          query        = <<-KQL
            AppRequests
            | where TimeGenerated {TimeRange}
            | summarize
                ErrorRate = round(100.0 * countif(Success == false) / count(), 2)
              by bin(TimeGenerated, {TimeRange:grain})
            | render timechart
          KQL
          size         = 0
          title        = "Error Rate % Over Time"
          queryType    = 0
          resourceType = "microsoft.insights/components"
          visualization = "timechart"
        }
        customWidth = "50"
        name = "error-rate-chart"
      },
      # Top exceptions
      {
        type = 3
        content = {
          version      = "KqlItem/1.0"
          query        = <<-KQL
            AppExceptions
            | where TimeGenerated {TimeRange}
            | summarize Count = count() by ExceptionType, OuterMessage
            | top 10 by Count desc
            | project Exception = ExceptionType, Message = substring(OuterMessage, 0, 80), Count
          KQL
          size         = 1
          title        = "Top 10 Exceptions"
          queryType    = 0
          resourceType = "microsoft.insights/components"
          visualization = "table"
          gridSettings = {
            formatters = [
              { columnMatch = "Count", formatter = 4, formatOptions = { palette = "red" } }
            ]
          }
        }
        customWidth = "50"
        name = "top-exceptions"
      },
      # Failed requests detail
      {
        type = 3
        content = {
          version      = "KqlItem/1.0"
          query        = <<-KQL
            AppRequests
            | where TimeGenerated {TimeRange}
            | where Success == false
            | summarize
                Count = count(),
                AvgDuration = round(avg(DurationMs), 0)
              by Name, ResultCode
            | top 15 by Count desc
            | project Endpoint = Name, Status = ResultCode, Count, ["Avg (ms)"] = AvgDuration
          KQL
          size         = 1
          title        = "Top Failed Endpoints"
          queryType    = 0
          resourceType = "microsoft.insights/components"
          visualization = "table"
        }
        name = "failed-endpoints-table"
      },

      # ══════════════════════════════════════════════════════════
      # SECTION 5: Dependencies (OpenAI, PostgreSQL, Storage)
      # ══════════════════════════════════════════════════════════
      {
        type = 1
        content = { json = "## 🔗 External Dependencies (OpenAI, DB, Storage)" }
        name = "section-dependencies"
      },
      # Dependency call volume and latency
      {
        type = 3
        content = {
          version      = "KqlItem/1.0"
          query        = <<-KQL
            AppDependencies
            | where TimeGenerated {TimeRange}
            | summarize
                Calls = count(),
                AvgDuration = round(avg(DurationMs), 1),
                FailureRate = round(100.0 * countif(Success == false) / count(), 2)
              by DependencyType = Type, Target = coalesce(Target, Name)
            | top 10 by Calls desc
            | project DependencyType, Target, Calls, ["Avg (ms)"] = AvgDuration, ["Fail %"] = FailureRate
          KQL
          size         = 1
          title        = "Dependency Health"
          queryType    = 0
          resourceType = "microsoft.insights/components"
          visualization = "table"
          gridSettings = {
            formatters = [
              { columnMatch = "Calls", formatter = 4, formatOptions = { palette = "blue" } },
              { columnMatch = "Fail %", formatter = 18, formatOptions = { thresholdsOptions = "icons", thresholdsGrid = [
                { operator = ">=", thresholdValue = "5", representation = "4", text = "{0}%" },
                { operator = "Default", representation = "success", text = "{0}%" }
              ] } }
            ]
          }
        }
        customWidth = "50"
        name = "dependency-health"
      },
      # Dependency latency over time
      {
        type = 3
        content = {
          version      = "KqlItem/1.0"
          query        = <<-KQL
            AppDependencies
            | where TimeGenerated {TimeRange}
            | summarize AvgDuration = avg(DurationMs) by Type, bin(TimeGenerated, {TimeRange:grain})
            | render timechart
          KQL
          size         = 0
          title        = "Dependency Latency Over Time (ms)"
          queryType    = 0
          resourceType = "microsoft.insights/components"
          visualization = "timechart"
        }
        customWidth = "50"
        name = "dependency-latency-chart"
      },
      # OpenAI specific metrics
      {
        type = 3
        content = {
          version      = "KqlItem/1.0"
          query        = <<-KQL
            AppDependencies
            | where TimeGenerated {TimeRange}
            | where Type == "HTTP" and (Target has "openai" or Name has "openai")
            | summarize
                Calls = count(),
                AvgLatency = round(avg(DurationMs) / 1000, 2),
                P95Latency = round(percentile(DurationMs, 95) / 1000, 2),
                Failures = countif(Success == false)
              by bin(TimeGenerated, {TimeRange:grain})
            | render timechart
          KQL
          size         = 0
          title        = "OpenAI API Calls & Latency (seconds)"
          queryType    = 0
          resourceType = "microsoft.insights/components"
          visualization = "timechart"
        }
        name = "openai-metrics"
      },

      # ══════════════════════════════════════════════════════════
      # SECTION 6: Infrastructure Metrics
      # ══════════════════════════════════════════════════════════
      {
        type = 1
        content = { json = "## 🖥️ Infrastructure\nContainer App, PostgreSQL, Storage Account" }
        name = "section-infra"
      },
      # Container App – Replica count & restarts
      {
        type = 3
        content = {
          version      = "KqlItem/1.0"
          query        = <<-KQL
            ContainerAppConsoleLogs_CL
            | where TimeGenerated {TimeRange}
            | where ContainerAppName_s == "archmorph-api"
            | where Log_s has_any ("error", "exception", "critical", "failed", "traceback")
            | summarize Count = count() by bin(TimeGenerated, {TimeRange:grain})
            | render timechart
          KQL
          size         = 0
          title        = "Container App Error Logs"
          queryType    = 0
          resourceType = "microsoft.operationalinsights/workspaces"
          visualization = "timechart"
        }
        customWidth = "50"
        name = "container-errors"
      },
      # Container App system logs
      {
        type = 3
        content = {
          version      = "KqlItem/1.0"
          query        = <<-KQL
            ContainerAppSystemLogs_CL
            | where TimeGenerated {TimeRange}
            | where ContainerAppName_s == "archmorph-api"
            | summarize Count = count() by Type_s, Reason_s
            | top 10 by Count desc
          KQL
          size         = 1
          title        = "Container App System Events"
          queryType    = 0
          resourceType = "microsoft.operationalinsights/workspaces"
          visualization = "table"
        }
        customWidth = "50"
        name = "container-system-events"
      },
      # PostgreSQL metrics
      {
        type = 3
        content = {
          version      = "KqlItem/1.0"
          query        = <<-KQL
            AzureDiagnostics
            | where TimeGenerated {TimeRange}
            | where ResourceProvider == "MICROSOFT.DBFORPOSTGRESQL"
            | where Category == "PostgreSQLLogs"
            | where Message has_any ("ERROR", "FATAL", "PANIC")
            | summarize Count = count() by Severity = errorLevel_s, bin(TimeGenerated, {TimeRange:grain})
            | render timechart
          KQL
          size         = 0
          title        = "PostgreSQL Errors Over Time"
          queryType    = 0
          resourceType = "microsoft.operationalinsights/workspaces"
          visualization = "timechart"
        }
        customWidth = "50"
        name = "pg-errors"
      },
      # Key Vault audit
      {
        type = 3
        content = {
          version      = "KqlItem/1.0"
          query        = <<-KQL
            AzureDiagnostics
            | where TimeGenerated {TimeRange}
            | where ResourceProvider == "MICROSOFT.KEYVAULT"
            | summarize Operations = count() by OperationName, ResultType
            | top 10 by Operations desc
          KQL
          size         = 1
          title        = "Key Vault Operations"
          queryType    = 0
          resourceType = "microsoft.operationalinsights/workspaces"
          visualization = "table"
        }
        customWidth = "50"
        name = "keyvault-audit"
      },

      # ══════════════════════════════════════════════════════════
      # SECTION 7: User Analytics & Adoption
      # ══════════════════════════════════════════════════════════
      {
        type = 1
        content = { json = "## 👥 User Analytics & Adoption" }
        name = "section-users"
      },
      # Unique users over time
      {
        type = 3
        content = {
          version      = "KqlItem/1.0"
          query        = <<-KQL
            AppRequests
            | where TimeGenerated {TimeRange}
            | where ClientIP != "0.0.0.0"
            | summarize
                UniqueUsers = dcount(ClientIP),
                Sessions = dcount(SessionId)
              by bin(TimeGenerated, {TimeRange:grain})
            | render timechart
          KQL
          size         = 0
          title        = "Unique Users & Sessions"
          queryType    = 0
          resourceType = "microsoft.insights/components"
          visualization = "timechart"
        }
        customWidth = "50"
        name = "user-sessions"
      },
      # Feature adoption funnel
      {
        type = 3
        content = {
          version      = "KqlItem/1.0"
          query        = <<-KQL
            AppRequests
            | where TimeGenerated {TimeRange}
            | summarize
                DiagramUploads = countif(Name has "/diagrams" and Name has "POST"),
                Analyses = countif(Name has "analyze"),
                HLDs = countif(Name has "generate-hld"),
                IaCGenerated = countif(Name has "/generate" and not(Name has "hld")),
                Exports = countif(Name has "export"),
                ChatSessions = countif(Name has "/chat"),
                TFPreviews = countif(Name has "terraform-preview"),
                Feedback = countif(Name has "feedback" or Name has "nps")
          KQL
          size         = 4
          title        = "Feature Adoption (Count)"
          queryType    = 0
          resourceType = "microsoft.insights/components"
          visualization = "tiles"
        }
        customWidth = "50"
        name = "feature-adoption"
      },

      # ══════════════════════════════════════════════════════════
      # SECTION 8: Security & Compliance
      # ══════════════════════════════════════════════════════════
      {
        type = 1
        content = { json = "## 🔒 Security & Compliance" }
        name = "section-security"
      },
      # Auth events
      {
        type = 3
        content = {
          version      = "KqlItem/1.0"
          query        = <<-KQL
            AppRequests
            | where TimeGenerated {TimeRange}
            | where Name has "auth"
            | summarize
                Logins = countif(Name has "login"),
                Failed = countif(Name has "login" and Success == false),
                QuotaChecks = countif(Name has "quota")
              by bin(TimeGenerated, {TimeRange:grain})
            | render timechart
          KQL
          size         = 0
          title        = "Auth Events (Login / Failures / Quota)"
          queryType    = 0
          resourceType = "microsoft.insights/components"
          visualization = "timechart"
        }
        customWidth = "50"
        name = "auth-events"
      },
      # Suspicious activity
      {
        type = 3
        content = {
          version      = "KqlItem/1.0"
          query        = <<-KQL
            AppRequests
            | where TimeGenerated {TimeRange}
            | where ResultCode in ("401", "403", "429")
            | summarize Count = count() by ResultCode, ClientIP = ClientIP, Endpoint = Name
            | top 15 by Count desc
            | project Status = ResultCode, ClientIP, Endpoint, Count
          KQL
          size         = 1
          title        = "Blocked / Rate-Limited Requests"
          queryType    = 0
          resourceType = "microsoft.insights/components"
          visualization = "table"
          gridSettings = {
            formatters = [
              { columnMatch = "Count", formatter = 4, formatOptions = { palette = "redBright" } }
            ]
          }
        }
        customWidth = "50"
        name = "security-blocks"
      },

      # ══════════════════════════════════════════════════════════
      # SECTION 9: Alerts Summary
      # ══════════════════════════════════════════════════════════
      {
        type = 1
        content = { json = "## 🔔 Recent Alerts" }
        name = "section-alerts"
      },
      {
        type = 3
        content = {
          version      = "KqlItem/1.0"
          query        = <<-KQL
            AlertsManagementResources
            | where type == "microsoft.alertsmanagement/alerts"
            | where properties.essentials.targetResourceGroup has "archmorph"
            | extend
                Severity = tostring(properties.essentials.severity),
                State = tostring(properties.essentials.alertState),
                FiredTime = todatetime(properties.essentials.startDateTime),
                AlertName = tostring(properties.essentials.alertRule)
            | project FiredTime, AlertName, Severity, State
            | top 20 by FiredTime desc
          KQL
          size         = 1
          title        = "Recent Alert History"
          queryType    = 1
          resourceType = "microsoft.resourcegraph/resources"
          crossComponentResources = ["value::all"]
          visualization = "table"
        }
        name = "alert-history"
      }
    ]
    isLocked = false
    fallbackResourceIds = [azurerm_application_insights.main.id]
  })
  
  tags = local.tags
}

# ─────────────────────────────────────────────────────────────
# Microsoft Defender for Cloud (Optional - for enterprise)
# ─────────────────────────────────────────────────────────────
# Uncomment to enable Defender for key resources in production
# resource "azurerm_security_center_subscription_pricing" "storage" {
#   count         = var.environment == "prod" ? 1 : 0
#   tier          = "Standard"
#   resource_type = "StorageAccounts"
# }
#
# resource "azurerm_security_center_subscription_pricing" "keyvault" {
#   count         = var.environment == "prod" ? 1 : 0
#   tier          = "Standard"
#   resource_type = "KeyVaults"
# }
#
# resource "azurerm_security_center_subscription_pricing" "containers" {
#   count         = var.environment == "prod" ? 1 : 0
#   tier          = "Standard"
#   resource_type = "Containers"
# }
