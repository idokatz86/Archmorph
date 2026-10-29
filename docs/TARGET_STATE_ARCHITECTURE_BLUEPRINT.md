# Archmorph Target-State Architecture Blueprint

**Status:** Wave 0 foundations and Wave 1 safety implemented locally; reviewed integration/PR pending

**Date:** October 26, 2026

**Scope:** Backend, frontend, quality architecture, platform, and release governance

**Production impact:** None. Application deployment remains paused.

> This document synthesizes the October 2026 backend, frontend, quality, and
> platform audits into one incremental target state. It authorizes planning and
> PR-sized implementation only. It does not authorize a production deployment,
> infrastructure apply, traffic change, schema migration, or release resumption.

## 1. Executive Decision

Archmorph will evolve from a large FastAPI and React monolith into an
**enforceable modular monolith** with a durable asynchronous execution plane.
Container Apps remains the assumed application runtime until a separate
architecture decision establishes a concrete AKS-only requirement.

The technical north star is:

1. Tenant identity and authorization are explicit at every application boundary.
2. Domain modules own their state and contracts; transport and infrastructure are
   adapters.
3. PostgreSQL is authoritative, Redis is non-authoritative, and accepted
   asynchronous work survives process restarts.
4. The frontend has one route registry, one owner for each state category, and
   generated API contracts at its transport boundary.
5. A tested immutable artifact is promoted by one release controller through a
   human-approved, evidence-backed workflow.
6. Architecture, migration, contract, security, and critical-journey checks are
   aggregated into one release-readiness decision.

### 1.1 Approaches considered

| Approach | Decision | Reason |
| --- | --- | --- |
| Split directly into microservices | Rejected | Current boundaries, ownership, contracts, and operational failure modes are not stable enough. A service split would distribute existing coupling and add deployment complexity. |
| Preserve the current structure and refactor individual hotspots | Rejected | Local cleanup would not resolve competing data owners, import direction, release authority, or the process-local execution model. |
| Modular monolith with ports, durable workers, and strangler adapters | Selected | Establishes enforceable ownership and permits small reversible PRs while preserving URLs and deployment topology. |

The selected model is deliberately conservative: no service split is justified
until a module has stable contracts, independent scaling pressure, an accountable
owner, and evidence that separate deployment reduces rather than increases risk.

## 2. Baseline Constraints

- The audited local `main` snapshot is 29 commits behind `origin/main`. Upstream
  reconciliation must be reviewed and must preserve existing untracked work.
- Existing application deployment remains paused. No wave below resumes it
  automatically.
- The Azure Monitor email receiver confirmation remains an external operational
  blocker for end-to-end notification delivery.
- Existing public URLs and response envelopes remain compatible during boundary
  extraction unless a separately approved contract change says otherwise.
- Existing release, rollback, and migration guidance remains applicable:
  [Release Checklist](RELEASE_CHECKLIST.md),
  [Release Evidence](RELEASE_EVIDENCE.md), and
  [Rollback Runbook](runbooks/rollback.md).
- Regional or production infrastructure migration remains a parallel-build
  activity, consistent with the
  [Sweden Central migration plan](infra/sweden-central-migration-plan.md).

## 3. Target Backend Architecture

### 3.1 Bounded contexts

| Context | Owns | Does not own |
| --- | --- | --- |
| Identity and Access | Organizations, memberships, invitations, actor roles, tenant resolution, authorization policy | Workspace data, agent execution, UI session state |
| Workspaces | Workspace, source asset, analysis run, immutable analysis version, artifact metadata, decision records | AI provider calls, presentation state, external deployment |
| Translation | Normalized architecture model, mapping rules, refinement and merge policy | Persistence technology, HTTP schemas, provider credentials |
| Artifacts | IaC, HLD, diagram, report, cost, and package-generation use cases | Workspace authorization, direct HTTP handling |
| Agents and Executions | Agent definitions and versions, tool policy, execution lifecycle, cancellation, usage records | Raw secret storage, process-local background ownership |
| Integrations | GitHub, cloud inventory, deployment, and notification operation records, idempotency, retries | Core domain invariants |
| Platform | Database sessions, cache, messaging, secrets, telemetry, clocks, identifiers | Business workflows and domain decisions |

The canonical workspace aggregate is:

```text
Workspace
  ├── SourceAsset
  ├── AnalysisRun
  │     └── immutable AnalysisVersion
  ├── Artifact
  └── Decision
```

Session and cache records may project this state or hold temporary uploads. They
must never be the only authoritative record after a command is accepted.

### 3.2 Dependency direction

Every bounded context follows this direction:

```text
api/transport -> application -> domain
                         |
                         v
                    ports/protocols
                         ^
                         |
                 infrastructure adapters
```

Rules:

- Domain code imports only domain types and language-level libraries.
- Application code coordinates domain objects through declared ports.
- API modules map transport schemas to one application command or query.
- Infrastructure implements ports and may import SDKs, SQLAlchemy, Redis,
  filesystem, or provider clients.
- Infrastructure modules do not call routers.
- Bounded contexts communicate through application contracts or domain events,
  never another context's ORM models or repository implementation.
- Cross-context writes use a transactional outbox and idempotent handlers. Do not
  introduce distributed transactions.
- Temporary architecture exceptions require an owner, rationale, removal issue,
  and expiration date. The allowed violation count can only decrease.

The [source dependency policy](architecture/source-boundaries.md) is enforced in
CI. It complements the product rules described in
[Architecture Limitations Engine](ARCHITECTURE_RULES.md); the two rule sets have
different purposes and must not be conflated.

### 3.3 Package target

```text
backend/
  bootstrap/
    app.py
    settings.py
    lifecycle.py
    observability.py
    container.py
  platform/
    database.py
    cache.py
    messaging.py
    secrets.py
  identity/{domain,application,infrastructure,api}/
  workspaces/{domain,application,infrastructure,api}/
  translation/{domain,application,infrastructure,api}/
  artifacts/{domain,application,infrastructure,api}/
  agents/{domain,application,infrastructure,api}/
  integrations/{github,cloud_inventory,deployment,notifications}/
```

This is a target dependency shape, not permission for a bulk directory move.
Each package is introduced only as a tested vertical slice.

## 4. Composition Roots and Contract Ownership

### 4.1 Backend composition roots

`backend/bootstrap/app.py` is the sole application composition root. It:

- creates one validated immutable settings object;
- creates database, cache, queue, secret, model, and telemetry adapters;
- wires repositories and application services;
- registers explicit `/api/v1` routers and intentional compatibility aliases;
- owns startup, readiness, and shutdown;
- performs an Alembic-head readiness check but never creates or migrates schema.

The execution worker has a separate composition root. It uses the same settings
schema and application contracts but independently creates queue consumers,
leases, tool adapters, model gateways, and telemetry.

Import-time construction of engines, clients, repositories, and mutable stores is
not allowed in refactored packages.

### 4.2 Contract ownership

| Contract | Accountable owner | Source of truth |
| --- | --- | --- |
| Public HTTP API | API owner with bounded-context owner | Explicit FastAPI transport schema and committed OpenAPI snapshot |
| Frontend client | Frontend owner | Generated OpenAPI path/type artifacts consumed through the shared HTTP client |
| CLI and SWA consumers | Respective consumer owner | Consumer-contract tests against the public API |
| Application command/query | Bounded-context owner | Typed application request/result and typed failures |
| Repository, queue, model, secret, clock ports | Context application owner | Protocol/interface next to the consuming application layer |
| Domain event | Producing context | Versioned event schema; consumers cannot mutate producer state |
| Database schema | Backend/database owner | Alembic migrations only |
| Release manifest | Platform/release owner | Immutable manifest referencing source SHA, image digest, SBOM, provenance, schema contract, and evidence |
| Infrastructure module inputs/outputs | Platform owner | Versioned Terraform root interface |

Breaking API approval must be bound to the current PR, base and head schema
hashes, named break identifiers, approver, and expiry. A reusable non-empty
approval file is not valid release evidence. Repository variable
`OPENAPI_AUTHORIZED_APPROVERS` must name at least one reviewer other than the
pull-request author; author approvals are rejected and an owner-only
configuration fails closed.

### 4.3 Persistence and consistency

- PostgreSQL provides strong consistency within one command and bounded-context
  transaction.
- An outbox record is committed with domain state before asynchronous publication.
- Execution transitions are conditional and monotonic:

  ```text
  queued -> running -> completed | failed | timed_out
  queued | running -> cancellation_requested -> cancelled
  ```

- Redis contains cache, temporary upload, lease, and progress projections only.
- External integration mutations are eventual, idempotent, retry-budgeted, and
  recorded with operation and idempotency identifiers.
- Secrets are referenced by identifier and resolved at invocation. Provider keys
  are not persisted in general JSON fields or returned in repository entities.

## 5. Target Frontend Architecture

### 5.1 Module boundaries

```text
frontend/src/
  app/
    AppShell.jsx
    providers.jsx
    routeRegistry.js
    AppRouter.jsx
  features/
    auth/
    workbench/
      api/
      model/
      orchestration/
      persistence/
      components/
    history/
    templates/
    services-catalog/
    drift/
    roadmap/
  shared/
    api/
      httpClient.js
      generated/
    ui/
    hooks/
```

Dependency direction is:

```text
app -> features -> shared
feature components -> feature orchestration/model -> feature API -> shared API
shared !-> features
feature A !-> feature B internals
```

Feature-to-feature interaction uses navigation parameters or an exported feature
contract. Components must not call `fetch`, embed backend route strings, or
coordinate cross-feature persistence.

### 5.2 State ownership

| State category | Sole owner | Examples |
| --- | --- | --- |
| URL/navigation | Route registry and router adapter | Active route, durable route parameters, feature gates |
| Global client state | Auth store only | Authenticated actor, session lifecycle |
| Feature state | Feature-local reducer/state machine | Workbench step, job, artifact, error, cancellation |
| Server state | Feature API/orchestration hook | Loading, success, empty, error, retry, cancellation |
| Component state | Component | Focus, expanded state, temporary input, presentation |
| Durable browser persistence | Named persistence adapter | Explicitly allowlisted recovery data with version and expiry |

Auth context and Zustand must not remain independent mutable owners. The selected
auth store is canonical; any React provider is a thin subscription adapter.
Theme and SSE behavior likewise have one implementation each.

The workbench remains feature-local. Its unrestricted partial update action is
replaced with named events and invariant tests before stage components are split.
The large controller is reduced through orchestration-hook extraction while
preserving current UI props and hash URLs.

### 5.3 Shared UI and accessibility

Shared dialog, tabs, buttons, fields, async boundaries, and error presentation
are owned in `shared/ui`. They must provide:

- focus trapping and restoration for dialogs;
- unique accessible-name relationships;
- keyboard-complete tabs;
- busy, alert, and live-region semantics;
- serious and critical axe findings as blocking failures.

## 6. Infrastructure and Release Authority

### 6.1 Authority map

| Surface | Sole authority | Boundary |
| --- | --- | --- |
| Azure resources, identities, networking, diagnostics, runtime configuration structure | Terraform | Does not select application image or shift release traffic |
| Application image, schema migration job, revision, verification, traffic, rollback manifest | One release controller | Consumes an existing digest; does not rebuild artifacts |
| Frontend artifact promotion | Same release decision and manifest | Deploys the tested artifact associated with the selected build |
| Monitoring resources and notification configuration | Isolated monitoring Terraform root/workflow | Never deploys the application |
| Database schema | Serialized migration job | Application startup checks head; it does not migrate |
| Emergency rollback | Manifest-backed release controller | Selects a known schema-compatible revision |
| Helm | Separate AKS environment only, if explicitly approved | Not a second controller for Container Apps production |

The release controller selection is an architecture decision that must be recorded
before production changes. Until then, no existing workflow gains authority by
default.

### 6.2 Infrastructure roots

The target Terraform ownership roots are:

```text
foundation
network
data
runtime
observability
release-monitoring
```

Each root has a distinct state key, OIDC role, plan artifact, approval boundary,
drift schedule, and CODEOWNER. Root extraction follows state-adoption and
zero-surprise-plan procedures; it is never performed as an unreviewed state move.

### 6.3 Promotion model

1. A PR produces tests, scans, SBOMs, provenance, contract evidence, and artifacts.
2. Merge to `main` builds and publishes only; it does not mutate production.
3. A protected manual promotion selects an exact successful build and digest.
4. One durable rollout lease serializes migration, release, rollback, and
   infrastructure mutation that could conflict with a release.
5. The controller validates schema compatibility and runs one migration job.
6. A zero-traffic revision receives authenticated smoke and synthetic checks.
7. Traffic moves progressively with explicit abort thresholds.
8. The prior compatible revision remains available.
9. The signed release manifest and final evidence are retained.

Production must never resolve `latest`, rebuild during promotion, or interpret a
monitoring-query failure as zero application failures.

## 7. Scaling, Reliability, Security, and Observability

### 7.1 Scaling model

- API replicas scale on concurrency and p95 latency.
- Execution workers scale on oldest queued age and queue depth.
- Model admission is limited by provider quota, tenant budgets, and saturation.
- PostgreSQL, Redis, provider quota, and integration dependencies are explicit
  failure domains, not hidden fallbacks.

Initial reliability objectives:

- API availability: 99.9%.
- No accepted `202` execution is lost after process restart.
- Submission and external mutations are idempotent.
- Provider and integration retries are bounded.
- Rollback uses old-binary/schema compatibility, not destructive downgrade.

The detailed service indicators remain owned by [SLO](SLO.md).

### 7.2 Security baseline

- `ActorContext` is constructed from authenticated identity, never caller-supplied
  tenant input.
- One `TenantId`, backed by the organization record, is required on tenant-owned
  records.
- Repository methods require tenant scope; agent definitions, versions, clones,
  and executions use the same ownership predicate.
- Production configuration fails closed for PostgreSQL, Redis, JWT, telemetry,
  origin lock, release metadata, and expected worker topology.
- Key Vault plus managed identity is the default secret boundary.
- Sensitive changes require code-owner review and two independent approvals:
  migrations, auth/tenant boundaries, breaking API changes, production workflows,
  and destructive Terraform changes.

### 7.3 Observability contract

Every command and execution records correlation ID, actor ID, tenant ID,
aggregate ID, execution ID, transition, provider, latency, retry count, token
usage, release identifier, and normalized failure code as applicable.

Platform Engineering owns collection, alert infrastructure, release telemetry,
and runbooks. Application owners own instrumentation and endpoint SLOs. Security
owns audit and security-event policy. Monitoring-system failure alerts separately
from application-health failure.

## 8. Mandatory Risk Gates

### 8.1 P0 gates

No structural refactor slice may merge until the applicable P0 gate is present.
No production promotion may resume until all P0 release gates are verified.

| Gate | Blocking condition | Required evidence |
| --- | --- | --- |
| Deployment pause | Any workflow can deploy from a push to `main`, or production has no independent reviewer | Protected environment configuration, required approval, and build-only push workflow |
| Release aggregation | Production deployment depends on selected jobs rather than one immutable `release-ready` decision | Aggregate job proves backend, frontend, contracts, migrations, architecture, IaC, E2E, security, and touched-path performance |
| Tenant isolation | Agent or execution access can omit authenticated tenant scope | Negative cross-tenant contract tests and repository predicates |
| Durable execution | Accepted work is process-local or cancellation can be overwritten | Lease/recovery and conditional-transition tests |
| Schema authority | Runtime calls `create_all`, tolerates schema mismatch, or migration is not a release job | Alembic-head readiness failure and serialized migration evidence |
| Migration safety | Only an empty-database cycle is tested | Sanitized N-1 fixture, data invariants, expand/contract proof, old/new binary compatibility, lock-duration budget |
| API compatibility | A stale approval can authorize an unrelated break | Mature compatibility result and approval bound to hashes and current PR |
| Workbench invariants | Orchestration extraction changes behavior without characterization | Golden workflow tests, explicit reducer transitions, cancellation and recovery tests |
| Checkout currency | Release work uses the stale local snapshot | Reviewed reconciliation with upstream that preserves unrelated work |

### 8.2 P1 gates

| Gate | Blocking condition | Required evidence |
| --- | --- | --- |
| Source boundaries | A touched module introduces a forbidden dependency or cycle | Import/dependency graph check with ratcheted exception baseline |
| Contract use | Refactored frontend bypasses shared API or generated contracts | Static boundary check and consumer-contract tests |
| Type safety | Touched backend/frontend seams add unchecked types | Mypy for refactored packages and JS/TS checking for API, store, and orchestration seams |
| Coverage | Refactored critical behavior falls below thresholds | Changed lines >=90%, branches >=80%; auth/tenant/migration/persistence/export branches >=90% |
| Root policy tests | A tracked test directory is not mapped to CI | Repository-policy job and test-inventory assertion |
| Accessibility | Serious/critical violations or conditional no-op E2E assertions pass | Blocking axe checks and explicit assertion/skip prerequisites |
| Immutable packaging | Production can use a mutable tag or rebuilt artifact | Digest-based manifest with SBOM, provenance, source SHA, and scan evidence |
| Runtime configuration | Required production dependency can silently fall back | Typed startup contract and fail-closed readiness tests |
| Release authority | Terraform, CLI, Helm, and CI can independently mutate the same workload | Approved authority map and enforcement tests |
| Production hardening | Live production posture differs from declared controls | Parallel migration plan, adopted state, private connectivity proof, rollback drill |
| Dependency governance | A deployable manifest is unaudited or unlocked | Audit/update coverage, deterministic lock, and component SBOM |

Quality conventions in [Testing Standards](TESTING_STANDARDS.md) continue to
apply. Generated output changes must also satisfy the
[Generated Artifact Validation Matrix](GENERATED_ARTIFACT_VALIDATION_MATRIX.md).

## 9. Migration Waves

Each wave is a collection of small PRs. Entry and exit criteria are cumulative.
A wave may prepare release controls while deployment remains paused.

### Wave 0 - Governance and evidence baseline

**Entry**

- Audit blueprint approved as the planning baseline.
- Worktree status and upstream divergence recorded.

**Work**

- Reconcile the reviewed upstream changes without overwriting untracked work.
- Record architecture ownership and temporary dependency exceptions.
- Add source-boundary checks, repository-policy test collection, and test inventory.
- Define `release-ready` and immutable release evidence without deploying.
- Replace reusable OpenAPI breaking-change approval.

**Exit**

- Every tracked test surface maps to CI.
- Boundary checks run with an owner-tagged, expiring baseline.
- Release-readiness aggregation is testable and cannot deploy.
- Deployment remains paused.

### Wave 1 - P0 safety boundaries

**Entry**

- Wave 0 gates are green.
- Characterization corpus exists for auth, agent execution, workspace recovery,
  exports, and API contracts.

**Work**

- Tenant-scope agent APIs and repositories through authenticated `ActorContext`.
- Make execution transitions conditional and repair tenant propagation.
- Remove production runtime schema creation; enforce Alembic-head readiness.
- Add seeded N-1 migration and old/new binary compatibility tests.
- Fix the frontend transport options contract and direct-fetch bypasses.

**Exit**

- Cross-tenant access and stale cancellation completion are impossible in tests.
- Schema mismatch fails readiness.
- Migration gates prove zero data/ownership loss and the lock-duration budget.
- Frontend requests flow through one transport boundary.

### Wave 2 - Composition and stable contracts

**Entry**

- Wave 1 P0 tests are blocking.

**Work**

- Introduce typed settings, unit of work, clock, identifiers, and secret ports.
- Establish backend API and worker composition roots.
- Introduce the frontend route registry and canonical auth store.
- Consume generated API artifacts through feature API modules.
- Add typed error and application command/query contracts.

**Exit**

- Refactored packages have no import-time infrastructure construction.
- Route labels, gates, navigation, and rendering come from one registry.
- Touched seams pass type, contract, boundary, and changed-line coverage gates.

### Wave 3 - Workspace and workbench convergence

**Entry**

- Composition roots can wire old and new adapters behind stable contracts.

**Work**

- Declare durable workspace records canonical.
- Implement a compatibility adapter for the legacy project/session interface.
- Extract workbench analysis-job, recovery, and capability orchestration.
- Replace unrestricted reducer mutation with named events and invariants.
- Consolidate SSE, theme, dialogs, tabs, and error presentation.

**Exit**

- PostgreSQL remains authoritative across process restart.
- Cache/session expiry cannot delete the canonical workspace representation.
- Old and new paths pass differential contract and golden-output tests.
- Workbench cancellation, restore, export recovery, and accessibility gates pass.

### Wave 4 - Durable execution and unified model gateway

**Entry**

- Workspace and execution contracts are stable and tenant-scoped.

**Work**

- Add database-backed command/outbox and leased execution worker.
- Add cancellation acknowledgment, retry budgets, and idempotency.
- Introduce model, tool, credential, and usage ports.
- Adapt translation and agent execution incrementally to the unified gateway.

**Exit**

- Accepted work survives API and worker restart.
- Duplicate claims and stale transitions are rejected.
- Provider failures are typed and model-visible tool-error JSON is eliminated.
- Queue age, execution state, retries, usage, and tenant attribution are observable.

### Wave 5 - Release authority and platform hardening

**Entry**

- Waves 0-4 are green.
- One release-controller decision and accountable operator are recorded.

**Work**

- Separate build from promotion and require protected manual approval.
- Promote immutable digests and signed manifests.
- Split Terraform roots through reviewed state adoption.
- Complete monitoring ownership migration and alert on query/delivery failures.
- Build the parallel production-hardening path and prove DR.

**Exit**

- One controller owns migration, revision, traffic, verification, and rollback.
- Terraform plans have no unexplained creates, destroys, or state drift.
- Authenticated canary, rollback, monitoring, data restore, secrets, cache, and
  customer-transaction drills pass.
- A human explicitly authorizes deployment resumption. Without that decision,
  deployment remains paused even when all technical gates are green.

## 10. Explicit Non-Goals

- No production code refactor in this architecture-audit deliverable.
- No merge, deployment, Terraform apply, traffic shift, migration, secret change,
  GitHub environment change, or branch-protection mutation.
- No direct microservice decomposition.
- No AKS adoption or Helm authority for the Container Apps workload.
- No replacement of hash navigation solely to introduce a routing library.
- No move of the workbench state object into global Zustand.
- No broad frontend TypeScript rewrite; type checking starts at changed seams.
- No dual-write without reconciliation, idempotency, and removal criteria.
- No destructive database downgrade as the normal rollback mechanism.
- No claim that staging or DR is ready before production-equivalent recovery proof.
- No in-place production hardening or regional move without a parallel migration
  and rollback path.
- No increase in functional scope, billing activation, or unrelated feature work.

## 11. Incremental Implementation Backlog

Every item is intentionally sized for one focused PR. A PR includes tests and
directly related docs; it must not bundle the next item.

| ID | PR-sized outcome | Depends on | Definition of done |
| --- | --- | --- | --- |
| ARC-001 | Add Python and frontend dependency-direction checks with an exception manifest | None | Implemented by `scripts/check_source_boundaries.py`; existing violations are baselined with owner/expiry and new violations fail CI |
| QLT-001 | Run root repository-policy tests and assert every test directory has a CI owner | None | Root tests collected; unmapped test directory fails |
| REL-001 | Add non-deploying `release-ready` aggregation | QLT-001 | All named critical jobs aggregate; no production mutation |
| API-001 | Bind breaking-change approval to PR, schema hashes, break IDs, approver, and expiry | None | Stale/unrelated approval test fails |
| DB-001 | Add production Alembic-head readiness and remove runtime `create_all` from production path | None | Schema mismatch blocks readiness; local/test bootstrap remains explicit |
| DB-002 | Add sanitized N-1 migration fixture and data-invariant assertions | DB-001 | Row, hash, relationship, tenant, duration, and lock assertions pass |
| IAM-001 | Introduce `ActorContext` and one tenant identifier contract | ARC-001 | Context derives tenant from authenticated identity |
| IAM-002 | Tenant-scope agent CRUD and repository queries | IAM-001 | Cross-tenant negative tests cover definitions, versions, and clones |
| EXE-001 | Enforce conditional execution transitions and correct tenant propagation | IAM-001 | Cancellation cannot become completed; tenant reaches model/tool path |
| CFG-001 | Introduce immutable typed settings without changing runtime behavior | ARC-001 | Production-required settings validate; focused compatibility tests pass |
| BE-001 | Create backend app composition root around existing adapters | CFG-001 | Router URLs unchanged; no new import-time clients |
| FE-001 | Normalize shared API client options and binary/cancellation handling | API-001 | Cost/profile/client regression tests pass |
| FE-002 | Add one route registry while preserving hash URLs | ARC-001 | App, nav, command palette, and feature gates consume registry |
| FE-003 | Make auth store canonical and provider a subscription adapter | FE-002 | One mutable auth owner; bootstrap/logout tests pass |
| WS-001 | Add durable workspace adapter for the legacy project interface | BE-001, IAM-001 | Restart/recovery and authorization characterization tests pass |
| FE-004 | Extract `useAnalysisJob` and use the shared SSE hook | FE-001 | Current component props retained; abort/reconnect tests pass |
| FE-005 | Extract recovery/capability orchestration | FE-004 | Restore and export-token retry behavior is characterized |
| FE-006 | Replace unrestricted workflow mutation with named events | FE-005 | Invalid states rejected by reducer invariants |
| UI-001 | Consolidate dialog/tabs/error/button accessibility primitives | ARC-001 | Keyboard tests and serious/critical axe gates pass |
| EXE-002 | Add outbox and leased database-backed execution worker | EXE-001, BE-001, DB-002 | Restart, duplicate-claim, lease-expiry, and idempotency tests pass |
| AI-001 | Introduce model gateway, credential, tool, and usage ports around one existing path | EXE-002, CFG-001 | Existing output contract retained; typed failures and telemetry verified |
| REL-002 | Separate build from protected manual digest promotion | REL-001 | Push cannot deploy; promotion selects attested digest and manifest |
| INF-001 | Publish and enforce release/Terraform/monitoring authority map | REL-002 | Conflicting workflow mutation paths fail policy tests |
| MON-001 | Move telemetry queries to isolated monitoring ownership and fail distinctly | INF-001 | Query failure cannot report zero app errors; delivery evidence retained |
| INF-002 | Produce no-apply root-split and production-hardening adoption plan | INF-001 | State backup, import map, zero-surprise plan, rollback owner documented |
| DR-001 | Execute production-equivalent restore/failover rehearsal in an approved environment | INF-002, MON-001 | Data, secrets, Redis, image, DNS, smoke, and rollback evidence pass |

Backlog sequencing follows dependencies, not table order. Parallel PRs are allowed
only when they do not edit the same authority boundary or invalidate another
item's characterization baseline.

## 12. Ownership and Decision Records

| Area | Accountable owner |
| --- | --- |
| Target architecture and boundary exceptions | Technical architecture owner |
| Identity, migrations, application contracts | Backend/database owner |
| Frontend modules, state, accessibility, client contracts | Frontend owner |
| Test topology and release evidence | QA/test architecture owner |
| Promotion, rollback, infrastructure roots, monitoring | Platform/SRE owner |
| Security scans, secrets, exception policy | Security owner |
| Public API compatibility | API owner plus affected bounded-context owner |

The following decisions require a short architecture decision record before the
dependent backlog item begins:

1. Canonical production release controller.
2. Named production environment reviewers and CODEOWNERS.
3. Harden-in-parallel destination for the legacy dev-named production stack.
4. Queue technology after the database-leased worker proves the execution port.
5. Any module proposed for independent service deployment.

## 13. Definition of Blueprint Completion

This architecture-audit deliverable is complete when:

- the four audit domains are represented in one target state;
- bounded contexts, dependency direction, contracts, composition roots, frontend
  state, infrastructure authority, risk gates, waves, and non-goals are explicit;
- the implementation backlog is PR-sized and dependency-aware;
- referenced repository paths are valid in the audited checkout;
- no production code or deployment control is changed; and
- application deployment remains paused.
