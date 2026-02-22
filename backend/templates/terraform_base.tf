# ============================================================
# Archmorph – Azure Infrastructure as Code (Terraform)
# Auto-generated from architecture diagram analysis
# ============================================================

terraform {
  required_version = ">= 1.5"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.85"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  features {}
}

locals {
  project  = "{{PROJECT_NAME}}"
  env      = "{{ENVIRONMENT}}"
  location = "{{REGION}}"
  tags = {
    Project     = "{{PROJECT_NAME}}"
    ManagedBy   = "Archmorph"
    Environment = local.env
    Source      = "Cloud-Migration"
  }
}

# ── Resource Group ──────────────────────────────────────────
resource "azurerm_resource_group" "main" {
  name     = "rg-${local.project}-${local.env}"
  location = local.location
  tags     = local.tags
}

# ── Key Vault (central secret management) ──────────────────
data "azurerm_client_config" "current" {}

resource "azurerm_key_vault" "main" {
  name                       = "kv-${local.project}-${local.env}"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days = 7
  purge_protection_enabled   = false
  rbac_authorization_enabled = true
  tags                       = local.tags
}
