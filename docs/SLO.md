# Archmorph Full-Spine SLOs

Archmorph protects the core value spine with endpoint-specific latency SLOs, a deterministic CI gate, and Azure Monitor alerts. The spine is the path users rely on to turn an architecture image into analysis, deployment artifacts, landing-zone visuals, and drift evidence.

## SLO Table

| Operation | CI metric name | Route | Objective | Severity |
| --- | --- | --- | ---: | --- |
| Diagram analysis | `analyze` | `POST /api/diagrams/{diagram_id}/analyze` | p95 < 8s | Sev 2 |
| Landing-zone SVG generation | `generate_landing_zone` | `POST /api/diagrams/{diagram_id}/export-diagram?format=landing-zone-svg` | p95 < 1.5s | Sev 2 |
| Terraform generation | `generate_iac_terraform` | `POST /api/diagrams/{diagram_id}/generate?format=terraform&force=true` | p95 < 12s | Sev 2 |
| Bicep generation | `generate_iac_bicep` | `POST /api/diagrams/{diagram_id}/generate?format=bicep&force=true` | p95 < 12s | Sev 2 |
| Drift comparison | `drift_compare` | `POST /api/drift/baselines/{baseline_id}/compare` | p95 < 5s | Sev 3 |

The CI gate also requires endpoint failure rate to stay below 1% and requires every protected endpoint to receive samples.

## CI Enforcement

The `sla-spine` GitHub Actions job runs Locust at 30 RPS against a single-process deterministic backend. The backend is started with:

- `ENVIRONMENT=test`
- `ARCHMORPH_CI_SMOKE_MODE=1`
- `ARCHMORPH_EXPORT_CAPABILITY_REQUIRED=false`
- `ARCHMORPH_DISABLE_IAC_CLI_VALIDATION=1`

This keeps the gate stable by using the same mocked/smoke analysis path as the CLI full-spine smoke tests instead of depending on external Azure OpenAI latency. The Locust run writes `sla-spine-summary.json`, uploads it as an artifact, comments a p95 table on pull requests, and fails if achieved throughput drops below 85% of the 30 RPS target.

## Production Alerts

`infra/observability/alerts.tf` defines Azure Monitor scheduled-query alerts for production telemetry:

- Existing ALZ alerts cover landing-zone icon miss rate and landing-zone SVG p95.
- Full-spine p95 alerts cover analyze, Terraform generation, Bicep generation, and drift compare using `http.request.duration_ms` custom metrics.
- Production IaC alerts split Terraform and Bicep with the `format` metric dimension emitted by request telemetry; route matching covers both `/api/...` and `/api/v1/...` clients.
- Full-spine burn-rate alerts evaluate both 5-minute and 1-hour windows.

Burn-rate alerts treat requests as bad when the request exceeds the operation latency SLO or returns HTTP 5xx. They alert when both windows burn faster than 2x a 99% latency/error budget. Low-sample windows are suppressed to avoid paging on empty traffic.

## Response Guidance

When an SLO fails in CI, inspect the PR comment first to identify the endpoint with the highest p95 or failures. Reproduce locally with the Locust script and the same smoke-mode environment. If the regression is isolated to IaC generation or diagram export, prefer focused profiling around those route handlers before broad backend tuning.

When an Azure Monitor alert fires, compare the p95 alert with the burn-rate alert. A p95-only page usually means a latency regression with enough traffic to be meaningful. A burn-rate page means the endpoint is consuming its latency/error budget across both short and long windows and should be treated as customer-impacting until ruled out.

## PR Performance Budgets

Pull requests now enforce two deterministic performance budgets before merge:

- `frontend/perf/bundle-budget.json` caps the built Vite bundle at 1.12 MB total (`980 KB` JavaScript, `140 KB` CSS, `280 KB` for the largest emitted asset). This is wired into `.github/workflows/ci.yml` through `scripts/perf_budget.py`, so an extra `100 KB` of built bundle weight fails CI.
- `frontend/lighthouse-budget.json` is enforced by Lighthouse CI against the built `dist/` output and caps transfer size at `520 KB` total, `380 KB` script, and `130 KB` stylesheet.
- `backend/tests/performance/analyze_latency_budget.json` keeps the deterministic `/analyze` smoke test at an `8.0 ms` p95 CI baseline with a maximum `1.3x` regression ratio after warmup, so backend latency regressions are caught in the main pytest gate instead of waiting for production telemetry.
