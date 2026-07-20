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

`workspace_store.persist_analysis_mutation()` is the sole active authenticated
analysis write boundary. Analysis add/apply, review dispositions, HLD, IaC,
infrastructure import, cost configuration, migration timeline, network topology,
IaC chat code/history/clear, async completion, and compatibility version routes
all use it. It resolves or
creates the tenant-scoped workspace and analysis, appends an immutable version,
persists any generated HLD/IaC `Artifact` against that exact version, commits
PostgreSQL, then refreshes the shared cache. A cache failure cannot roll back or
supersede the committed row.
Callers that need an immediately readable cache receive a retryable error after
the durable commit. Reads may hydrate a missing cache only from a query filtered
by both `owner_user_id` and `tenant_id`.

Authenticated durable writes require an explicit tenant claim. SWA GitHub,
Google, and AAD identities without a tenant claim use an opaque SHA-256
provider-subject scope derived only from immutable provider and subject values.
The durable owner remains the stable provider user ID already used by API and
workspace ownership contracts; direct B2C uses its verified immutable provider
subject because legacy B2C rows were keyed by that subject. Mutable
email/login/display-name values are never used for either owner or tenant
identity.
There is no shared `default_tenant` fallback. Legacy tokens carrying that value
map to the same provider-subject scope used by current tokens. API keys map to
opaque service-principal owner/tenant markers and use the same durable UoW. Only
anonymous development, sample, and template compatibility paths may remain
tenantless and transient; they are not promoted to durable user records.

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

Migration `014` widens tenant scopes, rehomes the explicit pre-hardening
`github:github_<subject>` alias to its deterministic provider-subject namespace,
and leaves ambiguous `default_tenant` rows untouched until exact-owner access by
a currently verified provider principal. It writes row counts to
`tenant_rehome_audit`, merges duplicate analysis identities while preserving and
renumbering all versions/artifacts/decisions, removes exact duplicate artifacts,
and retains legacy/target conflicts in place for operator review. It then adds
partial unique durable analysis identity `(owner_user_id, tenant_id, diagram_id)`,
idempotent artifact identity `(version_id, artifact_type, content_hash)`, and one
`is_default` workspace per owner/tenant. Downgrade intentionally retains widened
tenant columns, preventing opaque tenant truncation during `014 → 013 → 014`.

The old in-memory RBAC organization/membership/quota/analysis-owner dictionaries
were removed after repository-wide import analysis proved no active route used
them. `RequireRole` remains as a state-free compatibility adapter for the model
registry. Durable organization services remain in `models.tenant` and
`services.tenant_service`.

Legacy diagram version route contracts now adapt to `analysis_versions` for
signed-in users and API-key service principals. Anonymous/sample callers retain
an explicitly marked transient compatibility response and cannot write transient
state into an authenticated canonical namespace.

`restore-session` requires either an existing same-owner namespace, a durable
same-owner analysis, or a reusable signed restore capability issued at upload
and bound to diagram plus user/tenant or API-key marker. Missing and unauthorized
claims return the same 404 response. Export capabilities are principal-bound as
well and are never stored in durable snapshots.

Legacy `default_tenant` cache entries and exact-owner durable rows are rehomed
only from an authenticated provider principal's verified current scope, or are
replaced by the already-migrated target-tenant durable version. Raw owner text
never selects the provider. If legacy and target durable identities conflict,
access fails with the same 404 and emits a conflict audit event; neither scope
nor cache is promoted.

Concurrent writers are serialized by row locks after the unique identity insert
and retry PostgreSQL uniqueness conflicts. Version allocation uses the maximum
durable version plus the analysis pointer. Redis projections carry the committed
`_analysis_version`; exact-owner compare-and-set rejects an older projection
after a newer commit, preventing completion-order reversal or ownerless cache
claims.

`/healthz` remains anonymous process liveness. `/readyz` is anonymous and
sanitized but returns 503 unless required PostgreSQL and Redis probes succeed.
Terraform Container Apps/Front Door/availability readiness and Helm readiness
use `/readyz`; startup and liveness continue to use `/healthz`.

## Retention and deletion

- Redis analysis/session and uploaded-image cache: 2-hour sliding TTL.
- Redis async job/event state: 2-hour TTL; durable records are unaffected.
- Analysis versions: at most 50 unreferenced versions per analysis; versions
  referenced by artifacts or decisions are retained.
- Workspaces, analyses, artifacts, and ownership: retained until explicit
  workspace deletion; foreign keys cascade dependent analyses and versions.
- Diagram purge: synchronously deletes tenant-scoped decisions, artifacts,
  versions, and the analysis before issuing its receipt; an empty implicit
  default workspace is deleted as well.
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
