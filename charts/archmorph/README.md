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
- `JWT_SECRET`

Use placeholder remote keys in public examples. Supply real secret-store names,
resource identifiers, endpoints, and values only through private deployment
configuration.

## Schema rollout

When `migrations.enabled=true`, Helm runs a `pre-install,pre-upgrade` Job using
the same immutable application image and `DATABASE_URL` secret as the
Deployment. The Job runs `run_migrations.py`, which takes a PostgreSQL advisory
lock, executes Alembic to `head`, verifies the required schema, and exits
non-zero on any failure. Helm does not roll application pods until this hook
succeeds. Application replicas only verify schema state; they never run DDL.
