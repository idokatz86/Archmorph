variable "subscription_id" {
  description = "Azure Subscription ID"
  type        = string
}

variable "release_automation_principal_id" {
  description = "Object ID of the reviewed workload identity allowed to coordinate production rollout Blob leases. Supply only through private configuration."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.release_automation_principal_id))
    error_message = "release_automation_principal_id must be a UUID-shaped Microsoft Entra object ID."
  }
}

variable "rollout_priority_principal_id" {
  description = "Object ID of the priority-only GitHub OIDC identity. It receives only coordination-container data-plane access."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.rollout_priority_principal_id))
    error_message = "rollout_priority_principal_id must be a UUID-shaped Microsoft Entra object ID."
  }
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

variable "resource_group_environment" {
  description = "Optional legacy environment suffix used for Azure resource names/resource group while runtime environment remains production."
  type        = string
  nullable    = true
  default     = null

  validation {
    condition     = var.resource_group_environment == null || contains(["dev", "staging", "prod"], var.resource_group_environment)
    error_message = "resource_group_environment must be null, dev, staging, or prod."
  }
}

variable "enable_production_infra_hardening" {
  description = "Enable production SKU, network, DR, and private endpoint hardening. Keep false for the legacy live-stack identity cutover until the migration plan is reviewed."
  type        = bool
  default     = true
}

variable "key_vault_rbac_authorization_enabled" {
  description = "Reviewed Key Vault authorization mode. Set true only after all workload identities have equivalent RBAC grants; false retains access-policy mode during migration."
  type        = bool
  default     = true

  validation {
    condition     = !var.enable_production_infra_hardening || var.environment != "prod" || var.key_vault_rbac_authorization_enabled
    error_message = "Production infrastructure hardening requires reviewed Key Vault RBAC authorization."
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

variable "openai_api_key" {
  description = "Legacy Azure OpenAI API key secret value retained during the production managed identity cutover."
  type        = string
  sensitive   = true
  nullable    = true
  default     = null

  validation {
    condition     = var.openai_api_key == null || length(var.openai_api_key) > 0
    error_message = "openai_api_key must be null or a non-empty string."
  }
}

variable "preserve_legacy_openai_key" {
  description = "Manage the existing legacy openai-api-key Key Vault secret during the production managed identity cutover."
  type        = bool
  default     = false

  validation {
    condition     = !var.preserve_legacy_openai_key || (var.openai_api_key != null && length(var.openai_api_key) > 0)
    error_message = "openai_api_key must be provided when preserve_legacy_openai_key is true."
  }
}

variable "archmorph_api_key" {
  description = "Base Archmorph static API credential. Supply only through private sensitive configuration."
  type        = string
  sensitive   = true
  nullable    = true
  default     = null
}

variable "manage_archmorph_api_key" {
  description = "Manage the base Archmorph API key in Key Vault and wire it to Container Apps."
  type        = bool
  default     = false
}

variable "archmorph_api_key_rotated" {
  description = "Optional current Archmorph static API credential used during rotation. Supply only through private sensitive configuration."
  type        = string
  sensitive   = true
  nullable    = true
  default     = null
}

variable "manage_archmorph_api_key_rotated" {
  description = "Manage the current rotated Archmorph API key in Key Vault and wire it to Container Apps."
  type        = bool
  default     = false
}

variable "archmorph_api_key_principal_id" {
  description = "Stable non-secret static service principal identifier. It must remain unchanged across credential rotations."
  type        = string
  nullable    = true
  default     = null

  validation {
    condition     = var.archmorph_api_key_principal_id == null || can(regex("^[A-Za-z0-9][A-Za-z0-9._:-]{2,99}$", var.archmorph_api_key_principal_id))
    error_message = "archmorph_api_key_principal_id must be null or a stable 3-100 character identifier."
  }
}

variable "archmorph_api_key_allow_legacy_overlap" {
  description = "Allow the base static API credential while a rotated credential is configured. Set false for cutover."
  type        = bool
  default     = false

  validation {
    condition     = !var.archmorph_api_key_allow_legacy_overlap || var.manage_archmorph_api_key_rotated
    error_message = "Legacy overlap requires manage_archmorph_api_key_rotated=true."
  }
}

# ─────────────────────────────────────────────────────────────
# Azure Cache for Redis
# ─────────────────────────────────────────────────────────────
variable "redis_name_override" {
  description = "Optional existing Redis cache name to preserve during legacy live-stack import reconciliation. Leave null for suffix-based names on new stacks."
  type        = string
  nullable    = true
  default     = null

  validation {
    condition     = var.redis_name_override == null || can(regex("^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$", var.redis_name_override))
    error_message = "redis_name_override must be null or a valid Azure Cache for Redis name."
  }
}

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
  description = "Container image reference for backend app. Production/staging require an immutable digest; dev may use a non-latest tag."
  type        = string

  validation {
    condition = (
      var.environment == "dev"
      ? (length(trimspace(var.backend_container_image)) > 0 && !endswith(lower(var.backend_container_image), ":latest"))
      : can(regex("^[^[:space:]@]+@sha256:[0-9a-f]{64}$", var.backend_container_image))
    )
    error_message = "Production/staging backend_container_image must be an immutable registry/repository@sha256:<64 lowercase hex> reference; latest is never allowed."
  }
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

variable "enable_redis_private_endpoint" {
  description = "Enable Redis private endpoint + private DNS in production. Must be true when environment=prod (Redis disables public access in production)."
  type        = bool
  default     = true
}

variable "enable_storage_private_endpoint" {
  description = "Enable Blob Storage private endpoint + private DNS in production. Must be true when environment=prod (Storage uses deny-by-default firewall in production)."
  type        = bool
  default     = true
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

variable "aoai_budget_start_date" {
  description = "Stable UTC start date for AOAI budget alerts in RFC3339 format."
  type        = string
  default     = "2026-01-01T00:00:00Z"
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
  description = "Anonymous liveness probe path. Must not depend on PostgreSQL or Redis."
  type        = string
  default     = "/healthz"
}

variable "readiness_probe_path" {
  description = "Anonymous readiness probe path for required PostgreSQL and Redis dependencies."
  type        = string
  default     = "/readyz"
}

variable "app_insights_sampling_percentage_prod" {
  description = "Production Application Insights sampling percentage for cost control. Non-production remains 100%."
  type        = number
  default     = 10

  validation {
    condition     = var.app_insights_sampling_percentage_prod >= 1 && var.app_insights_sampling_percentage_prod <= 100
    error_message = "app_insights_sampling_percentage_prod must be between 1 and 100."
  }
}

variable "workbook_id_override" {
  description = "Optional existing Azure Monitor Workbook UUID. Supply privately when adopting an existing stack."
  type        = string
  nullable    = true
  default     = null

  validation {
    condition     = var.workbook_id_override == null || can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.workbook_id_override))
    error_message = "workbook_id_override must be null or a UUID."
  }
}
