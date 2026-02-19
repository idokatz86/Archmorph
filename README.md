# Archmorph

**AI-Powered Cloud Architecture Translator to Azure**

Convert AWS and GCP architecture diagrams into Azure equivalents with ready-to-deploy Terraform/Bicep infrastructure code.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Azure](https://img.shields.io/badge/cloud-Azure-0078D4.svg)
![Status](https://img.shields.io/badge/status-MVP-orange.svg)

---

## Overview

Archmorph uses Azure OpenAI GPT-4 Vision to analyze cloud architecture diagrams, identify services, map them to Azure equivalents, and generate deployable infrastructure as code.

**Key Capabilities:**
- Upload architecture diagrams (PNG, JPG, SVG, PDF, Draw.io)
- Auto-detect AWS/GCP services with AI vision
- Map to Azure equivalents with confidence scores
- Generate Terraform HCL or Bicep code
- Estimate Azure deployment costs

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
| Frontend | React 18, Vite, TailwindCSS | Static Web Apps |
| Backend API | Python 3.11, FastAPI | Container Apps |
| AI Engine | GPT-4 Vision | Azure OpenAI |
| Database | PostgreSQL | Flexible Server |
| Storage | Blob | Storage Account |

---

## Service Mappings

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

Full mapping database: 350+ services across AWS and GCP.

---

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/projects` | POST | Create project |
| `/api/projects/{id}/diagrams` | POST | Upload diagram |
| `/api/diagrams/{id}/analyze` | POST | Trigger AI analysis |
| `/api/diagrams/{id}/mappings` | GET | Get service mappings |
| `/api/diagrams/{id}/generate` | POST | Generate IaC |
| `/api/diagrams/{id}/export` | GET | Download IaC/report |
| `/api/health` | GET | Health check |

---

## Project Structure

```
Archmorph/
├── frontend/          # React SPA
│   ├── src/
│   └── package.json
├── backend/           # FastAPI service
│   ├── main.py
│   ├── routers/
│   └── requirements.txt
├── infra/             # Terraform IaC
│   ├── main.tf
│   ├── variables.tf
│   └── outputs.tf
├── docs/              # Documentation
│   ├── PRD.md
│   └── DEPLOYMENT_COSTS.md
└── README.md
```

---

## Deployment Costs

See [docs/DEPLOYMENT_COSTS.md](docs/DEPLOYMENT_COSTS.md) for detailed Azure cost breakdown.

**Estimated Monthly (Dev/Test):** ~$180-250  
**Estimated Monthly (Production):** ~$500-800

---

## Roadmap

| Phase | Timeline | Features |
|-------|----------|----------|
| MVP | Q2 2026 | AWS→Azure mapping, Terraform output |
| Phase 2 | Q3 2026 | GCP support, Bicep output, cost estimation |
| Phase 3 | Q4 2026 | Visio support, API keys, SSO |
| Phase 4 | 2027 | Pulumi, Azure Migrate integration |

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

## Links

- **Live App:** https://agreeable-ground-01012c003.2.azurestaticapps.net
- **API:** https://archmorph-api.icyisland-c0dee6ba.northeurope.azurecontainerapps.io
- **Docs:** [docs/PRD.md](docs/PRD.md)
