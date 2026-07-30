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

`ARCHMORPH_API_KEY_ROTATED` is optional only in the default development values;
production and staging require it to make rollout wiring deterministic. The
ConfigMap flag `ARCHMORPH_API_KEY_ALLOW_LEGACY_OVERLAP` controls the policy:

1. Keep `ARCHMORPH_API_KEY_PRINCIPAL_ID` unchanged.
2. Materialize `ARCHMORPH_API_KEY_ROTATED` and set overlap to `"true"`; both
	base and current credentials authenticate as the same static principal.
3. Move callers to the current credential.
4. Set overlap to `"false"`; the base credential is rejected immediately.
5. Promote the current credential to the base secret and remove the optional
	rotated secret before the next rotation.

Never derive or change the principal identifier from either credential value.
Managed API keys use `read`, `write`, and `admin` scopes. `read` authorizes only
safe reads, `write` authorizes mutations, and `admin` authorizes both plus API
key management. Static service credentials are service administrators.

Project member assignments support only `viewer` and `editor`; there is no
assignable project-level `admin` role. The project owner and active tenant
owner/admin can manage members and all project actions. Editors can read,
generate, and mutate diagrams but cannot manage members. Viewers can read
project status, combined analysis, and diagrams only.

Use placeholder remote keys in public examples. Supply real secret-store names,
resource identifiers, endpoints, and values only through private deployment
configuration.

## Schema rollout

The owning release controller renders and applies a uniquely named
`migration-secret-preflight` phase before the migration phase. It mounts every required Secret key as an
environment reference, resolves `DATABASE_URL`, executes `SELECT 1`, and checks
every revision in `migrations.acceptedCurrentAlembicRevisions` before the migration Job is
created. A missing Secret, inaccessible database, or unexpected schema therefore
fails before DDL instead of becoming a normal `ExternalSecret` first-install
race or a partial migration.

The subsequent separately applied migration Job uses the same
immutable application image and `DATABASE_URL` secret as the Deployment. The Job
runs `run_migrations.py` with one canonical JSON runtime-envelope argument. The
envelope binds the phase, reviewed revision contract, bootstrap decision, unique
execution marker, and immutable image digest without passing leading-option
tokens through the container runtime. The runner takes a PostgreSQL
advisory lock, validates that the reviewed target exists and is reachable from
the current revision, upgrades only to that target, verifies the exact declared head, and exits
non-zero on any failure. If the database is already at that exact head, the
runner validates readiness and emits evidence without running DDL. Phase Jobs use
unique run/attempt names, `activeDeadlineSeconds`, and
`ttlSecondsAfterFinished`. Kubernetes TTL cleanup therefore bounds both failed
and successful history without ever deleting an active execution.

For a brand-new database only, set `migrations.bootstrapEmptyDatabase=true` in
an explicitly reviewed first-provisioning values file. Both preflight and
migration then require that `alembic_version` is absent and that no application
objects exist before applying the reviewed `expectedAlembicHead`. Leave the flag
false for all existing environments. A database with non-Alembic objects, or a
credential/SQL failure, is never treated as empty and fails closed.

Production and staging require `image.digest=sha256:<digest>`. Tags, including
`latest`, are rejected. The manual workflow does not accept a digest or source
SHA directly: it selects one exact successful CI/CD run and attempt, downloads
immutable build evidence, verifies the GitHub SLSA attestation against this
repository and build workflow, then inspects the exact OCI digest, labels,
platform, and embedded schema contract before cluster mutation. The controller verifies the currently serving image's
schema contract before migration. If it excludes the target schema, a reviewed
immutable bridge that accepts both revisions is brought up and selected by the
Service before DDL. After migration, the bridge (or a verified compatible prior
image) stays serving while a workload-only `helm upgrade --install --wait` runs
with `migrations.enabled=false`. The workload phase intentionally does **not** use
`--atomic`: target readiness failure is explicit fix-forward and never rolls the
workload back across a committed schema boundary.
Production/staging rendering fails when `migrations.phase=disabled` while
`migrations.enabled=true`; only the serialized owner may enter the workload phase,
and it must set `migrations.enabled=false` after both Jobs complete.

The chart creates the application ServiceAccount when
`serviceAccount.create=true`. Migration phases require a dedicated ServiceAccount
provisioned before release; production and staging use explicit environment names,
never `default`. The Jobs disable token automount and require no Kubernetes API
RBAC. Any configured `imagePullSecrets` are propagated to the Deployment and both
migration phases so private-registry execution is deterministic.

### External Secrets controller integration limitation

This repository has robust Helm render, ordering, RBAC, and failure-contract
tests but no disposable cluster integration for an External Secrets controller.
The ExternalSecret must be reconciled and its target Secret materialized before
running `helm install` or `helm upgrade`. Bootstrap it in a separate, serialized
GitOps/CI phase, wait for the ExternalSecret `Ready=True` condition and target
Secret keys, then run the chart. The chart intentionally fails first install
instead of waiting on or racing an external controller.

The owning executable path is `scripts/helm_release.sh`, invoked by the manual
`Helm Release` workflow. Before the namespace Lease, the workflow acquires the
same private Azure Blob rollout lease used by Container Apps, Terraform apply,
and rollback. Every schema-safe checkpoint observes durable rollback priority;
GitHub's one-pending-run slot is not the lock. It then acquires a namespace Lease with holder identity,
acquire/renew timestamps, duration, periodic heartbeat, bounded wait, and
resourceVersion compare-and-swap. Normal exit releases only the currently owned
record; a runner lost without cleanup expires, and a live holder cannot be
stolen. It fails clearly when the
External Secrets CRD/controller is unavailable, applies and waits for the
ExternalSecret when configured, verifies required Secret keys, then renders the
chart against that pre-existing Secret. The workflow records previous/target
image contracts, build-provenance digest, schema phases, customer-degraded state,
failure action, and a signed final release manifest. A retained bridge emits the
severity-1 Platform Engineering page. The workload carries explicit final role, source
SHA, and canonical schema-contract digest environment metadata, all checked
against the deployed Deployment before the manifest is signed.

Application replicas only verify schema state; they never run DDL.
