# ─────────────────────────────────────────────────────────────
# Archmorph — Disaster Recovery Configuration
# Issue #147: Staging / DR / Blue-Green Deploy
#
# DR Strategy:
# 1. PostgreSQL — PITR (Point-in-Time Recovery) with geo-redundant backups
# 2. Storage — GRS (Geo-Redundant Storage) already configured in prod
# 3. ACR — Geo-replication to secondary region
# 4. DNS — Azure Traffic Manager for failover routing
# 5. Container Apps — Secondary region standby environment
#
# This module adds DR-specific resources to the production deployment.
# It should be included alongside the main infra/main.tf configuration.
# ─────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────
# Variables
# ─────────────────────────────────────────────────────────────
variable "enable_dr" {
  description = "Enable disaster recovery resources (additional cost)"
  type        = bool
  default     = false
}

variable "dr_location" {
  description = "Secondary Azure region for DR"
  type        = string
  default     = "northeurope"
}

variable "primary_app_fqdn" {
  description = "FQDN of the primary Container App"
  type        = string
  default     = ""
}

variable "primary_resource_group" {
  description = "Primary resource group name"
  type        = string
  default     = "archmorph-rg-prod"
}

variable "frontend_url" {
  description = "Frontend URL for CORS (same SWA origin used by production)"
  type        = string
  default     = "https://archmorphai.com"
}

variable "health_probe_path" {
  description = "Health probe path used by DR traffic manager checks."
  type        = string
  default     = "/api/health"
}

# ─────────────────────────────────────────────────────────────
# DR Resource Group
# ─────────────────────────────────────────────────────────────
resource "azurerm_resource_group" "dr" {
  count    = var.enable_dr ? 1 : 0
  name     = "archmorph-rg-dr"
  location = var.dr_location
  tags = {
    project     = "archmorph"
    environment = "dr"
    managed_by  = "terraform"
    purpose     = "disaster-recovery"
  }
}

# ─────────────────────────────────────────────────────────────
# DR Log Analytics
# ─────────────────────────────────────────────────────────────
resource "azurerm_log_analytics_workspace" "dr" {
  count               = var.enable_dr ? 1 : 0
  name                = "archmorph-logs-dr"
  resource_group_name = azurerm_resource_group.dr[0].name
  location            = azurerm_resource_group.dr[0].location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags = {
    project     = "archmorph"
    environment = "dr"
    managed_by  = "terraform"
  }
}

# ─────────────────────────────────────────────────────────────
# DR Container App Environment (North Europe)
# ─────────────────────────────────────────────────────────────
resource "azurerm_container_app_environment" "dr" {
  count                      = var.enable_dr ? 1 : 0
  name                       = "archmorph-cae-dr"
  resource_group_name        = azurerm_resource_group.dr[0].name
  location                   = azurerm_resource_group.dr[0].location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.dr[0].id

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }

  tags = {
    project     = "archmorph"
    environment = "dr"
    managed_by  = "terraform"
  }
}

# ─────────────────────────────────────────────────────────────
# DR Container App (standby — 0 replicas until failover)
# ─────────────────────────────────────────────────────────────
resource "azurerm_container_app" "dr_backend" {
  count                        = var.enable_dr ? 1 : 0
  name                         = "archmorph-api-dr"
  resource_group_name          = azurerm_resource_group.dr[0].name
  container_app_environment_id = azurerm_container_app_environment.dr[0].id
  revision_mode                = "Single"

  tags = {
    project     = "archmorph"
    environment = "dr"
    managed_by  = "terraform"
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "http"

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }

    cors {
      allowed_origins    = [var.frontend_url]
      allowed_methods    = ["GET", "POST", "PATCH", "DELETE", "OPTIONS"]
      allowed_headers    = ["Content-Type", "Authorization", "X-API-Key", "X-Correlation-ID"]
      exposed_headers    = ["X-Correlation-ID", "X-Response-Time"]
      max_age_in_seconds = 3600
    }
  }

  template {
    min_replicas = 0 # Standby — scale to 0 until failover
    max_replicas = 10

    container {
      name   = "api"
      image  = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"
      cpu    = 1.0
      memory = "2Gi"

      env {
        name  = "ENVIRONMENT"
        value = "dr"
      }

      env {
        name  = "ALLOWED_ORIGINS"
        value = var.frontend_url
      }
    }
  }
}

# ─────────────────────────────────────────────────────────────
# Azure Traffic Manager (DNS-based failover)
# ─────────────────────────────────────────────────────────────
resource "azurerm_traffic_manager_profile" "failover" {
  count               = var.enable_dr ? 1 : 0
  name                = "archmorph-tm"
  resource_group_name = var.primary_resource_group
  profile_status      = "Enabled"

  traffic_routing_method = "Priority"

  dns_config {
    relative_name = "archmorph-api"
    ttl           = 60
  }

  monitor_config {
    protocol                     = "HTTPS"
    port                         = 443
    path                         = var.health_probe_path
    interval_in_seconds          = 30
    timeout_in_seconds           = 10
    tolerated_number_of_failures = 3
  }

  tags = {
    project     = "archmorph"
    environment = "global"
    managed_by  = "terraform"
  }
}

# Primary endpoint (West Europe — priority 1)
resource "azurerm_traffic_manager_external_endpoint" "primary" {
  count      = var.enable_dr ? 1 : 0
  name       = "primary-westeurope"
  profile_id = azurerm_traffic_manager_profile.failover[0].id
  target     = var.primary_app_fqdn
  priority   = 1
  weight     = 1

  custom_header {
    name  = "host"
    value = var.primary_app_fqdn
  }
}

# DR endpoint (North Europe — priority 2, failover)
resource "azurerm_traffic_manager_external_endpoint" "dr" {
  count      = var.enable_dr ? 1 : 0
  name       = "dr-northeurope"
  profile_id = azurerm_traffic_manager_profile.failover[0].id
  target     = var.enable_dr ? azurerm_container_app.dr_backend[0].ingress[0].fqdn : ""
  priority   = 2
  weight     = 1

  custom_header {
    name  = "host"
    value = var.enable_dr ? azurerm_container_app.dr_backend[0].ingress[0].fqdn : ""
  }
}

# ─────────────────────────────────────────────────────────────
# Outputs
# ─────────────────────────────────────────────────────────────
output "dr_enabled" {
  description = "Whether DR is enabled"
  value       = var.enable_dr
}

output "dr_app_url" {
  description = "DR Container App URL"
  value       = var.enable_dr ? "https://${azurerm_container_app.dr_backend[0].ingress[0].fqdn}" : "N/A"
}

output "traffic_manager_fqdn" {
  description = "Traffic Manager FQDN for DNS failover"
  value       = var.enable_dr ? azurerm_traffic_manager_profile.failover[0].fqdn : "N/A"
}
