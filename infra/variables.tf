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

variable "prefer_paired_dr_region" {
  description = "When true, derive DR region from Azure paired-region map for the primary location."
  type        = bool
  default     = true
}

variable "paired_region_overrides" {
  description = "Optional overrides for paired DR regions keyed by primary region."
  type        = map(string)
  default     = {}
}

variable "backend_container_image" {
  description = "Container image reference for backend app (tag or immutable digest). Empty uses ACR latest."
  type        = string
  default     = ""
}

variable "acr_prod_sku" {
  description = "ACR SKU used in production."
  type        = string
  default     = "Premium"

  validation {
    condition     = contains(["Standard", "Premium"], var.acr_prod_sku)
    error_message = "acr_prod_sku must be Standard or Premium."
  }
}

variable "acr_geo_replica_locations" {
  description = "Optional list of extra regions for ACR geo-replication (Premium only)."
  type        = list(string)
  default     = []
}

variable "enable_redis_private_endpoint" {
  description = "Enable Redis private endpoint + private DNS in production."
  type        = bool
  default     = false
}

variable "enable_front_door_waf" {
  description = "Enable Azure Front Door Premium and WAF resources."
  type        = bool
  default     = true
}

variable "enable_policy_assignments" {
  description = "Enable baseline policy definitions and assignments for location/tags/SKUs."
  type        = bool
  default     = false
}

variable "allowed_resource_locations" {
  description = "Allowed Azure locations enforced by policy assignment."
  type        = list(string)
  default     = ["westeurope", "northeurope"]
}

variable "openai_auth_mode" {
  description = "Azure OpenAI auth mode for app config."
  type        = string
  default     = "managed_identity"

  validation {
    condition     = contains(["managed_identity", "api_key"], var.openai_auth_mode)
    error_message = "openai_auth_mode must be managed_identity or api_key."
  }
}

variable "prod_max_replicas" {
  description = "Maximum replicas for production backend Container App."
  type        = number
  default     = 10
}

variable "prod_http_concurrent_requests" {
  description = "HTTP concurrent requests scale threshold for production."
  type        = number
  default     = 25
}

variable "cpu_scale_threshold_percent" {
  description = "CPU utilization scale-out threshold percent."
  type        = number
  default     = 70
}

variable "aoai_monthly_budget_amount" {
  description = "Monthly AOAI budget amount for resource-group budget alerts. Set to 0 to disable."
  type        = number
  default     = 0
}

variable "storage_cmk_key_vault_key_id" {
  description = "Optional Key Vault key ID to enable customer-managed key encryption for Storage."
  type        = string
  default     = ""

  validation {
    condition     = var.storage_cmk_key_vault_key_id == "" || can(regex("^https://[a-zA-Z0-9-]+\\.vault\\.azure\\.net/keys/[^/]+/[^/]+$", var.storage_cmk_key_vault_key_id))
    error_message = "storage_cmk_key_vault_key_id must be empty or a full Key Vault URL like https://<vault>.vault.azure.net/keys/<name>/<version>."
  }
}

variable "health_probe_path" {
  description = "Health probe path for infra checks (set to /healthz once endpoint is live in deployed API)."
  type        = string
  default     = "/api/health"
}
