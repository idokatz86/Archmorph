# Archmorph Enterprise Readiness Blueprint

This document is the Archmorph enterprise readiness track for Wave 4. It maps
each required enterprise control to its implementation status, evidence source,
and any outstanding gaps. **Controls are classified as IMPLEMENTED, PARTIAL, or
PLANNED — never described as complete when evidence is absent.**

Evidence is sourced from implemented code, CI test results, and committed
Terraform, never from aspirational prose.

---

## 1. Private Ingress and Direct-Origin Access Policy

**Status: IMPLEMENTED**

### What is implemented

- Azure Front Door is the only permitted public ingress path to the backend.
- The Container App origin is not publicly addressable through a direct FQDN
  call in production — every request must carry the correct `X-Azure-FDID`
  header matching the owned Front Door profile GUID.
- Requests that bypass Front Door receive HTTP 403 `TRUSTED_ORIGIN_REQUIRED`.
- `/healthz` and `/readyz` are exempt (infrastructure probes use them directly).

### Evidence

| Evidence item | Source |
| --- | --- |
| Middleware enforcement | `backend/main.py` — `_validate_trusted_origin()` |
| Origin-lock unit tests | `backend/tests/test_front_door_origin_lock.py` (4 tests) |
| Terraform origin contract | `infra/main.tf` — `TRUSTED_FRONT_DOOR_FDID`, `TRUSTED_FRONT_DOOR_HOSTS` env vars |
| Front Door origin host header | `infra/main.tf` — `origin_host_header = azurerm_cdn_frontdoor_endpoint.api[0].host_name` |
| Infra contract test | `backend/tests/test_front_door_origin_lock_infra.py` |
| CI blue-green smoke check | `backend/tests/test_ci_workflow_post_deploy_smoke.py` — `test_backend_green_revision_smoke_checks_origin_lock_and_reuses_front_door_contract` |
| Direct-origin blocked metric | `backend/main.py` — `_emit_direct_origin_blocked()` → `security.direct_origin_blocked` counter |

### Monitoring

The `security.direct_origin_blocked` counter is emitted via the observability
module on every blocked direct-origin attempt. When
`APPLICATIONINSIGHTS_CONNECTION_STRING` is set the counter is forwarded to Azure
Monitor so dashboards can track direct-access attempts over time.

### Operator verification

```bash
cd infra
terraform output front_door_api_hostname
terraform output front_door_profile_resource_guid
```

See `infra/README.md` § "Front Door Origin Lock Contract" for the full
verification procedure.

---

## 2. Regional DR Plan and Azure OpenAI Failover Posture

**Status: PARTIAL**

### What is implemented

- A Terraform DR module (`infra/dr/main.tf`) provisions a standby Container App
  environment in a secondary Azure region (`northeurope` by default) when
  `enable_dr = true`.
- The DR environment shares the same ACR, and the Traffic Manager profile
  (`azurerm_traffic_manager_profile`) routes failover traffic.
- The DR Container App uses an independent Log Analytics workspace and App
  Insights instance so observability does not depend on the primary region.
- Architecture Package DR readiness rubric (`backend/architecture_package.py`
  `_build_dr_readiness_rubric`) scores user diagrams across replication,
  failover routing, data durability, observability, and runbook dimensions.
- Landing Zone SVG DR variant generates a two-region canvas with dedicated SLO:
  p95 < 3s (vs. 1.5s primary).

### Initial RTO/RPO targets

| Target | Value | Basis |
| --- | --- | --- |
| RTO (Recovery Time Objective) | ≤ 60 minutes | Traffic Manager TTL + Container App cold start |
| RPO (Recovery Point Objective) | ≤ 15 minutes | PostgreSQL PITR backup frequency |

These targets are initial estimates based on the deployed infrastructure
configuration. They must be validated through a DR drill (see below).

### Gaps / Planned

| Gap | Status |
| --- | --- |
| Azure OpenAI endpoint failover (primary → secondary deployment) | **PLANNED** — primary endpoint only; secondary deployment not yet provisioned |
| Automated DR drill CI workflow | **PLANNED** — manual runbook only |
| DR drill success metrics (time-to-recover) | **PLANNED** — requires drill execution |
| Prometheus / Azure Monitor DR health dashboard | **PLANNED** — see `infra/main.tf` observability workbook |

### DR drill runbook (initial)

1. Confirm `enable_dr = true` in `infra/dr/main.tf` variables.
2. Run `terraform apply` in `infra/dr/` to provision the DR environment.
3. Trigger a Traffic Manager DNS failover to the DR endpoint.
4. Verify `/healthz` and `/readyz` return expected status on the DR FQDN.
5. Run a subset of the production smoke suite against the DR FQDN.
6. Record time-to-detect, time-to-failover, and time-to-recover.
7. Document the drill result in `docs/RELEASE_EVIDENCE.md`.

---

## 3. Tenant Isolation Model and Per-Tenant Quotas

**Status: IMPLEMENTED**

### What is implemented

- Organization model (`backend/models/tenant.py`, `OrgRole`, `InviteStatus`).
- Tenant service layer (`backend/services/tenant_service.py`) with plan-based
  per-tenant quota enforcement:

  | Plan | Max members | Max analyses/month |
  | --- | ---: | ---: |
  | free | 3 | 5 |
  | team | 50 | 500 |
  | enterprise | 10 000 | 100 000 |

- RBAC permission matrix enforces `owner`, `admin`, `editor`, `viewer` roles.
- Diagram sessions are scoped to the authenticated user's principal — cross-tenant
  session access is rejected by `authorize_diagram_access()` in
  `backend/routers/shared.py`.
- Multi-tenant auth hardening tests: `backend/tests/test_auth_multitenant_hardening.py`,
  `backend/tests/test_cross_tenant.py`.

### Evidence

| Evidence item | Source |
| --- | --- |
| Plan limits definition | `backend/services/tenant_service.py` — `PLAN_LIMITS` dict |
| RBAC matrix | `backend/services/tenant_service.py` — `ROLE_PERMISSIONS` dict |
| Tenant model tests | `backend/tests/test_tenant.py` |
| Cross-tenant isolation tests | `backend/tests/test_cross_tenant.py` |
| Auth hardening tests | `backend/tests/test_auth_multitenant_hardening.py` |

### Gaps / Planned

| Gap | Status |
| --- | --- |
| Per-tenant Azure OpenAI quota enforcement (token-level) | **PLANNED** |
| Tenant-scoped encryption key rotation | **PLANNED** |
| Enterprise SSO / SCIM provisioning | **SCAFFOLD** — feature-flagged (`enterprise_sso_scim`), fail-closed until enabled |

---

## 4. Dependency SLO Dashboard

**Status: IMPLEMENTED**

### What is implemented

- `/api/health` reports live dependency check results for OpenAI, storage, Redis,
  service catalog, and circuit breakers. Degraded or unhealthy states are
  surfaced in the response body and in CI watchdog alerts.
- `/readyz` (new — added in this release) provides an anonymous production
  readiness probe that infrastructure probes (k8s readiness, Traffic Manager)
  can use to distinguish dependency readiness from process liveness (`/healthz`).
- Azure Monitor SLO alerts (`infra/observability/alerts.tf`) fire when p95 latency
  exceeds the spine SLO budgets:

  | Operation | SLO | Alert severity |
  | --- | ---: | --- |
  | Diagram analysis | p95 < 8 s | Sev 2 |
  | Landing-zone SVG (primary) | p95 < 1.5 s | Sev 2 |
  | Landing-zone SVG (DR) | p95 < 3 s | Sev 2 |
  | Terraform generation | p95 < 12 s | Sev 2 |
  | Bicep generation | p95 < 12 s | Sev 2 |
  | Drift comparison | p95 < 5 s | Sev 3 |

- Burn-rate alerts evaluate both 5-minute and 1-hour windows; they treat
  requests as bad when the p95 budget is exceeded or HTTP 5xx is returned.
- Scheduled-job freshness is tracked via the freshness registry; any job stale
  beyond its budget marks the system degraded and triggers a watchdog issue.
- In-process dependency check results are cached for 10 seconds to avoid
  blocking Redis/OpenAI connections under high traffic.

### Evidence

| Evidence item | Source |
| --- | --- |
| `/api/health` dependency checks | `backend/routers/health.py` — `_run_dependency_checks()` |
| `/readyz` endpoint | `backend/routers/health.py` — `readyz()` |
| `/readyz` tests | `backend/tests/test_readyz_endpoint.py` |
| Azure Monitor alert definitions | `infra/observability/alerts.tf` |
| Spine SLO documentation | `docs/SLO.md` |

### Liveness vs. readiness distinction

| Probe | Endpoint | What it checks | Auth |
| --- | --- | --- | --- |
| Liveness | `GET /healthz` | Process is alive | None |
| Readiness | `GET /readyz` | Dependencies ready | None |
| Full health | `GET /api/health` | All deps + catalog freshness + jobs | API key |

Infrastructure should configure:
- **Liveness probe** → `/healthz` (kills and restarts if fails)
- **Readiness probe** → `/readyz` (removes from load-balancer pool if fails)

---

## 5. Release Annotations

**Status: IMPLEMENTED**

### What is implemented

Release annotation events (deploy, traffic shift, rollback, config change) are
recorded via a new admin API endpoint and emitted as OTel span events to Azure
Monitor so dashboards can overlay deployment events on latency and error-rate
charts.

- **POST `/api/admin/release-annotations`** — CI/CD writes an annotation.
- **GET `/api/admin/release-annotations`** — dashboards and operators read recent
  annotations with optional `environment` / `kind` filters.
- Annotations are persisted in an in-process ring buffer (last 200 entries).
- Each annotation emits a `release.annotation` OTel span event forwarded to
  Application Insights when `APPLICATIONINSIGHTS_CONNECTION_STRING` is set.
- A `release.annotation` counter is dual-written to the in-memory admin
  monitoring dashboard without requiring a live App Insights connection.

### Annotation kinds

| Kind | When to use |
| --- | --- |
| `deploy` | A new container revision is promoted to traffic |
| `traffic_shift` | Traffic weight is shifted to a revision (blue-green) |
| `rollback` | A revision is rolled back due to an incident |
| `config_change` | An environment variable or secret is updated |

### CI usage example

```bash
curl -s -X POST "${API_URL}/api/admin/release-annotations" \
  -H "Authorization: Bearer ${ADMIN_JWT}" \
  -H "Content-Type: application/json" \
  -d '{
    "kind": "deploy",
    "revision": "'"${GITHUB_SHA}"'",
    "environment": "production",
    "description": "Deployed via CI run '"${GITHUB_RUN_ID}"'",
    "actor": "'"${GITHUB_ACTOR}"'",
    "run_url": "'"${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"'"
  }'
```

### Evidence

| Evidence item | Source |
| --- | --- |
| Annotation router | `backend/routers/release_annotations.py` |
| Annotation tests | `backend/tests/test_release_annotations.py` |
| OTel span event emission | `backend/routers/release_annotations.py` — `trace_span()` |
| Counter metric | `backend/routers/release_annotations.py` — `increment_counter()` |

---

## 6. Compliance and Security Evidence Pack

**Status: PARTIAL**

### Implemented controls with evidence

| Control | Status | Evidence source |
| --- | --- | --- |
| Private backend origin (Front Door only) | ✅ IMPLEMENTED | Section 1 above; `test_front_door_origin_lock.py` |
| Direct-origin attempt monitoring | ✅ IMPLEMENTED | `security.direct_origin_blocked` counter; `main.py` |
| Container image vulnerability scanning | ✅ IMPLEMENTED | Trivy gate in `.github/workflows/ci.yml`; SARIF upload |
| Dependency vulnerability scanning | ✅ IMPLEMENTED | Grype SBOM gate; Dependabot alerts |
| Static code analysis | ✅ IMPLEMENTED | CodeQL (Python + JavaScript) on every PR |
| Secret scanning | ✅ IMPLEMENTED | GitHub secret scanning; `.gitleaksignore` |
| Upload validation (magic bytes, PDF, SVG, VSDX) | ✅ IMPLEMENTED | `backend/upload_validator.py`; `test_upload_validation.py` |
| CSRF protection | ✅ IMPLEMENTED | `backend/csrf.py`; `test_csrf_protection.py` |
| Rate limiting | ✅ IMPLEMENTED | SlowAPI; 200 req/min per IP default |
| Tenant isolation (RBAC + session scoping) | ✅ IMPLEMENTED | Section 3 above |
| Production parity guard (Postgres + Redis enforcement) | ✅ IMPLEMENTED | `docker-compose.parity.yml`; `test_production_parity.py` |
| OpenAPI contract snapshot gate | ✅ IMPLEMENTED | `backend/check_openapi_contract.py`; CI `openapi-contract` job |
| Liveness probe | ✅ IMPLEMENTED | `GET /healthz` |
| Readiness probe (dependency-aware) | ✅ IMPLEMENTED | `GET /readyz` (this release) |
| Release annotations in telemetry | ✅ IMPLEMENTED | Section 5 above (this release) |
| Audit logging | ✅ IMPLEMENTED | `backend/audit_logging.py`; `test_audit_logging.py` |

### Planned controls

| Control | Status | Blocker |
| --- | --- | --- |
| Azure OpenAI secondary endpoint failover | **PLANNED** | Requires secondary deployment provisioning |
| Per-tenant token-level quota enforcement | **PLANNED** | Requires Azure APIM or custom metering layer |
| Tenant-scoped encryption key rotation | **PLANNED** | Requires Key Vault managed-identity key policy |
| Automated DR drill CI workflow | **PLANNED** | Requires DR environment to be active |
| Enterprise SSO / SCIM | **SCAFFOLD** | Feature-flagged; requires `enterprise_sso_scim=true` |
| Formal HIPAA / SOC 2 report | **PLANNED** | Requires third-party audit engagement |

### Security review cycle guidance

Enterprise security reviews should reference:

1. This document for the control catalogue.
2. `docs/RELEASE_EVIDENCE.md` for timestamped release checkpoints.
3. `docs/RELEASE_CHECKLIST.md` for the production promotion gate.
4. `docs/SECURITY_ASSESSMENT.md` for the threat model.
5. `docs/RETENTION_CISO_THREAT_MODEL_BRIEF.md` for the CISO brief.
6. GitHub Actions workflow runs for CI gate evidence (Trivy, CodeQL, Grype, Playwright).

Controls marked **PLANNED** are not production-ready and must not be cited as
implemented in a customer security questionnaire until the corresponding code
and evidence are committed.

---

## Document History

| Date | Author | Summary |
| --- | --- | --- |
| 2026-05-25 | Copilot (Wave 4) | Initial enterprise readiness blueprint: private ingress, DR posture, tenant isolation, dependency SLOs, release annotations, compliance evidence pack |
