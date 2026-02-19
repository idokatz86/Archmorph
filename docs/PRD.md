# Archmorph — Cloud Architecture Translator to Azure
## Product Requirements Document (PRD)
**Version:** 2.2.0
**Date:** February 19, 2026
**Author:** Ido Katz

---

## 1. Executive Summary

Archmorph is an AI-powered tool that converts AWS and GCP architecture diagrams into Azure equivalents. It analyzes uploaded diagrams, identifies cloud services, asks guided migration questions to refine the translation, maps services to Azure counterparts with confidence scores, exports translated architecture diagrams in multiple formats, generates ready-to-deploy Terraform/Bicep infrastructure code, provides dynamic cost estimates based on the Azure Retail Prices API, and automatically discovers and integrates new cloud services into its catalog.

**Problem:** Organizations migrating to Azure spend weeks manually mapping source architecture to Azure services. This process is error-prone, requires deep multi-cloud expertise, and lacks tooling for interactive refinement.

**Solution:** Automated diagram analysis and service translation with guided migration questions, confidence-scored mappings, multi-format diagram export, self-updating service catalog with auto-integration, generated IaC with secure credential handling, region-aware pricing, and an integrated chatbot assistant.

---

## 2. Target Users

| Persona | Role | Primary Need |
|---------|------|--------------|
| **Cloud Architect** | Solution design | Validate migration feasibility quickly |
| **DevOps Engineer** | Infrastructure automation | Generate deployable IaC from diagrams |
| **Technical Manager** | Migration planning | Estimate effort, costs, and identify gaps |
| **Consultant** | Multi-cloud advisory | Rapid proposal generation with exportable diagrams |

---

## 3. Core Features

### 3.1 Diagram Upload & Analysis
- **Supported formats:** PNG, JPG, SVG, PDF, Draw.io (.drawio), Lucidchart export
- **Visio (.vsdx) import:** Phase 3 (complex parsing)
- **Max file size:** 25 MB
- **Analysis time:** ≤30 seconds for diagrams ≤50 services

### 3.2 Service Detection
- AI-powered identification using Azure OpenAI GPT-4 Vision
- Detects: Services, connections/data flows, annotations
- **Multi-pass analysis:** Diagrams with >30 services trigger 2-pass analysis (quadrant split + merge)
- **405+ service catalog:** 145 AWS, 143 Azure, 117 GCP services with 122 cross-cloud mappings (grows automatically via auto-discovery)

### 3.3 Service Mapping
- Maps detected services to Azure equivalents
- Confidence scores: Critical (≥90%), High (70-89%), Medium (50-69%), Low (<50%)
- **Manual intervention flags** for services with <60% confidence or no direct equivalent
- Zone-based grouping (Networking, Compute, Data, Security, Integration, Monitoring)

### 3.4 Guided Migration Questions (v2.0)
- **32 contextual questions** across 8 categories
- Categories: Environment & Scale, Compliance & Security, Architecture Preferences, Data Processing, IoT, Monitoring & Operations, Containers, AI/ML
- Questions are dynamically selected based on detected services (8–18 questions per analysis)
- Answers refine Azure SKU selection, compliance settings, networking topology, DR strategy, security posture, and deployment region
- Question types: Radio (single-select), Checkbox (multi-select), Boolean (yes/no)
- **Deployment region question** (v2.1): User selects target Azure region from 20 options, affects pricing and IaC parameters

### 3.5 IaC Generation
- **Terraform (HCL):** Primary output with `random_password` for credentials, Key Vault secret storage
- **Bicep:** Secondary output with `@secure()` parameter for sensitive values
- **Scope:** Greenfield deployments only
- **Import blocks:** Phase 3 feature for existing resource adoption
- Read-only code preview with syntax highlighting (Prism.js)
- Secure credential handling — no hardcoded passwords

### 3.6 Cost Estimation (v2.1)
- **Dynamic pricing** via Azure Retail Prices API (`https://prices.azure.com/api/retail/prices`)
- **Region-aware:** Prices fetched per the user's selected deployment region (default: West Europe)
- **SKU strategy multipliers:** Cost-optimized (0.65x), Balanced (1.0x), Performance-first (1.6x), Enterprise (2.2x)
- **Monthly cache:** Prices cached to disk for 30 days, refreshed on next request
- **46 service mappings** to Azure Retail Prices API product names with fallback estimates
- Provides per-service low/high range and total monthly estimate
- Displays region, service count, and pricing source in the UI

### 3.7 Diagram Export (v2.0)
- **Excalidraw (.excalidraw):** Interactive JSON format with Azure service stencils
- **Draw.io (.drawio):** mxGraphModel XML with Azure stencils, compatible with diagrams.net
- **Visio (.vsdx):** VDX XML format for Microsoft Visio
- 36 Azure service stencils with color-coded categories
- Architecture zones with automatic layout

### 3.8 Self-Updating Service Catalog (v2.2)
- **APScheduler** CronTrigger runs daily at 2:00 AM UTC
- Fetches latest service data from AWS Pricing Index, Azure Retail Prices API, and GCP Pricing Calculator
- **Auto-integration** — newly discovered services are automatically written into the Python catalog files (`aws_services.py`, `azure_services.py`, `gcp_services.py`) under an `AUTO-DISCOVERED` section
- **Fuzzy name matching** — normalises service names (lowercase, strip non-alnum) and compares `name`, `fullName`, and `id` fields to prevent false-positive "new" detections
- **Category auto-classification** — 55 keyword hints map new services to categories (Compute, Storage, Database, AI/ML, etc.) with matching icons
- **Dry-run mode** — CLI `--dry-run` flag detects new services without writing to files
- Persists updates to `data/service_updates.json` (last 90 checks, cumulative `auto_added` tracking)
- Manual trigger available via API (`POST /api/service-updates/run-now`)
- Status and last update queryable via API (includes `auto_added_total` per provider)

### 3.9 Chatbot Assistant (v2.0)
- **Floating widget** (bottom-right corner) with assistant greeting
- **FAQ support:** Answers common questions about features, usage, and supported services
- **GitHub issue creation:** Draft → confirm workflow, auto-detects intent (bug/feature/question), applies labels
- **Markdown rendering:** Bold text and inline links in responses
- **Session management:** Persistent chat history per session, clearable

### 3.10 Admin Dashboard (v2.0)
- **Hidden access:** 5 rapid clicks on footer version text
- **Conversion funnel:** Visual funnel from upload → analyze → customize → results → generate IaC
- **Daily activity:** 14-day bar chart of all tracked events
- **Event counters:** All-time totals for each event type
- **Recent sessions:** Session list with completion status
- **API key protected:** Requires matching admin key

### 3.11 Export Options
- Download generated IaC (.tf, .bicep)
- Export translated architecture diagram (Excalidraw, Draw.io, Visio)
- Export mapping report (JSON)
- Copy to clipboard

---

## 4. Service Mapping Database

### 4.1 AWS → Azure Mappings (Core)

| AWS Service | Azure Equivalent | Confidence | Notes |
|-------------|------------------|------------|-------|
| EC2 | Virtual Machines | 95% | Direct mapping |
| S3 | Blob Storage | 95% | Direct mapping |
| RDS | Azure SQL / PostgreSQL Flexible | 90% | Engine-specific |
| Lambda | Azure Functions | 90% | Consumption model |
| DynamoDB | Cosmos DB | 85% | NoSQL, different consistency models |
| EKS | AKS | 90% | Managed Kubernetes |
| API Gateway | API Management | 85% | Feature parity varies |
| CloudFront | Front Door / CDN | 85% | Combined services |
| SQS | Service Bus Queues | 90% | Direct mapping |
| SNS | Service Bus Topics / Event Grid | 80% | Depends on use case |
| Cognito | Azure AD B2C | 75% | Different auth model |
| Step Functions | Logic Apps / Durable Functions | 80% | Depends on workflow |
| Secrets Manager | Key Vault | 95% | Direct mapping |
| Aurora Serverless | Azure SQL Serverless | 70% | Manual review flag |

### 4.2 GCP → Azure Mappings (Core)

| GCP Service | Azure Equivalent | Confidence | Notes |
|-------------|------------------|------------|-------|
| Compute Engine | Virtual Machines | 95% | Direct mapping |
| Cloud Storage | Blob Storage | 95% | Direct mapping |
| Cloud SQL | Azure SQL / PostgreSQL Flexible | 90% | Engine-specific |
| Cloud Functions | Azure Functions | 90% | Direct mapping |
| GKE | AKS | 90% | Managed Kubernetes |
| Pub/Sub | Service Bus / Event Grid | 85% | Pub/Sub model |
| BigQuery | Synapse Analytics | 80% | Different pricing model |
| Cloud Run | Container Apps | 90% | Serverless containers |
| Firestore | Cosmos DB | 85% | Document DB |
| Secret Manager | Key Vault | 95% | Direct mapping |
| Workflows | Logic Apps | 80% | YAML vs designer |
| Spanner | Cosmos DB (distributed) | 70% | Manual review flag |

### 4.3 Mapping Governance Process

| Activity | Frequency | Owner |
|----------|-----------|-------|
| Automated service sync + auto-add | Daily (2:00 AM UTC) | APScheduler |
| New service review & QA | Monthly | Product team |
| Confidence score recalibration | Quarterly | Engineering |
| Deprecation review | Quarterly | Product team |
| Community contribution review | Bi-weekly | Maintainers |

**Versioning:** Mappings stored in `mappings/v{MAJOR}.{MINOR}.json` with changelog. Auto-updates tracked in `data/service_updates.json` with cumulative `auto_added` counters.

---

## 5. Authentication & Authorization

### 5.1 Authentication Methods

| Method | Use Case | Details |
|--------|----------|---------|
| **Azure AD (B2B)** | Enterprise users | SSO via tenant federation |
| **Microsoft Account** | Individual users | Consumer sign-in |
| **API Keys** | CI/CD automation | Phase 3, scoped to project |

### 5.2 Authorization Levels

| Role | Permissions |
|------|-------------|
| Viewer | View projects, download exports |
| Editor | Upload diagrams, run analysis, answer guided questions |
| Admin | Manage team, API keys, billing, trigger service updates, access admin dashboard |

### 5.3 API Key Management (Phase 3)
- Keys scoped per project
- Rate limits: 100 requests/hour (standard), 1000/hour (enterprise)
- Rotation: Manual + auto-expire after 90 days

---

## 6. Error Handling & Edge Cases

### 6.1 Analysis Errors

| Scenario | User Message | System Behavior |
|----------|--------------|-----------------|
| Unrecognized service icon | "1 service could not be identified" | Mark as `UNKNOWN`, allow manual mapping |
| Blurry/low-res diagram | "Image quality too low for reliable analysis" | Show preview, allow retry |
| No services detected | "No cloud services found in this diagram" | Suggest supported formats |
| Timeout (>60s) | "Analysis taking longer than expected" | Background job, notify on completion |
| Unsupported format | "This file format is not supported" | List supported formats |

### 6.2 Mapping Errors

| Scenario | Handling |
|----------|----------|
| No Azure equivalent exists | Flag as "Manual Intervention Required", suggest closest alternative |
| Deprecated source service | Show warning, map to replacement if known |
| Ambiguous service (e.g., generic "database" icon) | Prompt user to select from options |

### 6.3 IaC Generation Errors

| Scenario | Handling |
|----------|----------|
| Service missing required config | Generate placeholder with `# TODO: Configure X` |
| Circular dependencies detected | Warning banner, manual reordering suggested |
| Hardcoded credentials | Auto-replaced with `random_password` + Key Vault (Terraform) or `@secure()` param (Bicep) |

---

## 7. Non-Functional Requirements

| Requirement | Target | Phase |
|-------------|--------|-------|
| Analysis latency | ≤30s for ≤50 services | v1.0 |
| Availability | 99.5% uptime | v1.0 |
| Max diagram size | 25 MB | v1.0 |
| Max services per diagram | 50 | v1.0 |
| Max services per project | 200 (across multiple diagrams) | v1.0 |
| Concurrent analyses | 10 per user | v1.0 |
| Data retention | 90 days (free), unlimited (paid) | v1.0 |
| **Accessibility** | WCAG 2.1 AA | v1.0 |
| Guided question response | ≤2s per question set generation | v2.0 |
| Diagram export | ≤5s for all formats | v2.0 |
| Service catalog freshness | ≤24 hours | v2.0 |
| Cost estimate response | ≤5s (cached), ≤15s (cold fetch) | v2.1 |
| Pricing cache duration | 30 days | v2.1 |
| Auto-add integration | ≤60s (full cycle per provider) | v2.2 |

---

## 8. Technical Architecture

### 8.1 Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 18, Vite, TailwindCSS, Lucide React (icons), Prism.js (syntax highlighting) |
| Backend | Python 3.11, FastAPI |
| AI | Azure OpenAI GPT-4 Vision |
| Database | PostgreSQL (Azure Flexible Server) |
| Storage | Azure Blob Storage |
| Hosting | Azure Container Apps (API), Static Web Apps (frontend) |
| Container Registry | Azure Container Registry (Basic) |
| Scheduler | APScheduler 3.10 (CronTrigger, daily service sync + auto-add) |
| Guided Questions | In-process engine (32 questions, 8 categories) |
| Diagram Export | In-process engine (Excalidraw, Draw.io, Visio with 36 Azure stencils) |
| Pricing | Azure Retail Prices API with 30-day disk cache (46 service queries) |
| IaC | Terraform (infra), Bicep support in-app |
| Testing | pytest (backend, 75 tests), Playwright (E2E, 27 tests) |

### 8.2 API Endpoints (30 total)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check (version, mode, catalog stats, scheduler) |
| `/api/services` | GET | List services with optional filters (provider, category, search) |
| `/api/services/providers` | GET | List cloud providers with service counts |
| `/api/services/categories` | GET | List categories with per-provider counts |
| `/api/services/mappings` | GET | List cross-cloud mappings (filter, search, confidence) |
| `/api/services/{provider}/{id}` | GET | Get specific service with cross-cloud equivalents |
| `/api/services/stats` | GET | Catalog statistics (totals, average confidence) |
| `/api/projects` | POST | Create project |
| `/api/projects/{id}` | GET | Get project details |
| `/api/projects/{id}/diagrams` | POST | Upload diagram file |
| `/api/diagrams/{id}/analyze` | POST | Analyze diagram — detect services, generate mappings |
| `/api/diagrams/{id}/mappings` | GET | Get diagram mappings |
| `/api/diagrams/{id}/mappings/{svc}` | PATCH | Override a service mapping |
| `/api/diagrams/{id}/questions` | POST | Generate guided migration questions |
| `/api/diagrams/{id}/apply-answers` | POST | Apply answers to refine analysis |
| `/api/diagrams/{id}/export-diagram` | POST | Export diagram (Excalidraw/Draw.io/Visio) |
| `/api/diagrams/{id}/generate` | POST | Generate IaC code (Terraform/Bicep) |
| `/api/diagrams/{id}/export` | GET | Export IaC file download |
| `/api/diagrams/{id}/cost-estimate` | GET | Dynamic cost estimate (Azure Retail Prices API) |
| `/api/service-updates/status` | GET | Scheduler status, auto-added totals |
| `/api/service-updates/last` | GET | Last catalog update details |
| `/api/service-updates/run-now` | POST | Trigger immediate catalog refresh + auto-add |
| `/api/chat` | POST | Send message to chatbot assistant |
| `/api/chat/history/{session_id}` | GET | Get chat session history |
| `/api/chat/{session_id}` | DELETE | Clear chat session |
| `/api/admin/metrics` | GET | Admin usage metrics summary (key-protected) |
| `/api/admin/metrics/funnel` | GET | Admin conversion funnel data |
| `/api/admin/metrics/daily` | GET | Admin daily metrics |
| `/api/admin/metrics/recent` | GET | Admin recent events |
| `/api/contact` | GET | Contact information |

### 8.3 Design System (v2.0)

| Token | Value | Usage |
|-------|-------|-------|
| Primary | #0F172A | Headers, navigation |
| Secondary | #1E293B | Cards, surfaces |
| CTA | #22C55E | Buttons, active states |
| Background | #020617 | Page background |
| Text Primary | #F8FAFC | Body text |
| Text Muted | #64748B | Secondary text |
| Font | Plus Jakarta Sans | All typography |
| Icons | Lucide React (SVG) | All icons, no emojis |
| Style | Flat Design | Clean, minimal aesthetic |

---

## 9. Roadmap

| Phase | Status | Features |
|-------|--------|----------|
| **v1.0 — MVP** | Done | Diagram upload, AWS/GCP → Azure mapping, Terraform/Bicep output, basic cost estimation |
| **v2.0 — Production** | Done | Guided questions (32 across 8 categories), diagram export (Excalidraw/Draw.io/Visio with stencils), daily auto-updating service catalog (APScheduler), 405-service catalog, secure IaC credentials, design system UI with Lucide icons, chatbot assistant, admin dashboard |
| **v2.1 — Pricing & Polish** | Done | Dynamic Azure pricing via Retail Prices API, deployment region question, region-aware cost estimates, monthly pricing cache, SKU strategy multipliers, 46 service price mappings, comprehensive test suites (181 unit + 34 E2E) |
| **v2.2 — Self-Updating Catalog** | Done | Auto-integration of new services into catalog files, fuzzy name matching, category auto-classification (55 keyword hints), dry-run CLI mode, cumulative auto-added tracking |
| **v3.0 — Enterprise** | Planned | Visio import, API keys, import blocks for existing resources, SSO, RBAC |
| **v4.0 — Advanced** | Planned | Pulumi output, Azure Migrate integration, multi-diagram projects |

---

## 10. Success Metrics

| Metric | Target (v1.0) | Target (v2.0) | Target (GA) |
|--------|---------------|---------------|-------------|
| Analysis accuracy | ≥85% | ≥88% | ≥92% |
| Mapping accuracy | ≥90% | ≥93% | ≥95% |
| Time to first IaC export | ≤5 min | ≤3 min | ≤2 min |
| User retention (30-day) | ≥40% | ≥50% | ≥60% |
| Guided question completion rate | — | ≥70% | ≥80% |
| Cost estimate accuracy (vs actual) | — | — | ±30% |
| Catalog freshness (new service lag) | — | ≤24h detect | ≤24h detect + auto-add |

---

## 11. Open Items & Suggestions

| Item | Decision | Owner | Priority |
|------|----------|-------|----------|
| Pricing model | Usage-based (per diagram) with 5 free/month | PM | High |
| Pulumi support | Phase 4 | Engineering | Medium |
| Azure Migrate partnership | Phase 4, requires BD | PM | Low |
| Visio import support | Phase 3, complex parsing | Engineering | High |
| Multi-diagram project support | Phase 4 | Engineering | Medium |
| **Cost estimate drill-down** | Add per-service config (instance count, storage size) for refined pricing | Engineering | Medium |
| **PDF report export** | Export full analysis as branded PDF (mappings, diagram, IaC, cost) | Engineering | Medium |
| **Migration timeline generator** | Auto-generate phased migration plan with dependencies | Engineering | High |
| **Service dependency graph** | Visualize detected service connections and data flows | Engineering | Medium |
| **Collaboration features** | Share projects, comments, review workflow | Engineering | Medium |
| **Terraform plan validation** | Preview `terraform plan` output against an Azure subscription | Engineering | High |
| **Historical pricing trends** | Track cost estimates over time for the same architecture | Engineering | Low |
| **Multi-language IaC** | ARM Templates (JSON) and CloudFormation reverse output | Engineering | Low |
| **Compliance mapping** | Auto-detect regulatory requirements and map to Azure compliance services | Engineering | Medium |
| **Auto-discovered service review UI** | Admin dashboard panel to review, approve, or reject auto-added services with metadata editing | Engineering | Medium |
| **Cross-cloud mapping auto-suggestion** | Use AI to suggest Azure equivalents for newly discovered AWS/GCP services | Engineering | High |
| **Webhook notifications** | Notify via Slack/Teams/email when new services are auto-discovered and added | Engineering | Low |

---

*End of Document*
