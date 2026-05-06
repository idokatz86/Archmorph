# Archmorph CLI

Command-line interface for the Archmorph Cloud Architecture Translator API.

Designed for CI/CD pipelines, batch processing, and terminal-based workflows.

## Installation

```bash
cd cli/
pip install .
```

Or in development mode:

```bash
pip install -e .
```

## Quick Start

```bash
# 1. Save credentials
archmorph login --api-key YOUR_API_KEY
archmorph login --api-key YOUR_API_KEY --api-url https://api.archmorphai.com

# 2. Check connectivity
archmorph status

# 3. Analyze a diagram
archmorph analyze architecture.png

# 4. Generate Terraform
archmorph generate diag-abc12345 --iac-format terraform --output main.tf

# 5. Get cost estimate
archmorph cost diag-abc12345

# 6. Generate HLD document
archmorph hld diag-abc12345 --hld-format docx

# 7. Export diagram
archmorph export diag-abc12345 --export-format drawio

# 8. Migration timeline
archmorph timeline diag-abc12345 --timeline-format md

# 9. Download PDF report
archmorph report diag-abc12345
```

## Commands

| Command     | Description                                      |
|-------------|--------------------------------------------------|
| `analyze`   | Upload and analyze an architecture diagram       |
| `generate`  | Generate IaC (Terraform / Bicep)|
| `cost`      | Get monthly cost estimate                        |
| `hld`       | Generate High-Level Design document              |
| `export`    | Export diagram (Excalidraw / Draw.io / Visio)    |
| `timeline`  | Generate migration timeline                      |
| `report`    | Download full PDF analysis report                |
| `status`    | Check API health                                 |
| `login`     | Save authentication credentials                  |

## Authentication

Three methods, checked in order:

1. **CLI flags**: `--api-key` / `--token`
2. **Environment variables**: `ARCHMORPH_API_KEY` / `ARCHMORPH_TOKEN`
3. **Config file**: `~/.archmorph/config.json` or `.archmorphrc` in cwd

```bash
# API key
archmorph login --api-key sk-xxxx

# JWT token
archmorph login --token eyJhbGci...

# Environment variables
export ARCHMORPH_API_KEY=sk-xxxx
export ARCHMORPH_API_URL=https://api.archmorphai.com
```

## Global Options

```
--api-url TEXT         API base URL (default: http://localhost:8000)
--api-key TEXT         API key
--token TEXT           JWT token
--format [json|table]  Output format (default: json)
--output PATH          Write output to file
--verbose              Enable debug logging
--version              Show version
--help                 Show help
```

## Configuration File

Create `~/.archmorph/config.json`:

```json
{
  "api_url": "https://api.archmorphai.com",
  "api_key": "sk-xxxx",
  "default_format": "table",
  "default_iac": "terraform"
}
```

Or `.archmorphrc` in your project root (same format, takes precedence).

## CI/CD Examples

### GitHub Actions

```yaml
- name: Analyze architecture
  env:
    ARCHMORPH_API_KEY: ${{ secrets.ARCHMORPH_API_KEY }}
    ARCHMORPH_API_URL: https://api.archmorphai.com
  run: |
    pip install ./cli
    archmorph analyze diagrams/current-arch.png --format json --output analysis.json
    archmorph generate $(jq -r .diagram_id analysis.json) --iac-format terraform --output infra/
    archmorph cost $(jq -r .diagram_id analysis.json) --output cost-report.json
```

### GitLab CI

```yaml
translate-architecture:
  image: python:3.12-slim
  script:
    - pip install ./cli
    - archmorph analyze arch.png --format json --output result.json
    - archmorph generate $(cat result.json | python -c "import sys,json; print(json.load(sys.stdin)['diagram_id'])") --iac-format bicep --output main.bicep
  artifacts:
    paths:
      - result.json
      - main.bicep
```

## Exit Codes

| Code | Meaning             |
|------|---------------------|
| 0    | Success             |
| 1    | CLI / API error     |
| 2    | Invalid usage       |
