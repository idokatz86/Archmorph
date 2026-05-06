variable "subscription_id" {
  description = "Azure Subscription ID"
  type        = string
}

variable "location" {
  description = "Azure region for resources"
  type        = string
  default     = "westeurope"
}

variable "openai_location" {
  description = "Azure region for OpenAI (limited availability)"
  type        = string
  default     = "westeurope"
  # #607 cutover is live in West Europe. Import the live account before applying #608 Terraform state sync.
}

variable "openai_capacity" {
  description = "Azure OpenAI deployment capacity in thousands of tokens per minute (TPM). 10 matches the live West Europe cutover; raise only after quota validation."
  type        = number
  default     = 10

  validation {
    condition     = var.openai_capacity >= 10 && var.openai_capacity <= 1000
    error_message = "OpenAI capacity must be between 10 and 1000 TPM."
  }
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be dev, staging, or prod."
  }
}

variable "db_admin_username" {
  description = "PostgreSQL administrator username"
  type        = string
  # Must be set in terraform.tfvars - no default for security
}

variable "db_admin_password" {
  description = "PostgreSQL administrator password"
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.db_admin_password) >= 16
    error_message = "Database password must be at least 16 characters for security compliance."
  }
}

variable "alert_email" {
  description = "Email address for Azure Monitor alerts"
  type        = string
  # Must be set in terraform.tfvars - no default for security
}

variable "frontend_url" {
  description = "Frontend URL for CORS configuration"
  type        = string
  # Must be set in terraform.tfvars - no default for security
}

# ─────────────────────────────────────────────────────────────
# Azure Cache for Redis
# ─────────────────────────────────────────────────────────────
variable "redis_capacity" {
  description = "Redis cache capacity (0 = 250MB, 1 = 1GB, 2 = 2.5GB). Basic C0 ~$16/mo, Standard C0 ~$40/mo."
  type        = number
  default     = 0

  validation {
    condition     = var.redis_capacity >= 0 && var.redis_capacity <= 6
    error_message = "Redis capacity must be between 0 and 6."
  }
}

# ─────────────────────────────────────────────────────────────
# DR Configuration (Issue #147)
# ─────────────────────────────────────────────────────────────
variable "enable_dr" {
  description = "Enable disaster recovery (secondary region, Traffic Manager). Additional cost applies."
  type        = bool
  default     = false
}

variable "dr_location" {
  description = "Secondary Azure region for disaster recovery"
  type        = string
  default     = "northeurope"
}
