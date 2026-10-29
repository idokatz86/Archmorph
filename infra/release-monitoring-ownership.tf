# Existing deployments must transfer ownership through a reviewed plan, never destroy monitors.
removed {
  from = azurerm_monitor_action_group.critical
  lifecycle {
    destroy = false
  }
}

removed {
  from = azurerm_monitor_scheduled_query_rules_alert_v2.migration_job_failure
  lifecycle {
    destroy = false
  }
}

removed {
  from = azurerm_monitor_scheduled_query_rules_alert_v2.migration_job_timeout
  lifecycle {
    destroy = false
  }
}

removed {
  from = azurerm_monitor_scheduled_query_rules_alert_v2.migration_missing_evidence
  lifecycle {
    destroy = false
  }
}

removed {
  from = azurerm_monitor_scheduled_query_rules_alert_v2.bridge_customer_degraded
  lifecycle {
    destroy = false
  }
}
