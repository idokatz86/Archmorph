# Testing Standards

## FastAPI Parameter Testing

FastAPI treats plain scalar handler arguments as query parameters unless the route declares a body model, `Body(...)`, or explicitly reads the request body. Tests must send those values with `params=`, not `json=`. A JSON body sent to a query-only route is ignored by FastAPI and can make a test pass while it is exercising the default query value.

Use this pattern for query parameters:

```python
resp = client.post(
    f"/api/diagrams/{diagram_id}/export-diagram",
    params={"format": "drawio"},
)
```

Use `json=` only for routes that declare a request body in the OpenAPI contract:

```python
resp = client.post(
    f"/api/diagrams/{diagram_id}/apply-answers",
    json={"answers": {}},
)
```

CI runs `backend/scripts/lint_fastapi_query_body_tests.py` to catch `json=` calls that target query-only FastAPI routes in `backend/tests/**/*.py` and `tests/**/*.py`.

## CI Test Ownership

Every tracked directory named `test`, `tests`, or `__tests__` must have a named
workflow job in `docs/testing/ci-test-inventory.json`. The root
`repository-policy` job collects the safe root pytest suite. Non-pytest utility
scripts whose names match pytest discovery patterns must be listed as justified
`test_file_exceptions` in the inventory and as matching `--ignore` arguments in
CI. Manual exclusions require a `manual-local-path` classification; automated
exceptions require a `separately-collected` workflow, job, and command.
Automated files excluded because they use another runner must have a separate CI
collection command; the root Locust workload is validated with `locust --list`.
The inventory assertion fails for unmapped test directories, missing workflow
jobs, stale exclusions, or CI exclusions without inventory justification.

## Database Migration Safety

The `alembic-migration-smoke` CI job owns both the empty-database Alembic cycle
and the N-1 data-safety gate. The N-1 gate loads the sanitized fixture at
`backend/tests/fixtures/migration_n_minus_1.json` into an isolated temporary
PostgreSQL database at revision `013`, then migrates to
the repository head. The production backend deployment requires this job to
pass.

The gate verifies deterministic row counts and a canonical SHA-256 content
hash, foreign-key relationships, tenant/owner alignment, old-reader and
new-writer compatibility, downgrade contract behavior, total migration
duration, and absence of waiting locks. The gate validates the N-1 reader
contract before upgrading, commits that read transaction, and then applies the
migration within a five-second duration and subprocess timeout budget while
sampling the disposable database for waiting locks.

For safety, the test only creates its disposable database when
`MIGRATION_TEST_DATABASE_URL` uses PostgreSQL on localhost. It never migrates,
truncates, or drops the database named in that variable. Run it locally against
a disposable local PostgreSQL server with:

```bash
cd backend
MIGRATION_TEST_DATABASE_URL=postgresql://USER:PASSWORD@localhost:5432/archmorph \
  python -m pytest -n 0 tests/test_migration_safety.py
```
