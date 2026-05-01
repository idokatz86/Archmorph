# Archmorph — Cloud Architecture Translator to Azure
## Product Requirements Document (PRD)
**Version:** 4.1.0
**Date:** April 28, 2026
**Author:** Ido Katz

---

## 1. Executive Summary

Archmorph is an AI-assisted cloud migration workbench in preview/stabilization. Its live product path converts uploaded AWS/GCP architecture diagrams into Azure migration artifacts: detected services, confidence-scored mappings, guided migration questions, IaC drafts, HLD/report exports, and cost estimates. The application is 100% free for customers: no subscriptions, paid tiers, billing setup, or hidden fees are required. The platform codebase also contains beta and scaffolded enterprise modules for collaboration, replay, gallery, RAG/Agent PaaS, Terraform state import, scanner, deploy, SSO/SCIM, and drift.

The PRD distinguishes three maturity levels. **Live** features are usable in the core flow and should remain protected by CI. **Beta** features are implemented but need production validation, UX hardening, or broader tests. **Scaffold** features have routes, UI, or models present but must not be described as production-ready until cloud/provider execution is verified.

**Problem:** Organizations migrating to Azure spend weeks manually mapping source architecture to Azure services. This process is error-prone, requires deep multi-cloud expertise, and lacks tooling for interactive refinement.

**Solution:** Keep the core migration workflow fast, free, and reviewable: upload or select a sample diagram, analyze it with Azure OpenAI, map services against the catalog, capture migration constraints, generate IaC/HLD/cost artifacts, and export a package for human review. Enterprise modules continue behind explicit beta/scaffold labeling until scanner, deploy, SSO/SCIM, and drift paths meet production gates.

### 1.1 Capability Maturity

| Maturity | Capabilities |
|----------|--------------|
| Live | Diagram upload, sample playground, service mapping, guided questions, IaC/HLD/report export, cost estimates, service catalog, admin analytics, auth shell, API versioning, CI/security gates |
| Beta | RAG, Agent PaaS proof, cost/token observability, collaboration, migration gallery, migration replay, Terraform state import, multi-cloud cost comparison, social auth/RBAC |
| Scaffold | Live cloud scanner, credential vault, deploy engine, SSO/SAML/SCIM production validation |
| Beta/Hardening | Living architecture/drift baselines, admin release gates, release evidence, dependency/security remediation workflow |
| Planned | VS Code extension, PR-based IaC workflows, multi-diagram projects |

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
- **Supported formats:** PNG, JPG, SVG, PDF, Draw.io (.drawio), Lucidchart export, **Visio (.vsdx)**
- **Visio (.vsdx) import:** Open XML parser extracts shapes, connections, page metadata, and cloud service identification
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
- **CloudFormation (YAML):** AWS-native IaC with VPC, subnet, IGW scaffolding and Secrets Manager integration
- **Scope:** Greenfield deployments only
- **Import blocks:** Phase 4 feature for existing resource adoption
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

### 3.25 HLD Document Export (v2.11.1)
- **Multi-format export** — download HLD documents as Word (.docx), PDF, or PowerPoint (.pptx)
- **Branded formatting** — consistent Archmorph branding with green (#22C55E) accent color across all formats
- **Word export:** python-docx with styled headings, tables, bullet lists, and section numbering
- **PDF export:** fpdf2 with custom ArchmorphPDF class, Unicode sanitization (Latin-1 safe), TOC, branded header/footer
- **PowerPoint export:** python-pptx with slide-per-section layout, title slides, content slides with bullet points
- **Diagram embedding** — optional base64-encoded architecture diagram embedded in exports
- **Section coverage:** Executive Summary, Architecture Overview, Services, Networking, Security, Data, CAF, FinOps, WAF Assessment, Migration, Risks, Next Steps
- **Filename convention:** `archmorph-{project-title}.{ext}` with slug-safe naming
- **Base64 response:** Export returned as base64-encoded content with filename and MIME type for frontend download
- **27 unit tests** covering all 3 export formats, edge cases, dispatcher, and diagram inclusion

### 3.26 Modular Router Architecture (v2.12.0)
- **main.py decomposition** — reduced from 2,189 lines to 181 lines (app factory + middleware registration)
- **60 FastAPI router modules** under `backend/routers/`, grouped by domain routes, API versioning, auth/RBAC, analytics, RAG/Agent PaaS, imports, collaboration, scanner/deploy scaffolds, and operational APIs
- **Clean separation of concerns** — each router owns its own endpoints, dependencies, and error handling
- **Frontend decomposition** — DiagramTranslator.jsx split from 1,201 lines into 9 sub-components with useReducer state machine
- **Structured JSON logging** — `logging_config.py` with CorrelationIdMiddleware for request tracing
- **OTel observability rewrite** — consolidated 3 overlapping metrics systems into real OpenTelemetry SDK integration

### 3.27 API Versioning (v2.12.0)
- **v1 prefix mirror** — all `/api/*` routes automatically mirrored at `/api/v1/*`
- **Middleware-based** — transparent routing via `api_versioning.py` middleware
- **Backward compatible** — existing `/api/*` routes continue to work unchanged
- **Future-proof** — infrastructure in place for v2 breaking changes without disrupting v1 consumers

### 3.28 Feature Flags System (v2.12.0)
- **Percentage rollout** — gradually enable features for a percentage of users
- **User targeting** — enable/disable features for specific users or user segments
- **Admin API** — `GET /api/flags`, `GET /api/flags/{name}`, `PUT /api/flags/{name}`
- **In-process evaluation** — zero-latency flag checks with in-memory state
- **Configurable defaults** — flags can be enabled/disabled globally with override rules

### 3.29 Comprehensive Audit Logging (v2.12.0)
- **Structured JSON logs** — machine-parseable audit trail for all security-relevant actions
- **Risk levels** — each audit event tagged with risk level (Low, Medium, High, Critical)
- **Alerting rules** — configurable rules for triggering alerts on high-risk events
- **Compliance queries** — pre-built queries for SOC2, ISO 27001, and GDPR audit evidence
- **Searchable** — admin API for querying audit events by time range, risk level, actor, and action

### 3.30 Session Persistence (v2.12.0)
- **SessionStore abstraction** — pluggable interface for session storage backends
- **InMemory backend** — default for development and single-instance deployments
- **Redis backend** — production-ready adapter for Azure Cache for Redis
- **TTL management** — automatic session expiration with configurable TTL
- **Backward compatible** — transparent replacement of previous in-memory-only session handling

### 3.31 GPT Response Caching (v2.12.0)
- **Content-hash TTLCache** — cache GPT-4o responses by hashing input content
- **Configurable TTL** — tunable cache duration (default: 1 hour)
- **Cost reduction** — eliminates redundant GPT-4o API calls for identical inputs
- **Azure pricing cache** — pricing data persisted to Blob Storage with TTL for cross-instance sharing

### 3.32 Zero Trust WAF (v2.12.0)
- **Azure Front Door Premium** — global load balancer with WAF integration
- **OWASP CRS 3.2** — Core Rule Set for web application protection
- **Zero Trust network** — Container Apps locked down to Front Door origin only
- **Terraform config** — full infrastructure-as-code for WAF policies, rules, and Front Door profiles

### 3.33 Multi-Cloud Target Support (v3.0.0)
- **Parameterized target provider** — vision_analyzer and IaC generator support aws, azure, and gcp as target
- **Dynamic mapping resolution** — `_MAPPING_INDEX` resolves source→target mappings for any provider pair
- **Backward compatible** — `azure_service` field preserved alongside new `target_service` + `target_provider` fields
- **120+ cross-cloud mappings** — tri-directional: AWS↔Azure, GCP↔Azure, GCP↔AWS
- **Frontend target badge** — dynamic provider badge in AnalysisResults based on target_provider
- **CloudFormation IaC** — AWS-specific prompt engineering with Secrets Manager, IAM, valid regions

### 3.34 User Dashboard (v3.0.0)
- **Analysis history** — paginated list of past analyses with provider badges and bookmarking
- **Stat cards** — 6 metrics: total analyses, success rate, services mapped, IaC generated, bookmarks, average confidence
- **Provider filter** — filter analysis history by source cloud provider
- **Bookmarks** — save/unsave analyses for quick access
- **Navigation integration** — dedicated Dashboard tab in the navbar

### 3.35 Template Gallery (v3.0.0)
- **10 architecture patterns** — 3-tier-web, serverless-api, microservices-k8s, data-pipeline, ml-platform, static-site-cdn, event-driven-saga, multi-region-ha, iot-platform, gcp-web-app
- **8 categories** — Web, API, Microservices, Data, AI/ML, Static, Event-Driven, IoT
- **Search & filter** — category buttons and text search across template names, descriptions, services
- **Difficulty badges** — Beginner, Intermediate, Advanced with color coding
- **Use template** — one-click navigation to translator with pre-populated services
- **Template API** — `GET /templates` (with category/source_provider filters), `GET /templates/{template_id}`

### 3.36 Internationalization (v3.0.0)
- **react-i18next** — lazy-loaded translations with HTTP backend and browser language detection
- **3 locales** — English (en), Spanish (es), French (fr)
- **70+ translation keys** — nav, landing, dashboard, translator, templates, common, footer sections
- **Language selector** — globe dropdown in navbar with instant language switching
- **LocalStorage persistence** — selected language remembered across sessions
- **Extensible** — add new locales by dropping a JSON file in `/locales/{lng}/translation.json`

### 3.37 Living Architecture Engine (v3.0.0)
- **Health scoring** — 5 weighted dimensions: Availability (25%), Cost Efficiency (20%), Compliance (20%), Performance (20%), Security (15%)
- **Status classification** — healthy (≥80), warning (≥60), critical (<60) per dimension and overall
- **Drift detection** — identifies configuration drift, missing tags, version skew, network exposure, unencrypted resources
- **Drift baselines** — `/api/drift/baselines` stores intended-state snapshots, repeat compare history, deterministic finding IDs, accepted/rejected/deferred decisions, and Markdown report export
- **Cost anomaly alerts** — detects deviation from expected daily spend with percentage thresholds
- **Recommendations** — actionable remediation suggestions per drift/anomaly finding
- **Registration API** — `POST /living-architecture/register` to onboard an architecture for monitoring
- **5 API endpoints** — register, health, drifts, cost-anomalies, registered list

### 3.38 Migration Intelligence (v3.0.0)
- **Anonymous event pipeline** — records anonymized migration events (service pair + success boolean + confidence)
- **Community confidence scoring** — blends base mapping confidence (60%) with community success rate (30%) and volume factor (10%)
- **18 seed patterns** — pre-populated with realistic migration data (AWS→Azure and GCP→Azure)
- **Pattern library** — ranked list of migration pathways with success rates and trending indicators
- **Trending migrations** — identifies patterns with >1000 community migrations
- **5 API endpoints** — submit events, list patterns, query confidence, trending, aggregate stats
- **Privacy-first** — no PII, no diagram content stored; only service names, providers, and outcomes

### 3.39 White-Label SDK (v3.0.0)
- **Config-driven branding** — product name, tagline, logo, favicon, color palette (7 tokens), font families (3 slots)
- **Feature flags per partner** — toggle powered-by badge, community patterns, template gallery, IaC generation, exports
- **Upload quotas** — configurable max_uploads_per_day per partner
- **Partner API key management** — `am_wl_` prefixed keys with `X-Partner-Key` header authentication
- **Embeddable widget** — auto-generated iframe snippet with configurable dimensions and allowed origins
- **Public config endpoint** — `GET /whitelabel/config/{partner_id}` for frontend startup (no auth required)
- **6 API endpoints** — register partner, get config, update branding, get embed snippet, list partners, default config

### 3.40 Multi-Tenant Foundation (v3.0.0)
- **Alembic migration 002** — 5 new tables: organizations, team_members, invitations, user_analyses, saved_diagrams
- **Organization model** — slug, display_name, free access profile, owner relationship
- **Team members** — role-based (admin/member/viewer) with invitation workflow
- **User analysis history** — per-user tracking with source/target provider, service count, confidence scores
- **Saved diagrams** — user bookmarks with diagram_data JSON storage

### 3.41 Error Envelope Middleware (v3.0.1)
- **Structured error responses** — all API errors wrapped in consistent JSON envelope with correlation IDs
- **Error categories** — validation, authentication, authorization, not_found, rate_limit, internal
- **Correlation ID propagation** — unique request ID in every response header and error body for debugging
- **Client-friendly messages** — user-facing messages separated from technical details

### 3.42 Compliance Mapper (v3.0.1)
- **4 framework support** — GDPR, HIPAA, SOC2, PCI DSS compliance mapping
- **Azure service alignment** — maps detected architecture services to compliance requirements
- **Gap analysis** — identifies missing compliance controls in the architecture
- **Remediation suggestions** — actionable recommendations for each compliance gap

### 3.43 AI-Powered Service Suggestions (v3.0.1)
- **Context-aware recommendations** — GPT-4o suggests additional Azure services based on architecture patterns
- **Pattern detection** — identifies common architecture patterns and suggests missing components
- **Confidence scoring** — each suggestion includes relevance confidence
- **Fuzzy Azure service matching** — maps suggestions to canonical service catalog entries

### 3.53 Interactive Architecture Map (v3.9.0)
- **Dagre auto-layout** — automatic top-to-bottom hierarchical layout via dagre.js with compound graph support for zone grouping
- **Confidence rings** — SVG circular progress indicators per node showing mapping confidence (green ≥85%, amber ≥60%, red <60%)
- **Effort badges** — Low/Medium/High migration effort indicators with color-coded backgrounds
- **Typed edges** — 6 connection styles: Traffic (blue solid), Database (green solid), Auth (purple dashed), Control (grey dashed), Security (orange dotted), Storage (teal solid)
- **Zone grouping** — Services grouped into architectural zones (Hub, Spokes) with dashed-border containers and floating labels
- **Manual mapping nodes** — Red dashed nodes with AlertTriangle icon for unmapped services requiring manual review
- **Map legend** — Collapsible overlay explaining node types, edge styles, and confidence levels
- **MiniMap** — React Flow minimap with node-type color coding (green=mapped, red=manual, transparent=group)
- **Full interactivity** — Pan, zoom, drag via `useNodesState`/`useEdgesState` hooks inside `ReactFlowProvider`
- **NaN position guards** — All dagre-computed positions validated with `Number.isFinite()` to prevent SVG attribute errors

### 3.54 Email Notifications (v3.9.0)
- **Azure Communication Services** — Branded HTML email delivery for migration report notifications
- **Email validation** — Server-side email format validation with rate limiting
- **Notify endpoint** — `POST /api/diagrams/{id}/notify-email` triggers formatted email with analysis summary

### 3.55 GPT-4.1 Model Upgrade (v3.9.0)
- **Primary model** — Azure OpenAI `gpt-4.1` (2025-04-14) with 32K max output tokens
- **Fallback model** — Automatic fallback to `gpt-4o` on rate limits, timeouts, or connection errors
- **API version** — Updated to `2025-04-01-preview`
- **Cached chat completion** — All AI calls routed through `cached_chat_completion` with bypass option and specific exception handling

### 3.56 IaC Diff Highlighting (v3.9.0)
- **Previous code tracking** — Frontend stores previous IaC generation for comparison
- **Line-level diff** — Changed lines highlighted with green tint and left border marker
- **Visual feedback** — Users can see exactly what changed after IaC chat modifications or regeneration

### 3.44 API Client Rewrite (v3.0.2)
- **Retry with exponential backoff** — automatic retry for transient failures (429, 500, 502, 503)
- **AbortController-based timeouts** — configurable per-request timeouts with cleanup
- **User-friendly error messages** — HTTP status codes mapped to human-readable messages
- **Centralized error handling** — all API calls go through single client with consistent behavior

### 3.45 IaC Security Scanning (v3.0.2)
- **8-rule security scanner** — checks generated IaC for common security issues
- **Rule categories** — hardcoded passwords, missing encryption, overly permissive access, missing tags, public endpoints, missing logging, default credentials, unencrypted storage
- **Inline warnings** — security issues flagged as comments in generated code
- **Integration** — runs automatically during IaC validation step

### 3.46 Vision Analysis Cache (v3.0.2)
- **TTLCache layer** — caches GPT-4o vision analysis results by content hash
- **Configurable TTL** — tunable cache duration (default: 1 hour)
- **Cost reduction** — prevents duplicate API calls for re-analyzed diagrams
- **Truncation detection** — detects when GPT-4o output is truncated (finish_reason=length)

### 3.47 Inter-Question Constraint System (v3.0.0 / v3.0.3)
- **QUESTION_CONSTRAINTS mapping** — compliance and data residency answers filter available deploy regions
- **REGION_GROUPS** — geographic groupings (EU, US, APAC) for constraint resolution
- **Real-time filtering** — frontend applies constraints dynamically as users answer questions
- **Auto-clear invalid selections** — previously selected options that violate new constraints are cleared
- **Constraint badges** — amber badges explain why certain options are restricted

### 3.48 Confidence Transparency (v3.2.0)
- **Confidence explanations** — each confidence score includes a human-readable explanation of why that level was assigned
- **Visual confidence badges** — color-coded badges (green/yellow/orange/red) with tooltips
- **Factor breakdown** — shows mapping strength, community data, fuzzy match quality contributing to score
- **Recalculation on answers** — confidence explanations update after guided question answers are applied

### 3.49 Toast Notification System (v3.4.0)
- **Global ToastProvider** — React Context-based notification system wrapped around entire app
- **useToast() hook** — returns `{success, error, info, dismiss}` functions for any component
- **Auto-dismiss** — 5s default, 8s for errors, max 5 visible simultaneously
- **Accessibility** — `aria-live="polite"`, `role="alert"` per toast, dismiss button with `aria-label`
- **Slide-in animation** — CSS `@keyframes slideInRight` for smooth entry

### 3.50 Browser Close Protection (v3.4.0)
- **useBeforeUnload hook** — warns users before closing browser tab during active work
- **Conditional activation** — only triggers when user has active analysis (step !== 'upload' && diagramId exists)
- **Standard browser dialog** — uses native `beforeunload` event for consistent UX across browsers

### 3.51 Accessibility Improvements (v3.4.0)
- **ARIA labels** — icon-only buttons throughout the app now have descriptive `aria-label` attributes
- **Keyboard navigation** — footer version easter egg accessible via Enter/Space keys with `role="button"` and `tabIndex`
- **ARIA pressed state** — ServicesBrowser view toggle buttons expose selected state via `aria-pressed`
- **Role groups** — related controls wrapped in `role="group"` with `aria-label` for screen readers
- **Components fixed** — ServicesBrowser, CompliancePanel, FeedbackWidget, Nav, App footer

### 3.52 Performance Optimizations (v3.4.0)
- **Gunicorn process manager** — Dockerfile switched from uvicorn to gunicorn with UvicornWorker, `--max-requests 1000` for worker recycling, `--preload` for memory efficiency
- **asyncio.to_thread** — CPU-bound handlers (`analyze_architecture()`, `analyze_cost_optimizations()`, `get_quick_wins()`) offloaded from event loop
- **Speculative parallel analysis** — `classify_image()` and `analyze_image()` fire simultaneously via `asyncio.gather()`, classification gates result usage; saves 10–30s per upload
- **Pre-commit hooks** — `.pre-commit-config.yaml` with ruff (lint+format), eslint, prettier, and file hygiene hooks

### 3.15 Security Hardening (v2.6 + v2.11.1)
- **Security headers middleware** — X-Content-Type-Options, X-Frame-Options, Referrer-Policy, HSTS, Permissions-Policy
- **Timing-safe key comparison** — `secrets.compare_digest()` for API key and admin key verification
- **No default admin secret** — `ARCHMORPH_ADMIN_KEY` must be set via environment variable (503 if unset)
- **Restricted CORS** — explicit method and header allowlists instead of wildcards
- **ZIP slip prevention** — path traversal entries (`../`, absolute paths) rejected during icon pack ingestion
- **XSS protection** — SVG sanitizer blocks `javascript:`, `vbscript:` URIs and dangerous CSS (`expression()`, `-moz-binding`, `url()`)
- **Error sanitization** — internal exception details no longer leaked to API responses
- **Dependabot** — automated dependency updates for pip, npm, Docker, GitHub Actions, and Terraform
- **CI hardening** — `npm audit` failures no longer silently ignored
- **SAST scanning** (v2.11.1) — Semgrep static analysis with OWASP Top 10, security-audit, and Python rulesets
- **Secret detection** (v2.11.1) — Gitleaks full-history scanning on every push/PR
- **Container scanning** (v2.11.1) — Trivy vulnerability scan (CRITICAL/HIGH) on every deployment
- **SBOM generation** (v2.11.1) — CycloneDX Bill of Materials for Python and npm dependencies (90-day retention)

### 3.16 User Authentication & Usage Safeguards (v2.9)
- **Azure AD B2C** — Enterprise SSO with JWT validation, JWKS caching, user persistence
- **GitHub OAuth** — Developer-friendly authentication with email access
- **Anonymous users** — IP-based tracking with abuse-prevention limits
- **Free customer access** — no paid tiers, subscription gates, billing setup, or customer payment required
- **Usage safeguards** — Real-time usage tracking for fair use, abuse prevention, and capacity planning
- **Session management** — Secure session tokens with TTL-based expiration
- **Lead capture** — Optional email capture for follow-up and feedback, not paid unlocks
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
| Admin | Manage team, API keys, service updates, and admin dashboard access |

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
| Data retention | 90 days by default, configurable for enterprise deployments | v1.0 |
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
| Frontend | React 19.2, Vite 8.0, TailwindCSS 4.2, Lucide React (icons), Prism.js (syntax highlighting), react-i18next (i18n) |
| Backend | Python 3.12, FastAPI, Gunicorn (UvicornWorker) |
| AI | Azure OpenAI GPT-4.1 (deployment `gpt-4.1`, model 2025-04-14) with GPT-4o fallback |
| Database | PostgreSQL (Azure Flexible Server) |
| Storage | Azure Blob Storage |
| Hosting | Azure Container Apps (API + MCP gateway), Static Web Apps (frontend) |
| Container Registry | Single Azure Container Registry (`archmorphacm7pd`, Basic, West Europe). Legacy East US `cafd43cfd4deacr` retired May 2026 — see [CHANGELOG](../CHANGELOG.md). |
| Scheduler | APScheduler 3.10 (CronTrigger, daily service sync + auto-add) |
| Guided Questions | In-process engine (32 questions, 8 categories) |
| Diagram Export | In-process engine (Excalidraw, Draw.io, Visio with 36 Azure stencils + 405-icon registry fallback) |
| Pricing | Azure Retail Prices API with 30-day disk cache (134 service entries, 56 aliases, targeted queries) |
| IaC | Terraform (infra), Bicep + CloudFormation support in-app |
| Testing | pytest (1554 backend tests), Vitest (262 frontend tests), Playwright smoke (17 browser tests), integration tests, contract tests, chaos tests, coverage gap tests, middleware tests, pre-commit hooks (ruff, eslint, prettier) |
| Best Practices | In-process WAF linter (5 pillars, 15+ rules, quick wins, pillar scores) |
| Cost Optimizer | In-process engine (7 categories, RI/Spot/tiering/auto-shutdown recommendations) |
| Feedback | In-process NPS/feature/bug collection (30-day trend, admin dashboard) |
| HLD Generator | In-process GPT-4o engine (60+ Azure doc links, 13-section HLD, markdown converter) |
| IaC Chat | In-process GPT-4o assistant (session management, code modification, context-aware) |
| Icon Registry | In-process engine (405 icons, Draw.io/Excalidraw/Visio library builders, SVG sanitization, thread-safe, persistent) |
| Security | JWT admin auth (HS256, 1h TTL), security headers, timing-safe auth, Dependabot, defusedxml, ZIP slip protection, Semgrep SAST, Gitleaks, Trivy, CycloneDX SBOM, Azure Front Door WAF (OWASP CRS 3.2), Zero Trust networking, comprehensive audit logging |
| Feature Flags | In-process engine (percentage rollout, user targeting, admin API) |
| Session Store | Pluggable backends (InMemory default, Redis for production) |
| GPT Response Cache | Content-hash TTLCache for GPT-4o responses, Blob Storage pricing cache |
| API Versioning | Middleware-based v1 prefix mirror for all routes |
| Router Architecture | 60 FastAPI router modules (main.py as app factory/middleware registration) |
| NL Service Builder | In-process GPT-4o engine (fuzzy Azure service matching, alias support, confidence scoring) |
| Smart Question Dedup | In-process engine (implicit answer detection, smart defaults from analysis) |
| E2E Monitoring | GitHub Actions workflow (Azure Monitor + App Insights health checks, auto GitHub issue creation) |
| Living Architecture | In-process engine (saved drift baselines, compare history, finding decisions, Markdown reports; live scanner validation still gated) |
| Migration Intelligence | In-process engine (anonymous event pipeline, community confidence scoring, 18 seed patterns, trending analysis) |
| White-Label SDK | In-process engine (config-driven branding, partner API keys, embeddable widgets, 7 color tokens) |
| Authentication | In-process (Azure AD B2C JWT validation, GitHub OAuth, session tokens, usage quotas) |
| Migration Runbook | In-process generator (7 phases, task templates, risk assessment, Markdown export) |
| Architecture Versioning | In-memory store (change detection, version comparison, restore, 7-day TTL) |
| Terraform Preview | In-process HCL parser (resource extraction, syntax validation, plan simulation) |
| Application Analytics | Persistent metrics via Azure Blob Storage (background flush, crash-safe shutdown, event tracking, sessions, funnels) |
| Azure Monitoring | Application Insights + Azure Monitor (alerts, workbooks, Log Analytics queries) |

### 8.2 API Endpoints (200+ total, including v1 mirrored routes)

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
| `/api/diagrams/{id}/export-hld` | POST | Export HLD as DOCX, PDF, or PPTX (v2.11.1) |
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
| `/api/dashboard/stats` | GET | User dashboard aggregate statistics (v3.0) |
| `/api/dashboard/analyses` | GET | Paginated analysis history with filters (v3.0) |
| `/api/dashboard/analyses/{id}` | GET | Single analysis detail (v3.0) |
| `/api/dashboard/analyses/{id}/save` | POST | Bookmark an analysis (v3.0) |
| `/api/dashboard/analyses/{id}/save` | DELETE | Remove bookmark (v3.0) |
| `/api/templates` | GET | List architecture templates with category/provider filters (v3.0) |
| `/api/templates/{id}` | GET | Get template details by ID (v3.0) |
| `/api/living-architecture/register` | POST | Register architecture for health monitoring (v3.0) |
| `/api/living-architecture/{id}/health` | GET | Get architecture health scores (v3.0) |
| `/api/living-architecture/{id}/drifts` | GET | Get drift detection findings (v3.0) |
| `/api/living-architecture/{id}/cost-anomalies` | GET | Get cost anomaly alerts (v3.0) |
| `/api/living-architecture/registered` | GET | List registered architectures (v3.0) |
| `/api/drift/detect` | POST | Run one-off environmental drift detection |
| `/api/drift/baselines` | POST | Create a drift baseline with optional first compare |
| `/api/drift/baselines` | GET | List drift baselines with latest audit summary |
| `/api/drift/baselines/{id}` | GET | Get a drift baseline, history, and last result |
| `/api/drift/baselines/{id}/compare` | POST | Compare live state against a saved baseline |
| `/api/drift/baselines/{id}/findings/{finding_id}` | PATCH | Accept, reject, defer, or reopen a finding |
| `/api/drift/baselines/{id}/report` | GET | Export latest drift audit as Markdown |
| `/api/migration-intelligence/events` | POST | Submit anonymized migration event (v3.0) |
| `/api/migration-intelligence/patterns` | GET | Get top migration patterns (v3.0) |
| `/api/migration-intelligence/confidence` | GET | Query community confidence for a service pair (v3.0) |
| `/api/migration-intelligence/trending` | GET | Get trending migration patterns (v3.0) |
| `/api/migration-intelligence/stats` | GET | Aggregate migration intelligence stats (v3.0) |
| `/api/whitelabel/partners` | POST | Register white-label partner (v3.0) |
| `/api/whitelabel/partners` | GET | List registered partners (v3.0) |
| `/api/whitelabel/config/{id}` | GET | Get partner branding config (v3.0) |
| `/api/whitelabel/branding` | PUT | Update partner branding (v3.0) |
| `/api/whitelabel/embed-snippet/{id}` | GET | Get embeddable widget snippet (v3.0) |
| `/api/whitelabel/default-config` | GET | Get default Archmorph branding (v3.0) |

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
| **v2.0 — Foundation** | Done | Guided questions (32 across 8 categories), diagram export (Excalidraw/Draw.io/Visio with stencils), daily auto-updating service catalog (APScheduler), 405-service catalog, secure IaC credentials, design system UI with Lucide icons, chatbot assistant, admin dashboard |
| **v2.1 — Pricing & Polish** | Done | Dynamic Azure pricing via Retail Prices API, deployment region question, region-aware cost estimates, monthly pricing cache, SKU strategy multipliers |
| **v2.2 — Self-Updating Catalog** | Done | Auto-integration of new services into catalog files, fuzzy name matching, category auto-classification (55 keyword hints), dry-run CLI mode, cumulative auto-added tracking |
| **v2.3 — Real Pricing & GCP Validation** | Done | Real Azure pricing (134 entries + 56 aliases), 6-step price resolution, optimized targeted API queries, session key fix, full GCP → Azure E2E validation (5 diagrams, 50/50 steps pass), 184 unit tests |
| **v2.4 — HLD, IaC Chat & Confidence** | Done | AI-powered HLD generation (13 sections, 60+ doc links, WAF assessment, migration phases), IaC Chat assistant (GPT-4o, session-based, quick actions), confidence engine (70+ GCP synonyms, fuzzy matching ≥65%, confidence blending 70/30, recalculation), service connections extraction, 257 unit tests, 65 E2E steps |
| **v2.5 — Audit & Quality** | Done | 34 audit improvements, comprehensive test coverage (290 → 348 tests) |
| **v2.6 — Icon Registry & Security** | Done | Icon Registry (405 icons, 3 library formats, SVG sanitization, thread-safe, persistent, auto-load), security hardening (timing-safe auth, security headers, ZIP slip protection, XSS prevention, Dependabot), diagram export bridge to registry |
| **v2.7 — NL Builder & Monitoring** | Done | Natural Language Service Builder (add Azure services via text after diagram analysis), Smart Question Deduplication (filters questions based on implicit user answers), E2E Monitoring (Azure Monitor + Application Insights health checks, automatic GitHub issue creation), enhanced test coverage (21 service builder tests, integration tests, E2E monitoring workflow) |
| **v2.8 — UX & Insights** | Done | Sample diagrams for onboarding (4 pre-built AWS/GCP examples), WAF Best Practices Linter (5 pillars, 15+ rules), Cost Optimization recommendations (7 categories, RI/Spot/tiering), NPS & Feedback collection (surveys, feature ratings, bug reports), share links (24h TTL), question progress bar, Feedback Widget UI, 438 unit tests |
| **v2.9 — Enterprise Security** | Done | Azure AD B2C authentication, GitHub OAuth, free customer access safeguards, Lead capture, Migration runbook generator (7 phases), Architecture versioning with restore, Terraform plan preview, Application analytics, Azure Monitor alerts & workbook |
| **v2.10 — AI Assistant & Roadmap** | Done | GPT-4o AI Assistant (natural language, context-aware), Product Roadmap UI (timeline from Day 0), Feature request system (GitHub integration), Bug report system (GitHub integration), Buy Me a Coffee support link |
| **v2.11.0 — Admin & Analytics** | Done | JWT admin auth (HS256, 1h TTL, in-memory revocation), persistent analytics (Azure Blob Storage with background flush), conversion funnel, security headers middleware |
| **v2.11.1 — UX Polish & Document Export** | Done | HLD export (DOCX/PDF/PPTX), 15 UX improvements, CI/CD security (Semgrep SAST, Gitleaks secret detection, Trivy container scan, CycloneDX SBOM), Python 3.11+3.12 matrix testing, 747 tests in 30 files across 82 endpoints |
| **v2.12.0 — Modular Architecture & Security** | Done | Router decomposition (main.py 2,189→181 lines, 13 router modules), API versioning (v1 prefix), feature flags system (% rollout + user targeting), comprehensive audit logging (risk levels, alerting rules, compliance queries), session persistence (InMemory/Redis), GPT-4o response caching (content-hash TTLCache), DiagramTranslator decomposed (1,201→ 9 sub-components with useReducer), structured JSON logging with correlation IDs, OTel observability rewrite, Azure Front Door WAF + Zero Trust, Helm charts for self-hosted K8s, blue-green deployment with instant rollback, SBOM (CycloneDX + Grype), SAST/DAST/SCA pipeline (Semgrep, Bandit, CodeQL, Trivy, Gitleaks), storage RBAC auth (DefaultAzureCredential), pricing cache persisted to Blob Storage, monitoring reduced to hourly, "None" alerting option, service_updater JSON output, 1149 tests (contract 56, chaos 26, coverage 46, middleware 55) in 35+ files |
| **v3.0.0 — Multi-Cloud & Enterprise** | Done | Multi-cloud target support (AWS/GCP/Azure as target), CloudFormation IaC generation, User Dashboard (stats, history, bookmarks), Template Gallery (10 patterns, 8 categories), Visio (.vsdx) import with Open XML parser, i18n (en/es/fr with react-i18next), Living Architecture engine (health scoring, drift detection, cost anomalies), Migration Intelligence (community confidence, pattern library, trending), White-Label SDK (branding, partner API keys, embeddable widgets), multi-tenant foundation (organizations, teams, invitations), inter-question constraint system, enhanced PR template with DoD checklist |
| **v3.0.1 — Sprint 1: Production Critical** | Done | Error envelope middleware with correlation IDs, Visio import parser, white-label theming engine, session restore & UX improvements, API versioning with /v1/ prefix, best-practice validation engine, cost optimizer engine, migration assessment & risk scoring, compliance mapper (GDPR/HIPAA/SOC2/PCI DSS), living architecture health monitoring, AI-powered service suggestions |
| **v3.0.2 — Sprint 2: Reliability & DX** | Done | API client rewrite with retry/backoff/timeout, user-friendly error messages, configurable OpenAI timeout & fallback model, GPT output truncation detection, vision analysis cache (TTLCache), IaC security scanning (8 rules), session cache for IaC/HLD persistence, session expiry countdown warning, cancel analysis button, error clearing on new file, mobile responsive buttons, Docker Compose (PostgreSQL 16 + Redis 7), configurable user cache TTL |
| **v3.0.3 — Sprint 3: Advanced Features** | Done | Azure/GCP services pagination fix, prompt guard for IaC chat, migration runbook generator, CloudFormation IaC format, Terraform plan preview, architecture versioning with diff, migration intelligence with community data, infrastructure import from live cloud, organization & team management, journey analytics, dependency graph visualization, risk score & compliance panels, URL hash sync, feature flags system, admin dashboard with analytics |
| **v3.1.0 — Landing Page Redesign** | Done | Landing page redesign with feature cards, stats bar, updated FAQs, and preview-friendly messaging |
| **v3.2.0 — Confidence Transparency** | Done | Confidence score transparency with human-readable explanations, visual confidence badges, tooltip explanations, critical stabilization fixes (HLD 404, memory leaks, CORS, version sync) |
| **v3.3.0 — Stabilization & Quality** | Done | 13 stability issues closed, DiagramTranslator lazy-loaded, ChatWidget migrated to apiClient, dead components removed, HLD export fixed, SSE deduplication, AbortController cleanup, session leak prevention |
| **v3.4.0 — Performance & Accessibility** | Done | Gunicorn process manager with worker recycling, asyncio.to_thread for CPU-bound handlers, speculative parallel classify+analyze (saves 10-30s), toast notification system, beforeunload guard, accessibility fixes (ARIA labels, keyboard nav), pre-commit hooks (ruff, eslint, prettier), roadmap data updated, dead code removed |
| **v3.5.0 — Developer Experience** | Planned | Service dependency graph visualization, cost estimate drill-down, full analysis PDF report, CLI tool for automation, split diagrams.py god router, code coverage gate, Template Gallery re-enable |
| **v3.6.0 — Intelligence & Identity** | Planned | Redis-backed session persistence, AI cross-cloud mapping auto-suggestion, migration timeline generator, social authentication (Microsoft, Google, GitHub), user profiles with persistent history |
| **v3.8.0 — Complete Migration Flow** | Done | Migration package ZIP export (IaC + HLD + costs), before/after architecture visualization, guided onboarding tour, CI coverage gate (60%), stale bot, migration Q&A chat advisor |
| **v3.8.1 — UX Polish & Bug Bash** | Done | Fix HLD generation 500 crashes, recover missing Map layers, unblock IaC dynamic modifications, populate Coming Soon tab, and Drift Alpha warnings |
| **v3.9.0 — AI Upgrade & Architecture Map** | Done | GPT-4.1 with 32K output tokens, interactive Architecture Map (dagre layout, confidence rings, effort badges, typed edges, zone grouping, MiniMap), email notifications via Azure Communication Services, IaC diff highlighting, parallel IaC+HLD generation, limitations UX redesign, Deploy/Drift Coming Soon overlays |
| **v4.0 — Platform Maturity** | Mixed | RAG, Agent PaaS proof, cost/token observability, AI mapping suggestions, migration timeline, service dependency graph, social auth, user profiles, RBAC/multi-tenant, PDF report export, and DevOps modernization are implemented/beta. Scanner/deploy paths remain hardening work. |
| **v4.1 — Release Hardening** | Mixed | Drift baselines, admin release gate, post-deploy smoke, dependency/security remediation, release evidence, and warning cleanup are implemented. Live scanner/deploy execution and SSO/SCIM tenant validation remain scaffolded/operator-gated. Customer billing is not part of the release path. |

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

| Item | Decision | Owner | Priority | Issue |
|------|----------|-------|----------|-------|
| **Split diagrams.py god router** | 1,173 LOC → focused sub-routers (upload, export, IaC, HLD) | Engineering | Medium | #284 |
| **Code coverage gate in CI** | Active at `--cov-fail-under=63`; raise gradually as legacy coverage improves | Engineering | Medium | #288 |
| **Load testing** | SLA targets in performance_config.py untested; k6/Locust benchmark needed | Engineering | Medium | #290 |
| **Cyclomatic complexity gate** | 8 deeply nested functions, 5 over 100 lines; add radon/xenon | Engineering | Low | #315 |
| **Magic numbers & docstrings** | 138 missing docstrings; extract hardcoded constants | Engineering | Low | #317 |
| **Re-enable Template Gallery** | Disabled during stabilization; needs loading states and data verification | Engineering | Medium | #244 |
| **Redis-backed session persistence** | Redis/File/Memory store abstraction exists; production promotion should set `REDIS_HOST`/`REDIS_URL` plus `REQUIRE_REDIS=true` for horizontal scale | Engineering | P0 | #232 |
| **Service dependency graph** | Visualize detected service connections and data flows | Engineering | P1 | #233 |
| **Cost estimate drill-down** | Per-service configuration (instance count, storage size) for refined pricing | Engineering | P2 | #234 |
| **CLI tool for automation** | CLI for CI/CD integration and headless diagram analysis | Engineering | P2 | #235 |
| **Full analysis PDF report** | Branded PDF with mappings, diagram, IaC, cost, HLD | Engineering | P2 | #236 |
| **AI cross-cloud mapping auto-suggestion** | AI suggests Azure equivalents for newly discovered services | Engineering | P1 | #230 |
| **Migration timeline generator** | Auto-generate phased migration plan with dependencies | Engineering | P1 | #231 |
| **Social authentication** | Microsoft, Google, GitHub sign-in via OAuth | Engineering | P1 | #246 |
| **User profiles** | Personal details, preferences, avatar, persistent history | Engineering | P1 | #247 |
| **Persistent analysis history** | Analysis history tied to user accounts | Engineering | P2 | #245 |
| **RBAC & multi-tenant isolation** | Enforce role-based access control on organizational boundaries | Engineering | P1 | #238 |
| **Collaboration features** | Shared projects, comments, review workflow | Engineering | P2 | #237 |
| **Compliance framework mapping** | Auto-detect regulatory requirements, map to Azure compliance services | Engineering | P2 | #239 |
| **Pulumi & CDK IaC output** | Additional IaC formats beyond Terraform/Bicep/CloudFormation | Engineering | P2 | #242 |
| **Multi-diagram project support** | Multiple diagrams per project with unified analysis | Engineering | P2 | #241 |
| **VS Code extension** | In-editor architecture translation and IaC generation | Engineering | P2 | #240 |
| **Real infrastructure scanning** | Provider scanners are route-gated behind `live_cloud_scanner`; tenant credential validation and provider-contract tests remain before beta enablement | Engineering | P3 | #243 |
| **One-click Deploy to Azure** | Preview/preflight can run, but execute/rollback paths are gated behind `deploy_engine` and release controls | Engineering | P1 | #248 |
| **Migration risk scorecard** | Comprehensive readiness assessment with risk factors | Engineering | P1 | #249 |
| **Interactive before/after visualization** | Side-by-side source vs target architecture view | Engineering | P1 | #250 |
| **End-to-end migration wizard** | Full migration package export with step-by-step flow | Engineering | P1 | #252 |
| **AI Architecture Advisor** | Proactive optimization suggestions based on architecture patterns | Engineering | P1 | #255 |
| **Guided onboarding tour** | Interactive walkthrough with achievement badges | Engineering | P2 | #257 |
| **Contextual migration Q&A** | Chat on analysis results with migration-specific context | Engineering | P1 | #258 |
| **Real-time collaborative workspace** | Multi-user simultaneous editing of migration projects | Engineering | P2 | #251 |
| **Built-in diagram editor** | Canvas-based architecture diagram editor | Engineering | P2 | #253 |
| **Migration replay** | Animated analysis timeline for presentations | Engineering | P3 | #254 |
| **Migration Gallery** | Public anonymized success stories from community | Engineering | P2 | #256 |
| **Public API & webhooks** | Enterprise integrations (Slack, Teams, Jira) | Engineering | P2 | #259 |
| **AI Agent PaaS** | Control/Runtime design with routing/memory/policy | Engineering | P1 | #319 |
| **Live Cloud Discovery & Auto-Deploy** | End-to-end migration execution platform | Engineering | P1 | #321 |
| **GitHub Actions reliability** | Keep CI runners healthy; backend coverage, frontend lint, and frontend tests are hard gates | DevOps | High | #320 |

---

## 12. v4.1 Strategic & Technical Gaps (March 24, 2026 — Cross-Functional Review)

Identified by CEO Master + CTO Master cross-functional review with all agent hierarchy participation.

### 12.1 Strategic Gaps (CEO Review)

| # | Gap | Priority | Business Impact | Owner | SP |
|---|-----|----------|----------------|-------|----|
| S1 | Free access positioning | P0 | No production billing in current release scope; 100% free customer positioning remains explicit | CRO + Backend | 5 |
| S2 | Self-serve onboarding funnel with product analytics | P0 | No funnel metrics = blind PLG motion | PM + FE | 8 |
| S3 | Interactive demo / playground (no sign-up) | P0 | PLG requires zero-friction try-it-now | UX + FE | 5 |
| S4 | Customer testimonials / case study framework | P1 | Zero social proof for investors | CRO + PM | 3 |
| S5 | SOC 2 Type I readiness & compliance dashboard | P1 | Blocks enterprise deals | CISO + CLO | 8 |
| S6 | SSO / SAML / SCIM integration | P1 | Preview routes are feature-gated; tenant validation and signed assertion verification remain enterprise-readiness gates | CISO + Backend | 8 |
| S7 | Terraform state import / reverse engineering | P1 | "10x moat" — existing infra to diagram | CTO + Cloud | 13 |
| S8 | Public API documentation & developer portal | P1 | PLG for developers needs self-serve docs | API + PM | 5 |
| S9 | Multi-cloud cost comparison engine | P1 | Side-by-side Azure/AWS/GCP cost = differentiator | Cloud + Backend | 8 |
| S10 | Waitlist / early access with referral loop | P1 | No growth loop for pre-seed traction | CRO + FE | 3 |
| S11 | Investor data room & metrics dashboard | P1 | No structured data room for fundraising | Venture + PM | 5 |
| S12 | GitHub/GitLab integration for IaC push | P2 | Push Terraform as PR = one-click workflow | DevOps + Backend | 5 |
| S13 | Migration risk scoring & blast radius analysis | P2 | Advisory layer enterprises pay premium for | Cloud + Backend | 8 |
| S14 | Slack / Teams notification integrations | P2 | Enterprise teams live in these tools | Backend | 3 |
| S15 | White-label / embed SDK for partners | P2 | MSP distribution channel = B2B2B revenue | CTO + API | 13 |

### 12.2 Technical Gaps (CTO Review)

| # | Gap | Priority | Risk Domain | Owner | SP |
|---|-----|----------|-------------|-------|----|
| T1 | Session state needs enforced Redis in scaled production | P1 | Architecture | Backend | 13 |
| T2 | 60 routers with coupling via shared.py | P2 | Architecture | VP R&D | 8 |
| T3 | OpenTelemetry instrumentation is superficial | P2 | Observability | DevOps | 8 |
| T4 | No resilience patterns beyond OpenAI retry | P2 | Reliability | Backend | 5 |
| T5 | pgvector missing HNSW index + scaling plan | P2 | Data/Performance | Performance | 8 |
| T6 | Cost metering is volatile in-memory state | P2 | AI/LLM Cost | PM | 5 |
| T7 | Playwright smoke coverage exists, but critical funnel depth still needs broader E2E scenarios | P2 | Testing | QA | 8 |
| T8 | No shared API schema between FE/BE | P2 | Contract Drift | FE + API | 5 |
| T9 | Load tests skip LLM-bound endpoints | P2 | Performance | Performance | 5 |
| T10 | PostgreSQL parity requires production `DATABASE_URL` plus `ENFORCE_POSTGRES=true`; Alembic uses env-driven database URL | P1 | DX/Reliability | DevOps | 3 |
| T11 | Model router has no fallback chain | P2 | AI/Reliability | Cloud | 5 |
| T12 | No local dev Docker Compose with full stack | P3 | DX/Onboarding | DevOps | 5 |

---

*End of Document*
