output "resource_group_name" {
  description = "Name of the resource group"
  value       = azurerm_resource_group.main.name
}

output "backend_url" {
  description = "Direct Container App origin URL for the backend API"
  value       = "https://${azurerm_container_app.backend.ingress[0].fqdn}"
}

output "front_door_api_hostname" {
  description = "Front Door hostname that the backend origin expects on trusted requests"
  value       = var.enable_front_door_waf ? azurerm_cdn_frontdoor_endpoint.api[0].host_name : null
}

output "front_door_profile_resource_guid" {
  description = "Azure Front Door profile resource GUID forwarded in the X-Azure-FDID header"
  value       = var.enable_front_door_waf ? azurerm_cdn_frontdoor_profile.main[0].resource_guid : null
}

output "backend_image_reference" {
  description = "Resolved backend container image reference (supports digest pinning)."
  value       = local.backend_image
}

output "frontend_url" {
  description = "URL for the frontend Static Web App"
  value       = "https://${azurerm_static_web_app.frontend.default_host_name}"
}

output "acr_login_server" {
  description = "Azure Container Registry login server"
  value       = azurerm_container_registry.main.login_server
}

output "acr_admin_username" {
  description = "ACR admin username"
  value       = azurerm_container_registry.main.admin_username
}

output "acr_admin_password" {
  description = "ACR admin password"
  value       = azurerm_container_registry.main.admin_password
  sensitive   = true
}

output "database_fqdn" {
  description = "PostgreSQL server FQDN"
  value       = azurerm_postgresql_flexible_server.main.fqdn
}

output "storage_account_name" {
  description = "Storage account name"
  value       = azurerm_storage_account.main.name
}

output "key_vault_name" {
  description = "Key Vault name"
  value       = azurerm_key_vault.main.name
}

output "key_vault_uri" {
  description = "Key Vault URI"
  value       = azurerm_key_vault.main.vault_uri
}

output "openai_endpoint" {
  description = "Azure OpenAI endpoint"
  value       = azurerm_cognitive_account.openai.endpoint
}

output "openai_deployment_name" {
  description = "Primary Azure OpenAI deployment name"
  value       = azurerm_cognitive_deployment.gpt41_primary.name
}

output "openai_fallback_deployment_name" {
  description = "Fallback Azure OpenAI deployment name"
  value       = azurerm_cognitive_deployment.gpt4_vision.name
}

output "dr_planned_location" {
  description = "Planned DR location derived from paired-region mapping or override."
  value       = local.dr_planned_location
}

output "log_analytics_workspace_id" {
  description = "Log Analytics Workspace ID"
  value       = azurerm_log_analytics_workspace.main.id
}

output "static_web_app_api_key" {
  description = "Static Web App deployment token"
  value       = azurerm_static_web_app.frontend.api_key
  sensitive   = true
}

output "application_insights_connection_string" {
  description = "Application Insights connection string for telemetry"
  value       = azurerm_application_insights.main.connection_string
  sensitive   = true
}

output "application_insights_instrumentation_key" {
  description = "Application Insights instrumentation key"
  value       = azurerm_application_insights.main.instrumentation_key
  sensitive   = true
}

output "managed_identity_client_id" {
  description = "Managed Identity client ID for Container App"
  value       = azurerm_user_assigned_identity.container_app.client_id
}

output "redis_hostname" {
  description = "Azure Cache for Redis hostname"
  value       = azurerm_redis_cache.main.hostname
}

output "redis_ssl_port" {
  description = "Azure Cache for Redis SSL port"
  value       = azurerm_redis_cache.main.ssl_port
}

output "redis_primary_key" {
  description = "Azure Cache for Redis primary access key"
  value       = azurerm_redis_cache.main.primary_access_key
  sensitive   = true
}
