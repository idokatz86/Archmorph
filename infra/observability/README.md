# Landing-Zone-SVG Observability — #595

This directory contains the OTel-instrumentation companion infrastructure for
the landing-zone-svg pipeline.

## Components

| File | Purpose |
| --- | --- |
| [`alerts.tf`](alerts.tf) | Terraform module: 2 scheduled-query-rule alerts on the custom metrics emitted from `backend/azure_landing_zone.py`. |
| [`dashboards/landing_zone.json`](dashboards/landing_zone.json) | Azure Workbook JSON: 5 tiles covering hit/fallback rate, duration percentiles, size percentiles, error breakdown. |

## Custom metrics emitted (single source of truth)

| Metric | Type | Tags | Emitted by |
| --- | --- | --- | --- |
| `archmorph.lz.icon_resolution_total` | Counter | `result` ∈ `{hit, fallback}`, `icon_key` | `_img()` in `azure_landing_zone.py` |
| `archmorph.lz.svg_generation_duration_seconds` | Histogram | — | `generate_landing_zone_svg()` success path |
| `archmorph.lz.svg_size_bytes` | Histogram | — | `generate_landing_zone_svg()` success path |
| `archmorph.lz.errors_total` | Counter | `stage` ∈ `{validate, validate_xml, size_check, render}`, `error_type` | `generate_landing_zone_svg()` exception path |

## OTel spans emitted

* `archmorph.lz.generate` (top-level, attributes: `dr_variant`, `source_provider`, `dr_mode`, `svg_size_bytes`, `duration_seconds`)
* `archmorph.lz.infer` (sub-span: schema inference)
* `archmorph.lz.render` (sub-span: SVG part assembly)

## Local validation

The metric/span emission is locked under `backend/tests/test_landing_zone_observability.py`
(9 tests, runs in <10s). Run with:

```sh
cd backend && python -m pytest tests/test_landing_zone_observability.py -v
```

## Deployment

Wire the alerts into `infra/main.tf` by appending:

```hcl
module "landing_zone_alerts" {
  source                   = "./observability"
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  application_insights_id  = azurerm_application_insights.main.id
  action_group_critical_id = azurerm_monitor_action_group.critical.id
  tags                     = local.tags
}
```

Import the workbook via Azure Portal → Application Insights → Workbooks →
**New** → Edit → Advanced Editor → paste `dashboards/landing_zone.json`.

## References

* Issue: <https://github.com/idokatz86/Archmorph/issues/595>
* Parent epic: <https://github.com/idokatz86/Archmorph/issues/586>
* Backstop tests: `backend/tests/test_landing_zone_observability.py`
