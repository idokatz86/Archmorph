# Archmorph — Landing-Zone-SVG observability alerts (#595).
#
# Custom OTel metrics emitted from `backend/azure_landing_zone.py` flow through
# the `azure-monitor-opentelemetry` exporter into App Insights as
# `customMetrics`. Platform metric alerts (`azurerm_monitor_metric_alert`)
# cannot read `customMetrics`, so we use scheduled-query-rules v2 (KQL-based
# alerts) instead. The two rules below match the acceptance criteria in #595:
#
#   1. icon_resolution_miss_rate_high   — pages DevOps when fallback ratio
#                                          exceeds 50% over 5min.
#   2. svg_generation_p95_high          — warns DevOps when p95 generation
#                                          duration exceeds 1.5s over 10min.
#
# Both alerts reference the existing `azurerm_application_insights.main` and
# `azurerm_monitor_action_group.critical` resources defined in `infra/main.tf`.
#
# Reference:
#   * Issue:       https://github.com/idokatz86/Archmorph/issues/595
#   * Parent epic: https://github.com/idokatz86/Archmorph/issues/586
#
# To wire these into the root module, add the following to `infra/main.tf`
# AFTER the existing alert block (or use a `module` reference):
#
#     module "landing_zone_alerts" {
#       source                  = "./observability"
#       resource_group_name     = azurerm_resource_group.main.name
#       location                = azurerm_resource_group.main.location
#       application_insights_id = azurerm_application_insights.main.id
#       action_group_critical_id = azurerm_monitor_action_group.critical.id
#       tags                    = local.tags
#     }
#
# This file is intentionally module-shaped (parameterised via `var.*`) so it
# composes cleanly. Apply standalone with:
#     terraform plan -target=module.landing_zone_alerts
#     terraform apply -target=module.landing_zone_alerts

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.60"
    }
  }
}

variable "resource_group_name" {
  description = "Resource group containing the App Insights workspace."
  type        = string
}

variable "location" {
  description = "Region for the alert resources."
  type        = string
}

variable "application_insights_id" {
  description = "ID of the App Insights component receiving custom metrics."
  type        = string
}

variable "action_group_critical_id" {
  description = "Action group to notify on alert. Reuses the project-wide critical group."
  type        = string
}

variable "tags" {
  description = "Tags applied to alert resources."
  type        = map(string)
  default     = {}
}

# ─────────────────────────────────────────────────────────────
# Alert 1 — icon resolution miss rate
#
# KQL: ratio of fallback events to total icon-resolution events, summarised
# every 5 minutes. Trips when ratio > 0.5 over the window. The fallback path
# means the registry returned no SVG so we drew the placeholder tile — a
# 50%+ fallback rate means the diagram is mostly placeholder colour-blobs,
# which the CTO E2E review on 2026-05-01 explicitly flagged as a red-flag
# regression.
# ─────────────────────────────────────────────────────────────
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "lz_icon_miss_rate_high" {
  name                = "archmorph-lz-icon-miss-rate-high"
  resource_group_name = var.resource_group_name
  location            = var.location

  description = "Pages when icon-fallback rate exceeds 50% over 5 minutes."
  severity    = 1

  evaluation_frequency = "PT5M"
  window_duration      = "PT5M"

  scopes               = [var.application_insights_id]
  target_resource_types = ["microsoft.insights/components"]

  criteria {
    query = <<-KQL
      let total = customMetrics
        | where name == 'archmorph.lz.icon_resolution_total'
        | summarize total = sum(valueCount);
      let fallback = customMetrics
        | where name == 'archmorph.lz.icon_resolution_total'
        | where tostring(customDimensions.result) == 'fallback'
        | summarize fallback = sum(valueCount);
      total | extend fallback = toscalar(fallback)
            | extend miss_rate = todouble(fallback) / todouble(total)
            | project miss_rate
    KQL

    time_aggregation_method = "Maximum"
    operator                = "GreaterThan"
    threshold               = 0.5
    metric_measure_column   = "miss_rate"

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [var.action_group_critical_id]
  }

  auto_mitigation_enabled = true
  tags                    = var.tags
}

# ─────────────────────────────────────────────────────────────
# Alert 2 — SVG generation p95 latency
#
# KQL: rolling p95 over the last 10 minutes. Trips when > 1.5s. Tracks the
# overall pipeline latency including OTel span overhead, registry lookup,
# and the XML pretty-print step. SLO target is < 1.0s p95 at production
# load, alert fires at 1.5s to leave headroom for paging acknowledgement
# before the user-visible regression becomes a customer complaint.
# ─────────────────────────────────────────────────────────────
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "lz_svg_p95_high" {
  name                = "archmorph-lz-svg-generation-p95-high"
  resource_group_name = var.resource_group_name
  location            = var.location

  description = "Warns when p95 LZ SVG generation duration exceeds 1.5s over 10 minutes."
  severity    = 2

  evaluation_frequency = "PT5M"
  window_duration      = "PT10M"

  scopes                = [var.application_insights_id]
  target_resource_types = ["microsoft.insights/components"]

  criteria {
    query = <<-KQL
      customMetrics
      | where name == 'archmorph.lz.svg_generation_duration_seconds'
      | summarize p95 = percentile(value, 95)
      | project p95
    KQL

    time_aggregation_method = "Maximum"
    operator                = "GreaterThan"
    threshold               = 1.5
    metric_measure_column   = "p95"

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 2
      number_of_evaluation_periods             = 2
    }
  }

  action {
    action_groups = [var.action_group_critical_id]
  }

  auto_mitigation_enabled = true
  tags                    = var.tags
}

output "alert_ids" {
  description = "IDs of the two alert rules wired up by this module."
  value = {
    icon_miss_rate_high = azurerm_monitor_scheduled_query_rules_alert_v2.lz_icon_miss_rate_high.id
    svg_p95_high        = azurerm_monitor_scheduled_query_rules_alert_v2.lz_svg_p95_high.id
  }
}
