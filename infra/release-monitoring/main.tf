terraform {
  required_version = ">= 1.9.0, < 2.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "= 4.75.0"
    }
  }

  backend "azurerm" {
    use_azuread_auth = true
  }
}

provider "azurerm" {
  features {}
  subscription_id                 = var.subscription_id
  resource_provider_registrations = "none"
}

# Resource-list reads do not retrieve instrumentation keys or workspace secrets.
data "azurerm_resources" "application_insights" {
  name                = var.application_insights_name
  resource_group_name = var.resource_group_name
  type                = "Microsoft.Insights/components"

  lifecycle {
    postcondition {
      condition     = length(self.resources) == 1
      error_message = "Exactly one existing Application Insights component is required."
    }
  }
}

data "azurerm_resources" "workspace" {
  name                = var.workspace_name
  resource_group_name = var.resource_group_name
  type                = "Microsoft.OperationalInsights/workspaces"

  lifecycle {
    postcondition {
      condition     = length(self.resources) == 1
      error_message = "Exactly one existing Log Analytics workspace is required."
    }
  }
}

locals {
  application_insights = one(data.azurerm_resources.application_insights.resources)
  workspace            = one(data.azurerm_resources.workspace.resources)
  alert_specs          = jsondecode(file("${path.module}/../monitoring/migration-alert-specs.json")).alerts
  alert_names = {
    failure           = "archmorph-migration-job-failure"
    timeout           = "archmorph-migration-job-timeout"
    missing_evidence  = "archmorph-migration-missing-evidence"
    customer_degraded = "archmorph-bridge-customer-degraded"
  }
  tags = {
    project     = "archmorph"
    environment = "prod"
    managed_by  = "terraform"
    owner       = "platform-engineering"
    component   = "release-monitoring"
  }
}

resource "azurerm_monitor_action_group" "critical" {
  name                = "archmorph-critical-alerts"
  resource_group_name = var.resource_group_name
  location            = "global"
  short_name          = "archcrit"
  enabled             = true

  email_receiver {
    name                    = "admin"
    email_address           = var.alert_email
    use_common_alert_schema = true
  }

  tags = local.tags
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "release" {
  for_each = local.alert_specs

  name                 = local.alert_names[each.key]
  resource_group_name  = var.resource_group_name
  location             = local.application_insights.location
  description          = "Platform Engineering: reviewed ${each.key} release-monitoring gate"
  enabled              = each.value.enabled
  severity             = each.value.severity
  scopes               = [local.application_insights.id]
  evaluation_frequency = each.value.evaluation_frequency
  window_duration      = each.value.window_duration

  criteria {
    query                   = each.value.query
    time_aggregation_method = each.value.criteria.time_aggregation_method
    operator                = each.value.criteria.operator
    threshold               = each.value.criteria.threshold
    metric_measure_column   = each.value.criteria.metric_measure_column

    failing_periods {
      minimum_failing_periods_to_trigger_alert = each.value.criteria.failing_periods.minimum_failing_periods_to_trigger_alert
      number_of_evaluation_periods             = each.value.criteria.failing_periods.number_of_evaluation_periods
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.critical.id]
  }

  auto_mitigation_enabled          = true
  skip_query_validation            = false
  workspace_alerts_storage_enabled = false
  tags                             = local.tags

  lifecycle {
    precondition {
      condition = (
        toset(keys(local.alert_specs)) == toset(keys(local.alert_names)) &&
        each.value.scope_refs == ["application_insights"] &&
        each.value.action_group_refs == ["critical"] &&
        lower(local.workspace.resource_group_name) == lower(var.resource_group_name)
      )
      error_message = "Only the four canonical release-monitoring roles and existing telemetry scope are allowed."
    }
  }
}
