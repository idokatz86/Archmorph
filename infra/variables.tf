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
  default     = "eastus" # GPT-4 Vision available, Sweden blocked by policy
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
