variable "subscription_id" {
  description = "Existing production subscription, supplied through protected deployment configuration."
  type        = string
  sensitive   = true
}

variable "resource_group_name" {
  description = "Existing resource group containing the monitored telemetry services."
  type        = string
}

variable "application_insights_name" {
  description = "Existing workspace-based Application Insights component; never created by this root."
  type        = string
}

variable "workspace_name" {
  description = "Existing linked Log Analytics workspace, verified before planning."
  type        = string
}

variable "alert_email" {
  description = "Owner-approved existing ALERT_EMAIL recipient; no notification test is authorized by plan."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^[^[:space:]@]+@[^[:space:]@]+\\.[^[:space:]@]+$", var.alert_email))
    error_message = "Exactly one valid on-call email address is required."
  }
}
