# Archmorph — Cloud Architecture Translator to Azure
## Product Requirements Document (PRD)
**Version:** 2.11.1
**Date:** June 22, 2025
**Author:** Ido Katz

---

## 1. Executive Summary

Archmorph is an AI-powered tool that converts AWS and GCP architecture diagrams into Azure equivalents. It analyzes uploaded diagrams using GPT-4o vision, identifies cloud services, allows users to add services via natural language, asks guided migration questions with smart deduplication to refine the translation, maps services to Azure counterparts with confidence scores, exports translated architecture diagrams in multiple formats, generates ready-to-deploy Terraform/Bicep infrastructure code, provides dynamic cost estimates based on the Azure Retail Prices API with 134 service pricing entries, automatically discovers and integrates new cloud services into its catalog, generates comprehensive AI-powered High-Level Design (HLD) documents, provides an interactive IaC chat assistant, analyzes architecture against Azure Well-Architected Framework (WAF), provides cost optimization recommendations, includes sample diagrams for onboarding, collects NPS feedback, supports shareable analysis links, provides user authentication with Azure AD B2C and GitHub OAuth, implements usage quotas and lead capture, generates migration runbooks with step-by-step task tracking, supports architecture versioning with change history, provides Terraform plan previews, comprehensive application analytics, and includes E2E monitoring with automatic GitHub issue creation.

**Problem:** Organizations migrating to Azure spend weeks manually mapping source architecture to Azure services. This process is error-prone, requires deep multi-cloud expertise, and lacks tooling for interactive refinement.

**Solution:** Automated diagram analysis and service translation with natural language service addition, smart question deduplication, confidence-scored mappings, multi-format diagram export, self-updating service catalog with auto-integration, generated IaC with secure credential handling, region-aware pricing with optimized targeted queries, AI-powered HLD generation, interactive IaC chat assistant, WAF best practices linting, cost optimization tips, sample diagram onboarding, NPS feedback collection, shareable links, user authentication with quotas, migration runbook generation, architecture versioning, Terraform plan preview, comprehensive analytics, Azure Monitor integration with alerts, and an integrated chatbot assistant.

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
- AI-powered identification using Azure OpenAI GPT-4o Vision
- Detects: Services, connections/data flows, annotations
- **Multi-pass analysis:** Diagrams with >30 services trigger 2-pass analysis (quadrant split + merge)
- **405+ service catalog:** 145 AWS, 143 Azure, 117 GCP services with 122 cross-cloud mappings (grows automatically via auto-discovery)

### 3.3 Service Mapping & Confidence Engine
- Maps detected services to Azure equivalents
- Confidence scores: Critical (≥90%), High (70-89%), Medium (50-69%), Low (<50%)
- **Manual intervention flags** for services with <60% confidence or no direct equivalent
- Zone-based grouping (Networking, Compute, Data, Security, Integration, Monitoring)
- **70+ GCP synonyms** (v2.4): Maps alternate GCP service names to canonical names (e.g., "Google Kubernetes Engine" → "GKE", "Cloud Load Balancing" → mapping key)
- **Fuzzy matching fallback** (v2.4): Uses `difflib.SequenceMatcher` with ≥65% threshold to match services that don't have exact catalog entries
- **GPT-4o confidence blending** (v2.4): Combines mapping confidence (70%) with GPT-4o detection confidence (30%) for more accurate scores
- **Confidence recalculation** (v2.4): Summary statistics (high/medium/low/average) are recalculated after guided question answers are applied
- **Service connections** (v2.4): GPT-4o extracts inter-service data flows and protocols from diagrams

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

### 3.6 Cost Estimation (v2.3)
- **Dynamic pricing** via Azure Retail Prices API (`https://prices.azure.com/api/retail/prices`)
- **Region-aware:** Prices fetched per the user's selected deployment region (default: West Europe)
- **SKU strategy multipliers:** Cost-optimized (0.65x), Balanced (1.0x), Performance-first (1.6x), Enterprise (2.2x)
- **Monthly cache:** Prices cached to disk for 30 days, refreshed on next request
- **134 service pricing entries** to Azure Retail Prices API product names with fallback estimates
- **56 service aliases** mapping cross-cloud naming variants to canonical pricing keys
- **6-step price resolution:** exact match → alias → prefix match → word overlap → alias fallback → substring fallback
- **Optimized targeted queries:** Only fetches prices for services actually detected in the diagram (not the full catalog)
- Provides per-service low/high range and total monthly estimate
- Displays region, service count, and pricing source in the UI
- **E2E validated:** Real pricing confirmed across 5 diagrams (3 AWS + 2 GCP), ranges $120–$2,100/mo

### 3.7 Diagram Export (v2.0)
- **Excalidraw (.excalidraw):** Interactive JSON format with Azure service stencils
- **Draw.io (.drawio):** mxGraphModel XML with Azure stencils, compatible with diagrams.net
- **Visio (.vsdx):** VDX XML format for Microsoft Visio
- 36 Azure service stencils with color-coded categories
- Architecture zones with automatic layout
- **Icon Registry fallback** (v2.6): Services not in the 36 hardcoded stencils now fall back to the 405-icon registry for richer diagrams

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

### 3.12 HLD Generation (v2.4)
- **AI-powered High-Level Design** document generated via GPT-4o
- **13 HLD sections:** Title, Executive Summary, Architecture Overview, Services (detailed), Networking, Security, Data Architecture, CAF Alignment, FinOps, Region Strategy, WAF Assessment, Migration Approach, Risks & Mitigations, Next Steps
- **60+ Azure documentation links** automatically enriched into service entries (fuzzy matching against doc link catalog)
- **Service deduplication** — duplicate Azure service entries are merged before HLD generation
- **Cost context integration** — if cost estimate is available, it's included in the GPT-4o prompt for FinOps recommendations
- **WAF assessment** — scores across 5 pillars: Reliability, Security, Cost Optimization, Operational Excellence, Performance Efficiency (1-5 scale with color coding)
- **Migration phases** — phased migration approach with timelines and dependencies
- **Markdown export** — 14-section markdown document downloadable as `.md` file
- **JSON export** — raw HLD data downloadable as `.json` file
- **Frontend UI** — 7-tab interface (Overview, Services, Networking, Security, FinOps, Migration, WAF) with service cards, doc links, alternatives, limitations, and SLA info

### 3.13 IaC Chat Assistant (v2.4)
- **Interactive GPT-4o assistant** for modifying generated Terraform/Bicep code
- **Context-aware** — receives current IaC code, analysis results, and IaC parameters as context
- **Session management** — in-memory conversation history (last 10 turns) per diagram
- **Quick actions** — pre-built prompts: "Add monitoring", "Add security", "Add backup", "Optimize costs"
- **Code updates** — assistant returns both explanation and updated code that auto-replaces the editor content
- **Format-aware** — supports both Terraform and Bicep syntax based on current generation format
- **Chat UI** — collapsible panel with message history, auto-scroll, and clear session button

### 3.14 Icon Registry & Library Builder (v2.6)
- **Central icon catalog** — 405 normalized cloud service icons (143 Azure, 145 AWS, 117 GCP) as sanitized SVGs with deterministic canonical IDs
- **Multi-format library export:**
  - **Draw.io** custom libraries (`.xml`) with reference and full-embed modes
  - **Excalidraw** library bundles (`.excalidrawlib`) with materialized SVG images
  - **Visio** sidecar stencil packs (`.zip`) with SVG master shapes and manifest
- **SVG sanitization** — strips scripts, event handlers, external references, foreignObject, `javascript:` URIs, dangerous CSS patterns; minification removes comments and collapses whitespace
- **Thread-safe** — `RLock`-protected mutable state for concurrent request safety
- **Persistent storage** — registry state serialized to JSON sidecar file, auto-restored on startup
- **Auto-load** — built-in sample packs loaded from `samples/` directory on application boot
- **ZIP/folder ingestion** — upload icon packs via API (ZIP with metadata.json or folder scan)
- **Search & resolve** — search by provider, category, query; resolve best icon for a service via `service_id` or fuzzy name match
- **Diagram bridge** — `diagram_export.py` falls back to the 405-icon registry when services aren't in the 36 hardcoded stencils
- **DELETE endpoint** — remove icon packs and their icons via `DELETE /api/icon-packs/{pack_id}`
- **Cache** — TTL-based asset cache (1-hour, 200 entries) for transformed library outputs

### 3.15 Security Hardening (v2.6)
- **Security headers middleware** — X-Content-Type-Options, X-Frame-Options, Referrer-Policy, HSTS, Permissions-Policy
- **Timing-safe key comparison** — `secrets.compare_digest()` for API key and admin key verification
- **No default admin secret** — `ARCHMORPH_ADMIN_KEY` must be set via environment variable (503 if unset)
- **Restricted CORS** — explicit method and header allowlists instead of wildcards
- **ZIP slip prevention** — path traversal entries (`../`, absolute paths) rejected during icon pack ingestion
- **XSS protection** — SVG sanitizer blocks `javascript:`, `vbscript:` URIs and dangerous CSS (`expression()`, `-moz-binding`, `url()`)
- **Error sanitization** — internal exception details no longer leaked to API responses
- **Dependabot** — automated dependency updates for pip, npm, Docker, GitHub Actions, and Terraform
- **CI hardening** — `npm audit` failures no longer silently ignored

### 3.16 User Authentication & Quotas (v2.9)
- **Azure AD B2C** — Enterprise SSO with JWT validation, JWKS caching, user persistence
- **GitHub OAuth** — Developer-friendly authentication with email access
- **Anonymous users** — IP-based tracking with free tier limits
- **User tiers:**
  - **Free:** 5 analyses, 3 IaC downloads, 2 HLD generations, 10 cost estimates, 3 share links per month
  - **Pro:** 50 analyses, 30 IaC downloads, 20 HLD generations, 100 cost estimates, 50 share links per month
  - **Enterprise:** Unlimited usage
- **Quota enforcement** — Real-time usage tracking with upgrade prompts at low quota
- **Session management** — Secure session tokens with TTL-based expiration
- **Lead capture** — Optional email capture before gated actions (IaC download, HLD, share)
- **Marketing consent** — GDPR-compliant opt-in for marketing communications

### 3.17 Migration Runbook Generator (v2.9)
- **AI-generated runbooks** — Step-by-step migration guide based on architecture analysis
- **7 migration phases:** Assessment, Planning, Preparation, Migration, Validation, Cutover, Post-Migration
- **Task prioritization:** Critical, High, Medium, Low with dependency tracking
- **Service-specific tasks:** Compute, Database, Storage, Networking, Security, Monitoring
- **Risk assessment:** Automatic risk level calculation based on service complexity and confidence scores
- **Azure CLI commands** — Pre-built commands for common migration tasks
- **Validation checklists** — Per-task validation steps with checkbox tracking
- **Rollback procedures** — Documented rollback steps for each critical task
- **Markdown export** — Downloadable runbook as `.md` file with full formatting
- **Duration estimation** — Automatic calculation of total migration duration in days

### 3.18 Architecture Versioning (v2.9)
- **Version history** — Track all changes to architecture analyses over time
- **Change detection:** Service Added, Service Removed, Mapping Changed, Configuration Changed, NL Addition
- **Version comparison** — Side-by-side diff of any two versions with detailed change list
- **Restore versions** — Restore any previous version, creating a new version from it
- **Content hashing** — SHA-256 based content fingerprinting for change detection
- **Timeline view** — Chronological timeline of all architecture changes
- **7-day retention** — In-memory storage with TTL-based cleanup

### 3.19 Terraform Plan Preview (v2.9)
- **HCL parsing** — Extracts resource definitions from generated Terraform code
- **Simulation mode** — Preview what resources would be created without running Terraform
- **Resource categorization:** Create, Update, Delete, Replace, No-Op, Read
- **Syntax validation** — Checks for common HCL errors (unbalanced braces, double equals, invalid names)
- **Best practices warnings:**
  - Hardcoded passwords detection
  - Missing tags warning
  - Missing terraform block
  - Missing provider block
- **Plan summary** — Resource counts by action type
- **Markdown preview** — Human-readable plan output with emoji indicators

### 3.20 Application Analytics (v2.9)
- **Event tracking** — Comprehensive event capture with category, properties, and metrics
- **Session management** — Track user sessions with page views and conversion status
- **Metrics types:** Counter, Gauge, Histogram, Timer
- **Performance monitoring:**
  - Request latency tracking by endpoint and method
  - P50, P95, P99 percentile calculations
  - Error rate tracking
- **Feature analytics** — Track usage of each feature for product decisions
- **Conversion funnel:** Upload → Analyze → Questions → Export → IaC Download
- **Timer context manager** — Easy timing of operations with automatic recording
- **Admin dashboard** — Comprehensive analytics summary with performance metrics

### 3.21 Azure Monitor Integration (v2.9)
- **Application Insights** — Distributed tracing, APM, and telemetry
- **Azure Monitor Alerts:**
  - High error rate (>50 failures in 15 min)
  - High response time (>5s average)
  - High CPU usage (>80%)
  - Database connection saturation (>80%)
  - Storage availability drop (<99%)
- **Action groups** — Email notifications for critical alerts
- **Log Analytics saved queries:**
  - Error logs by exception type
  - API latency by endpoint
  - User analytics by action
- **Workbook dashboard** — Operations dashboard with request trends and failure analysis

### 3.22 GPT-4o AI Assistant (v2.10)
- **Natural language conversations** — True AI assistant powered by GPT-4o for any question
- **Context-aware responses** — Understands Archmorph features, cloud architecture, migrations
- **Knowledge domains:**
  - Archmorph platform features and usage
  - AWS, Azure, GCP services and best practices
  - Terraform and Bicep IaC code
  - Migration strategies and patterns
- **Automatic action detection** — Recognizes bug reports and feature requests in conversation
- **GitHub issue creation** — Creates structured issues with templates when users report bugs/request features
- **Session history** — Maintains conversation context across messages (2-hour TTL)
- **Fallback handling** — Graceful degradation when AI unavailable

### 3.23 Product Roadmap & Timeline (v2.10)
- **Complete version history** — Timeline from Day 0 (Dec 2025) to current release
- **Release categorization:**
  - Released — Shipped features with dates and metrics
  - In Progress — Currently being developed
  - Planned — Scheduled for future releases
  - Ideas — Under consideration based on feedback
- **Release details** — Version, name, date, highlights, service/mapping counts
- **Statistics dashboard** — Total releases, features shipped, days since launch
- **Interactive timeline UI** — Expandable cards with filters (All/Released/Planned/Ideas)
- **GitHub repository link** — Direct access to source code and contributions

### 3.24 Feature Request & Bug Report System (v2.10)
- **Feature request submission** — Users can request features via UI or AI assistant
- **Structured templates:**
  - Feature requests: title, description, use case, email
  - Bug reports: title, description, steps, expected/actual behavior, browser/OS
- **Automatic GitHub integration** — Creates issues with appropriate labels
- **Rate limiting** — 3 feature requests/hour, 5 bug reports/hour to prevent abuse
- **Email capture** — Optional contact email for follow-up
- **Success confirmation** — Toast notification with link to created issue

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
| Frontend | React 19.1, Vite 7.3, TailwindCSS 4.2, Lucide React (icons), Prism.js (syntax highlighting) |
| Backend | Python 3.11, FastAPI |
| AI | Azure OpenAI GPT-4o (deployment `gpt-4o`, model 2024-05-13) |
| Database | PostgreSQL (Azure Flexible Server) |
| Storage | Azure Blob Storage |
| Hosting | Azure Container Apps (API), Static Web Apps (frontend) |
| Container Registry | Azure Container Registry (Basic) |
| Scheduler | APScheduler 3.10 (CronTrigger, daily service sync + auto-add) |
| Guided Questions | In-process engine (32 questions, 8 categories) |
| Diagram Export | In-process engine (Excalidraw, Draw.io, Visio with 36 Azure stencils + 405-icon registry fallback) |
| Pricing | Azure Retail Prices API with 30-day disk cache (134 service entries, 56 aliases, targeted queries) |
| IaC | Terraform (infra), Bicep support in-app |
| Testing | pytest (backend, 719 tests in 29 files), E2E flow test (65 steps across 5 diagrams), Playwright (35+ browser tests), integration tests |
| Best Practices | In-process WAF linter (5 pillars, 15+ rules, quick wins, pillar scores) |
| Cost Optimizer | In-process engine (7 categories, RI/Spot/tiering/auto-shutdown recommendations) |
| Feedback | In-process NPS/feature/bug collection (30-day trend, admin dashboard) |
| HLD Generator | In-process GPT-4o engine (60+ Azure doc links, 13-section HLD, markdown converter) |
| IaC Chat | In-process GPT-4o assistant (session management, code modification, context-aware) |
| Icon Registry | In-process engine (405 icons, Draw.io/Excalidraw/Visio library builders, SVG sanitization, thread-safe, persistent) |
| Security | JWT admin auth (HS256, 1h TTL), security headers, timing-safe auth, Dependabot, defusedxml, ZIP slip protection |
| NL Service Builder | In-process GPT-4o engine (fuzzy Azure service matching, alias support, confidence scoring) |
| Smart Question Dedup | In-process engine (implicit answer detection, smart defaults from analysis) |
| E2E Monitoring | GitHub Actions workflow (Azure Monitor + App Insights health checks, auto GitHub issue creation) |
| Authentication | In-process (Azure AD B2C JWT validation, GitHub OAuth, session tokens, usage quotas) |
| Migration Runbook | In-process generator (7 phases, task templates, risk assessment, Markdown export) |
| Architecture Versioning | In-memory store (change detection, version comparison, restore, 7-day TTL) |
| Terraform Preview | In-process HCL parser (resource extraction, syntax validation, plan simulation) |
| Application Analytics | Persistent metrics via Azure Blob Storage (background flush, crash-safe shutdown, event tracking, sessions, funnels) |
| Azure Monitoring | Application Insights + Azure Monitor (alerts, workbooks, Log Analytics queries) |

### 8.2 API Endpoints (81 total)

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
| `/api/diagrams/{id}/add-services` | POST | Add Azure services via natural language text |
| `/api/diagrams/{id}/apply-answers` | POST | Apply answers to refine analysis |
| `/api/diagrams/{id}/export-diagram` | POST | Export diagram (Excalidraw/Draw.io/Visio) |
| `/api/diagrams/{id}/generate` | POST | Generate IaC code (Terraform/Bicep) |
| `/api/diagrams/{id}/export` | GET | Export IaC file download |
| `/api/diagrams/{id}/cost-estimate` | GET | Dynamic cost estimate (Azure Retail Prices API) |
| `/api/diagrams/{id}/best-practices` | GET | Analyze architecture against Azure WAF (v2.8) |
| `/api/diagrams/{id}/cost-optimization` | GET | Get cost optimization recommendations (v2.8) |
| `/api/diagrams/{id}/share` | POST | Create shareable read-only link (v2.8) |
| `/api/shared/{id}` | GET | Get shared analysis by share ID (v2.8) |
| `/api/samples` | GET | List available sample diagrams (v2.8) |
| `/api/samples/{id}/analyze` | POST | Analyze a sample diagram (v2.8) |
| `/api/feedback/nps` | POST | Submit NPS score with follow-up (v2.8) |
| `/api/feedback/feature` | POST | Submit feature feedback thumbs up/down (v2.8) |
| `/api/feedback/bug` | POST | Submit bug report with context (v2.8) |
| `/api/admin/feedback` | GET | Get feedback summary (admin only, v2.8) |
| `/api/auth/config` | GET | Get public authentication configuration (v2.9) |
| `/api/auth/login` | POST | Login with Azure AD B2C or GitHub OAuth (v2.9) |
| `/api/auth/me` | GET | Get current authenticated user (v2.9) |
| `/api/auth/quota` | GET | Check user quota for an action (v2.9) |
| `/api/leads/capture` | POST | Capture lead information before gated action (v2.9) |
| `/api/admin/leads` | GET | Get captured leads summary (admin only, v2.9) |
| `/api/diagrams/{id}/versions` | POST | Create a new version of an architecture (v2.9) |
| `/api/diagrams/{id}/versions` | GET | Get version history for a diagram (v2.9) |
| `/api/diagrams/{id}/versions/{num}` | GET | Get a specific version of an architecture (v2.9) |
| `/api/diagrams/{id}/versions/{num}/restore` | POST | Restore a previous version (v2.9) |
| `/api/diagrams/{id}/versions/compare` | GET | Compare two versions of an architecture (v2.9) |
| `/api/diagrams/{id}/runbook` | POST | Generate a migration runbook (v2.9) |
| `/api/diagrams/{id}/runbook` | GET | Get generated runbook for a diagram (v2.9) |
| `/api/diagrams/{id}/runbook/markdown` | GET | Get runbook as downloadable Markdown (v2.9) |
| `/api/diagrams/{id}/terraform-preview` | POST | Generate a preview of Terraform plan (v2.9) |
| `/api/terraform/validate` | POST | Validate Terraform HCL syntax (v2.9) |
| `/api/admin/analytics` | GET | Get comprehensive analytics summary (admin, v2.9) |
| `/api/admin/analytics/performance` | GET | Get API performance metrics (admin, v2.9) |
| `/api/admin/analytics/features` | GET | Get feature usage metrics (admin, v2.9) |
| `/api/admin/analytics/funnel` | GET | Get conversion funnel metrics (admin, v2.9) |
| `/api/roadmap` | GET | Get complete roadmap with timeline (v2.10) |
| `/api/roadmap/release/{version}` | GET | Get details for a specific release (v2.10) |
| `/api/roadmap/feature-request` | POST | Submit a feature request to GitHub (v2.10) |
| `/api/roadmap/bug-report` | POST | Submit a bug report to GitHub (v2.10) |
| `/api/chat` | POST | Send message to GPT-4o AI assistant (v2.10) |
| `/api/chat/history/{session_id}` | GET | Get AI chat session history (v2.10) |
| `/api/chat/history/{session_id}` | GET | Get chat session history |
| `/api/chat/{session_id}` | DELETE | Clear chat session |
| `/api/admin/metrics` | GET | Admin usage metrics summary (key-protected) |
| `/api/admin/metrics/funnel` | GET | Admin conversion funnel data |
| `/api/admin/metrics/daily` | GET | Admin daily metrics |
| `/api/admin/metrics/recent` | GET | Admin recent events |
| `/api/diagrams/{id}/generate-hld` | POST | Generate AI-powered High-Level Design document |
| `/api/diagrams/{id}/hld` | GET | Retrieve cached HLD document |
| `/api/diagrams/{id}/iac-chat` | POST | Send message to IaC chat assistant |
| `/api/diagrams/{id}/iac-chat` | GET | Get IaC chat session history |
| `/api/diagrams/{id}/iac-chat` | DELETE | Clear IaC chat session |
| `/api/contact` | GET | Contact information |
| `/api/icon-packs` | POST | Upload ZIP/JSON icon pack |
| `/api/icon-packs/{pack_id}` | DELETE | Remove icon pack and its icons |
| `/api/icons` | GET | Search icons (provider, query, category, packId) |
| `/api/icons/packs` | GET | List registered icon packs |
| `/api/icons/metrics` | GET | Icon registry observability counters |
| `/api/icons/{icon_id}/svg` | GET | Get raw SVG for a single icon |
| `/api/libraries/drawio` | GET | Download Draw.io custom library |
| `/api/libraries/excalidraw` | GET | Download Excalidraw library bundle |
| `/api/libraries/visio` | GET | Download Visio sidecar stencil pack |

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
| **v2.1 — Pricing & Polish** | Done | Dynamic Azure pricing via Retail Prices API, deployment region question, region-aware cost estimates, monthly pricing cache, SKU strategy multipliers |
| **v2.2 — Self-Updating Catalog** | Done | Auto-integration of new services into catalog files, fuzzy name matching, category auto-classification (55 keyword hints), dry-run CLI mode, cumulative auto-added tracking |
| **v2.3 — Real Pricing & GCP Validation** | Done | Real Azure pricing (134 entries + 56 aliases), 6-step price resolution, optimized targeted API queries, session key fix, full GCP → Azure E2E validation (5 diagrams, 50/50 steps pass), 184 unit tests |
| **v2.4 — HLD, IaC Chat & Confidence** | Done | AI-powered HLD generation (13 sections, 60+ doc links, WAF assessment, migration phases), IaC Chat assistant (GPT-4o, session-based, quick actions), confidence engine (70+ GCP synonyms, fuzzy matching ≥65%, confidence blending 70/30, recalculation), service connections extraction, 257 unit tests, 65 E2E steps |
| **v2.5 — Audit & Quality** | Done | 34 audit improvements, comprehensive test coverage (290 → 348 tests) |
| **v2.6 — Icon Registry & Security** | Done | Icon Registry (405 icons, 3 library formats, SVG sanitization, thread-safe, persistent, auto-load), security hardening (timing-safe auth, security headers, ZIP slip protection, XSS prevention, Dependabot), diagram export bridge to registry |
| **v2.7 — NL Builder & Monitoring** | Done | Natural Language Service Builder (add Azure services via text after diagram analysis), Smart Question Deduplication (filters questions based on implicit user answers), E2E Monitoring (Azure Monitor + Application Insights health checks, automatic GitHub issue creation), enhanced test coverage (21 service builder tests, integration tests, E2E monitoring workflow) |
| **v2.8 — UX & Insights** | Done | Sample diagrams for onboarding (4 pre-built AWS/GCP examples), WAF Best Practices Linter (5 pillars, 15+ rules), Cost Optimization recommendations (7 categories, RI/Spot/tiering), NPS & Feedback collection (surveys, feature ratings, bug reports), share links (24h TTL), question progress bar, Feedback Widget UI, 438 unit tests |
| **v2.9 — Enterprise Security** | Done | Azure AD B2C authentication, GitHub OAuth, User tiers (Free/Pro/Enterprise), Usage quotas, Lead capture, Migration runbook generator (7 phases), Architecture versioning with restore, Terraform plan preview, Application analytics, Azure Monitor alerts & workbook |
| **v2.10 — AI Assistant & Roadmap** | Done | GPT-4o AI Assistant (natural language, context-aware), Product Roadmap UI (timeline from Day 0), Feature request system (GitHub integration), Bug report system (GitHub integration), Buy Me a Coffee support link |
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
