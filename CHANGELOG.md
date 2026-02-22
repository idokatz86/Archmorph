# Changelog

All notable changes to Archmorph will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/idokatz86/Archmorph/compare/v2.12.0...HEAD
[2.12.0]: https://github.com/idokatz86/Archmorph/compare/v2.11.0...v2.12.0
[2.11.0]: https://github.com/idokatz86/Archmorph/compare/v2.10.0...v2.11.0
[2.10.0]: https://github.com/idokatz86/Archmorph/compare/v2.9.0...v2.10.0
[2.9.0]: https://github.com/idokatz86/Archmorph/compare/v2.8.0...v2.9.0
[2.8.0]: https://github.com/idokatz86/Archmorph/compare/v2.7.0...v2.8.0
[2.7.0]: https://github.com/idokatz86/Archmorph/compare/v2.6.0...v2.7.0
[2.6.0]: https://github.com/idokatz86/Archmorph/releases/tag/v2.6.0
