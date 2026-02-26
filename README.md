# Archmorph

**AI-Powered Cloud Architecture Translator to Azure**

Convert AWS and GCP architecture diagrams into Azure equivalents with guided migration questions, interactive diagram exports, ready-to-deploy Terraform/Bicep infrastructure code, dynamic cost estimates, and a self-updating service catalog.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Azure](https://img.shields.io/badge/cloud-Azure-0078D4.svg)
![Version](https://img.shields.io/badge/version-3.4.0-22C55E.svg)
![Status](https://img.shields.io/badge/status-Production-22C55E.svg)
![Tests](https://img.shields.io/badge/tests-1653%20passing-22C55E.svg)
![Python](https://img.shields.io/badge/python-3.12-3776AB.svg)
![React](https://img.shields.io/badge/react-19.1-61DAFB.svg)

> **[Live Demo](https://agreeable-ground-01012c003.2.azurestaticapps.net)** | **[API Docs](https://archmorph-api.nicesea-1430d1f7.westeurope.azurecontainerapps.io/docs)**

---

## Overview

Archmorph uses Azure OpenAI GPT-4o to analyze cloud architecture diagrams, identify services, ask guided migration questions with inter-question constraints, map services to Azure equivalents with confidence scores and transparency explanations, export architecture diagrams in multiple formats, generate deployable infrastructure as code with security scanning, estimate costs using the Azure Retail Prices API, automatically discover and integrate new cloud services into its catalog, and provide a comprehensive icon registry with multi-format library export.

**Key Capabilities:**
- Upload architecture diagrams (PNG, JPG, SVG, PDF, Draw.io, Visio)
- Auto-detect AWS/GCP services with AI vision across a **405+ service catalog** (145 AWS, 143 Azure, 117 GCP — grows automatically)
- **Guided migration questions** — 32 contextual questions across 8 categories with **inter-question constraint system** that dynamically filters options based on compliance and data residency choices
- Map to Azure equivalents with **confidence scores and transparency explanations** showing why each level was assigned
- **Export architecture diagrams** as Excalidraw, Draw.io, or Visio with Azure stencils
- Generate Terraform HCL or Bicep code with secure credential handling and **8-rule IaC security scanning**
- **Dynamic cost estimates** — region-aware pricing via Azure Retail Prices API with 46 service mappings and monthly cache
- **Cost comparison** — side-by-side AWS/GCP vs Azure cost analysis with optimization recommendations
- **Self-updating service catalog** — daily auto-discovery and auto-integration of new cloud services with fuzzy matching and category classification
- **Icon Registry** — 405 normalized cloud service icons with Draw.io, Excalidraw, and Visio library builders
- **AI-powered HLD generation** — 13-section High-Level Design documents with WAF assessment
- **HLD document export** — download HLD as Word (.docx), PDF, or PowerPoint (.pptx) with branded formatting
- **IaC Chat assistant** — interactive GPT-4o assistant for code modifications
- **Chatbot assistant** — FAQ support and GitHub issue creation with intent detection
- **AI-powered service suggestions** — intelligent Azure service recommendations based on workload context
- **Compliance mapper** — map requirements to Azure compliance frameworks (GDPR, HIPAA, SOC2, FedRAMP)
- **Migration risk assessment** — risk scoring with automated runbook generation
- **Migration intelligence** — ML-powered analysis with historical pattern matching
- **Infrastructure import** — import existing Terraform/ARM/CloudFormation configurations
- **Living architecture** — real-time architecture drift detection and versioning
- **Admin dashboard** — conversion funnel, daily metrics, session tracking
- **JWT admin authentication** — HS256 tokens with 1-hour TTL, in-memory revocation
- **Persistent analytics** — Azure Blob Storage with background flush and crash-safe shutdown
- **Journey analytics** — user journey tracking with funnel analysis
- **Toast notification system** — non-blocking success/error/warning notifications with auto-dismiss
- **Session expiry warning** — countdown banner with session extension capability
- **Browser close protection** — `beforeunload` guard prevents accidental data loss during analysis
- **Accessibility** — focus traps for modals, keyboard navigation, ARIA attributes
- **Error envelope middleware** — standardized JSON error responses with correlation IDs
- **Security hardening** — timing-safe auth, security headers, XSS protection, Dependabot
- **CI/CD security** — Semgrep SAST, Gitleaks secret detection, Trivy container scanning, CycloneDX SBOM
- **API versioning** — all `/api/*` routes mirrored at `/api/v1/*` for stable integrations
- **Feature flags system** — percentage rollout + user targeting with admin API
- **Comprehensive audit logging** — structured JSON with risk levels, alerting rules, compliance queries
- **Session persistence** — pluggable SessionStore with InMemory and Redis backends
- **GPT response caching** — content-hash TTLCache for GPT-4o responses with configurable timeout and fallback model
- **Vision analysis cache** — TTLCache for repeated diagram analysis avoiding redundant API calls
- **Zero Trust WAF** — Azure Front Door Premium with OWASP CRS 3.2
- **Helm charts** — self-hosted Kubernetes deployment via `charts/archmorph/`
- **Server-Sent Events** — real-time progress streaming for long-running operations
- **Job queue** — background task processing with status tracking
- **Gunicorn process manager** — production worker management with UvicornWorker
- **Docker Compose** — local development with PostgreSQL 16 + Redis 7

---

## Quick Start

### Prerequisites
- Azure subscription
- Azure CLI installed
- Terraform 1.5+
- Node.js 20+
- Python 3.12+

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

**Docker Compose (full stack):**
```bash
docker-compose up -d   # PostgreSQL 16 + Redis 7 + Backend + Frontend
```

---

## Architecture

### System Architecture Diagram

```mermaid
flowchart TB
    subgraph Azure["☁️ Azure Cloud"]
        subgraph Frontend["Static Web Apps"]
            UI[React 19 + Vite 7.3<br/>TailwindCSS + Zustand]
        end
        
        WAF[Azure Front Door<br/>WAF / OWASP CRS 3.2]
        
        subgraph Backend["Container Apps — Gunicorn + Uvicorn"]
            API[FastAPI<br/>Python 3.12]
            subgraph Engines["Processing Engines"]
                Vision[GPT-4o Vision Analyzer<br/>+ TTLCache]
                GQ[Guided Questions<br/>32 rules, 8 categories<br/>+ Constraint System]
                Export[Diagram Export<br/>Excalidraw/Draw.io/Visio]
                IaC[IaC Generator<br/>Terraform/Bicep<br/>+ Security Scan]
                HLD[HLD Generator<br/>13 sections + WAF]
                HLDExport[HLD Export<br/>DOCX/PDF/PPTX]
                Chat[IaC Chat<br/>GPT-4o Assistant]
                AISuggest[AI Suggestions<br/>Service Recommendations]
                Compliance[Compliance Mapper<br/>GDPR/HIPAA/SOC2/FedRAMP]
                MigRisk[Migration Risk<br/>Assessment + Runbook]
                MigIntel[Migration Intelligence<br/>ML Pattern Matching]
                InfraImport[Infra Import<br/>TF/ARM/CFN]
                Living[Living Architecture<br/>Drift Detection]
                CostComp[Cost Comparison<br/>Cross-Cloud Analysis]
                CostOpt[Cost Optimizer<br/>Savings Recommendations]
            end
            ErrorEnv[Error Envelope<br/>Middleware]
            FeatureFlags[Feature Flags<br/>% rollout + targeting]
            AuditLog[Audit Logging<br/>Structured JSON]
            SessionStore[Session Store<br/>InMemory / Redis]
            JobQueue[Job Queue + SSE<br/>Background Tasks]
        end
        
        subgraph Data["Data Services"]
            ACR[Container Registry]
            DB[(PostgreSQL 16<br/>Flexible Server)]
            Blob[(Blob Storage)]
            Redis[(Redis 7<br/>Session + Cache)]
        end
        
        subgraph AI["Azure OpenAI"]
            GPT4O[GPT-4o<br/>+ Fallback Model]
        end
        
        Pricing[Azure Retail<br/>Prices API]
        AppInsights[Application<br/>Insights]
    end
    
    User((User)) --> UI
    UI <--> WAF --> API
    API --> Vision --> GPT4O
    API --> GQ
    API --> Export
    API --> IaC
    API --> HLD --> GPT4O
    HLD --> HLDExport
    API --> Chat --> GPT4O
    API --> AISuggest --> GPT4O
    API --> Compliance
    API --> MigRisk
    API --> MigIntel
    API --> InfraImport
    API --> Living
    API --> CostComp
    API --> CostOpt
    API --> Pricing
    API --> DB
    API --> Blob
    API --> FeatureFlags
    API --> AuditLog
    API --> ErrorEnv
    SessionStore --> Redis
    JobQueue -.-> API
    ACR --> API
    API --> AppInsights
```

### Component Overview

| Component | Technology | Azure Service |
|-----------|------------|---------------|
| Frontend | React 19.1, Vite 7.3, TailwindCSS 4.2, Zustand, Lucide React | Static Web Apps |
| Backend API | Python 3.12, FastAPI 0.128, Gunicorn + Uvicorn | Container Apps |
| AI Engine | GPT-4o (vision + chat) with fallback model | Azure OpenAI |
| Container Registry | Docker | Azure Container Registry |
| Database | PostgreSQL 16 | Flexible Server |
| Cache / Sessions | Redis 7 | Azure Cache for Redis |
| Storage | Blob | Storage Account (metrics persistence) |
| Scheduler | APScheduler (CronTrigger) | In-process |
| Service Auto-Discovery | Daily sync + auto-integration | In-process engine |
| Guided Questions | 32 questions, 8 categories, inter-question constraints | In-process engine |
| Diagram Export | Excalidraw / Draw.io / Visio | In-process engine |
| Icon Registry | 405 icons, 3 library formats | In-process engine |
| Pricing | Azure Retail Prices API (46 queries) | 30-day disk cache |
| Cost Comparison | Cross-cloud price comparison | In-process engine |
| Cost Optimizer | Savings recommendations engine | In-process engine |
| HLD Generator | GPT-4o, 13 sections + WAF, 60+ doc links | In-process engine |
| HLD Export | DOCX/PDF/PPTX with branded formatting | In-process engine |
| IaC Generator | Terraform/Bicep + security scanning | In-process engine |
| IaC Chat | GPT-4o interactive assistant | In-process engine |
| AI Suggestions | Service recommendation engine | In-process engine |
| Compliance Mapper | GDPR/HIPAA/SOC2/FedRAMP mapping | In-process engine |
| Migration Risk | Risk assessment + runbook generation | In-process engine |
| Migration Intelligence | ML-powered pattern matching | In-process engine |
| Infrastructure Import | TF/ARM/CloudFormation parser | In-process engine |
| Living Architecture | Drift detection & change tracking | In-process engine |
| Auth | JWT (HS256), in-memory revocation | Middleware |
| Security | Headers, timing-safe auth, XSS protection, Dependabot | Middleware |
| Error Envelope | Structured error responses with correlation IDs | Middleware |
| Feature Flags | Python module, % rollout + user targeting | In-process |
| Audit Logging | Structured JSON + querying with risk levels | In-process |
| Session Store | InMemory/Redis adapter | Azure Cache for Redis |
| Job Queue + SSE | Background task processing with Server-Sent Events | In-process |
| API Versioning | v1 prefix mirror for all routes | Middleware |
| WAF | OWASP CRS 3.2 | Azure Front Door Premium |
| Testing | pytest (1609 tests) + Vitest + Playwright E2E | CI/CD |

> 📐 **Detailed Diagrams:** [architecture.excalidraw](docs/architecture.excalidraw) | [application-flow.excalidraw](docs/application-flow.excalidraw) — Open in [Excalidraw](https://excalidraw.com)

---

## Application Flow

### User Journey

```mermaid
flowchart LR
    subgraph Upload["1️⃣ Upload"]
        A[📤 Upload Diagram<br/>PNG/JPG/SVG/PDF/Draw.io<br/>or Import TF/ARM/CFN]
    end
    
    subgraph Analysis["2️⃣ AI Analysis"]
        B[🤖 GPT-4o Vision<br/>Service Detection + Cache]
    end
    
    subgraph Questions["3️⃣ Guided Questions"]
        C[❓ 8-18 Questions<br/>SKU/Compliance/DR/Region<br/>+ Inter-Question Constraints]
    end
    
    subgraph Results["4️⃣ Results"]
        D[📊 Multi-Cloud Mappings<br/>Confidence Scores<br/>+ Transparency Explanations]
    end
    
    subgraph Export["5️⃣ Export"]
        E[📐 Diagram Export<br/>Excalidraw/Draw.io/Visio]
        F[📝 IaC Generator<br/>Terraform/Bicep/CFN<br/>+ Security Scan]
        G[💰 Cost Estimate<br/>Cross-Cloud Comparison]
        H[📄 HLD Document<br/>13 Sections + WAF]
    end
    
    subgraph Intelligence["6️⃣ Intelligence"]
        I[🧠 AI Suggestions<br/>Service Recommendations]
        J[📋 Compliance Map<br/>GDPR/HIPAA/SOC2]
        K[⚠️ Migration Risk<br/>Assessment + Runbook]
    end
    
    A --> B --> C --> D --> E
    D --> F
    D --> G
    D --> H
    D --> I
    D --> J
    D --> K
    
    style Upload fill:#3B82F6,color:#fff
    style Analysis fill:#8B5CF6,color:#fff
    style Questions fill:#F59E0B,color:#fff
    style Results fill:#22C55E,color:#fff
    style Export fill:#06B6D4,color:#fff
    style Intelligence fill:#EC4899,color:#fff
```

### Step-by-Step Flow

```
Upload Diagram → AI Analysis → Guided Questions → Results & Export → Generate IaC → Cost Estimate
```

1. **Upload** — User uploads an AWS or GCP architecture diagram, or imports existing IaC (Terraform/ARM/CloudFormation)
2. **AI Analysis** — GPT-4o Vision detects services, connections, and annotations (with TTL cache)
3. **Feature Flags** — Feature availability checked via flags system (percentage rollout + user targeting)
4. **Guided Questions** — 8–18 contextual questions refine migration choices (SKU, compliance, networking, DR, security, deployment region) with inter-question constraints
5. **Results** — Multi-cloud service mappings grouped by zone with confidence scores and transparency explanations
6. **Diagram Export** — Download translated architecture as Excalidraw, Draw.io, or Visio
7. **IaC Generation** — Generate Terraform HCL, Bicep, or CloudFormation with syntax highlighting and security scanning
8. **Cost Estimation** — Region-aware monthly cost breakdown with cross-cloud comparison
9. **HLD Generation** — AI-powered High-Level Design document with WAF assessment
10. **HLD Export** — Download HLD as Word, PDF, or PowerPoint with branded formatting
11. **IaC Chat** — Interactive code modification via GPT-4o assistant
12. **AI Suggestions** — Intelligent service recommendations based on workload analysis
13. **Compliance Mapping** — GDPR/HIPAA/SOC2/FedRAMP compliance assessment
14. **Migration Risk** — Risk assessment with automated runbook generation
15. **Migration Intelligence** — ML-powered pattern matching for migration optimization

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

### Core Endpoints (~172 total across 25 router modules)

> **Note:** All `/api/*` routes are also available at `/api/v1/*` for versioned API access.

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
| `/api/diagrams/{id}/export-hld` | POST | Export HLD as DOCX, PDF, or PPTX |
| `/api/diagrams/{id}/generate` | POST | Generate Terraform or Bicep code |
| `/api/diagrams/{id}/cost-estimate` | GET | Dynamic cost estimate |

### Chatbot & Admin

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chat` | POST | Send message to chatbot assistant |
| `/api/chat/history/{session_id}` | GET | Get chat session history |
| `/api/chat/{session_id}` | DELETE | Clear chat session |
| `/api/admin/login` | POST | Authenticate with admin key, receive JWT |
| `/api/admin/logout` | POST | Revoke admin session token |
| `/api/admin/metrics` | GET | Usage metrics (JWT-protected) |
| `/api/admin/metrics/funnel` | GET | Conversion funnel data |
| `/api/admin/metrics/daily` | GET | Daily activity metrics |
| `/api/admin/metrics/recent` | GET | Recent events feed |
| `/api/admin/monitoring` | GET | System health & performance |
| `/api/admin/costs` | GET | Azure deployment cost tracking |
| `/api/admin/analytics` | GET | Comprehensive analytics dashboard |
| `/api/admin/analytics/performance` | GET | Performance metrics |
| `/api/admin/analytics/features` | GET | Feature usage analytics |
| `/api/admin/analytics/funnel` | GET | Detailed funnel analytics |
| `/api/admin/audit` | GET | Security audit log |
| `/api/admin/observability` | GET | Observability spans & traces |
| `/api/admin/feedback` | GET | User feedback summary |
| `/api/admin/leads` | GET | Lead capture data |

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

### Feature Flags

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/flags` | GET | List all feature flags |
| `/api/flags/{name}` | GET | Get specific flag status |
| `/api/flags/{name}` | PUT | Update flag configuration (admin) |

> **Note:** All routes also available at `/api/v1/*`

### AI & Intelligence

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ai-suggestions` | POST | Generate AI-powered service recommendations |
| `/api/compliance-map` | POST | Map architecture to compliance frameworks |
| `/api/migration-risk` | POST | Assess migration risks + generate runbook |
| `/api/migration-intelligence` | POST | ML-powered migration pattern matching |
| `/api/infra-import` | POST | Import existing TF/ARM/CFN infrastructure |
| `/api/living-architecture` | GET | Drift detection and change tracking |
| `/api/cost-comparison` | POST | Cross-cloud cost comparison |
| `/api/cost-optimizer` | POST | Savings recommendations |

### Jobs & Real-Time

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/jobs/{id}` | GET | Check background job status |
| `/api/jobs/{id}/stream` | GET | SSE stream for real-time progress |

Full API documentation: [Swagger UI](https://archmorph-api.nicesea-1430d1f7.westeurope.azurecontainerapps.io/docs)

---

## Testing

| Suite | Framework | Tests | Command |
|-------|-----------|-------|---------|
| Backend unit | pytest | 1609 | `cd backend && python -m pytest tests/ -v` |
| Frontend unit | Vitest | 22 | `cd frontend && npx vitest run` |
| E2E | Playwright | 34 | `npx playwright test` |
| **Total** | | **1665** | |

### Coverage

- **70+ test files** covering all API endpoints and router modules
- **89 core API tests** covering the full translation flow
- **65 audit logging tests** covering structured logs, risk levels, queries
- **64 journey analytics tests** covering user journey tracking
- **58 icon registry tests** covering SVG sanitization, registry ops, all 3 library builders, API routes, and Pydantic models
- **57 session UX tests** covering session expiry, before-unload, focus trap
- **56 contract tests** covering API contract validation
- **55 middleware tests** covering correlation ID, logging, versioning, and feature flags middleware
- **50 compliance mapper tests** covering GDPR/HIPAA/SOC2/FedRAMP frameworks
- **48 AI suggestion tests** covering service recommendations
- **46 coverage gap tests** covering edge cases and uncovered paths
- **45 service updater tests** covering auto-discovery, fuzzy matching, and catalog integration
- **44 migration risk tests** covering risk assessment and runbook generation
- **42 migration intelligence tests** covering ML pattern matching
- **40 error envelope tests** covering structured error middleware
- **38 infrastructure import tests** covering TF/ARM/CFN parsing
- **36 HLD generator tests** covering AI document generation and WAF assessment
- **34 cost comparison tests** covering cross-cloud pricing
- **33 guided questions tests** covering rule evaluation and deduplication
- **32 prompt injection guard tests** covering input sanitization
- **30 living architecture tests** covering drift detection
- **28 analytics tests** covering funnel tracking, metrics persistence, and Azure Blob Storage
- **28 pricing tests** covering Azure Retail Prices API integration and caching
- **27 HLD export tests** covering Word/PDF/PowerPoint generation and diagram inclusion
- **26 chaos engineering tests** covering fault injection, recovery, and resilience
- **24 roadmap tests** covering feature requests and bug reports
- **21 auth tests** covering JWT session management, login/logout, token revocation
- **22 frontend Vitest tests** covering component rendering and interactions
- **34 Playwright E2E tests** covering full translation flow, diagram export, IaC generation, chat widget, services browser, admin dashboard
- All backend tests run against a test FastAPI client; E2E tests run against the deployed app

---

## Project Structure

```
Archmorph/
├── frontend/                        # React SPA
│   ├── src/
│   │   ├── App.jsx                  # Main application with tab routing
│   │   ├── constants.js             # API_BASE, APP_VERSION
│   │   ├── index.css                # Global styles, fonts, scrollbar
│   │   ├── main.jsx                 # Entry point
│   │   ├── components/
│   │   │   ├── AISuggestionPanel.jsx # AI service recommendation panel
│   │   │   ├── AdminDashboard.jsx   # Admin metrics & monitoring panel
│   │   │   ├── ChatWidget.jsx       # AI chatbot assistant overlay
│   │   │   ├── CompliancePanel.jsx  # Compliance framework mapping
│   │   │   ├── CookieBanner.jsx     # GDPR cookie consent banner
│   │   │   ├── DiagramTranslator/   # Main diagram upload & translation flow
│   │   │   │   ├── index.jsx            # Root component with useWorkflow hook
│   │   │   │   ├── UploadStep.jsx       # Diagram upload + infra import
│   │   │   │   ├── AnalysisResults.jsx  # AI analysis results display
│   │   │   │   ├── GuidedQuestions.jsx  # Guided questions with constraints
│   │   │   │   ├── ExportPanel.jsx      # Diagram export panel
│   │   │   │   ├── IaCViewer.jsx        # IaC code viewer with security scan
│   │   │   │   ├── CostPanel.jsx        # Cost estimation + comparison
│   │   │   │   ├── HLDPanel.jsx         # HLD generation & export
│   │   │   │   └── useWorkflow.js       # Workflow state machine hook
│   │   │   ├── ErrorBoundary.jsx    # React error boundary
│   │   │   ├── FeedbackWidget.jsx   # NPS and feedback collection
│   │   │   ├── InfraImportPanel.jsx # Import existing TF/ARM/CFN
│   │   │   ├── LandingPage.jsx      # Marketing landing page
│   │   │   ├── LegalPages.jsx       # Privacy policy, terms of service
│   │   │   ├── MigrationRiskPanel.jsx # Migration risk assessment
│   │   │   ├── MonitoringDashboard.jsx # Observability dashboard
│   │   │   ├── Nav.jsx              # Navigation bar
│   │   │   ├── OrganizationSettings.jsx # Multi-tenant org settings
│   │   │   ├── Roadmap.jsx          # Product roadmap timeline
│   │   │   ├── ServicesBrowser.jsx  # Service catalog browser
│   │   │   ├── Toast.jsx            # Toast notification system
│   │   │   └── ui.jsx               # Shared UI components
│   │   ├── hooks/
│   │   │   ├── useBeforeUnload.js   # Unsaved changes protection
│   │   │   ├── useFocusTrap.js      # Modal focus trap (accessibility)
│   │   │   ├── useJobStatus.js      # Background job polling
│   │   │   ├── useSSE.js            # Server-Sent Events hook
│   │   │   └── useSessionExpiry.js  # JWT session expiry handling
│   │   └── stores/
│   │       └── useAppStore.js       # Zustand global state store
│   ├── vite.config.js
│   └── package.json
├── backend/                         # FastAPI service
│   ├── main.py                      # App factory, middleware (181 lines)
│   ├── routers/                     # 25 FastAPI router modules
│   │   ├── services.py              # Service catalog routes
│   │   ├── diagrams.py              # Diagram analysis routes
│   │   ├── chat.py                  # Chat & IaC chat routes
│   │   ├── admin.py                 # Admin dashboard routes
│   │   ├── auth.py                  # Auth routes
│   │   ├── billing.py               # Billing & subscription routes
│   │   ├── dashboard.py             # User dashboard routes
│   │   ├── feature_flags.py         # Feature flag management routes
│   │   ├── feedback.py              # Feedback & NPS routes
│   │   ├── health.py                # Health check routes
│   │   ├── jobs.py                  # Background job & SSE routes
│   │   ├── journey_analytics.py     # User journey tracking routes
│   │   ├── legal.py                 # Legal & privacy routes
│   │   ├── marketplace.py           # Template marketplace routes
│   │   ├── migration.py             # Migration intelligence routes
│   │   ├── organizations.py         # Multi-tenant org routes
│   │   ├── privacy.py               # Privacy & data management routes
│   │   ├── roadmap.py               # Roadmap routes
│   │   ├── samples.py               # Sample diagram routes
│   │   ├── shared.py                # Shared utility routes
│   │   ├── templates.py             # Template gallery routes
│   │   ├── terraform.py             # Terraform preview routes
│   │   ├── v1.py                    # API v1 prefix router
│   │   ├── versioning.py            # Architecture versioning routes
│   │   └── webhooks.py              # Webhook integration routes
│   ├── admin_auth.py                # JWT session management (HS256, 1h TTL)
│   ├── ai_suggestion.py             # AI-powered service recommendations
│   ├── compliance_mapper.py         # GDPR/HIPAA/SOC2/FedRAMP compliance mapping
│   ├── cost_comparison.py           # Cross-cloud cost comparison engine
│   ├── cost_optimizer.py            # Savings recommendation engine
│   ├── error_envelope.py            # Structured error response middleware
│   ├── vision_analyzer.py           # GPT-4o image analysis engine + TTL cache
│   ├── image_classifier.py          # Pre-check gate for diagram validation
│   ├── guided_questions.py          # 32 questions, 8 categories, constraint system
│   ├── diagram_export.py            # Excalidraw/Draw.io/Visio export
│   ├── hld_generator.py             # AI-powered HLD generation (13 sections)
│   ├── hld_export.py                # HLD export to DOCX/PDF/PPTX
│   ├── iac_generator.py             # Terraform/Bicep/CFN code generation
│   ├── iac_chat.py                  # Interactive IaC chat assistant
│   ├── chatbot.py                   # FAQ chatbot with intent detection
│   ├── infra_import.py              # Import TF/ARM/CloudFormation
│   ├── job_queue.py                 # Background job queue + SSE
│   ├── journey_analytics.py         # User journey tracking engine
│   ├── living_architecture.py       # Drift detection & change tracking
│   ├── migration_intelligence.py    # ML-powered migration patterns
│   ├── migration_risk.py            # Risk assessment engine
│   ├── migration_runbook.py         # Automated runbook generation
│   ├── service_updater.py           # APScheduler daily catalog sync
│   ├── openai_client.py             # Shared Azure OpenAI client factory
│   ├── feature_flags.py             # Feature flags with % rollout + user targeting
│   ├── session_store.py             # Session persistence (InMemory/Redis backends)
│   ├── logging_config.py            # Structured JSON logging + CorrelationIdMiddleware
│   ├── audit_logging.py             # Comprehensive audit logging with risk levels
│   ├── api_versioning.py            # API v1 prefix mirror middleware
│   ├── usage_metrics.py             # Analytics with Azure Blob Storage persistence
│   ├── prompt_guard.py              # Prompt injection detection
│   ├── best_practices.py            # Best practices evaluation
│   ├── marketplace.py               # Template marketplace engine
│   ├── whitelabel.py                # White-label SDK
│   ├── icons/                       # Icon Registry system
│   │   ├── models.py                # Pydantic models
│   │   ├── svg_sanitizer.py         # SVG validation & XSS prevention
│   │   ├── registry.py              # Thread-safe icon catalog
│   │   ├── routes.py                # Icon management API endpoints
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
│   │   └── azure_pricing.py         # Azure Retail Prices API + cache
│   ├── tests/                       # 70+ test files, 1609 tests
│   ├── Dockerfile
│   └── requirements.txt
├── e2e/
│   └── archmorph.spec.ts            # Playwright E2E tests
├── infra/                           # Terraform IaC
│   ├── main.tf                      # All Azure resources
│   ├── variables.tf                 # Input variables
│   ├── outputs.tf                   # Output values
│   └── terraform.tfvars.example     # Example configuration
├── .github/
│   └── workflows/
│       ├── ci.yml                   # CI/CD: lint, test, build, deploy
│       ├── security.yml             # SAST/DAST/SCA security pipeline
│       ├── sbom.yml                 # CycloneDX SBOM generation
│       └── rollback.yml             # Blue-green rollback workflow
├── charts/
│   └── archmorph/                   # Helm chart for self-hosted K8s deployment
├── docs/                            # Documentation
│   ├── PRD.md                       # Product Requirements Document
│   ├── DEPLOYMENT_COSTS.md          # Azure cost breakdown
│   ├── architecture.excalidraw      # System architecture diagram
│   └── application-flow.excalidraw  # Application flow diagram
├── docker-compose.yml               # Full-stack local development
├── CONTRIBUTING.md
├── playwright.config.ts
└── README.md
```

---

## Deployment

Deployment is fully automated via **GitHub Actions CI/CD** on every push to `main`.

### Azure Resources

| Resource | SKU | Region |
|----------|-----|--------|
| Container Apps | Consumption | West Europe |
| Static Web Apps | Free | West Europe |
| Container Registry | Basic | West Europe |
| Azure OpenAI | S0 | East US |
| PostgreSQL Flexible Server | Burstable B1ms | West Europe |
| Azure Cache for Redis | Basic C0 | West Europe |
| Application Insights | — | West Europe |

### CI/CD Pipeline

The CI/CD workflow (`.github/workflows/ci.yml`) runs 8 jobs:

1. **backend-lint** — Ruff linting + Bandit security scan + pip-audit
2. **sast-semgrep** — Semgrep SAST scan (OWASP Top 10, security-audit, Python rules)
3. **secret-detection** — Gitleaks full-history secret scanning
4. **sbom** — CycloneDX SBOM generation (Python + npm, 90-day artifact retention)
5. **backend-tests** — 1609 pytest tests (matrix: Python 3.11 + 3.12)
6. **frontend-build** — Vite production build + npm audit
7. **deploy-backend** — Docker build → ACR push → Trivy container scan → Container Apps revision (blue-green with instant rollback)
8. **deploy-frontend** — Azure Static Web Apps (automatic)

Additional workflows:
- **security.yml** — SAST/DAST/SCA security pipeline (Semgrep, Bandit, CodeQL, Trivy, Gitleaks)
- **sbom.yml** — CycloneDX + Grype SBOM generation and vulnerability scanning
- **rollback.yml** — Blue-green deployment rollback trigger

### Manual Deploy (if needed)

```bash
# Backend
cd backend
az acr build --registry <acr-name> --image archmorph-api:latest .
az containerapp update --name archmorph-api --resource-group <rg> --image <acr>.azurecr.io/archmorph-api:latest

# Frontend
cd frontend
npm run build
npx swa deploy dist --deployment-token <token> --env production
```

### Helm Chart (Self-Hosted Kubernetes)

```bash
helm install archmorph charts/archmorph/ \
  --set backend.image=<acr>.azurecr.io/archmorph-api:latest \
  --set frontend.image=<acr>.azurecr.io/archmorph-frontend:latest \
  --namespace archmorph --create-namespace
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
| v2.1 — Pricing | Done | Dynamic Azure pricing, deployment region question, monthly cache, SKU multipliers |
| v2.2 — Self-Updating | Done | Auto-integration of new services, fuzzy name matching, category auto-classification, dry-run CLI |
| v2.5 — Audit & Quality | Done | 34 audit improvements, comprehensive test coverage |
| v2.6 — Icon Registry & Security | Done | Icon Registry (405 icons, 3 library formats), security hardening (timing-safe auth, headers, XSS protection) |
| v2.11.0 — Admin & Analytics | Done | JWT admin auth, persistent analytics (Azure Blob Storage), conversion funnel |
| v2.11.1 — UX Polish & Document Export | Done | HLD export (DOCX/PDF/PPTX), 15 UX improvements, CI/CD security (Semgrep, Gitleaks, SBOM, Trivy), 747 tests |
| v2.12.0 — Modular Architecture & Security | Done | Router decomposition (main.py 2,189→181 lines, 13 router modules), API versioning (v1 prefix), feature flags system, comprehensive audit logging, session persistence (InMemory/Redis), GPT response caching, DiagramTranslator decomposed (1,201→ 9 sub-components), structured JSON logging with correlation IDs, OTel observability rewrite, Azure Front Door WAF + Zero Trust, Helm charts, blue-green deployment, SBOM (CycloneDX + Grype), SAST/DAST/SCA pipeline, storage RBAC auth, pricing cache to Blob, monitoring optimization, 1149 tests |
| v3.0 — Multi-Cloud & Enterprise | Done | Multi-cloud targets (AWS/GCP/Azure), CloudFormation IaC, User Dashboard, Template Gallery, Visio import, i18n (en/es/fr), Living Architecture engine, Migration Intelligence, White-Label SDK, multi-tenant foundation |
| v3.0.1 — Confidence Transparency | Done | Confidence score explanations, transparency badge indicators, factor breakdown in analysis results |
| v3.1.0 — Stabilization Sprint | Done | Docker Compose stack, error envelope middleware, Gunicorn + Uvicorn workers, session expiry handling, before-unload protection, focus trap accessibility, toast notifications |
| v3.2.0 — Intelligence Suite | Done | AI suggestions engine, compliance mapper (GDPR/HIPAA/SOC2/FedRAMP), migration risk assessment, migration runbook generator, infrastructure import (TF/ARM/CFN) |
| v3.3.0 — Analytics & UX | Done | Journey analytics engine, cost comparison engine, cost optimizer, job queue with SSE, cookie consent banner, landing page, legal pages, organization settings |
| v3.4.0 — Quality & Documentation | Done | 1609 backend tests (70 files), PRD v3.4.0, roadmap alignment with 40 open issues, comprehensive documentation update |
| v3.5 — Performance & Scale | Planned | Connection pooling, read replicas, CDN edge caching, WebSocket live collaboration |
| v4.0 — Advanced | Planned | Pulumi output, Azure Migrate integration, multi-diagram projects, team collaboration |

---

## Security

- **Authentication:** JWT tokens (HS256) with 1-hour expiry and in-memory revocation for admin endpoints
- **Input validation:** Pydantic models on all endpoints, prompt injection guard on AI inputs
- **Error envelope:** Structured error responses with correlation IDs, no stack trace leakage
- **Transport:** HTTPS-only with TLS 1.2+ for all Azure resources
- **Headers:** Security headers middleware (X-Content-Type-Options, X-Frame-Options, CSP, HSTS, Permissions-Policy)
- **SVG sanitization:** DefusedXML-based sanitizer strips scripts and event handlers
- **IaC security scanning:** Generated Terraform/Bicep scanned for misconfigurations
- **Rate limiting:** SlowAPI rate limits on public endpoints
- **Secrets management:** All credentials via environment variables or GitHub Secrets; no secrets in code or git history
- **Dependencies:** Dependabot enabled for automated security updates, pip-audit in CI
- **SAST:** Semgrep static analysis (OWASP Top 10, security-audit, Python rules) in CI
- **Secret scanning:** Gitleaks full-history detection in CI
- **Container security:** Trivy vulnerability scanning (CRITICAL/HIGH) on every deployment
- **SBOM:** CycloneDX Bill of Materials generated for Python and npm dependencies (90-day retention)
- **WAF:** Azure Front Door Premium with OWASP CRS 3.2, Zero Trust network configuration
- **Audit logging:** Comprehensive structured JSON audit logs with risk levels, alerting rules, compliance queries
- **Feature flags:** Controlled feature rollout with percentage-based and user-targeted flags
- **Blue-green deployment:** Instant rollback capability for production deployments
- **Privacy:** Cookie consent banner, legal pages, GDPR-aware data handling
- **GPT truncation detection:** Guards against incomplete AI responses

### Reporting Vulnerabilities

If you discover a security vulnerability, please report it privately by opening a [GitHub Security Advisory](https://github.com/idokatz86/Archmorph/security/advisories/new).

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
- **API:** https://archmorph-api.nicesea-1430d1f7.westeurope.azurecontainerapps.io
- **API Docs (Swagger):** https://archmorph-api.nicesea-1430d1f7.westeurope.azurecontainerapps.io/docs
- **PRD:** [docs/PRD.md](docs/PRD.md)
- **Architecture Diagram:** [docs/architecture.excalidraw](docs/architecture.excalidraw) — Open in [Excalidraw](https://excalidraw.com)
- **Application Flow:** [docs/application-flow.excalidraw](docs/application-flow.excalidraw) — Open in [Excalidraw](https://excalidraw.com)
