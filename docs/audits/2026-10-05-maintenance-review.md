# Archmorph maintenance assessment and plan

## Scope and evidence

Reviewed on 2026-10-05 against GitHub `main` at
`f21393a7f195f8c39b4c3169d99e5ee0f5c998bc`.
The maintenance work is on `chore/maintenance-20261005` in an isolated worktree;
the existing checkout and its untracked customer artifacts were left untouched.

The review retrieved every page of Dependabot, code-scanning, and secret-scanning
alerts; inventoried all 10 open issues and 22 open pull requests; and examined
75 recent workflow runs plus targeted failure logs, default-branch CI history,
scanning freshness, and production environment protection metadata.
Individual remediation analysis focused on open alerts. Historical dismissals
were counted, not independently recertified.

This is a repository and GitHub assessment, not a live Azure infrastructure audit.
No production deployment, permission change, alert dismissal, issue closure,
secret retrieval, merge, or push was performed.

## GitHub alert inventory

| Surface | Open | Reported severity | Historical records retrieved |
|---|---:|---|---|
| Dependabot | 22 | 8 high, 11 medium, 3 low | 42 fixed, 6 auto-dismissed |
| Code scanning | 25 | 20 high, 5 medium; all open reports are CodeQL | 141 fixed, 83 dismissed as false positives |
| Secret scanning | 0 | None reported | 0 |

These are scanner classifications, not 47 independently confirmed exploitable
vulnerabilities. The GitHub alerts remain open until changes reach the relevant
branch and GitHub evaluates them again.

### Dependency reports and updated components

| Component | Dependabot alert numbers | Previous locked version | Maintenance lockfile |
|---|---|---|---|
| Undici | 44, 45, 46, 47, 48, 64, 66, 67, 70, 71, 72 | 7.28.0 | 7.30.0 |
| js-yaml, root and frontend | 51, 52, 61, 62 | 4.3.0, vendored | 4.3.2 |
| baseline-browser-mapping | 60 | 2.10.37 | 2.11.26 |
| Vitest / mocker / coverage provider | 58, 59 | 4.1.10 | 4.1.11 |
| Browserslist | 57 | 4.28.2 | 4.29.1 |
| Nano ID | 55 | 3.3.16, vendored | 3.3.19 |
| PostCSS | 54 | 8.5.20, vendored | 8.5.28 |
| DOMPurify | 50 | 3.4.12 | 3.4.16 |
| brace-expansion compatibility package | Additional findings from fresh npm audit | 5.0.8 | 5.0.12 |

The clean npm audit additionally identified four brace-expansion advisories:
GHSA-rgw5-rvv9-x895, GHSA-q2hr-2g5m-vwhr, GHSA-qhr7-859c-m2p7, and
GHSA-6j4f-fj2g-mc7p. The updated deterministic compatibility archive preserves
the callable CommonJS interface needed by legacy Minimatch consumers.

Regression checks verify patched minimum versions across all matching lockfile
entries, approved download origins, and SHA-512 integrity pins. Both root and
frontend clean installs now pass `npm audit --audit-level=low` with zero findings.
This establishes the local dependency result, not a production image attestation.

### CodeQL triage, without blanket dismissal

| Rule | Reports | Evidence and next action |
|---|---:|---|
| Path injection | 19: 338-348, 374-381 | Concentrated in [FileStore](../../backend/session_store.py). Existing filename rewriting is not the same as a demonstrated exploitable escape. Test path containment, key collisions, symlinks, locking, and every supported deployment mode before choosing validation/encoding changes or a narrow analysis model. Redis is required by default in production. |
| Log injection | 5: 382-386 | Four sites in [workspace_store.py](../../backend/workspace_store.py) already call the shared sanitizer. The [logging configuration](../../backend/logging_config.py) also removes CR/LF before output. A new [versioning regression](../../backend/tests/test_versioning.py) passes against existing runtime behavior, so no speculative logging fix was made. Validate all sinks and CodeQL paths before dismissing any report. |
| Weak sensitive-data hashing | 1: 361 | The reported [principal identifier](../../backend/routers/shared.py) uses HMAC-SHA256 in a development compatibility path. This is not evidence of a broken hash algorithm or production password storage. Review its purpose, reachability, and secret/salt lifecycle before disposition. |

The latest retrieved main-branch CodeQL analysis was from 2026-09-28 at the
reviewed commit. The latest retrieved backend Trivy analysis was from
2026-09-21; a newer backend container-health gate failed. Fresh container scans
and hosted CodeQL results are still required.

## Shared CI blockers and maintenance changes

1. **Missing async database dependency.** The
   [2026-10-05 CI run](https://github.com/idokatz86/Archmorph/actions/runs/37271148037)
   failed migration, backend, latency, rollout, IaC, and CLI jobs with the same
   missing `greenlet` / SQLAlchemy asyncio import error.
   [requirements.txt](../../backend/requirements.txt) now declares
   `sqlalchemy[asyncio]`, rather than relying on an incidental transitive install.
   A fresh Python 3.12 environment resolved SQLAlchemy 2.1.1 with greenlet 3.5.6;
   real async query and application smoke tests pass.
2. **Obsolete vendored npm packages.** The
   [security run](https://github.com/idokatz86/Archmorph/actions/runs/37271147617)
   stopped at the root js-yaml audit, before reaching the frontend audit.
   The three obsolete js-yaml/Nano ID/PostCSS archives are removed. Only the
   necessary, updated brace-expansion source/compatibility pair remains.
3. **Explicitly approved package-source change.** npmjs.org returned 404 for
   patched releases including js-yaml 4.3.2 and DOMPurify 3.4.16. The user approved
   the publicly reachable Microsoft npm feed instead. Credential-free,
   empty-cache installs were verified. See [package provenance and maintenance
   instructions](../../vendor/README.md); no registry credentials are committed.
4. **Strong lockfile integrity retained.** Some feed metadata supplies only
   SHA-1 pins. The explicit `npm run security:lock-integrity` maintenance command
   verifies the existing archive identity and records SHA-512 pins. Its tests
   cover mismatches, download failures, unapproved sources, idempotence, and
   concurrent edits. CI does not silently rewrite lockfiles. Dependabot PRs may
   require this reviewed maintenance step until registry metadata improves.
5. **Dependency-monitoring gaps closed.** [Dependabot configuration](../../.github/dependabot.yml)
   now also covers root npm, the SWA API, CLI, MCP gateway, and the gateway image.
   The retired `reviewers` option was removed; the existing
   [CODEOWNERS](../../.github/CODEOWNERS) remains responsible for review routing.
   The resulting configuration passes the published schema and regression tests.
   GitHub [retired that option on May 20, 2025](https://github.blog/changelog/2025-04-29-dependabot-reviewers-configuration-option-being-replaced-by-code-owners/).

No React, Vitest 5, Terraform provider major, database-engine, or architectural
migration was bundled into this patch. Backend dependencies are still broadly
floating; a fresh environment is not a substitute for a reproducible runtime lock.

## Architecture assessment

**Recommendation: retain the modular monolith and harden its boundaries.**
A microservice rewrite would add migration and operational risk without addressing
the immediate dependency, CI, or state-lifecycle problems.

The current application path is:

```text
React / Vite on Static Web Apps
  -> Front Door / WAF
  -> FastAPI on Container Apps
       -> Azure OpenAI analysis and generation
       -> PostgreSQL canonical workspaces, versions, and artifacts
       -> Redis session/cache and shared job state
       -> Blob-backed catalog/metrics storage
       -> leased in-process workers and SSE progress
```

### Strengths already present

- Canonical, tenant-scoped analysis persistence and transactional mutation
  handling are implemented; do not propose rebuilding them from scratch.
- Jobs already have shared state, leases, heartbeats, retry/recovery behavior,
  and startup reconciliation.
- Production startup checks require PostgreSQL, Redis, and shared rate-limit
  storage rather than silently accepting development fallbacks.
- The latest retrieved production browser synthetic, freshness watchdog,
  catalog refresh, and performance soak runs were successful. These are useful
  signals, not proof that the latest source has passed every release gate.

### Risks that should drive the next work

| Priority | Evidence | Recommended change |
|---|---|---|
| P1 | [JobManager](../../backend/job_queue.py) stores jobs, events, active counts, and idempotency in the shared store; [Terraform](../../infra/main.tf) configures Redis with `allkeys-lru`. | Prove accepted-job behavior under eviction, Redis loss, restart, and lease contention. Separate durable execution state from evictable cache, or adopt a deliberately non-evicting durable design with explicit admission/backpressure. Worker-restart recovery alone is not sufficient evidence. |
| P1 | The production GitHub environment has a branch policy but no required reviewer. Secret push protection is disabled. | Establish independent production approval and enable push protection through a separately approved settings change. Keep deployments restricted to the protected branch. |
| P2 | [DiagramTranslator](../../frontend/src/components/DiagramTranslator/index.jsx) is 1,861 lines; [ESLint](../../frontend/eslint.config.js) disables `no-undef`, `no-dupe-keys`, `react/jsx-no-undef`, and exhaustive-dependencies checks. | Continue extracting workflow controllers around existing hooks, without a visual redesign. Restore the three basic safety rules first, then hook dependency enforcement with narrow exceptions. |
| P2 | [workspace_store.py](../../backend/workspace_store.py) is 4,373 lines; [job_queue.py](../../backend/job_queue.py) is 1,943 lines. | Extract cohesive policy/persistence services without breaking transaction, CAS, tenant-isolation, purge-fence, or idempotency boundaries. Add contract tests before moving behavior. |
| P2 | Terraform declares PostgreSQL 15; migration CI uses PostgreSQL 16 plus pgvector. | Confirm the actual deployed version, choose the supported target, and align migration testing. Do not upgrade the database merely to make documentation agree. |
| P2 | Sync and async database engines each have configured pools; API workers also run AI work. | Budget aggregate connections and model concurrency across workers and replicas against actual database/model quotas. Validate memory and backpressure under representative upload/export load. |
| P2 | Backend runtime, test, document-export, and optional integration dependencies share a broadly unpinned requirements file. | Separate runtime/test/optional sets and introduce a reviewed reproducible lock, including image/SBOM evidence. Upgrade sensitive packages in small compatible groups. |

**Feasibility verdict: conditional.** The application can be maintained and
improved incrementally. Production/enterprise readiness still needs deployed
configuration evidence, capacity measurements, independent approval, and
failure-mode tests. Source configuration alone cannot establish those facts.

## Prioritized execution plan

Owners below are proposed roles, not assignments already made.

| Order | Work and proposed owner | Exit criteria / dependency |
|---|---|---|
| 1: release baseline, now | Maintainer + QA: review this patch and run all required hosted CI checks. | Clean SCA and container scans; PostgreSQL migration smoke; full backend and browser gates; no regression in deployment contracts. Merge only after these pass, then verify the 22 dependency alerts resolve. Local validation does not replace these gates. |
| 2: security disposition, next | Backend + security reviewer: triage all 25 CodeQL reports by shared source/sink; separately complete approval/push-protection controls. | Every report has a tested fix or an evidence-backed, narrowly scoped disposition. No blanket exclusions. Track independent approval with [idokatz86/Archmorph#1282](https://github.com/idokatz86/Archmorph/issues/1282). |
| 3: state and frontend hardening, next sprint | Backend + frontend + QA: execute eviction/restart tests, define durable job guarantees, decompose controllers, restore lint safety, and budget quotas/pools. | Accepted jobs never silently disappear in the agreed failure tests; tenant/purge/idempotency contracts remain intact; lint passes with restored rules; agreed latency/memory/quota budgets pass. Continue [idokatz86/Archmorph#1242](https://github.com/idokatz86/Archmorph/issues/1242) and [idokatz86/Archmorph#988](https://github.com/idokatz86/Archmorph/issues/988). |
| 4: operational and enterprise evidence | Platform + maintainer: reconcile incidents, validate private ingress/identity/DR, agree RTO/RPO, and collect release evidence. | Recovery automation proves three successful intervals, respects manual holds, and handles recurrence. DR targets are measured in a drill. ACR authorization changes follow a staged pull/push/rollback plan, not a bulk role replacement. Continue [idokatz86/Archmorph#1245](https://github.com/idokatz86/Archmorph/issues/1245), [idokatz86/Archmorph#1137](https://github.com/idokatz86/Archmorph/issues/1137), and [idokatz86/Archmorph#1281](https://github.com/idokatz86/Archmorph/issues/1281). |

### Backlog reconciliation

- [idokatz86/Archmorph#1261](https://github.com/idokatz86/Archmorph/issues/1261)
  is a historical July catalog-refresh incident. Recent refresh/watchdog runs
  are green; verify sustained recovery and authenticated health evidence before
  closing it. It should not automatically be treated as an active outage.
- [idokatz86/Archmorph#1235](https://github.com/idokatz86/Archmorph/issues/1235)
  still has unchecked boxes for canonical state and restart-safe jobs, although
  [idokatz86/Archmorph#1237](https://github.com/idokatz86/Archmorph/issues/1237) and
  [idokatz86/Archmorph#1239](https://github.com/idokatz86/Archmorph/issues/1239)
  are closed as completed and their implementations are present. Reconcile the
  parent checklist; retain distinct new failure-mode validation work.
- [idokatz86/Archmorph#1313](https://github.com/idokatz86/Archmorph/issues/1313)
  reports zero mapping freshness errors/warnings. It is a quarterly semantic
  review, not evidence of a stale catalog. Review low-confidence/product-name
  mappings rather than mechanically changing review dates.
- Preserve the migration-decision-workbench direction in
  [idokatz86/Archmorph#1128](https://github.com/idokatz86/Archmorph/issues/1128).
  Stabilization should not become an unrelated feature expansion.
- Rebase or supersede overlapping dependency PRs after the baseline patch lands.
  Keep major upgrades such as
  [idokatz86/Archmorph#1308](https://github.com/idokatz86/Archmorph/pull/1308)
  (Vitest 5) and
  [idokatz86/Archmorph#1195](https://github.com/idokatz86/Archmorph/pull/1195)
  (AzureRM 5) separate from security patching.

## Verified local results and remaining gates

| Check | Result |
|---|---|
| Root and frontend credential-free, empty-cache `npm ci` | Passed with the approved public feed and final SHA-512 pins |
| Root and frontend `npm audit --audit-level=low` | Zero vulnerabilities |
| Security-package behavior + integrity-maintenance tests, Node 22.13.0 | 12 passed |
| Frontend tests with V8 coverage, Node 22.13.0 | 452 passed across 40 files; reported line coverage 88.03% |
| Frontend zero-warning lint and production build, Node 22.13.0 | Passed |
| Focused backend maintenance suite, fresh Python 3.12.13 | 195 passed, 1 skipped |
| CLI-to-API HTTP full-spine smoke, fresh Python 3.12.13 | 1 passed |
| Backend dependency consistency | `pip check` passed |
| Vendor identity and deterministic compatibility reconstruction | Passed |
| Dependabot published schema, Python lint, version/public-metadata checks | Passed |

The skipped test requires an isolated Redis instance and exercises orphan-event
purge recovery; no shared Redis database was used or flushed. The CLI smoke uses
a local server and mocked model responses, not the production service.

The full hosted backend suite, PostgreSQL/Redis service-backed checks, container
image rebuild/scans, browser release gates, and a new CodeQL run remain required
before release. No claim is made that GitHub alerts are already closed or that
production now runs the updated dependency graph.
