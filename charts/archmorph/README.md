# Archmorph Helm chart

## Required runtime secrets

Production and staging fail closed unless one of these contracts is configured:

- `externalSecrets.enabled=true`, with every key below mapped from an approved secret store; or
- `existingSecret.name`, naming a Kubernetes Secret that already contains every key.

Required keys (values are never committed):

- `AZURE_OPENAI_API_KEY`
- `DATABASE_URL`
- `REDIS_URL`
- `APPLICATIONINSIGHTS_CONNECTION_STRING`
- `ARCHMORPH_ADMIN_KEY`
- `ARCHMORPH_API_KEY`
- `ARCHMORPH_API_KEY_ROTATED` (current credential during static-key rotation)
- `ARCHMORPH_API_KEY_PRINCIPAL_ID` (stable non-secret durable principal ID)
- `JWT_SECRET`

Use placeholder remote keys in public examples. Supply real secret-store names,
resource identifiers, endpoints, and values only through private deployment
configuration.

## Schema rollout

When `migrations.enabled=true`, Helm first runs a revisioned
`migration-secret-preflight` hook. It mounts every required Secret key as an
optional environment reference, then fails with a direct list of absent keys
before the migration hook is created. A missing Secret therefore produces a
clear diagnostic instead of a normal `ExternalSecret` first-install race.

The subsequent revisioned `pre-install,pre-upgrade` migration Job uses the same
immutable application image and `DATABASE_URL` secret as the Deployment. The Job
runs `run_migrations.py --expect-head <revision>`, which takes a PostgreSQL
advisory lock, executes Alembic, verifies the exact declared head, and exits
non-zero on any failure. Hooks use unique release-revision names and
`hook-succeeded` cleanup only; they never use `before-hook-creation`, so a second
release cannot delete an active migration Job.

Production and staging require `image.digest=sha256:<digest>`. Tags, including
`latest`, are rejected. Run releases with `helm upgrade --install` plus
`--atomic --wait`, and serialize install/upgrade operations in the owning GitOps or CI
controller. Helm storage locking plus the database advisory lock are defensive
backstops, not a replacement for release serialization.

The chart creates the application ServiceAccount when
`serviceAccount.create=true`. Migration hooks default to the namespace `default`
ServiceAccount because normal resources are not available to pre-install hooks;
set `migrations.serviceAccountName` only to a ServiceAccount provisioned before
the release. Any configured `imagePullSecrets` are propagated to the Deployment
and both migration hooks so private-registry first install is deterministic.

### External Secrets controller integration limitation

This repository has robust Helm render, ordering, RBAC, and failure-contract
tests but no disposable cluster integration for an External Secrets controller.
The ExternalSecret must be reconciled and its target Secret materialized before
running `helm install` or `helm upgrade`. Bootstrap it in a separate, serialized
GitOps/CI phase, wait for the ExternalSecret `Ready=True` condition and target
Secret keys, then run the chart. The chart intentionally fails first install
instead of waiting on or racing an external controller.

Application replicas only verify schema state; they never run DDL.
