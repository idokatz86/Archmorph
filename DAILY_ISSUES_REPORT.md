# Daily Standup Issues Report — 2026-02-24

## Summary

Full codebase review conducted by Backend, Security, Frontend, DevOps, QA, and Performance specialist agents. **9 critical/high bugs fixed in this PR**. Remaining findings documented below as issues for backlog grooming.

---

## ✅ Fixed in This PR

| # | File | Issue | Severity |
|---|------|-------|----------|
| 1 | `backend/auth.py:312` | **IndexError** when Azure AD B2C returns empty `emails` list | High |
| 2 | `backend/database.py:117` | **DATABASE_URL with credentials logged** in plaintext at INFO level | High |
| 3 | `backend/session_store.py:166` | **Path traversal** — insufficient sanitization in FileStore (replaced with strict regex allowlist + resolve check) | High |
| 4 | `backend/openai_client.py:159` | **Thread-safety** — `reset_client()` not acquiring `_client_lock` | Medium |
| 5 | `backend/auth.py:418` | **Unsalted IP hash** — anonymous user IPs trivially reversible from SHA256 | Medium |
| 6 | `backend/auth.py:497` | **PII (email) logged in plaintext** — GDPR data minimization violation | Medium |
| 7 | `frontend/ChatWidget.jsx:39` | **Missing `res.ok` check** — crashes with `TypeError` on server error responses | Critical |
| 8 | `frontend/ChatWidget.jsx:66` | **XSS via `javascript:` URLs** in AI chat responses rendered as `<a href>` | Critical |
| 9 | `frontend/OrganizationSettings.jsx` | **Double `/api` prefix** on all 6 API paths — component completely non-functional | Critical |

---

## 🔴 Open Issues — Critical/High (Requires New GitHub Issues)

### Security

| # | File | Issue | Severity |
|---|------|-------|----------|
| S1 | `infra/terraform.tfvars.prod` | Real Azure subscription ID and placeholder password committed to source control | Critical |
| S2 | `backend/requirements.txt:4` | `python-multipart>=0.0.20` allows vulnerable versions (<0.0.22); safe to update since Dockerfile uses Python 3.12 | High |
| S3 | `backend/webhooks.py` | Stripe webhook bypasses signature verification in dev mode | High |

### DevOps/CI

| # | File | Issue | Severity |
|---|------|-------|----------|
| D1 | `.github/workflows/ci.yml` | Production deploy job missing `environment: production` protection — no approval gates | Critical |
| D2 | `.github/workflows/ci.yml:348` | Trivy action pinned to `@master` — supply chain risk | High |
| D3 | `.github/workflows/ci.yml:87` | `returntocorp/semgrep-action@v1` deprecated — use `semgrep/semgrep-action@v1` | High |
| D4 | `.github/workflows/ci.yml:375` | Storage connection string written to `$GITHUB_ENV` without masking | High |

### Backend

| # | File | Issue | Severity |
|---|------|-------|----------|
| B1 | `backend/job_queue.py:282` | In-memory JobManager fails ~75% of time under multi-worker (jobs invisible across workers) | High |
| B2 | `backend/routers/diagrams.py:474` | Exception type and internal message leaked to API clients | Medium |
| B3 | `backend/routers/diagrams.py:697` | 50MB `max_length` on JSON string field risks OOM under concurrent requests | Medium |

### Frontend

| # | File | Issue | Severity |
|---|------|-------|----------|
| F1 | `frontend/DiagramTranslator/index.jsx` | Questions fetch in 3 places has no error handling — loses successful analysis result on failure | High |
| F2 | `frontend/AdminDashboard.jsx:244` | Dynamic Tailwind classes (`bg-${color}/10`) won't compile — styles silently missing | High |
| F3 | `frontend/PricingPage.jsx:21` | No `res.ok` check and no error state shown to users | High |
| F4 | `frontend/ServicesBrowser.jsx:29` | Swallows all API errors silently — shows empty page with no explanation | High |

### Infrastructure

| # | File | Issue | Severity |
|---|------|-------|----------|
| I1 | `charts/archmorph/templates/networkpolicy.yaml:22` | NetworkPolicy ingress port uses service port 80 instead of container targetPort 8000 | Medium |
| I2 | `charts/archmorph/templates/networkpolicy.yaml:44` | Redis egress allows port 6379 but Terraform configures TLS-only Redis on port 6380 | Medium |

### QA/Testing

| # | File | Issue | Severity |
|---|------|-------|----------|
| Q1 | — | No code coverage measurement configured (pytest-cov, vitest coverage) | Critical |
| Q2 | `tests/e2e_flow_test.py` | Hardcoded paths to developer's local machine — tests non-runnable in CI | High |
| Q3 | — | 6 frontend components and `apiClient.js` have zero test coverage | High |

### Performance

| # | File | Issue | Severity |
|---|------|-------|----------|
| P1 | `backend/analytics.py` | All analytics counters in-memory, per-worker — admin dashboard shows ~25% of real traffic | High |
| P2 | `backend/database.py` | Missing `pool_recycle` for PostgreSQL — stale connections under cloud LB timeouts | Medium |

---

## 📋 Open Pull Requests — Review Recommendations

| PR | Title | Status | Recommendation |
|----|-------|--------|----------------|
| #204 | [WIP] Work on the entire application to find and fix bugs | Draft | Review when ready — currently WIP by Copilot |
| #92 | [WIP] Assess current project progress status | Stale | Close — superseded (see Issue #201) |
| #93 | Add team productivity metrics to roadmap | Stale | Close — superseded (see Issue #201) |
| Dependabot PRs | 10+ dependency update PRs (fastapi, pytest, azure-identity, etc.) | Open | Review and merge — all are minor/patch updates |

### Dependabot PRs to Merge

- `dependabot/pip/backend/fastapi-0.131.0`
- `dependabot/pip/backend/azure-identity-1.25.2`
- `dependabot/pip/backend/pytest-9.0.2`
- `dependabot/pip/backend/python-dotenv-1.2.1`
- `dependabot/pip/backend/email-validator-2.3.0`
- `dependabot/pip/backend/tenacity-9.1.4`
- `dependabot/pip/backend/psutil-7.2.2`
- `dependabot/pip/backend/fpdf2-2.8.6`
- `dependabot/pip/backend/python-docx-1.2.0`
- `dependabot/pip/backend/apscheduler-3.11.2`
- `dependabot/npm_and_yarn/frontend/tailwindcss-4.2.1`
- `dependabot/npm_and_yarn/frontend/tailwindcss/vite-4.2.1`

### Stale Branches to Clean Up

- `copilot/check-progress-status`
- `copilot/check-work-status`
- `copilot/monitor-team-productivity`
- `copilot/progress-check-inquiry`

---

## ✅ Positive Observations

- **1,537 backend tests all passing** — strong test foundation
- **Prompt injection defense** well-implemented in `prompt_guard.py`
- **Security headers, CORS, rate limiting** properly configured
- **Non-root Docker**, OIDC CI auth, blue-green deployments
- **Helm charts** with hardened security contexts and network policies
- **GPT response caching** reduces cost and latency
- **Comprehensive CI pipeline** with SAST, SCA, secret detection, SBOM
