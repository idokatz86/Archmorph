# Changelog

All notable changes to Archmorph will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
