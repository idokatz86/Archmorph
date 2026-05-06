# Production Architecture Package Smoke

Use this smoke before release sign-off when the live value spine changes. It validates the production path from a safe sample architecture through guided answers, Azure mapping, generated artifacts, customer-facing Architecture Package exports, a legacy classic export, and scheduled-job freshness evidence.

## Run From GitHub Actions

1. Open **Actions** → **Production Architecture Package Smoke**.
2. Choose **Run workflow** on `main`.
3. Keep `sample_id=aws-hub-spoke` unless validating a specific sample.
4. Keep `strict_freshness=true` for release sign-off.
5. Secondary artifact formats are enabled by default. Set `SECONDARY_FORMAT_SMOKE=false` only as a break-glass release override.
6. Download the `architecture-package-smoke-<run id>` artifact and retain the run URL in release evidence.

The workflow requires `API_URL`, `FRONTEND_URL`, and `ADMIN_KEY` GitHub secrets. `API_URL` may include or omit the `/api` suffix.

## Run Locally

```bash
cd Archmorph
API_URL="https://api.archmorphai.com/api" \
FRONTEND_URL="https://agreeable-ground-01012c003.2.azurestaticapps.net" \
ADMIN_KEY="<redacted>" \
STRICT_FRESHNESS=true \
./scripts/architecture_package_smoke.sh
```

Artifacts are written to `smoke-artifacts/architecture-package/<timestamp>/` by default.

## What It Proves

| Area | Evidence |
|---|---|
| Health and scheduled jobs | `/api/health` status, service catalog freshness, scheduled job `last_success`, age, and stale flag |
| Sample analysis | `diagram_id`, non-empty mappings, non-empty service connections |
| Guided answers | Questions endpoint responds and applied answers persist `customer_intent` plus IaC parameters |
| IaC | Terraform and Bicep outputs are non-empty, format-shaped, and free of markdown fences |
| HLD | Markdown HLD is generated and customer DOCX/PDF/PPTX exports decode to real documents |
| Cost | Cost JSON contains service rows and the CSV export contains a `TOTAL` row |
| Architecture Package | HTML contains target, DR, DR readiness rubric, customer intent, constraints, and inline SVG sections |
| Target and DR SVG | SVG XML parses and contains expected target/DR topology language |
| Classic diagram | Excalidraw parses as JSON, Draw.io parses as mxGraph XML, and VDX parses as Visio XML |

## Diagnostics Contract

Every failure prints the failed step, endpoint, HTTP status when applicable, and the first response excerpt. Raw responses and generated artifacts are saved in the artifact directory so the release operator can inspect the exact payload without rerunning the smoke.

The smoke intentionally validates structure and customer-visible artifact presence. It does not attempt pixel-perfect diagram comparison, load testing, or model-quality grading; those belong to the hardening backlog. Secondary decoded/generated artifacts are retained under `artifacts/` and indexed in `manifest.jsonl`.