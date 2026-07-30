output "migration_job_name" {
  description = "Manual-trigger migration Job name."
  value       = azurerm_container_app_job.database_migration.name
}

output "migration_job_id" {
  description = "Migration Job resource ID for private deployment evidence."
  value       = azurerm_container_app_job.database_migration.id
  sensitive   = true
}

output "migration_identity_id" {
  description = "Dedicated migration identity resource ID."
  value       = azurerm_user_assigned_identity.database_migration.id
  sensitive   = true
}

output "migration_identity_principal_id" {
  description = "Dedicated migration identity principal ID for RBAC propagation checks."
  value       = azurerm_user_assigned_identity.database_migration.principal_id
  sensitive   = true
}

output "acr_scope_id" {
  description = "ACR scope used by the AcrPull assignment."
  value       = data.azurerm_container_registry.runtime.id
  sensitive   = true
}

output "database_secret_scope_id" {
  description = "Versionless Key Vault secret scope used by the least-privilege assignment."
  value       = local.database_secret_scope
  sensitive   = true
}

output "key_vault_authorization_mode" {
  description = "Authorization mode detected on the existing Key Vault."
  value       = local.key_vault_rbac_mode ? "rbac" : "access-policy"
}

output "key_vault_id" {
  description = "Key Vault scope used by the policy-mode fallback."
  value       = data.azurerm_key_vault.runtime.id
  sensitive   = true
}
