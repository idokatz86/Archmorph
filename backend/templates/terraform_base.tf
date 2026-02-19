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
