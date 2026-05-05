# Landing Zone Performance SLO Runbook

Issue #597 defines the production-ready performance contract for `landing-zone-svg` exports.

## SLOs

| Variant | Route | Objective | Load Window |
| --- | --- | ---: | --- |
| Primary | `POST /api/diagrams/{diagram_id}/export-diagram?format=landing-zone-svg&dr_variant=primary` | p95 < 1.5s | 100 RPS for 5 min |
| DR | `POST /api/diagrams/{diagram_id}/export-diagram?format=landing-zone-svg&dr_variant=dr` | p95 < 3s | 100 RPS for 5 min |

Additional objectives:

- Error rate < 0.1% over the 5-minute soak.
- Sustained worker memory remains under 512 MB per worker.
- CI smoke runs may use lower RPS for stability, but the nightly staging soak uses the 100 RPS target.
- The nightly target must be a dedicated soak staging slot with `RATE_LIMIT_ENABLED=false` or equivalent raised per-IP limits; otherwise the test measures throttling instead of Landing Zone rendering.

## Harness

The Locust harness lives at `tests/perf/locustfile_landing_zone.py` and exercises both primary and DR variants against a primed diagram session. It writes a JSON summary with p95, error rate, achieved RPS, and the 512 MB worker-memory ceiling.

For authenticated staging, set `LANDING_ZONE_API_KEY` or `ARCHMORPH_API_KEY`. The harness captures and rotates the one-time `X-Export-Capability` token returned by upload, analyze, and export responses.

Local deterministic smoke run:

```bash
python -m venv .locust-venv
.locust-venv/bin/python -m pip install 'locust==2.32.6'
LANDING_ZONE_SOAK_SUMMARY_PATH=/tmp/landing-zone-soak-summary.json \
LANDING_ZONE_TARGET_RPS=30 \
.locust-venv/bin/python -m locust \
  -f tests/perf/locustfile_landing_zone.py \
  --headless \
  --host http://127.0.0.1:8000 \
  --users 30 \
  --spawn-rate 30 \
  --run-time 30s \
  --only-summary
```

Nightly staging soak:

- Workflow: `.github/workflows/perf-soak.yml`
- Schedule: nightly UTC plus manual `workflow_dispatch`
- Target: `vars.PERF_SOAK_BASE_URL` or `secrets.PERF_SOAK_BASE_URL`
- API key: `secrets.PERF_SOAK_API_KEY`
- Rate-limit guard: `vars.PERF_SOAK_RATE_LIMIT_PROFILE=soak`
- Summary artifact: `landing-zone-soak-summary`

## Alerts

`infra/observability/alerts.tf` wires Landing Zone p95 and burn-rate alerts from Application Insights `customMetrics`:

- Fast burn: 1-hour window, threshold 2x budget burn.
- Slow burn: 24-hour window, evaluated together with the 1-hour window at the alert threshold configured in Terraform.
- Bad requests are HTTP 5xx or latency above the variant SLO.

The export route must emit `http.request.duration_ms` with `format=landing-zone-svg` and `dr_variant=primary|dr` dimensions so alerts can distinguish primary and DR budgets.

## Triage

1. Check the Locust JSON summary for failed endpoint names and p95 values.
2. Compare primary vs DR p95; DR is allowed a 3s budget because it renders the full paired-region canvas.
3. Check worker memory and container restarts before tuning code.
4. If errors are HTTP 4xx, validate the setup/priming phase and session state.
5. If errors are HTTP 5xx or latency-only, profile `generate_landing_zone_svg` and icon registry lookup before tuning infrastructure.
