output "application_insights_resource_id" {
  description = "Existing telemetry scope required by release alert attestation."
  value       = local.application_insights.id
}

output "migration_failure_alert_id" {
  value = azurerm_monitor_scheduled_query_rules_alert_v2.release["failure"].id
}

output "migration_timeout_alert_id" {
  value = azurerm_monitor_scheduled_query_rules_alert_v2.release["timeout"].id
}

output "migration_missing_evidence_alert_id" {
  value = azurerm_monitor_scheduled_query_rules_alert_v2.release["missing_evidence"].id
}

output "bridge_customer_degraded_alert_id" {
  value = azurerm_monitor_scheduled_query_rules_alert_v2.release["customer_degraded"].id
}

output "critical_action_group_id" {
  value = azurerm_monitor_action_group.critical.id
}
