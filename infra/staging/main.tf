# ─────────────────────────────────────────────────────────────
# Archmorph — Staging Environment Terraform Configuration
# Issue #147: Staging / DR / Blue-Green Deploy
#
# Usage:
#   cd infra/staging
#   terraform init
#   terraform plan -var-file=staging.tfvars
#   terraform apply -var-file=staging.tfvars
#
# This module provisions a staging environment that mirrors production
# with reduced resource sizes for cost efficiency.
# ─────────────────────────────────────────────────────────────

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.60"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  backend "azurerm" {
    resource_group_name  = "archmorph-tfstate-rg"
    storage_account_name = "archmorphtfstate"
    container_name       = "tfstate"
    key                  = "archmorph-staging.tfstate"
    use_azuread_auth     = true
  }
}

provider "azurerm" {
  features {
    resource_group {
      prevent_deletion_if_contains_resources = true
    }
  }
  subscription_id = var.subscription_id
}

# ─────────────────────────────────────────────────────────────
# Variables
# ─────────────────────────────────────────────────────────────
variable "subscription_id" {
  description = "Azure Subscription ID"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "westeurope"
}

variable "alert_email" {
  description = "Email for staging alerts"
  type        = string
}

variable "staging_frontend_url" {
  description = "Staging frontend URL for CORS configuration"
  type        = string
  default     = "https://archmorph-staging.azurestaticapps.net"
}

# ─────────────────────────────────────────────────────────────
# Random suffix
# ─────────────────────────────────────────────────────────────
resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

locals {
  name_suffix = random_string.suffix.result
  environment = "staging"
  tags = {
    project     = "archmorph"
    environment = "staging"
    managed_by  = "terraform"
    purpose     = "pre-production validation"
  }
}

# ─────────────────────────────────────────────────────────────
# Resource Group
# ─────────────────────────────────────────────────────────────
resource "azurerm_resource_group" "staging" {
  name     = "archmorph-rg-staging"
  location = var.location
  tags     = local.tags
}

# ─────────────────────────────────────────────────────────────
# Log Analytics (shorter retention for cost savings)
# ─────────────────────────────────────────────────────────────
resource "azurerm_log_analytics_workspace" "staging" {
  name                = "archmorph-logs-stg-${local.name_suffix}"
  resource_group_name = azurerm_resource_group.staging.name
  location            = azurerm_resource_group.staging.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

# ─────────────────────────────────────────────────────────────
# Container App Environment (staging)
# ─────────────────────────────────────────────────────────────
resource "azurerm_container_app_environment" "staging" {
  name                       = "archmorph-cae-staging"
  resource_group_name        = azurerm_resource_group.staging.name
  location                   = azurerm_resource_group.staging.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.staging.id

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }

  tags = local.tags
}

# ─────────────────────────────────────────────────────────────
# Container App (staging — smaller resources)
# ─────────────────────────────────────────────────────────────
resource "azurerm_container_app" "staging_backend" {
  name                         = "archmorph-api-staging"
  resource_group_name          = azurerm_resource_group.staging.name
  container_app_environment_id = azurerm_container_app_environment.staging.id
  revision_mode                = "Multiple" # Blue-green support

  tags = local.tags

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "http"

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }

    cors_policy {
      allowed_origins   = [var.staging_frontend_url]
      allowed_methods   = ["GET", "POST", "PATCH", "DELETE", "OPTIONS"]
      allowed_headers   = ["Content-Type", "Authorization", "X-API-Key", "X-Correlation-ID"]
      expose_headers    = ["X-Correlation-ID", "X-Response-Time"]
      max_age           = 3600
      allow_credentials = false
    }
  }

  template {
    min_replicas = 1
    max_replicas = 3

    http_scale_rule {
      name                = "http-concurrency"
      concurrent_requests = "15"
    }

    container {
      name   = "api"
      image  = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest" # Placeholder — CI deploys real image
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "ENVIRONMENT"
        value = "staging"
      }

      env {
        name  = "ALLOWED_ORIGINS"
        value = var.staging_frontend_url
      }

      env {
        name  = "RATE_LIMIT_ENABLED"
        value = "true"
      }
    }
  }
}

# ─────────────────────────────────────────────────────────────
# Outputs
# ─────────────────────────────────────────────────────────────
output "staging_app_url" {
  description = "Staging Container App URL"
  value       = "https://${azurerm_container_app.staging_backend.ingress[0].fqdn}"
}

output "staging_resource_group" {
  description = "Staging resource group name"
  value       = azurerm_resource_group.staging.name
}

output "staging_container_app_name" {
  description = "Staging Container App name"
  value       = azurerm_container_app.staging_backend.name
}
