variable "subscription_id" {
  description = "Azure subscription containing the existing runtime prerequisites."
  type        = string
  sensitive   = true
}

variable "resource_group_name" {
  description = "Existing runtime resource group supplied through private deployment configuration."
  type        = string
}

variable "container_app_environment_name" {
  description = "Existing Container Apps environment supplied through private deployment configuration."
  type        = string
}

variable "container_registry_name" {
  description = "Existing Azure Container Registry supplied through private deployment configuration."
  type        = string
}

variable "key_vault_name" {
  description = "Existing Key Vault supplied through private deployment configuration."
  type        = string
}

variable "database_secret_name" {
  description = "Key Vault secret name containing DATABASE_URL. The value never enters Terraform state."
  type        = string
  default     = "db-connection-string"
}

variable "migration_job_name" {
  description = "Manual-trigger migration Job name supplied through private deployment configuration."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,30}[a-z0-9]$", var.migration_job_name))
    error_message = "migration_job_name must be a valid Container Apps Job name shorter than 32 characters."
  }
}

variable "migration_identity_name" {
  description = "Dedicated migration identity name supplied through private deployment configuration."
  type        = string

  validation {
    condition     = length(trimspace(var.migration_identity_name)) > 0
    error_message = "migration_identity_name must not be empty."
  }
}

variable "migration_image" {
  description = "Immutable ACR image reference used by the Job definition."
  type        = string

  validation {
    condition     = can(regex("^[^[:space:]@]+@sha256:[0-9a-f]{64}$", var.migration_image))
    error_message = "migration_image must be an immutable registry/repository@sha256:<64 lowercase hex> reference."
  }
}

variable "expected_alembic_head" {
  description = "Exact single Alembic head expected after migration."
  type        = string

  validation {
    condition = (
      can(regex("^[A-Za-z0-9_-]{1,128}$", var.expected_alembic_head)) &&
      !contains(["base", "head", "heads"], lower(var.expected_alembic_head))
    )
    error_message = "expected_alembic_head must be one exact Alembic revision."
  }
}

variable "environment" {
  description = "Runtime environment label."
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["staging", "prod"], var.environment)
    error_message = "environment must be staging or prod."
  }
}

variable "workload_profile_name" {
  description = "Existing Container Apps workload profile for the migration Job."
  type        = string
  default     = "Consumption"
}

variable "rbac_propagation_wait" {
  description = "Minimum control-plane propagation wait after least-privilege role assignment creation."
  type        = string
  default     = "60s"

  validation {
    condition     = can(regex("^[1-9][0-9]*s$", var.rbac_propagation_wait))
    error_message = "rbac_propagation_wait must be a positive whole-second duration such as 60s."
  }
}
