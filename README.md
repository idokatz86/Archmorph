# Archmorph

**AI-Powered Cloud Architecture Translator to Azure**

Convert AWS and GCP architecture diagrams into Azure equivalents with guided migration questions, interactive diagram exports, and ready-to-deploy Terraform/Bicep infrastructure code.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Azure](https://img.shields.io/badge/cloud-Azure-0078D4.svg)
![Version](https://img.shields.io/badge/version-2.0.0-22C55E.svg)
![Status](https://img.shields.io/badge/status-Production-22C55E.svg)

---

## Overview

Archmorph uses Azure OpenAI GPT-4 Vision to analyze cloud architecture diagrams, identify services, ask guided migration questions, map services to Azure equivalents with confidence scores, export architecture diagrams in multiple formats, and generate deployable infrastructure as code with cost estimates.

**Key Capabilities:**
- Upload architecture diagrams (PNG, JPG, SVG, PDF, Draw.io)
- Auto-detect AWS/GCP services with AI vision across a **405-service catalog** (145 AWS, 143 Azure, 117 GCP)
- **Guided migration questions** — 31 contextual questions across 8 categories that refine SKU selection, compliance, networking, and more
- Map to Azure equivalents with confidence scores and zone grouping
- **Export architecture diagrams** as Excalidraw, Draw.io, or Visio with Azure stencils
- Generate Terraform HCL or Bicep code with secure credential handling
- Estimate Azure deployment costs via Azure Retail Prices API
- **Auto-updating service catalog** — daily background sync at 2:00 AM UTC

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
| Database | PostgreSQL | Flexible Server |
| Storage | Blob | Storage Account |
| Scheduler | APScheduler (CronTrigger) | In-process |
| Guided Questions | 31 questions, 8 categories | In-process engine |
| Diagram Export | Excalidraw / Draw.io / Visio | In-process engine |

See [architecture.excalidraw](architecture.excalidraw) for the full architecture diagram and [application-flow.excalidraw](application-flow.excalidraw) for the user flow.

---

## Application Flow

```
Upload Diagram → AI Analysis → Guided Questions → Results & Export → Generate IaC → Cost Estimate
```

1. **Upload** — User uploads an AWS or GCP architecture diagram
2. **AI Analysis** — GPT-4 Vision detects services, connections, and annotations
3. **Guided Questions** — 8–18 contextual questions refine migration choices (SKU, compliance, networking, DR, security)
4. **Results** — Azure service mappings grouped by zone with confidence scores
5. **Diagram Export** — Download translated architecture as Excalidraw, Draw.io, or Visio
6. **IaC Generation** — Generate Terraform HCL or Bicep with syntax highlighting
7. **Cost Estimation** — Monthly cost breakdown via Azure Retail Prices API

---

## Service Catalog

**405 total services** across three providers, with 122 verified cross-cloud mappings.

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

Full mapping database: 405 services across AWS, Azure, and GCP with 122 mappings.

---

## API Reference

### Core Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check (version, mode, catalog stats) |
| `/api/services` | GET | List all services with optional filters |
| `/api/services/search` | GET | Search services by name/provider/category |
| `/api/analyze` | POST | Upload and analyze a diagram |
| `/api/mappings` | GET | Get all service mappings |
| `/api/mappings` | POST | Update/add a service mapping |

### Guided Questions

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/diagrams/{id}/questions` | POST | Generate guided migration questions |
| `/api/diagrams/{id}/apply-answers` | POST | Apply answers to refine mappings |

### Diagram Export

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/diagrams/{id}/export-diagram` | POST | Export as Excalidraw, Draw.io, or Visio |

### Service Updates

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/service-updates/status` | GET | Scheduler and update status |
| `/api/service-updates/last` | GET | Last update details |
| `/api/service-updates/run-now` | POST | Trigger immediate catalog refresh |

---

## Project Structure

```
Archmorph/
├── frontend/                   # React SPA
│   ├── src/
│   │   ├── App.jsx             # Main application (components, views, flow)
│   │   ├── index.css           # Global styles, fonts, scrollbar
│   │   └── main.jsx            # Entry point
│   ├── tailwind.config.js      # Design system (colors, fonts, animations)
│   └── package.json
├── backend/                    # FastAPI service
│   ├── main.py                 # API endpoints, analysis engine, IaC generation
│   ├── guided_questions.py     # 31 questions across 8 categories
│   ├── diagram_export.py       # Excalidraw/Draw.io/Visio export with stencils
│   ├── service_updater.py      # APScheduler daily catalog sync
│   ├── services/               # Service catalog data
│   ├── data/                   # Runtime data (service_updates.json)
│   ├── Dockerfile
│   └── requirements.txt
├── infra/                      # Terraform IaC
│   ├── main.tf
│   ├── terraform.tfvars
│   └── outputs.tf
├── docs/                       # Documentation
│   ├── PRD.md
│   ├── DEPLOYMENT_COSTS.md
│   └── AWS_AUTOMOTIVE_MAPPING.md
├── architecture.excalidraw     # Architecture diagram
├── application-flow.excalidraw # Application flow diagram
└── README.md
```

---

## Deployment Costs

See [docs/DEPLOYMENT_COSTS.md](docs/DEPLOYMENT_COSTS.md) for detailed Azure cost breakdown.

**Estimated Monthly (Dev/Test):** ~$180–250  
**Estimated Monthly (Production):** ~$500–800

---

## Roadmap

| Phase | Status | Features |
|-------|--------|----------|
| v1.0 — MVP | Done | AWS/GCP → Azure mapping, Terraform/Bicep output, cost estimation |
| v2.0 — Production | Done | Guided questions, diagram export (Excalidraw/Draw.io/Visio), daily service sync, 405-service catalog, secure IaC, design system UI |
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
- **Docs:** [docs/PRD.md](docs/PRD.md)
