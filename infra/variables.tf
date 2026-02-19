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
  default     = "swedencentral" # OpenAI with GPT-4 Vision available
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
  default     = "archmorphadmin"
}

variable "db_admin_password" {
  description = "PostgreSQL administrator password"
  type        = string
  sensitive   = true
}
