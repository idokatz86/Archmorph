mock_provider "azurerm" {}

variables {
  subscription_id           = "00000000-0000-0000-0000-000000000000"
  resource_group_name       = "example-runtime"
  application_insights_name = "example-insights"
  workspace_name            = "example-logs"
  alert_email               = "oncall@example.com"
}

override_data {
  target = data.azurerm_resources.application_insights
  values = {
    resources = [{
      name                = "example-insights"
      id                  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example-runtime/providers/Microsoft.Insights/components/example-insights"
      resource_group_name = "example-runtime"
      type                = "Microsoft.Insights/components"
      location            = "westeurope"
      tags                = {}
    }]
  }
}

override_data {
  target = data.azurerm_resources.workspace
  values = {
    resources = [{
      name                = "example-logs"
      id                  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example-runtime/providers/Microsoft.OperationalInsights/workspaces/example-logs"
      resource_group_name = "example-runtime"
      type                = "Microsoft.OperationalInsights/workspaces"
      location            = "westeurope"
      tags                = {}
    }]
  }
}

run "canonical_five_resource_plan" {
  command = plan

  assert {
    condition     = length(azurerm_monitor_scheduled_query_rules_alert_v2.release) == 4
    error_message = "Exactly four canonical release alerts are required."
  }

  assert {
    condition = alltrue([
      for role, alert in azurerm_monitor_scheduled_query_rules_alert_v2.release :
      alert.name == local.alert_names[role] &&
      alert.severity == local.alert_specs[role].severity &&
      alert.enabled == local.alert_specs[role].enabled &&
      alert.evaluation_frequency == local.alert_specs[role].evaluation_frequency &&
      alert.window_duration == local.alert_specs[role].window_duration &&
      one(alert.criteria).query == local.alert_specs[role].query &&
      one(alert.criteria).operator == local.alert_specs[role].criteria.operator &&
      one(alert.criteria).threshold == local.alert_specs[role].criteria.threshold &&
      one(alert.criteria).metric_measure_column == local.alert_specs[role].criteria.metric_measure_column &&
      one(alert.criteria).time_aggregation_method == local.alert_specs[role].criteria.time_aggregation_method &&
      alert.skip_query_validation == false &&
      alert.auto_mitigation_enabled == true
    ])
    error_message = "The Terraform plan must preserve every reviewed alert rule contract."
  }

  assert {
    condition = alltrue([
      for alert in azurerm_monitor_scheduled_query_rules_alert_v2.release :
      one(one(alert.action).action_groups) == local.critical_action_id
    ])
    error_message = "Every alert must have a concrete approved notification group in the saved plan."
  }

  assert {
    condition = (
      one(azurerm_monitor_action_group.critical.email_receiver).email_address == var.alert_email &&
      one(azurerm_monitor_action_group.critical.email_receiver).use_common_alert_schema &&
      azurerm_monitor_action_group.critical.enabled
    )
    error_message = "Only the approved active email notification contract is allowed."
  }
}

run "missing_telemetry_fails_closed" {
  command = plan
  override_data {
    target = data.azurerm_resources.application_insights
    values = { resources = [] }
  }
  expect_failures = [data.azurerm_resources.application_insights]
}
