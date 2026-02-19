output "resource_group_name" {
  description = "Name of the resource group"
  value       = azurerm_resource_group.main.name
}

output "backend_url" {
  description = "URL for the backend API"
  value       = "https://${azurerm_container_app.backend.ingress[0].fqdn}"
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
  description = "GPT-4 Vision deployment name"
  value       = azurerm_cognitive_deployment.gpt4_vision.name
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
