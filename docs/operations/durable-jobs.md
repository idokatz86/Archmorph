# Accepted async job durability

Archmorph treats a successful `202 Accepted` response from async analysis, IaC, or HLD generation as a durable commitment.

## Contract

Before returning `202`, the API persists all of the following in the shared job store:

- the job identity, owner, type, and public state;
- a versioned execution envelope containing only non-secret replay inputs;
- a SHA-256 input/configuration hash used as an atomic idempotency key;
- retry budget and lease metadata;
- the initial SSE event buffer.

Production uses Redis for this state. `REQUIRE_REDIS=true` makes startup fail instead of accepting jobs into revision-local storage when Redis is unavailable. Development can use memory or file storage, but those backends do not provide cross-revision durability.

Idempotency is scoped to the authenticated owner. A repeat submission for unchanged input/configuration returns the existing queued, running, or completed job and reports its current status; a different owner or changed configuration receives a distinct job.

A worker atomically claims a queued job using a lease token. Progress, heartbeat, completion, and failure transitions require the current live token. A stale worker cannot overwrite a replacement worker after lease expiry. Authenticated cancellation is an atomic terminal transition that revokes any live lease and releases analysis admission counters once.

Workers reconcile on startup and periodically. An expired running lease is requeued while attempts remain; exhausted jobs fail with a retry-budget error. Startup also rebuilds analysis admission counters from persisted active jobs. Recovery events remain in the SSE ring so reconnecting clients see continuity across workers and revisions.

The delivery guarantee is **at least once**. Handlers can run again after process loss, so canonical writes use existing compare-and-set/version guards and inputs are idempotent. The system does not promise exactly-once execution of external model calls.

## Settings

| Variable | Default | Purpose |
|---|---:|---|
| `JOB_LEASE_SECONDS` | `90` | Time a claim remains valid without a heartbeat. |
| `JOB_HEARTBEAT_SECONDS` | `15` | Lease renewal interval. Keep below one third of the lease. |
| `JOB_POLL_SECONDS` | `1` | Queue scan interval. |
| `JOB_RECOVERY_SECONDS` | `30` | Expired-lease reconciliation interval. |
| `JOB_MAX_ATTEMPTS` | `3` | Maximum claims before retry-budget failure. |
| `JOB_EVENT_RING_SIZE` | `200` | Retained SSE events per job. |
| `MAX_ACTIVE_JOBS_PER_USER` | `5` | Analysis admission limit per user/API principal. |
| `MAX_ACTIVE_JOBS_PER_TENANT` | `20` | Analysis admission limit per tenant. |

Operational constraints:

- `JOB_HEARTBEAT_SECONDS < JOB_LEASE_SECONDS`; production uses `15 < 90`.
- The job TTL must exceed the longest expected execution and reconnect window.
- Do not put credentials, raw images, generated code, or private endpoints in execution envelopes or logs.

## Monitoring and response

`GET /api/jobs/metrics/summary` exposes the shared-store backend, retryable backlog, and cumulative abandoned/recovered/retried totals. OpenTelemetry emits:

- `jobs.durable.abandoned_total`
- `jobs.durable.recovered_total`
- `jobs.durable.retried_total`
- `jobs.durable.retryable_jobs`

Azure Monitor alerts on any recovery event and on a retryable backlog sustained for 15 minutes.

When an alert fires:

1. Check Container Apps revision restarts and Redis availability/latency.
2. Inspect the job summary for retryable count and exhausted failures.
3. Verify the active revision has all three handlers registered.
4. Do not manually mutate Redis job records. Restore the dependency or deploy a fix and allow reconciliation to reclaim leases.
5. Confirm counters return to expected values and an authenticated SSE/poll client reaches a terminal state.
