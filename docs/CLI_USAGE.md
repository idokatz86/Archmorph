# Archmorph CLI Usage

The CLI lets engineers run the Archmorph value spine without opening the browser: upload a diagram, analyze it, generate selected artifacts, and write deterministic files to disk.

## Configure

Use a local backend or the deployed API. The CLI accepts the API URL as a flag, environment variable, or saved config.

```bash
export ARCHMORPH_API_URL="http://localhost:8000"
export ARCHMORPH_API_KEY="<api key if required>"
```

If your API URL already includes `/api`, the CLI normalizes it safely.

## Full-Spine Run

```bash
archmorph run \
  --diagram ./fixtures/aws.png \
  --target-rg rg-platform-prod \
  --emit terraform,bicep,alz-svg,cost \
  --out ./infra
```

Expected output:

```text
./infra/
  analysis.json
  terraform/main.tf
  bicep/main.bicep
  alz.svg
  cost-estimate.json
  run-summary.json
```

`--target-rg` is persisted into `analysis.json` and the backend session as CLI run context. When the analysis does not already include IaC parameters, the CLI also derives a stable IaC project hint from the resource group name.

Use `--emit all` for the default engineer bundle, or select any comma-separated subset of:

```text
terraform,bicep,alz-svg,cost
```

## Drift Baseline Comparison

If a drift baseline already exists in Archmorph, include its ID:

```bash
archmorph run \
  --diagram ./fixtures/aws.png \
  --emit terraform,alz-svg,cost \
  --baseline baseline-abc123 \
  --out ./infra
```

This adds:

```text
./infra/drift-report.json
```

## Push Generated IaC To GitHub

```bash
archmorph run \
  --diagram ./fixtures/aws.png \
  --emit terraform,cost \
  --push-pr owner/repo \
  --out ./infra
```

The CLI sends the first generated IaC artifact to `/api/integrations/github/push-pr` and writes the API response to:

```text
./infra/github-pr.json
```

When Terraform is emitted, Terraform is preferred for the PR. Otherwise the first requested IaC format is used.

## Existing Focused Commands

```bash
archmorph status
archmorph analyze ./diagram.png --project-id default
archmorph generate diag-123 --iac-format terraform --output main.tf
archmorph cost diag-123 --format table
archmorph export diag-123 --export-format excalidraw
```
