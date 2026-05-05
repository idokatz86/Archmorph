# Changelog

All notable changes to Archmorph will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

#### CI and release maintenance

- **GitHub Actions Node.js 24 readiness** — audited workflow action runtimes, moved deprecated Node.js 20 action pins to Node.js 24-compatible majors, pinned Trivy to a release tag, and documented the workflow runtime inventory for release maintenance.

#### QA guardrails

- **Cost assumptions artifact** — Architecture Package and cost-estimate flows now publish a reviewable assumptions JSON artifact with region/SKU/quantity/storage/data-transfer/reservation context, directional-cost notice, and missing-price warnings.
- **Landing Zone SLO soak** — nightly Locust performance soak now exercises primary and DR Landing Zone SVG exports at the 100 RPS / 5 minute contract, publishes a JSON summary artifact, and pairs the runbook with App Insights p95 and 1h/24h burn-rate alerts.
- **FastAPI query-parameter test guard** — CI now fails when tests send `json=` bodies to query-only FastAPI routes, and the E2E step helper converts `has_X=False` detail flags into failed steps.
- **Mappings freshness guard** — cross-cloud service mappings now carry `last_reviewed` metadata, with non-blocking CI freshness lint and a quarterly review issue workflow.
- **Adaptive post-upload questions** — translated architecture drafts now open immediately after analysis, while inferred defaults are shown as reviewable assumptions and only high-impact or low-confidence gaps become focused follow-up questions.

#### Architecture Package quality recovery

- **Customer-grade package shell** — Architecture Package HTML exports now use the richer Archmorph review structure with branded header metadata, source-to-target story strip, A/B/C/D tab semantics, and grouped talking-point/limitation rows.
- **Legacy export cleanup** — Draw.io, Excalidraw, and Visio are removed from visible website export controls so the customer UI leads only with Architecture Package HTML, Target SVG, and DR SVG.
- **Azure icon recovery** — Azure topology SVG rendering now falls back to Archmorph's bundled Azure service icons when the runtime icon registry is incomplete, avoiding letter-badge-only customer diagrams.
- **Secure icon-pack ingestion** — `POST /api/icon-packs` and `DELETE /api/icon-packs/{pack_id}` now require admin bearer-session auth, deployments fail closed without `ARCHMORPH_ADMIN_KEY`, uploaded SVGs are sanitized, reserved built-in pack/icon IDs are blocked for custom uploads, built-in packs cannot be deleted, built-in provider catalogs are protected from startup/restore/custom-capacity eviction, and Excalidraw/draw.io/Visio plus landing-zone icon caches use invalidation/generation guards to avoid stale assets.
- **Networking package icon fidelity** — Networking-heavy Architecture Packages now render a dedicated Network Services rail with real Azure icons for Virtual WAN, VPN Gateway, ExpressRoute, Azure Firewall, Front Door, Application Gateway, Azure DNS, Private Link, and related edge services.
- **Data-driven ALZ renderer strips** — Landing Zone top cards, VNet/subnet/AZ labels, and DR replication bands now derive from inferred tiers, regions, VPC metadata, and data-tier inventory instead of static AVD, fake `10.0.0.0/16`, placeholder pod, and fixed replication templates.
- **Diagram placeholder cleanup** — Azure topology SVG rendering suppresses visible `(empty)` workload cells in availability-zone columns.

#### Cross-cloud agent and diagramming parity

- **AWS/GCP source-cloud parity** — upgraded relevant custom agents so CTO, Cloud, Backend, API, DevOps, CISO, QA, Performance, Bug, PM, FE, UX, and Scrum guidance treats AWS and GCP source environments with the same architectural rigor as Azure while preserving Azure as the target artifact platform.
- **Diagramming skill parity** — Draw.io and Excalidraw skills now call out AWS-to-Azure, GCP-to-Azure, and mixed-cloud migration views, including GCP topology expectations and explicit source-provider context in Architecture Package handoffs.
- **Architecture Package cross-cloud validation** — Architecture Package HTML/SVG tests now cover AWS, GCP, and mixed AWS/GCP source scenarios, including source traceability, Azure target primacy, DR outputs, talking points, limitations, and customer source filenames.
- **Classic diagram mixed-cloud handoff validation** — Draw.io and Excalidraw parser tests now cover mixed AWS/GCP-to-Azure handoffs with provider-prefixed source labels and deterministic Draw.io fallback icons for unmapped GCP-origin services.

#### Main-branch convergence and Architecture Package export (PRs #651 #652 #649 #667 #666)

- **Architecture Package HTML/SVG export** — new customer-facing export path that produces a polished tabbed HTML package plus standalone target and DR SVG renderings. It preserves classic Excalidraw, Draw.io, and Visio compatibility endpoints while making the Azure topology package the lead deliverable.
- **Customer intent profile** — guided-question answers now feed a compact `customer_intent` object for export narration while raw `guided_answers` remain limited to user-provided answers.
- **Scheduled job freshness health** — service catalog refresh now registers durable freshness in `/api/health.scheduled_jobs`, restores last-success state after restart, and avoids marking success when provider refreshes fail.
- **Branch convergence** — all active convergence PRs were merged or superseded and the repository was reduced back to `main` as the only active branch.

#### Architecture limitations engine (PR [#615](https://github.com/idokatz86/Archmorph/pull/615); follow-up phases [#616](https://github.com/idokatz86/Archmorph/issues/616) [#617](https://github.com/idokatz86/Archmorph/issues/617) [#618](https://github.com/idokatz86/Archmorph/issues/618) [#619](https://github.com/idokatz86/Archmorph/issues/619))

A deterministic rule engine that flags structurally invalid Azure compositions during analysis — the worked example being SFTP-via-Front-Door (Front Door is HTTP/HTTPS-only and cannot proxy port-22 SSH traffic to a storage SFTP endpoint).

- **25 curated rules** across 7 categories (protocol, network-topology, sku-prereq, identity-auth, data-plane, region, tier-feature) authored from Microsoft Learn references.
- **Predicate library** with 8 reusable matchers (service presence, connection protocols, path-via mismatches, category co-occurrence, count thresholds).
- **YAML-driven rules** at [backend/data/architecture_rules.yaml](backend/data/architecture_rules.yaml); override path via `ARCHMORPH_ARCH_RULES_PATH`.
- **Three severities**: `blocker` (IaC will be wrong), `warning` (works but has gaps), `info` (best-practice nudges).
- **Analysis enrichment**: every analysis result now carries `architecture_issues[]` and `architecture_issues_summary{blocker, warning, info, total}`.
- **IaC generation gate**: `POST /api/diagrams/{id}/generate` (and `/generate-async`) returns 409 when blockers exist; pass `?force=true` to override (logged via `iac_blockers_overridden` event).
- 38 unit + integration tests covering predicates, YAML schema validation, golden scenarios, and the IaC blocker gate.

Phase 2-5 follow-ups (AI fallback, admin review queue, frontend Architecture Health panel, rule library expansion to 60-100) tracked separately.

### Planned — Production-Ready ALZ (epic #586, target v4.3.0)

**T2→T3 bridge — eight technical-debt issues (#587–#594)** to close the credibility gap surfaced by the post-merge CTO end-to-end review of `landing-zone-svg`: D1 icon-registry/security hardening is complete for upload/delete auth, SVG sanitization, built-in catalog preservation, custom-capacity bounds, and cache invalidation; remaining work covers `_CATEGORY_TO_TIER` mis-bucketing (D2, observability/network-security tiers stay empty), wiring `service_connections` through every renderer (D4), refreshing stale mappings (Aurora wrong-engine, Cognito B2C, CloudFront CDN), adding tier-population + min-real-icon test guardrails, shipping a golden-file visual regression catcher, and standing up mappings ownership + CI freshness lint. D3 is now addressed by deriving Landing Zone top cards, VNet/subnet/AZ labels, and DR replication strips from analysis data instead of static templates.

**Production-readiness — eleven additional issues (#595–#605)** lifting the ALZ feature from Beta/demo-ware to **Live** at end of Sprint 3:
- **#595 Observability** — OpenTelemetry spans + metrics (icon-resolution hit rate, latency p50/p95/p99, SVG size, error rate) + alerts on `landing-zone-svg` pipeline (Sprint 1, P0, Backend + DevOps).
- **#596 CISO security review** — OWASP API Top 10 + threat model: data-URI handling, ZIP-slip on icon ingestion, prompt-injection vectors, retention-pipeline cross-talk, PII boundary (Sprint 1, P0, CISO).
- **#597 Performance SLO** — p95 < 1.5 s primary / < 3 s DR, 100 RPS × 5 min Locust soak, 512 MB worker memory ceiling, multi-window burn-rate alerts (Sprint 2, P1, Performance).
- **#598 Accessibility** — SVG titles/desc/role=img, WCAG 2.1 AA contrast, keyboard navigation, axe-core CI (Sprint 2, P1, UX + FE).
- **#599 API stability** — locked OpenAPI 3.1 contract, `dr_variant` enum locked to `primary|secondary`, 90-day deprecation policy with `Deprecation`/`Sunset` headers, `oasdiff` breaking-change CI gate (Sprint 2, P1, API).
- **#600 Golden PDF regression suite** — 3 redacted customer PDFs (AWS-only, GCP-only, mixed) + the original CTO-review PDF (redacted) checked in as `backend/tests/fixtures/golden_pdfs/`. Legal/Privacy review gates redaction; synthetic-equivalent fallback if blocked (Sprint 2, P0, QA + PM).
- **#601 Frontend exposure** — closes #575: ExportHub option + `LandingZoneViewer` with DR toggle, pan/zoom, download, deep-linkable URL state, full E2E + unit coverage (Sprint 2, P1, FE + UX).
- **#602 Foundry model evaluation spike** — bench `gpt-5.4` / `gpt-5.5` / `gpt-5.3-codex` / `mistral-document-ai-2512` against `gpt-4.1` for vision_analyzer / iac_generator / hld_generator / mapping_suggester / agent_paas_react / retention_anonymizer using #600 fixtures + `gpt-5-pro` rubric grader. Locks per-agent model picks (Sprint 1, P0, Backend + Cloud).
- **#603 Customer-facing docs** — `docs/features/landing_zone.md` + sample gallery + FAQ (Sprint 3, P1, PM).
- **#604 GA gate** — re-run the original CTO E2E with the same PDF; binary rubric (icon hit ≥95%, all 8 tiers populated, ≥3 service_connections rendered, golden-file pixel diff <2%, p95 SLO met, CISO sign-off) plus `gpt-5-pro` rubric judge that **must** return `production-ready` (Sprint 3, P0, QA).
- **#605 Beta → Live promotion** — flip Capability Status table, cut v4.3.0 release with rendered before/after gallery, close epic #586 (Sprint 3, P0, PM + DevOps).

**Sprint allocation**:
- Sprint 1 (in flight): #587–#590 + #595, #596, #602
- Sprint 2: #591–#594 + #597, #598, #599, #600, #601
- Sprint 3 (GA): #603, #604, #605
- Sprint 4: fix-forward headroom only (no new work)

**Per-agent Foundry model strategy** (locked pending #602 verification): `gpt-5.4` for vision_analyzer + hld_generator (1 M ctx, GA, multimodal + reasoning); `gpt-5.3-codex` for iac_generator (Codex-tuned, GA, Responses API); `gpt-5.4-mini` for mapping_suggester + agent_paas_react (cheaper mid-tier reasoning); `gpt-5.4-nano` for retention_anonymizer (smallest GA, deterministic); **`gpt-5-pro` locked for the GA judge in #604** (decoupled from production code → unbiased). Fallback: `gpt-5.4` everywhere if `gpt-5.5` Tier 5/6 quota is unavailable.

## [4.2.0] - 2026-05-01

### Added
- **Azure Landing Zone target diagram** (#571 / closes #572 #573 #574) — new `format=landing-zone-svg` export. Pure-stdlib SVG generator emits a Microsoft-style hub-and-spoke ALZ diagram: management groups, identity hub, network hub, ingress / compute / data / observability / storage / identity tiers, plus a DR variant (`dr_variant=dr`, 1800×2120) showing region pairing and replication bands. All icons embedded as `data:image/svg+xml;base64,…` from the icon registry — no external URLs. Output validated via `ET.fromstring` and capped at 300KB. Round-trip tested: parse, no duplicate xmlns, region labels, legend present, `dr_variant` rejected on other formats.
- **Multi-source provider for landing zone** (#576 / closes #577 #578 #579) — Landing Zone generator now supports `source_provider="aws"` (default, backwards-compatible with #571) and `source_provider="gcp"`. The provider is read implicitly from the analysis payload (no new query param); the schema is vendor-neutral and required zero changes for GCP. Per-provider legend lines (e.g. GCP: `GCP → Azure · GLB → App Gateway · GKE → AKS · Filestore → Azure Files · Pub/Sub → Event Hubs · Cloud SQL → Managed DB`). Hardened `_validate_source_provider`: `None` → `"aws"`, non-string → `ValueError`, empty/whitespace → `ValueError`, unknown → `ValueError`.
- **Sprint 0 anonymized retention tracking** (#580) — privacy-safe HMAC-anon cohort tracking gated behind `RETENTION_TRACKING_ENABLED`. Three admin endpoints (`/api/admin/retention/{day7,baseline,taxonomy}`), 8 canonical events, KPI 0.35 documented. Admin dashboard gains a Day-7 retention tile (testid `retention-tile`).
- **Local production-parity Compose overlay** plus guard tests for PostgreSQL/Redis enforcement without requiring a staging environment.
- **OpenAPI contract snapshot gate** so backend route/schema drift fails CI unless the committed API baseline is updated intentionally.
- **Admin release gate view** for deployment metadata and required smoke checks, plus confirmation before enabling risky scaffold feature flags.
- **Admin dashboard health and feature flag tabs** with live monitoring, audit visibility, and runtime flag toggles.
- **Drift baselines** with compare history, deterministic finding IDs, finding accept/reject decisions, and Markdown report export. Drift dashboard wired to create a baseline, rerun live/sample compares, resolve findings, and download reports.
- **Post-deploy smoke job** that verifies the deployed frontend, hash-routed product paths, API health, and OpenAPI schema after production deploys.
- **Release checklist** covering required secrets, quality gates, manual smoke checks, scaffolded feature approvals, and rollback evidence.
- **Disabled-by-default feature flags** for scaffolded deploy, drift, cloud scanner, and SSO/SCIM capabilities, with frontend gating for drift and deploy surfaces.

### Changed

- Direct and hub-based diagram downloads now use consistent MIME types for Architecture Package HTML/SVG and classic Excalidraw/Draw.io/Visio exports.
- The `/api/v1/*` mirror is documented and generated as a stable public API subset instead of claiming to mirror every mounted internal router.
- Service catalog blob/bootstrap failures now use bounded Azure SDK timeouts and traceback logging so startup and live reload failures are observable without hanging workers.

### Removed

- Removed stale analytics retention/event surfaces from backend routes, frontend route constants, dependencies, and tests.
- Removed SSO, organization, profile, and multi-tenant router surfaces from the active API after the convergence triage; the current auth surface is the smaller auth shell plus API keys/admin gates.

#### Infrastructure consolidation (May 2026)

Resource-group hygiene pass on `archmorph-rg-dev` (West Europe). Three orphaned / duplicated Azure resources retired without service impact:

- **App Service `archmorph-backend` + plan `archmorph-backend-plan`** (Canada Central, B1) — deleted. Production traffic has been served exclusively by the `archmorph-api` Container App for months; the App Service was a stale parallel deployment.
- **Container Registry `cafd43cfd4deacr`** (East US, Basic) — deleted. The `archmorph-mcp-gateway` Container App image (`archmorph-mcp-gateway:20260309101659330272`, plus the `:20260309103959778879` companion tag for safety) was imported server-side into the primary `archmorphacm7pd` registry (West Europe) using `az acr import`, the Container App was reconfigured with the new registry credentials and image, the new revision (`archmorph-mcp-gateway--0000004`) was verified `Healthy` at 100% traffic with `/health` returning HTTP 200, and only then was the legacy registry binding removed and the registry deleted. Cuts cross-region image pulls and the second-registry monthly line item.
- **Cognitive Services `secondnature-openai-whisper`** (originally in `archmorph-rg-dev`) — moved to its actual project resource group `rg-secondnature`. Note: `az resource move` returned a misleading `ResourceMoveFailed` referencing an unrelated linked-notification provider error, but the move itself completed — verification (presence in `rg-secondnature`, absence from `archmorph-rg-dev`) confirmed success.

Net effect: roughly $18/mo in idle resource spend eliminated, IaC footprint matches reality except for the OpenAI account region. Follow-ups: [#607](https://github.com/idokatz86/Archmorph/issues/607) tracks the West Europe OpenAI cutover, [#608](https://github.com/idokatz86/Archmorph/issues/608) tracks the Terraform `var.openai_location` sync once the live account has been moved.

#### Other changes

- **APP_VERSION** bumped to 4.2.0 in frontend constants.
- Clarified the product is 100% free for customers, removed Pro/billing language from the playground and active customer-facing surfaces, and renamed paid-conversion analytics to free-product activation tracking.
- Added an OpenAPI contract snapshot gate so backend route/schema drift fails CI unless the committed API baseline is updated intentionally.
- Added a local production-parity Compose overlay plus guard tests for PostgreSQL/Redis enforcement without requiring a staging environment.
- Consolidated the first-run product experience around the playground/migration review flow, fixed hash routing for all visible app tabs, and replaced remaining active emoji icons with Lucide icons.
- Removed Archmorph's staging deployment path from GitHub Actions; updated release guidance for a production-only environment model.
- Added server-side production gates and readiness metadata for live scanner, deployment execution/rollback, SSO/SCIM, Redis-backed session persistence, and PostgreSQL production parity; no customer billing path is required.
- Refreshed README, PRD, architecture diagram, and application flow diagram for the April 28 release-hardening checkpoint, including React/Vite versions, test counts, drift baselines, admin release gates, post-deploy smoke, and gated scanner/deploy posture.
- Captured release evidence for the green `904132a592a1e9744a6a98ab54ddaa56c7f91059` dependency/security checkpoint.
- Upgraded drift detection from a placeholder overlay to a usable sample audit flow with summary counts, recommendations, and richer backend drift scoring.
- Audit-log feature flag updates through the existing admin configuration audit event stream.
- Tightened CI gates: backend tests no longer ignore Agent PaaS/property-based suites, and frontend lint/Vitest now fail the build instead of using `continue-on-error`.
- Updated README and PRD language to distinguish live, beta, scaffold, and planned capabilities instead of presenting all enterprise surfaces as production-ready.
- Refreshed landing page messaging with capability status labels, preview-safe trust copy, and a sample-diagram CTA that routes to the playground.

### Fixed
- **Diagram export pipeline** (#569) — `_generate_vsdx` emitted duplicate `xmlns` attributes on the root element, making the file invalid Visio XML. Replaced manual `attrib={"xmlns": ...}` with `ET.register_namespace`. Router now labels VDX 2003 XML with the correct `.vdx` extension (was incorrectly `.vsdx`, the OOXML zip extension; real Visio refused raw XML at `.vsdx`). Added empty-content guard returning 502 instead of writing zero-byte files. Test suite rewritten to actually parse Excalidraw JSON / drawio XML / VDX XML and validate element/page counts (previous `assert "content" in result or "filename" in result` always passed). `e2e_flow_test.py` switched from `json={"format":...}` (which silently fell back to defaults) to `params={"format":...}` so format is sent as a query parameter as FastAPI declares it.
- **MCP diagram fallback path** — `_fallback_generation` returned `None` on missing content; added `or ""` guard. MCP success path also falls back when payload is empty/non-string/invalid JSON.
- **Frontend Blob MIME types** — `ExportHub.jsx` now sends format-specific MIMEs (`application/json` / `application/xml` / `application/vnd.visio`) instead of generic `octet-stream`.
- Removed noisy frontend React `act(...)` test warnings around App navigation, ServicesBrowser loading, and Roadmap loading; removed the deprecated backend `TestClient(timeout=...)` usage.
- Cleaned low-risk backend deprecation warnings for Pydantic model config, FastAPI `Query(pattern=...)`, timezone-aware UTC timestamp generation, and async decorator tests.
- Repaired `test_agent_paas_real.py` with isolated in-memory SQLite, seeded tenant data, and realistic auth overrides so the suite can run in CI.
- Fixed frontend Vitest setup with a complete `localStorage` mock and aligned component tests with current Nav, DiagramTranslator, CostPanel, LandingPage, AnalysisResults, and AdminDashboard behavior.
- Fixed `CostPanel.jsx` hook ordering so frontend lint passes cleanly.

### Known Issues
- **Landing-zone fidelity** — post-merge CTO E2E review (May 1, 2026) flagged the new `landing-zone-svg` export as **demo-ware**: cold-import icon-store empties to 0/N hits because `_load_from_disk()` is only invoked from a FastAPI startup hook, `_CATEGORY_TO_TIER` mis-buckets `Management` / `DevTools` / `Integration` / WAF / Sentinel / Defender into `compute` and `identity`, `_TIER1_CARDS` / `_vnet_block` / `_replication_band` are static templates that ignore analysis input, and `service_connections` are not yet wired into the SVG/drawio/vdx renderers. Five mappings (Aurora wrong-engine, Cognito B2C name retired, CloudFront/CDN retiring, GuardDuty lossy, KMS missing FIPS tier) are stale. Tracked under epic #586 (T2→T3 bridge) with sub-issues #587–#594; targeted for Sprint 1 + Sprint 2.

### Removed
- Deleted transient frontend repair scripts and ignored future `frontend/fix_*` scratch files.

## [4.1.0] - 2026-03-24

### Added
- **Self-Serve Onboarding Funnel** (#492) — Product analytics event tracking (PostHog + backend ingestion), activation funnel metrics (page_view → returning_user), session-based anonymous tracking
- **Interactive Demo Playground** (#493) — Try-before-signup sandbox with sample diagrams, guided walkthrough, no authentication required
- **SSO / SAML / SCIM Integration** (#496) — Enterprise SSO with SAML 2.0 Assertion Consumer Service, Single Logout, SCIM v2.0 user/group provisioning with JIT
- **Terraform State Import** (#497) — Upload terraform.tfstate (v3/v4), CloudFormation templates, or ARM deployments to auto-generate architecture diagrams. ~165 resource type mappings across AWS/Azure/GCP
- **Public API Developer Portal** (#498) — API documentation page with Swagger/Redoc links, category overview, curl examples, "Try it" integration
- **Multi-Cloud Cost Comparison** (#499) — Side-by-side Azure vs AWS vs GCP cost estimation with TCO analysis and per-category savings recommendations
- **Real-Time Collaborative Workspace** (#251) — Multi-stakeholder migration sessions with share codes, role-based participants (architect/devops/manager/security), change tracking
- **Migration Replay** (#254) — Animated analysis timeline for presentations with play/pause/speed controls, event-by-event playback, JSON export
- **Migration Gallery** (#256) — Public anonymized success stories with cloud badges, complexity indicators, likes, filterable by source/target cloud

### Changed
- **UX Wave 1** (#508-511) — Micro-interaction animations (fade-in, slide-up, scale-in), reusable EmptyState component, Textarea/Checkbox/RadioGroup form primitives, nav active-tab glow effect, font-semibold wordmark
- **UX Wave 2** (#512-513) — 3-phase progress indicator (PhaseIndicator.jsx), design system primitives expansion
- **Redis State Migration** (#494) — Session store upgraded from in-memory to Redis/PostgreSQL for horizontal scaling
- **Alembic PostgreSQL Parity** (#495) — Enforced PostgreSQL for dev/prod parity, eliminated SQLite default
- **APP_VERSION** bumped to 4.1.0 in frontend constants

### Fixed
- Unused imports in analytics_routes.py (ruff lint)
- Missing posthog-js frontend dependency
- CodeQL security alerts: defusedxml for SAML XML parsing, stack-trace exposure fixes, log sanitization

## [4.0.0] - 2026-03-23

### Added
- **RAG Pipeline** (#395) — Document ingestion (PDF/DOCX/HTML/CSV/JSON/TXT/MD), recursive chunking, Azure OpenAI embedding with content-hash caching, in-memory vector store with hybrid search (cosine + BM25), 8 API endpoints, `assemble_context()` integration for HLD/IaC generators
- **AI Agent PaaS PoC** (#397) — End-to-end agent platform proof of concept: agent CRUD, tool attachment (web_search, code_interpreter mocks), ReAct execution loop with GPT-4o function calling, RAG integration, per-execution cost tracking, 12 API endpoints under `/api/agent-paas/`
- **Cost & Token Observability Dashboard** (#392) — Per-execution token metering, model-specific cost calculation (GPT-4o/4o-mini/embedding models), budget management with alert thresholds (50%/80%/100%), timeseries aggregation, CSV export, 10 API endpoints. Auto-instrumented via `cached_chat_completion` hook.
- **AI Cross-Cloud Mapping Auto-Suggestion** (#230) — GPT-4o powered mapping suggestions with few-shot learning from approved mappings, 0.9 confidence auto-approve threshold, admin review queue, feedback loop, batch processing
- **Migration Timeline Generator** (#231) — 7-phase migration plan (Assessment → Optimization) with Kahn's topological sort for dependency ordering, 4 complexity tiers for duration estimation, risk scoring, parallel workstream identification, export as JSON/Markdown/CSV
- **Service Dependency Graph Visualization** (#233) — Interactive React Flow canvas with dagre layout, custom service nodes (confidence badges, category colors), 6 typed edges (traffic/database/auth/control/security/storage), zone grouping, click-to-reveal detail panel, SVG export
- **Social Authentication** (#246) — Microsoft, Google, GitHub sign-in via Azure SWA built-in auth + JWT fallback for non-SWA deployments, `x-ms-client-principal` header parsing, AuthProvider React context, LoginModal, UserMenu components
- **User Profile** (#247) — Profile management with preferences (source cloud, IaC format, role, company), GDPR-compliant account deletion, ProfilePage modal, Zustand auth store with localStorage persistence
- **RBAC & Multi-Tenant Isolation** (#238) — 4-role hierarchy (viewer < member < admin < owner), organization CRUD, member invitation/management, usage safeguards, org-scoped audit logging, 11 API endpoints
- **Full Analysis PDF Report Export** (#236) — 6-section branded PDF (cover, executive summary, service mappings table, cost estimates, risk summary, IaC appendix) via fpdf2, StreamingResponse download
- **AI Agent PaaS HLD** (#380) — 1,720-line vendor-neutral High-Level Design document covering 11 subsystems across Control Plane and Runtime Plane, with 5 Mermaid diagrams
- **Microsoft Technology Mapping** (#381) — 1,288-line document mapping every HLD component to concrete Azure services (Cosmos DB, Container Apps, AI Search, APIM, Entra ID, etc.) with 6 Mermaid diagrams, SKU recommendations, and cost estimates

### Changed
- **DevOps Modernization** (#378) — Multi-stage Dockerfile (~50% image size reduction), CI migrated to `uv` (10-50x faster installs), Trivy container scanning with SARIF upload to GitHub Security tab, Helm chart health probes with 150s startup window
- **OpenAI Client** — Added transparent cost metering hook in `cached_chat_completion` for automatic token tracking
- **AI Suggestion Engine** — Enhanced with few-shot learning from approved mappings, feedback store, raised auto-approve threshold from 0.7 to 0.9

### Fixed
- Deploy tab greyscale overlay (#478) — already resolved in commit 6074da6
- Email notification confirmation UI (#477) — already resolved in commit 6074da6
- Ruff F401 lint errors in new modules (agent_tools, rag_pipeline, rag_routes, models/rag, cost_routes)

### Removed
- Duplicate issues: #243 (subsumed by #321), #248 (subsumed by #321)

## [3.9.0] - 2026-03-17

### Added
- **GPT-4.1 Model Upgrade** — Deployed Azure OpenAI `gpt-4.1` (2025-04-14) as primary model with `gpt-4o` fallback. Output token limit increased from 4K to 32K for significantly richer IaC and HLD generation.
- **Interactive Architecture Map** — Complete rewrite of `ArchitectureFlow.jsx` using dagre auto-layout with:
  - **Confidence rings** — SVG circular progress showing mapping confidence per node (green ≥85%, amber ≥60%, red <60%)
  - **Effort badges** — Low/Medium/High migration effort indicators per service
  - **Typed edges** — 6 edge styles (Traffic, Database, Auth, Control, Security, Storage) with color-coded lines and protocol labels
  - **Zone grouping** — Services grouped into architectural zones (Hub, Spoke, etc.) with dashed-border containers
  - **Manual mapping nodes** — Red dashed nodes for unmapped services requiring manual review
  - **Map legend overlay** — Collapsible legend explaining all visual elements
  - **MiniMap** — React Flow minimap with node-type color coding
  - **Full interactivity** — Pan, zoom, drag nodes, using `useNodesState`/`useEdgesState` inside `ReactFlowProvider`
- **Email Notifications** — Azure Communication Services integration for sending branded HTML migration report emails via `POST /api/diagrams/{id}/notify-email`
- **IaC Diff Highlighting** — `IaCViewer.jsx` compares previous vs current IaC code with green-tinted changed lines and left border markers
- **Parallel IaC + HLD Generation** — "Generate All" button fires IaC and HLD generation simultaneously for faster workflow
- **Generation Progress Indicator** — Real-time progress bar during IaC/HLD/cost generation in the Results panel
- **AWS Hub & Spoke Sample** — Enterprise Landing Zone sample diagram with Transit Gateway, Network Firewall, VPN, EKS, and Aurora across 3 zones with 8 typed connections

### Changed
- **Limitations UX Redesign** — Limitations displayed as 3-layer scannable cards with severity-tinted backgrounds, icons, and collapsible details instead of flat bullet lists
- **Deploy Tab** — Greyscale overlay with Rocket icon and "Coming Soon" badge (placeholder for future CI/CD deploy pipeline)
- **Drift Tab** — Greyscale overlay with ShieldCheck icon and "Coming Soon" badge
- **IaC Chat Backend** — Switched from direct OpenAI calls to `cached_chat_completion` with automatic fallback model support and specific exception handling (`RateLimitError`, `APITimeoutError`, `APIConnectionError`, `BadRequestError`)
- **CI/CD Pipeline** — Production deploy now sets `AZURE_OPENAI_DEPLOYMENT=gpt-4.1`, `AZURE_OPENAI_FALLBACK_DEPLOYMENT=gpt-4o`, and `AZURE_OPENAI_API_VERSION=2025-04-01-preview`

### Fixed
- **Architecture Map NaN Positions** — Group nodes in dagre layout had no dimensions, causing `undefined` x/y propagation as NaN across all SVG attributes (MiniMap circles, edge paths, viewBox). Fixed by passing explicit width/height to `g.setNode()` and adding `Number.isFinite()` guards.
- **Zone Service Matching** — `z.services?.includes(src)` compared strings against `{name, role}` objects (never matched). Fixed with `.some(s => s.name === src)`.
- **IaC Generation Truncation** — Output was cut off at 4K tokens. Increased `max_tokens` to 32,768 across IaC generator, HLD generator, and verification step.
- **IaC Chat Failures** — Broad `except Exception` handler silently swallowed errors. Replaced with specific exception types and fallback model retry.
- **HLD Generation 500 Errors** — Same 4K token limit caused truncated/invalid HLD output. Now uses 32K tokens.
- **Empty AZURE_OPENAI_ENDPOINT** — Production container had empty endpoint string (GitHub Secret unset). Fixed by setting directly on container app and storing as GitHub secret.
- **CI/CD Hardcoded Model** — Deployment workflow hardcoded `gpt-4o` instead of using the upgraded `gpt-4.1` deployment name.
- **Frontend Test Suite Stability** — Updated Vitest matchers in 4 test files to align with UI text changes (Hub & Spoke, provider labels).
- **Ruff Lint** — Removed unused `EmailStr` import and extraneous f-string prefix in email service.

## [3.8.1] - 2026-03-15

### Fixed
- **Frontend Crash**: Fixed a critical rendering crash in `ArchitectureFlow.jsx` where destructured return values from `useMemo` resulted in undefined array access, which had silently hidden the canvas causing E2E timeouts.
- **E2E Stability**: Updated Playwright specs (`ui-golden-paths.spec.ts`) to successfully navigate explicitly to the `/#translator` route and accurately hydrated mocked `sessionStorage` objects to use `mappings` instead of the legacy `mapped_services` array.
- **Backend Syntax**: Solved backend syntax issues (`logger_utils.py` / `migration_intelligence.py`) failing the CI pipeline via ruff lint checks.
- **Docker Volumes**: Addressed backend icon cache mounting issues (`/app/data/icon_registry.json`) ensuring write access for the application's runtime user.

### Planned (Sprint #465 - March 15)
- Tracked UX Polish and Bug Fixes planned for immediate resolution: Fix HLD generation 500/429 crashes, restore missing layout layers in Interactive Map, unblock IaC assistance dynamic modifications, populate the 'Coming Soon' tab safely, and place Alpha warning text above Drift Detection.

## [3.8.0] - 2026-03-09

### Added
- **Dynamic GitHub Roadmap Sync** — Community feature requests in GitHub automatically sync directly to the Roadmap tab's "Ideas" column allowing for live up-to-date tracking natively in the frontend.
- **Vibe-Coding Disclaimer Banner** — Global dismissible banner to outline the experimental and fast-paced nature of the application for users.

### Changed
- `LegalPages.jsx` — Overhauled the Terms of Service. Stripped out references to 'Subscription & Billing'. Clarified the free-of-charge, "as-is" vibe-coding nature of the tool for legal clarity.
- `ci.yml` — Fully optimized GitHub Actions CI pipeline removing duplicate node builds via Artifact caching reducing build time tremendously.
- `ci.yml` — Appended Azure CLI idempotency skips causing duplicate deployments to fast-skip saving over 60 seconds per CI pipeline.
- `security.yml` — Sliced redundantly overlapping SAST/SCA scanners (bandit, semgrep, test-trivy) leaving just a core optimized list (CodeQL, Grype) saving 40% Action minutes.
- `roadmap.py` — Now features a 15-minute runtime cache on `fetch_github_ideas` to manage API rate limits efficiently.


## [3.8.0] - 2026-03-05

### Added
- **Migration package export** — "Download Migration Package" button generates ZIP with IaC code, HLD (DOCX + Markdown), cost estimate (JSON), analysis summary, and README (#252)
- **Before/After architecture visualization** — collapsible source-to-Azure comparison view per zone with confidence badges (#250)
- **Guided onboarding tour** — 5-step first-time user walkthrough (Upload, Analyze, IaC, HLD, Pricing) with localStorage-based detection (#257)
- **CI coverage gate** — `--cov-fail-under=60` enforced in CI pipeline, tests fail if coverage drops below 60% (#288)
- **Stale bot** — GitHub Actions workflow for backlog hygiene: 60-day stale detection, 14-day auto-close, exempt P0/epic labels (#362)
- **BeforeAfterView.jsx** — interactive before/after architecture comparison component
- **OnboardingTour.jsx** — 5-step overlay tour with step dots and skip/dismiss

### Changed
- `ci.yml` — pytest coverage gate added
- `PricingTab.jsx` — "Download Migration Package" button with ZIP export
- `AnalysisResults.jsx` — BeforeAfterView integrated after export panel
- `App.jsx` — OnboardingTour lazy-loaded on first visit

## [3.6.0] - 2026-03-04

### Added
- **Dark mode toggle** — Sun/Moon button in Nav bar with localStorage persistence, smooth CSS transitions (#372)
- **Full light theme** — complete light theme variables (CTA, danger, warning, info colors) across all components (#372)
- **Skeleton loader CSS** — shimmer animation utility class for loading states (#372)
- **Focus-visible ring** — 2px CTA-colored outline on keyboard focus for WCAG 2.1 compliance (#372)
- **Reduced motion** — `prefers-reduced-motion` media query disables animations for accessibility (#372)
- **Cache-Control headers** — GET endpoints return appropriate caching (services: 5min, health: no-cache, costs: 2min, compliance: 10min) (#376)
- **HLD v2 template** — expanded from 6 to 10 sections: Executive Summary, Service Architecture, Networking, Security & IAM, Cost Model, Migration Plan, Risks & NFRs, WAF Alignment, Decision Log, Implementation Roadmap (#359)
- **Contextual help tooltips** — `HelpTooltip` component with predefined content for confidence, HLD, pricing, IaC, migration effort, strengths, and limitations (#367)
- **Confidence deep-dive UI** — tabbed Strengths/Limitations/Migration Notes panel per service mapping with severity badges and doc links (#405)
- **HelpTooltip.jsx** — new reusable tooltip component with 7 predefined help entries

### Changed
- `Nav.jsx` — added `useTheme()` hook, dark/light mode toggle button
- `index.css` — extended light theme, added skeleton/focus-visible/reduced-motion styles
- `main.py` — Cache-Control middleware for read-only endpoints
- `HLDPanel.jsx` — expanded HLD_TABS array from 6 to 10 professional sections
- `AnalysisResults.jsx` — MappingRow now shows DeepDivePanel with Strengths/Limitations/Migration tabs

## [3.5.0] - 2026-03-04

### Added
- **Confidence deep-dive** — per-mapping strengths, limitations, and migration notes with curated knowledge base for 15+ Azure services (#399, #404)
- **Enriched cost-breakdown endpoint** — `/api/diagrams/{id}/cost-breakdown` with per-service formula, assumptions, alternative SKUs, optimization recommendations, source vs target comparison, and cost-by-category (#401, #403)
- **7-step workflow** — Upload → Analyze → Customize → Results → IaC Code → HLD → Pricing (#402)
- **HLD auto-generation tab** — dedicated step with auto-trigger, loading skeleton, and regenerate button (#400)
- **Pricing tab** — deep cost breakdown with cost drivers, category chart, region impact, Reserved Instance comparison, and optimization recommendations (#406)
- **PricingTab.jsx** — new 300-line component with expandable per-service rows, SKU alternatives, and optimization cards
- **HLDTab.jsx** — new wrapper component for standalone HLD step
- Custom domain **archmorphai.com** with managed SSL certificates for frontend, API, and www subdomains

### Changed
- HLD moved from inline Results panel to dedicated workflow tab (auto-generates on entry)
- Pricing moved from IaC Code tab to dedicated final Pricing tab
- `AnalysisResults.jsx` simplified — HLD props removed, component focused on analysis display
- `useWorkflow.js` — added `costBreakdown` and `costBreakdownLoading` state fields
- `ai_suggestion.py` — `suggest_mapping()` now returns `strengths[]`, `limitations[]`, `migration_notes[]`
- `routers/insights.py` — new `/cost-breakdown` endpoint with enriched pricing data

## [3.0.0] - 2026-02-24

### Added
- **Multi-cloud target support** — parameterized target_provider (aws/azure/gcp) across vision_analyzer and IaC generator (#156, #31)
- **CloudFormation IaC generation** — AWS-specific prompts, region validation, base template (#31)
- **User Dashboard** — stat cards, analysis history, bookmarks, pagination, provider filtering (#151)
- **Template Gallery** — 10 architecture patterns, 8 categories, search, difficulty badges (#27)
- **Visio (.vsdx) import** — Open XML parser with shape/connection/cloud-service identification (#150)
- **i18n** — react-i18next with 3 locales (en/es/fr), LanguageSelector component, 70+ translation keys (#171)
- **Living Architecture engine** — health scoring (5 weighted dimensions), drift detection, cost anomaly alerts (#157)
- **Migration Intelligence** — anonymous event pipeline, community confidence scoring, pattern library, trending migrations (#159)
- **White-Label SDK** — config-driven branding (colors, fonts, logos, features), partner API key management, embeddable widget snippets (#29)
- **Dashboard API** — analysis history, stats, bookmarks endpoints (#111)
- **Multi-tenant foundation** — Alembic migration 002 with organizations, team_members, invitations tables (#113)
- **Enhanced PR template** — comprehensive Definition of Done checklist (#152)

## [2.12.0] - 2026-02-22

### Added
- GitHub Best Practices audit and governance hardening (#109)
- PR template, issue templates (bug report & feature request)
- Workflow concurrency controls and timeout-minutes on all jobs
- CHANGELOG.md, CODE_OF_CONDUCT.md, `.gitattributes`, `.editorconfig`
- PodDisruptionBudget for Kubernetes deployments
- Trivy container scan gate in security workflow

### Fixed
- Unbounded in-memory stores capped with LRU/TTL caches (#94)
- Race conditions in auth, feedback, metrics, sessions (#95)
- Authentication bypass risks in admin auth and shared router (#96)
- Frontend blob URL memory leak and upload error handling (#97)
- Stale closure, file size validation, missing `.ok` checks (#100)
- Terraform lifecycle guards and Helm tag pinning (#101)
- Backend error handling gaps — silent middleware, info leaks (#102)
- Broken `actions/checkout@v6` → `@v4` in monitoring workflow
- Semgrep `|| true` removed so security pipeline enforces findings

### Changed
- Share IDs upgraded from UUID hex (40-bit) to `secrets.token_urlsafe` (192-bit)
- Redis `KEYS` replaced with `SCAN` in session store
- Helm `image.tag` changed from `latest` to CI/CD-set value

## [2.11.0] - 2026-02-20

### Added
- Frontend Vitest test suite (186 tests across 13 component files)
- Version bumped to 2.11.0

## [2.10.0] - 2026-02-19

### Added
- Comprehensive backend test suite (1,149 tests across 30 files)
- Feature flags system with percentage rollout and user targeting
- Structured audit logging with risk levels and alerting rules
- Session persistence with pluggable InMemory/Redis backends
- GPT response caching with content-hash TTLCache
- API versioning — all routes mirrored at `/api/v1/*`

## [2.9.0] - 2026-02-18

### Added
- Blue-green deployment with smoke tests
- Manual rollback workflow
- E2E health monitoring with auto-issue creation
- Security pipeline (Semgrep, Bandit, CodeQL, Gitleaks, Trivy)
- CycloneDX SBOM generation for Python and npm
- Dependabot for 5 ecosystems (pip, npm, docker, github-actions, terraform)

## [2.8.0] - 2026-02-17

### Added
- HLD document export (Word, PDF, PowerPoint)
- IaC Chat assistant with GPT-4o
- Chatbot assistant with FAQ and GitHub issue integration
- Admin dashboard with conversion funnel and session tracking
- JWT admin authentication (HS256, 1-hour TTL)
- Persistent analytics with Azure Blob Storage

## [2.7.0] - 2026-02-16

### Added
- AI-powered HLD generation (13-section documents with WAF assessment)
- Dynamic cost estimates via Azure Retail Prices API
- Self-updating service catalog with daily auto-discovery
- Icon registry (405 normalized cloud service icons)
- Diagram export to Excalidraw, Draw.io, and Visio

## [2.6.0] - 2026-02-15

### Added
- Guided migration questions (32 questions across 8 categories)
- Terraform HCL and Bicep code generation
- Architecture diagram upload and analysis (PNG, JPG, SVG, PDF, Draw.io)
- AWS/GCP service detection with 405+ service catalog

[Unreleased]: https://github.com/idokatz86/Archmorph/compare/v3.0.0...HEAD
[3.0.0]: https://github.com/idokatz86/Archmorph/compare/v2.12.0...v3.0.0
[2.12.0]: https://github.com/idokatz86/Archmorph/compare/v2.11.0...v2.12.0
[2.11.0]: https://github.com/idokatz86/Archmorph/compare/v2.10.0...v2.11.0
[2.10.0]: https://github.com/idokatz86/Archmorph/compare/v2.9.0...v2.10.0
[2.9.0]: https://github.com/idokatz86/Archmorph/compare/v2.8.0...v2.9.0
[2.8.0]: https://github.com/idokatz86/Archmorph/compare/v2.7.0...v2.8.0
[2.7.0]: https://github.com/idokatz86/Archmorph/compare/v2.6.0...v2.7.0
[2.6.0]: https://github.com/idokatz86/Archmorph/releases/tag/v2.6.0
