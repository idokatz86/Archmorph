# Archmorph

**AI-Powered Cloud Architecture Translator to Azure**

Convert AWS and GCP architecture diagrams into Azure equivalents with guided migration questions, interactive diagram exports, ready-to-deploy Terraform/Bicep infrastructure code, dynamic cost estimates, and a self-updating service catalog.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Azure](https://img.shields.io/badge/cloud-Azure-0078D4.svg)
![Version](https://img.shields.io/badge/version-2.6.0-22C55E.svg)
![Status](https://img.shields.io/badge/status-Production-22C55E.svg)
![Tests](https://img.shields.io/badge/tests-348%20passing-22C55E.svg)

> **[Live Demo](https://agreeable-ground-01012c003.2.azurestaticapps.net)** | **[API Docs](https://archmorph-api.icyisland-c0dee6ba.northeurope.azurecontainerapps.io/docs)**

---

## Overview

Archmorph uses Azure OpenAI GPT-4 Vision to analyze cloud architecture diagrams, identify services, ask guided migration questions, map services to Azure equivalents with confidence scores, export architecture diagrams in multiple formats, generate deployable infrastructure as code, estimate costs using the Azure Retail Prices API, automatically discover and integrate new cloud services into its catalog, and provide a comprehensive icon registry with multi-format library export.

**Key Capabilities:**
- Upload architecture diagrams (PNG, JPG, SVG, PDF, Draw.io)
- Auto-detect AWS/GCP services with AI vision across a **405+ service catalog** (145 AWS, 143 Azure, 117 GCP — grows automatically)
- **Guided migration questions** — 32 contextual questions across 8 categories that refine SKU selection, compliance, networking, deployment region, and more
- Map to Azure equivalents with confidence scores and zone grouping
- **Export architecture diagrams** as Excalidraw, Draw.io, or Visio with Azure stencils
- Generate Terraform HCL or Bicep code with secure credential handling
- **Dynamic cost estimates** — region-aware pricing via Azure Retail Prices API with 46 service mappings and monthly cache
- **Self-updating service catalog** — daily auto-discovery and auto-integration of new cloud services with fuzzy matching and category classification
- **Icon Registry** — 405 normalized cloud service icons with Draw.io, Excalidraw, and Visio library builders
- **AI-powered HLD generation** — 13-section High-Level Design documents with WAF assessment
- **IaC Chat assistant** — interactive GPT-4o assistant for code modifications
- **Chatbot assistant** — FAQ support and GitHub issue creation with intent detection
- **Admin dashboard** — conversion funnel, daily metrics, session tracking
- **Security hardening** — timing-safe auth, security headers, XSS protection, Dependabot

---

## Quick Start

### Prerequisites
- Azure subscription
- Azure CLI installed
- Terraform 1.5+
- Node.js 20+
- Python 3.11+

### Deploy Infrastructure

```bash
cd infra
az login
terraform init
terraform apply -var-file="terraform.tfvars"
```

### Run Locally

**Backend:**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

---

## Architecture

| Component | Technology | Azure Service |
|-----------|------------|---------------|
| Frontend | React 18, Vite, TailwindCSS, Lucide React | Static Web Apps |
| Backend API | Python 3.11, FastAPI | Container Apps |
| AI Engine | GPT-4 Vision | Azure OpenAI |
| Container Registry | Docker | Azure Container Registry |
| Database | PostgreSQL | Flexible Server |
| Storage | Blob | Storage Account |
| Scheduler | APScheduler (CronTrigger) | In-process |
| Service Auto-Discovery | Daily sync + auto-integration | In-process |
| Guided Questions | 32 questions, 8 categories | In-process engine |
| Diagram Export | Excalidraw / Draw.io / Visio | In-process engine |
| Icon Registry | 405 icons, 3 library formats | In-process engine |
| Pricing | Azure Retail Prices API (46 queries) | 30-day disk cache |
| HLD Generator | GPT-4o, 13 sections, 60+ doc links | In-process engine |
| IaC Chat | GPT-4o interactive assistant | In-process engine |
| Security | Headers, timing-safe auth, Dependabot | Middleware |
| Testing | pytest + Playwright | 348 unit + 34 E2E tests |

See [docs/architecture.excalidraw](docs/architecture.excalidraw) for the full architecture diagram and [docs/application-flow.excalidraw](docs/application-flow.excalidraw) for the user flow.

---

## Application Flow

```
Upload Diagram → AI Analysis → Guided Questions → Results & Export → Generate IaC → Cost Estimate
```

1. **Upload** — User uploads an AWS or GCP architecture diagram
2. **AI Analysis** — GPT-4 Vision detects services, connections, and annotations
3. **Guided Questions** — 8–18 contextual questions refine migration choices (SKU, compliance, networking, DR, security, deployment region)
4. **Results** — Azure service mappings grouped by zone with confidence scores
5. **Diagram Export** — Download translated architecture as Excalidraw, Draw.io, or Visio
6. **IaC Generation** — Generate Terraform HCL or Bicep with syntax highlighting
7. **Cost Estimation** — Region-aware monthly cost breakdown via Azure Retail Prices API
8. **HLD Generation** — AI-powered High-Level Design document with WAF assessment
9. **IaC Chat** — Interactive code modification via GPT-4o assistant

---

## Self-Updating Service Catalog

The service catalog automatically discovers and integrates new cloud services:

- **Daily sync** — APScheduler runs at 2:00 AM UTC, fetching from AWS Pricing Index, Azure Retail Prices API, and GCP Pricing Calculator
- **Auto-integration** — newly discovered services are written directly into the Python catalog files under an `AUTO-DISCOVERED` section
- **Fuzzy matching** — normalised comparison (name, fullName, id) prevents false-positive detections
- **Category classification** — 55 keyword hints auto-assign categories (Compute, Storage, Database, AI/ML, etc.) and matching icons
- **Dry-run mode** — CLI `--dry-run` flag detects without writing
- **Tracking** — cumulative `auto_added` counts per provider in `service_updates.json`

### CLI Usage

```bash
cd backend
python service_updater.py --run-now     # Discover + auto-add
python service_updater.py --dry-run     # Discover only (no file writes)
```

---

## Service Catalog

**405+ total services** across three providers, with 122 verified cross-cloud mappings.

### AWS → Azure (Sample)

| AWS | Azure | Confidence |
|-----|-------|------------|
| EC2 | Virtual Machines | 95% |
| S3 | Blob Storage | 95% |
| Lambda | Azure Functions | 90% |
| RDS | Azure SQL / PostgreSQL Flexible | 90% |
| DynamoDB | Cosmos DB | 85% |
| EKS | AKS | 90% |

### GCP → Azure (Sample)

| GCP | Azure | Confidence |
|-----|-------|------------|
| Compute Engine | Virtual Machines | 95% |
| Cloud Storage | Blob Storage | 95% |
| Cloud Functions | Azure Functions | 90% |
| GKE | AKS | 90% |
| BigQuery | Synapse Analytics | 80% |

Full mapping database: 405+ services across AWS, Azure, and GCP with 122 mappings.

---

## Cost Estimation

Dynamic pricing powered by the [Azure Retail Prices API](https://prices.azure.com/api/retail/prices):

- **Region-aware** — prices fetched per the user's selected deployment region (20 regions, default: West Europe)
- **SKU strategy multipliers** — Cost-optimized (0.65x), Balanced (1.0x), Performance-first (1.6x), Enterprise (2.2x)
- **46 service mappings** with built-in fallback estimates
- **Monthly cache** — prices cached to disk for 30 days
- **Per-service breakdown** — low/high range for each Azure service plus total monthly estimate

---

## API Reference

### Core Endpoints (44 total)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check (version, mode, catalog stats) |
| `/api/services` | GET | List all services with optional filters |
| `/api/services/providers` | GET | List cloud providers with counts |
| `/api/services/categories` | GET | List categories with per-provider counts |
| `/api/services/mappings` | GET | List cross-cloud mappings |
| `/api/services/{provider}/{id}` | GET | Get specific service details |
| `/api/services/stats` | GET | Catalog statistics |

### Translation Flow

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/projects/{id}/diagrams` | POST | Upload diagram file |
| `/api/diagrams/{id}/analyze` | POST | Analyze diagram |
| `/api/diagrams/{id}/questions` | POST | Generate guided migration questions |
| `/api/diagrams/{id}/apply-answers` | POST | Apply answers to refine mappings |
| `/api/diagrams/{id}/export-diagram` | POST | Export as Excalidraw, Draw.io, or Visio |
| `/api/diagrams/{id}/generate` | POST | Generate Terraform or Bicep code |
| `/api/diagrams/{id}/cost-estimate` | GET | Dynamic cost estimate |

### Chatbot & Admin

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chat` | POST | Send message to chatbot assistant |
| `/api/chat/history/{session_id}` | GET | Get chat session history |
| `/api/chat/{session_id}` | DELETE | Clear chat session |
| `/api/admin/metrics` | GET | Usage metrics (key-protected) |
| `/api/admin/metrics/funnel` | GET | Conversion funnel data |
| `/api/admin/metrics/daily` | GET | Daily activity metrics |
| `/api/admin/metrics/recent` | GET | Recent events feed |

### Icon Registry

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/icon-packs` | POST | Upload ZIP/JSON icon pack |
| `/api/icon-packs/{pack_id}` | DELETE | Remove icon pack and its icons |
| `/api/icons` | GET | Search icons (provider, query, category) |
| `/api/icons/packs` | GET | List registered icon packs |
| `/api/icons/metrics` | GET | Icon registry observability counters |
| `/api/icons/{icon_id}/svg` | GET | Get raw SVG for a single icon |
| `/api/libraries/drawio` | GET | Download Draw.io custom library |
| `/api/libraries/excalidraw` | GET | Download Excalidraw library bundle |
| `/api/libraries/visio` | GET | Download Visio sidecar stencil pack |

### Service Updates

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/service-updates/status` | GET | Scheduler status + auto-added totals |
| `/api/service-updates/last` | GET | Last update details |
| `/api/service-updates/run-now` | POST | Trigger immediate catalog refresh + auto-add |

Full API documentation: [Swagger UI](https://archmorph-api.icyisland-c0dee6ba.northeurope.azurecontainerapps.io/docs)

---

## Testing

| Suite | Framework | Tests | Command |
|-------|-----------|-------|---------|
| Backend unit | pytest | 348 | `cd backend && python -m pytest tests/ -v` |
| E2E | Playwright | 34 | `npx playwright test` |
| **Total** | | **382** | |

### Coverage

- **14 test classes** covering all major API endpoints
- **58 icon registry tests** covering SVG sanitization, registry ops, all 3 library builders, API routes, and Pydantic models
- **10 E2E test groups** covering full translation flow, diagram export, IaC generation, chat widget, services browser, admin dashboard, API validation, and additional API coverage
- All tests run against the live deployed backend

---

## Project Structure

```
Archmorph/
├── frontend/                        # React SPA
│   ├── src/
│   │   ├── App.jsx                  # Main application (components, views, flow)
│   │   ├── index.css                # Global styles, fonts, scrollbar
│   │   └── main.jsx                 # Entry point
│   ├── tailwind.config.js           # Design system (colors, fonts, animations)
│   └── package.json
├── backend/                         # FastAPI service
│   ├── main.py                      # 44 API endpoints, analysis engine, IaC generation
│   ├── guided_questions.py          # 32 questions across 8 categories
│   ├── diagram_export.py            # Excalidraw/Draw.io/Visio export with 36 stencils + registry fallback
│   ├── hld_generator.py             # AI-powered HLD generation (13 sections)
│   ├── iac_chat.py                  # Interactive IaC chat assistant
│   ├── service_updater.py           # APScheduler daily catalog sync + auto-integration
│   ├── openai_client.py             # Shared Azure OpenAI client factory
│   ├── usage_metrics.py             # Admin metrics and funnel tracking
│   ├── icons/                       # Icon Registry system
│   │   ├── models.py                # Pydantic models (Provider, IconMeta, IconEntry)
│   │   ├── svg_sanitizer.py         # SVG validation, sanitization, XSS prevention
│   │   ├── registry.py              # Central icon catalog (thread-safe, persistent)
│   │   ├── routes.py                # FastAPI endpoints for icon management
│   │   └── builders/                # Library format builders
│   │       ├── drawio.py            # Draw.io mxlibrary XML builder
│   │       ├── excalidraw.py        # Excalidraw JSON library builder
│   │       └── visio.py             # Visio sidecar stencil pack builder
│   ├── samples/                     # Built-in icon packs (405 SVGs)
│   │   ├── azure/                   # 143 Azure service icons
│   │   ├── aws/                     # 145 AWS service icons
│   │   └── gcp/                     # 117 GCP service icons
│   ├── services/                    # Service catalog data
│   │   ├── aws_services.py          # 145 AWS services
│   │   ├── azure_services.py        # 143 Azure services
│   │   ├── gcp_services.py          # 117 GCP services
│   │   ├── mappings.py              # 122 cross-cloud mappings
│   │   └── azure_pricing.py         # Azure Retail Prices API + cache (46 queries)
│   ├── tests/
│   │   ├── test_api.py              # 75 core API tests (14 classes)
│   │   ├── test_icon_registry.py    # 58 icon registry tests
│   │   ├── test_service_updater.py  # 42 service updater tests
│   │   ├── test_azure_pricing.py    # 30 pricing service tests
│   │   └── test_guided_questions_rules.py  # 34 rule function tests
│   ├── data/                        # Runtime data (pricing cache, metrics, icon registry)
│   ├── Dockerfile
│   └── requirements.txt
├── e2e/
│   └── archmorph.spec.ts            # 27 Playwright E2E tests
├── infra/                           # Terraform IaC
│   ├── main.tf
│   ├── terraform.tfvars
│   └── outputs.tf
├── docs/                            # Documentation
│   ├── PRD.md                       # Product Requirements Document
│   ├── DEPLOYMENT_COSTS.md          # Azure cost breakdown
│   ├── AWS_AUTOMOTIVE_MAPPING.md    # Automotive industry mapping reference
│   ├── architecture.excalidraw      # Architecture diagram
│   └── application-flow.excalidraw  # Application flow diagram
├── playwright.config.ts             # E2E test configuration
└── README.md
```

---

## Deployment

### Azure Resources

| Resource | SKU | Region |
|----------|-----|--------|
| Container Apps | Consumption | North Europe |
| Static Web Apps | Free | West Europe |
| Container Registry | Basic | North Europe |

### Deploy Backend

```bash
cd backend
az acr build --registry <acr-name> --image archmorph-api:v8 .
az containerapp update --name archmorph-api --resource-group <rg> --image <acr>.azurecr.io/archmorph-api:v8
```

### Deploy Frontend

```bash
cd frontend
npm run build
npx swa deploy dist --deployment-token <token> --env production
```

### Estimated Costs

See [docs/DEPLOYMENT_COSTS.md](docs/DEPLOYMENT_COSTS.md) for full breakdown.

| Tier | Monthly |
|------|---------|
| Dev/Test | ~$180–250 |
| Production | ~$500–800 |

---

## Roadmap

| Phase | Status | Features |
|-------|--------|----------|
| v1.0 — MVP | Done | AWS/GCP → Azure mapping, Terraform/Bicep output, basic cost estimation |
| v2.0 — Production | Done | Guided questions, diagram export, daily service sync, 405-service catalog, secure IaC, chatbot, admin dashboard |
| v2.1 — Pricing | Done | Dynamic Azure pricing, deployment region question, monthly cache, SKU multipliers, 102 tests |
| v2.2 — Self-Updating | Done | Auto-integration of new services, fuzzy name matching, category auto-classification, dry-run CLI, auto-added tracking |
| v2.5 — Audit & Quality | Done | 34 audit improvements, comprehensive test coverage (290 → 348 tests) |
| v2.6 — Icon Registry & Security | Done | Icon Registry (405 icons, 3 library formats), security hardening (timing-safe auth, headers, XSS protection, Dependabot) |
| v3.0 — Enterprise | Planned | Visio import, API keys, import blocks, SSO, RBAC |
| v4.0 — Advanced | Planned | Pulumi output, Azure Migrate integration, multi-diagram projects |

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Links

- **Live App:** https://agreeable-ground-01012c003.2.azurestaticapps.net
- **API:** https://archmorph-api.icyisland-c0dee6ba.northeurope.azurecontainerapps.io
- **API Docs (Swagger):** https://archmorph-api.icyisland-c0dee6ba.northeurope.azurecontainerapps.io/docs
- **PRD:** [docs/PRD.md](docs/PRD.md)
