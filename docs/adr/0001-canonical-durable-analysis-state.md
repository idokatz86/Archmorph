# ADR 0001: Canonical durable analysis and workspace state

- Status: Accepted
- Date: 2026-07-19
- Decision owners: Backend and Security
- Scope: GitHub issue #1237

## Context

Archmorph previously exposed overlapping stores: live analysis dictionaries in
a TTL session store, optional workspace/version writes, an independent transient
version store, and an unused in-memory RBAC/analysis-owner registry. A cache loss
could therefore remove the only readable copy of an authenticated analysis, and
callers could skip the durable write.

## Decision

PostgreSQL is the canonical source for all durable product records. Redis is a
cache and coordination dependency only; loss of Redis must not delete durable
state or change ownership.

| Data | Canonical source | Cache / coordination | Consistency and ownership |
|---|---|---|---|
| Workspaces | PostgreSQL `workspaces` | None required | Strong; owner and tenant scoped |
| Analyses | PostgreSQL `analyses` | Redis `sessions` for hot reads | Strong durable commit, then cache refresh |
| Versions | PostgreSQL `analysis_versions` | Session cache may hold latest snapshot | Append-only; per-analysis sequence |
| Artifacts | PostgreSQL `artifacts`; external object storage only when referenced by the row | Generated response/cache is non-authoritative | Strong metadata/link ownership |
| Ownership and tenant membership | PostgreSQL owner/tenant columns and `team_members` | JWT/SWA claims are request identity, not authority storage | Exact owner plus tenant match; denied and missing both return 404 |
| Quota policy | PostgreSQL organization plan limits | Bounded user counters remain compatibility/display-only until a quota product is activated | No new quota product or enforcement is introduced here |
| Transient progress | Redis job envelopes, leases, events, and admission counters | In-process waiters are accelerators only | Eventual progress visibility; bounded retry and lease semantics |

`workspace_store.persist_analysis_state()` is the sole active authenticated
analysis write boundary. It resolves or creates the tenant-scoped workspace and
analysis, appends an immutable version, commits PostgreSQL, then refreshes the
shared cache. A cache failure cannot roll back or supersede the committed row.
Callers that need an immediately readable cache receive a retryable error after
the durable commit. Reads may hydrate a missing cache only from a query filtered
by both `owner_user_id` and `tenant_id`.

Authenticated durable writes require an explicit tenant claim. Individual GitHub
accounts, whose provider does not issue an organization tenant claim, use a
unique `github:<subject>` scope to preserve existing single-user behavior. There
is no shared `default_tenant` fallback. Anonymous, API-key, sample, and template
compatibility paths may remain tenantless and transient; they are not promoted
to durable user records.

## Failure domains and operations

- PostgreSQL failure domain: durable workspaces, analyses, versions, artifacts,
  ownership, and organization policy. Production startup/readiness fails closed
  when PostgreSQL is missing or unreachable.
- Redis failure domain: live cache, async progress, leases, events, and admission
  coordination. Production startup/readiness fails closed when Redis is missing
  or unreachable. Durable analysis records remain recoverable after Redis loss.
- Scaling trigger: any production deployment and any multi-worker/multi-replica
  deployment requires Redis. Stateless API replicas scale horizontally after
  PostgreSQL and Redis readiness pass.
- Logging coverage: durable write failures, cache refresh/hydration failures,
  denied metadata mismatches, and dependency readiness failures are logged with
  identifiers sanitized by the existing logging boundary.

## Compatibility and migration

No schema migration is required: migration `013` already created the canonical
workspace, analysis, version, artifact, and decision tables. Existing workspace
rows remain valid. Existing session-only records continue to work until their TTL
expires; the next authenticated analysis completion or restore creates/updates a
canonical durable record through the repository boundary. Session keys and all
public HTTP paths/response contracts remain unchanged.

The old in-memory RBAC organization/membership/quota/analysis-owner dictionaries
were removed after repository-wide import analysis proved no active route used
them. `RequireRole` remains as a state-free compatibility adapter for the model
registry. Durable organization services remain in `models.tenant` and
`services.tenant_service`.

The legacy transient version route contracts remain compatibility APIs; new
durable workspace version APIs and active authenticated analysis writes use
`analysis_versions`. Migrating the optional diff presentation metadata is not
required to establish durable analysis truth and is intentionally not a schema
expansion in this issue.

## Retention and deletion

- Redis analysis/session and uploaded-image cache: 2-hour sliding TTL.
- Redis async job/event state: 2-hour TTL; durable records are unaffected.
- Analysis versions: at most 50 unreferenced versions per analysis; versions
  referenced by artifacts or decisions are retained.
- Workspaces, analyses, artifacts, and ownership: retained until explicit
  workspace deletion; foreign keys cascade dependent analyses and versions.
- Audit/security logs: separate policy and storage; never treated as analysis
  cache and not deleted by cache loss.
- Existing session-only records are not backfilled blindly because a transient
  cache does not provide a trustworthy durable tenant migration source.

## Consequences

The system favors durable correctness over availability for authenticated writes
and production dependency startup. Redis can be rebuilt from PostgreSQL for
analysis reads, but PostgreSQL is never reconstructed from Redis. This avoids a
distributed transaction: the durable commit is authoritative and cache refresh
is an ordered projection.
