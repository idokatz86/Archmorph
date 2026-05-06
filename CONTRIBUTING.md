# Contributing to Archmorph

Thank you for your interest in contributing to Archmorph!

## Development Setup

### Quick Start (recommended)

```bash
# One command — starts backend + frontend with hot-reload
make dev

# Or use Docker Compose
docker compose up --build
```

### VS Code Dev Container

Open the repo in VS Code and select **"Reopen in Container"** — Python 3.12, Node 20,
and all extensions are pre-configured via `.devcontainer/devcontainer.json`.

### Manual Setup

#### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Fill in your Azure OpenAI credentials
uvicorn main:app --reload --port 8000
```

#### Frontend

```bash
cd frontend
npm install
cp .env.example .env  # Set VITE_API_BASE
npm run dev
```

### Running Tests

```bash
# All tests (backend + frontend)
make test

# Backend (1149 tests)
cd backend && python -m pytest -v

# Backend with markers
cd backend && python -m pytest -m fast      # Quick tests only
cd backend && python -m pytest -m security   # Security tests only

# Frontend (186 tests)
cd frontend && npm test
```

### Makefile Targets

Run `make help` to see all available targets, including:
- `make dev` — Start backend + frontend in parallel
- `make test` — Run all tests
- `make lint` — Run linters
- `make build` — Build production frontend
- `make docker-up` — Start Docker Compose stack
- `make clean` — Remove build artifacts & caches

## Code Quality

- **Python**: We use [ruff](https://docs.astral.sh/ruff/) for linting and [bandit](https://bandit.readthedocs.io/) for security scanning.
- **JavaScript/React**: Standard ESLint configuration via Vite.

Run linters before submitting:
```bash
cd backend && ruff check . && bandit -r . -x ./tests --skip B101
```

## Managed Azure Skills Upstream

Archmorph consumes `microsoft/azure-skills` as a managed upstream dependency.
The upstream repository is pinned as a git submodule at
`infra/skills-upstream/azure-skills`, with the expected commit and skill list
recorded in `infra/skills-upstream/azure-skills.lock.json`.

Custom local skills must use the `archmorph-*` namespace so VS Code extension
auto-sync cannot shadow them if Microsoft later adds a similarly named Azure
skill:

| Legacy local name | Protected name |
| --- | --- |
| `azure-observability` | `archmorph-observability` |
| `azure-postgres` | `archmorph-postgres` |
| `ui-ux-pro-max` | `archmorph-ui-ux` |

Before adopting an upstream update:

1. Fetch the new upstream commit in `infra/skills-upstream/azure-skills`.
2. Review the diff manually because skill content is authoritative agent
	instruction text.
3. Update `azure-skills.lock.json` with the new SHA and expected skill list.
4. Run:
	```bash
	AZURE_MCP_COLLECT_TELEMETRY=false python scripts/check_azure_skills_upstream.py --check-telemetry-env
	```
5. On a machine with VS Code Azure MCP skills installed, also compare local
	installed upstream skills against the pinned submodule before applying any
	sync:
	```bash
	AZURE_MCP_COLLECT_TELEMETRY=false python scripts/check_azure_skills_upstream.py --check-telemetry-env --require-local-skills --diff-local-upstream
	```
6. Include the upstream SHA and review notes in the PR description.

The checker is dry-run safe: it reports SHA drift, upstream skill-list drift,
protected-name collisions, legacy local skill names, local-vs-pinned content
drift, and telemetry default misconfiguration. It never overwrites
`~/.agents/skills`.

## Pull Request Process

1. Fork the repository and create a feature branch from `main`.
2. Make your changes with clear, descriptive commits.
3. Ensure all tests pass (`pytest` and `npm run build`).
4. Update documentation if you change APIs or add features.
5. Submit a PR against `main` with a clear description.

## Architecture

- **Backend**: FastAPI (Python 3.12), Azure OpenAI GPT-4o for vision/chat
- **Frontend**: React 19.1, Vite 7.3, TailwindCSS 4.2
- **Infrastructure**: Azure Container Apps, Azure Static Web Apps, ACR
- **Auth**: JWT (HS256) with 1-hour TTL for admin endpoints
- **CI/CD**: GitHub Actions with OIDC → ACR → Container Apps
- **Security**: Semgrep SAST, Gitleaks, Trivy container scan, CycloneDX SBOM
- **Testing**: pytest (1149+ backend tests, 30+ files), Vitest (186 frontend tests), Playwright E2E
- **DX**: Makefile, Docker Compose, VS Code Dev Container

## API Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/services/catalog` | List all cloud services |
| POST | `/api/projects/{id}/diagrams` | Upload architecture diagram |
| POST | `/api/diagrams/{id}/analyze` | Analyze with GPT-4o vision |
| POST | `/api/diagrams/{id}/questions` | Get guided migration questions |
| POST | `/api/diagrams/{id}/answers` | Submit answers |
| POST | `/api/diagrams/{id}/iac/generate` | Generate Terraform/Bicep |
| POST | `/api/diagrams/{id}/iac/chat` | IaC chat assistant |
| POST | `/api/diagrams/{id}/hld` | Generate HLD document |
| POST | `/api/diagrams/{id}/export-hld` | Export HLD as DOCX/PDF/PPTX |
| GET | `/api/diagrams/{id}/cost-estimate` | Azure cost estimation |
| POST | `/api/diagrams/{id}/export-diagram` | Export to Excalidraw/Draw.io |
| POST | `/api/chatbot/message` | General chatbot |
| GET | `/api/admin/metrics` | Admin analytics (requires X-Admin-Key header) |
| POST | `/api/service-updates/run-now` | Trigger service catalog update |
| GET | `/api/contact` | Contact info |

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
