# Release Evidence

This file records production readiness evidence for release checkpoints. Keep secrets out of this file; reference GitHub Actions, commit SHAs, and smoke summaries only.

## 2026-04-28 Dependency And Security Checkpoint

- Commit: `904132a592a1e9744a6a98ab54ddaa56c7f91059`
- Purpose: Resolve remaining Dependabot updates and verify security alert surfaces.
- Branch: `main`
- GitHub Actions: all check runs completed successfully for the checkpoint commit.
- Passing checks: Dependabot update jobs, `update-pip-graph`, Trivy container scan, CodeQL JavaScript, CodeQL Python, SLA verification, and tests.
- Alert status: no open Dependabot security alerts, code scanning alerts, or secret scanning alerts were reported by the GitHub APIs after the checkpoint.
- Dependabot PR status: stale superseded Dependabot PRs were commented and closed after their dependency updates landed on `main`.

### Local Verification

- Backend lint: `/Users/idokatz/VSCode/Archmorph/backend/.venv/bin/python -m ruff check backend` passed.
- Backend tests: `/Users/idokatz/VSCode/Archmorph/backend/.venv/bin/python -m pytest backend/tests` passed with `1554 passed, 1 skipped`.
- Frontend audit: `npm --prefix frontend audit --audit-level=moderate` reported `0 vulnerabilities`.
- Frontend lint: `npm --prefix frontend run lint` passed.
- Frontend tests: `npm --prefix frontend test -- --run` passed with `262 passed`.
- Frontend build: `npm --prefix frontend run build` passed with Vite `8.0.10`.
- Patch hygiene: `git diff --check` passed.

### Manual Smoke Scope

- Frontend root, translator, playground, service browser, roadmap, and admin release status are covered by automated component, build, and post-deploy checks.
- Drift baseline smoke is covered by `frontend/src/components/__tests__/DriftVisualizer.test.jsx` and backend drift tests.
- Playwright smoke: `npx playwright test` passed on 2026-04-28 with 17 tests covering home/navigation, upload, sample onboarding, mapped results, React Flow canvas, guided questions, IaC panel, export affordance, chatbot shell, and critical accessibility scans.
- Live production smoke remains the release operator's final sign-off when changing deployed environment variables or enabling scaffold feature flags.

## 2026-04-28 Release Hardening Pass

- Purpose: Reduce noisy CI/test output after the dependency refresh and make release evidence easier to audit.
- Backend warning cleanup: removed deprecated Starlette `TestClient(timeout=...)` usage from the SSE stream test.
- Frontend warning cleanup: made App tests reset shared Zustand state, mock auth/onboarding shell behavior, use `userEvent`, and wait for lazy components before assertions; made ServicesBrowser and Roadmap loading tests wait for their async fetches to settle.
- Validation: backend Ruff, full backend Pytest, frontend ESLint, full Vitest, production Vite build, npm audit, Playwright smoke, and `git diff --check` all passed locally.

## 2026-04-28 Production Gate Hardening Pass

- Purpose: Continue release hardening without activating billing.
- Server-side gates: live cloud scanner, deployment execute/rollback, and SSO/SCIM endpoints now fail closed unless `live_cloud_scanner`, `deploy_engine`, or `enterprise_sso_scim` are explicitly enabled.
- Storage readiness: session store exposes Redis/File/Memory readiness metadata and supports `REQUIRE_REDIS=true` for scaled production promotion.
- Database readiness: database layer exposes backend readiness metadata and supports `ENFORCE_POSTGRES=true` for production promotion.
- Identity readiness: SSO/SCIM readiness endpoint reports configured booleans without exposing secret values.
- Validation: focused backend gate tests passed with `/Users/idokatz/VSCode/Archmorph/backend/.venv/bin/python -m pytest tests/test_feature_flags.py tests/test_session_store.py tests/test_database.py tests/test_deployments.py tests/test_release_gates.py -q --no-cov`.
- Full backend gate: `/Users/idokatz/VSCode/Archmorph/backend/.venv/bin/python -m pytest --tb=short -q -n auto --dist loadfile --cov=. --cov-report=term-missing --cov-config=.coveragerc --cov-context=test --cov-fail-under=63` passed with total coverage `64.78%`.

## 2026-04-28 Production-Parity Local Stack Pass

- Purpose: Add a no-staging local parity path for validating production persistence guards before direct production promotion.
- Compose overlay: `docker-compose.parity.yml` starts the backend with `ENVIRONMENT=production`, `ENFORCE_POSTGRES=true`, `REQUIRE_REDIS=true`, PostgreSQL via `DATABASE_URL`, Redis via `REDIS_URL`, and Gunicorn/Uvicorn workers.
- Guard tests: `backend/tests/test_production_parity.py` verifies enforced PostgreSQL readiness, enforced Redis readiness, and fail-closed behavior when either guard is misconfigured.
- Validation: `/Users/idokatz/VSCode/Archmorph/backend/.venv/bin/python -m ruff check backend/tests/test_production_parity.py` passed.
- Validation: `/Users/idokatz/VSCode/Archmorph/backend/.venv/bin/python -m pytest tests/test_database.py tests/test_session_store.py tests/test_production_parity.py -q --no-cov` passed with `45` tests.
