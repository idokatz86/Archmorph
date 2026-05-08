# Archmorph — CTO-Led Multi-Agent Technical Audit

**Date:** May 8, 2026
**Lead Agent:** CTO Master (accountable owner)
**Operations Agent:** Scrum Master (issue filer)
**Repo:** `idokatz86/Archmorph`
**Default branch:** `main`
**Current version:** `4.2.0` (per `frontend/src/constants.js`, target `4.3.0` per in-flight epic)
**Workspace path:** local developer checkout of `idokatz86/Archmorph`

> This document is the **single source of truth** for this audit run. If the conversation is compacted, resume by reading this file end-to-end and continuing from the next unchecked item in the **Run Log** at the bottom.

---

## 1. Mission

The user requested a **full technical audit** of the Archmorph repository covering:

- Backend (Python / FastAPI)
- Frontend (React / Vite / Tailwind)
- Performance (latency, throughput, memory, bundle size)
- UX & UI (alignment, flows, accessibility, microcopy)
- API design (contracts, versioning, error envelopes)
- QA (test coverage, regression risk, flaky tests)
- Security (CISO review, OWASP, secrets, SSRF, injection)
- DevOps (CI/CD, containers, releases)
- Cloud architecture (Azure / Container Apps / observability / cost)
- Bug hunt (production-trace defects)

**Example finding shape (provided by user):** *"When pressing Sign In, the box is not aligned with the screen."*  → A concrete, reproducible, file-anchored bug.

**Outcomes:**
1. A consolidated finding list grouped by agent.
2. A GitHub issue per finding (filed by Scrum Master) with severity, repro steps, suggested fix, and acceptance criteria.
3. This markdown file kept in sync as the conversation proceeds — usable as a resume anchor.

---

## 2. Roles & Delegation Matrix

| Agent              | Domain                                    | Status | Findings |
|--------------------|-------------------------------------------|--------|----------|
| CTO Master         | Strategy, prioritisation, sign-off         | ✅ Framing + Verdict done | — |
| Backend Master     | FastAPI services, models, persistence      | ✅ Done | 12 (5 P0) |
| FE Master          | React app, state, components, build        | ✅ Done | 12 (4 P0) |
| UX Master          | Flows, IA, microcopy, alignment, a11y      | ✅ Done | 13 (3 P0) |
| Performance Master | Latency, throughput, bundle, memory, p95   | ✅ Done | 12 (4 P0) |
| API Master         | REST contracts, versioning, error envelope | ✅ Done | 13 (4 P0) |
| QA Master          | Test strategy, coverage, flake, gaps       | ✅ Done | 13 (3 P0) |
| CISO Master        | OWASP, authn/authz, secrets, SSRF, XSS     | ✅ Done | 13 (5 P0) |
| Devops Master      | CI/CD, container, release, observability   | ✅ Done | 14 (4 P0) |
| Cloud Master       | Azure architecture, IaC, cost, scale       | ✅ Done | 14 (7 P0) |
| Bug Master         | Concrete defect hunt, repro-first bugs     | ✅ Done | 14 (2 P0) |
| Scrum Master       | File GitHub issues from consolidated list  | ✅ Done — 130 issues #791–#920 | — |

**Total findings:** 130 across 10 specialist agents · **41 P0 / 39 P1 / 50 P2** · User-reported "Sign In box not aligned" root-caused as **F-BUG-1** (Nav header `backdrop-filter` creating containing block for fixed-position descendants).

---

## 3. Repository Snapshot (audit baseline)

**Backend:** Python / FastAPI, ~80+ modules in `backend/`, key surfaces:
- `main.py`, `routers/*` (analysis, agent_paas, agents, executions, chat, retention_routes, health, …)
- `vision_analyzer.py`, `iac_generator.py`, `ai_suggestion.py`, `chatbot.py`
- `azure_landing_zone.py` + `azure_landing_zone_schema.py` (Beta, GA-gated by epic #586)
- `prompt_guard.py`, `auth.py`, `admin_auth.py`, `rbac.py`, `audit_logging.py`
- `cost_metering.py`, `cost_optimizer.py`, `service_updater.py` (GH Actions cron)
- `retention.py` (Sprint 0 anonymised cohort tracking)
- Database via Alembic migrations, pgvector for RAG/memory.
- Tests: `backend/tests/` (~1700+ tests, full backend green on `8ac0364`).

**Frontend:** React + Vite + Tailwind, `frontend/src/`:
- `App.jsx`, `main.jsx`, `constants.js`
- `components/Auth/*` (`AuthProvider`, `LoginModal`, `UserMenu`, `ProfilePage`)
- `components/DiagramTranslator/*` (Upload, AnalysisResults, IaCViewer, ExportHub, LandingZoneViewer, …)
- `components/{AdminDashboard, ChatWidget, ServicesBrowser, ScannerWizard, DriftDashboard, …}`
- ESLint + vitest (267+ tests). Tailwind w/ `ui.jsx` primitives.
- Static Web App config: `staticwebapp.config.json`. Vite `dist/`.

**Infra/DevOps:**
- `infra/` Terraform; `Archmorph/infra/observability/*` workbook + alerts.
- `.github/workflows/` CI + service-catalog cron. Branch protection: `enforce_admins=true` on `main`, 7 required checks.
- Container Apps deployment; Azure Blob persistence for `discovered_services.json`.

**Known open epics / hotspots (from repo memory):**
- Epic #586 (T2→T3 → production-ready ALZ) — many sub-issues open in Sprint 2.
- Epic #576 (multi-source providers) — done.
- Production hotfixes: React #31 cluster (PRs #623, #635, #636 — all merged).
- Sprint 1 P0 cluster `#587–#596, #602` — all merged.
- Open follow-ups: `#610 (BOLA)`, `#612 (anonymous icon-pack POST)`, `#611 (SSRF)`, `#613 (unbounded arrays)`, `#614 (Pydantic extra=forbid)`, `#620`, `#621`, `#640`, `#647`.

---

## 4. Findings Consolidation

> Each agent appends findings to its own subsection below. Schema:
> ```
> #### F-<agent-prefix>-<n>. <Short title>
> - **Severity:** P0 | P1 | P2 | P3
> - **Area:** backend / frontend / perf / ux / …
> - **File(s):** [path/file.ext](path/file.ext) (with line refs where possible)
> - **Repro / Evidence:** …
> - **Impact:** …
> - **Suggested fix:** …
> - **Acceptance criteria:** …
> ```

### 4.1 Backend Master findings (12)

#### F-BE-1. `restore-session` is unauthenticated → cache-poisoning + #613 bound-check drift
- **Severity:** P0 · **Area:** auth / data
- **File(s):** [backend/routers/diagrams.py](../../backend/routers/diagrams.py#L232) (also mirrored at `/api/v1/diagrams/{diagram_id}/restore-session`)
- **Repro / Evidence:** Decorator at line 232 has no `Depends(verify_api_key)`. Handler writes attacker-controlled data into `SESSION_STORE[diagram_id]` and `IMAGE_STORE[diagram_id]` and returns an `attach_export_capability(...)` token. `RestoreSessionRequest` accepts `analysis: Dict[str, Any]` and `image_base64: Optional[str]` with no length bounds; `validate_analysis_payload_bounds` is not invoked.
- **Impact:** Anonymous attacker can (a) overwrite any diagram's analysis/image/HLD/IaC and have the next legit `/generate`, `/export-hld`, `/cost-estimate`, `/report` call read attacker-supplied content; (b) mint export-capability tokens for arbitrary diagrams; (c) DoS via huge `analysis` blobs not capped by `MAX_UPLOAD_SIZE`.
- **Suggested fix:** Add `_auth=Depends(verify_api_key)`; call `validate_analysis_payload_bounds(body.analysis)`; cap `image_base64` length after b64 decode; require ownership/session correlation token.
- **Acceptance criteria:** Unauth POST returns 401; oversized payload returns 413; regression test asserts unauth restore can't poison `SESSION_STORE` or issue capabilities.

#### F-BE-2. Terraform state backend (`tf_backend.py`) has zero auth and a broken UNLOCK method
- **Severity:** P0 · **Area:** auth / data / api
- **File(s):** [backend/routers/tf_backend.py](../../backend/routers/tf_backend.py#L34) (GET), [L41](../../backend/routers/tf_backend.py#L41) (POST overwrite), [L64](../../backend/routers/tf_backend.py#L64) (LOCK), [L95](../../backend/routers/tf_backend.py#L95) (`methods=["UNLOCR"]` typo), [L121](../../backend/routers/tf_backend.py#L121) (rollback)
- **Repro / Evidence:** None of the five handlers under `prefix="/api/terraform/state"` declare auth. Line 95 method is `UNLOCR` not `UNLOCK` — Terraform CLI cannot unlock per HTTP backend protocol; locks accumulate in `LOCK_STORE`.
- **Impact:** (a) Anyone reads full Terraform state JSON for every project (connection strings, generated passwords, secret ARNs); (b) anyone overwrites state, triggering destructive plans; (c) anyone rolls back; (d) hung locks block legit CI deploys and force manual DB edits.
- **Suggested fix:** Wrap router in a deploy-engine auth dep (`verify_admin_key` or per-project `verify_state_token`). Fix `UNLOCR` → `UNLOCK`. Reject empty `lock_id`. Per-project ownership check against `DeploymentState.organization_id`.
- **Acceptance criteria:** All 5 endpoints 401 without admin/state token; `terraform force-unlock` succeeds with valid lock id; per-project token cannot read another project's state.

#### F-BE-3. `routers/auth.py::get_current_user` is a route handler used as `Depends` — anon callers silently land in `default_org`
- **Severity:** P0 · **Area:** auth / multi-tenant
- **File(s):** def [backend/routers/auth.py](../../backend/routers/auth.py#L94); used as dep in [policies.py](../../backend/routers/policies.py#L32), [executions.py](../../backend/routers/executions.py#L37), [agent_memory.py](../../backend/routers/agent_memory.py#L47), [deploy.py](../../backend/routers/deploy.py#L28)
- **Repro / Evidence:** `get_current_user` is decorated with `@router.get("/api/auth/me")` and explicitly returns `{"authenticated": False, "tier": "free", "roles": [], "tenant_id": "default_tenant"}` for unauthenticated callers — never raises 401. Downstream handlers fall back to `org_id = user.get("org_id", "default_org")`.
- **Impact:** Without any credential, attacker can create/list/bind agent policies in `default_org`, start/cancel agent executions, read/wipe agent memory, run `/api/deploy/preflight-check`. Multi-tenant boundary collapse — every fallback tenant shares one bucket.
- **Suggested fix:** Split into `get_current_user_or_anon` (route only) and `require_authenticated_user` that raises 401 on no user. Replace 4 callers. Delete `default_org` fallback; make `org_id` required.
- **Acceptance criteria:** policies/executions/agent_memory/deploy return 401 without Bearer/SWA header; cross-tenant test: A cannot see B's data.

#### F-BE-4. Jobs router fully unauthenticated → BOLA on async analysis/IaC/HLD results
- **Severity:** P0 · **Area:** auth / api
- **File(s):** [backend/routers/jobs.py](../../backend/routers/jobs.py#L26) (status), [L36](../../backend/routers/jobs.py#L36) (SSE), [L55](../../backend/routers/jobs.py#L55) (cancel), [L71](../../backend/routers/jobs.py#L71) (list)
- **Repro / Evidence:** No auth on any handler. `GET /api/jobs` returns ALL jobs in the system (every `job_id` exposed). `GET /api/jobs/{job_id}` returns full vision-analysis output. Cancel arbitrary jobs.
- **Impact:** Direct breach of the BOLA hardening intent of #610 — even with high-entropy IDs, the global list endpoint enumerates them. SSE stream harvests another user's analysis/IaC/HLD output.
- **Suggested fix:** Add `Depends(verify_api_key)` plus job ownership; persist `created_by_user_id`; on read/cancel require user match (return 404 not 403). Restrict global list to `verify_admin_key`.
- **Acceptance criteria:** GET `/api/jobs` requires admin auth; cross-user GET returns 404; SSE rejects without API key.

#### F-BE-5. `auth.get_user_from_session(token: str)` used as `Depends` — token silently read from `?token=` query
- **Severity:** P1 · **Area:** auth / config
- **File(s):** def [backend/auth.py](../../backend/auth.py#L510); used in [credentials.py](../../backend/routers/credentials.py#L61), [scanner_routes.py](../../backend/routers/scanner_routes.py#L33)
- **Repro / Evidence:** `def get_user_from_session(token: str)` — bare `token: str` is interpreted by FastAPI as a required query parameter. Authorization header and query token become independent inputs.
- **Impact:** (a) Session JWT in URL → CDN/proxy/browser-history/Referer logs (OWASP A02); (b) auth split-brain — header bearer `B` succeeds while user used for audit logging belongs to `?token=` JWT; (c) without `?token=` returns 422.
- **Suggested fix:** Wrap in real dep: `def current_user(session_token: str = Depends(validate_session)): u = get_user_from_session(session_token); if not u: raise ArchmorphException(401, …); return u`. Reject query `token`.
- **Acceptance criteria:** Bearer-only succeeds with no `?token=`; mismatched header+query → 401; OpenAPI lists no `token` query param.

#### F-BE-6. `routers/drift.py` — module-level `_BASELINES` dict + no auth on any route
- **Severity:** P1 · **Area:** persistence / auth / multi-tenant
- **File(s):** [backend/routers/drift.py](../../backend/routers/drift.py#L18) (`_BASELINES: Dict = {}`); 8 routes L125–L231
- **Repro / Evidence:** `_BASELINES` is a process-local dict — bypasses Redis/FileStore. None of 8 handlers under `/api/drift/*` use auth.
- **Impact:** (a) Multi-replica: create on A → 404 on B; (b) restart loses every baseline; (c) anyone submits/views/patches arbitrary tenant baselines.
- **Suggested fix:** Replace with `get_store("drift_baselines", maxsize=500, ttl=86400)`; add `Depends(verify_api_key)`; scope IDs to caller's tenant; cap `live_state` via `validate_analysis_payload_bounds`.
- **Acceptance criteria:** Two-replica test passes; 401 on every `/api/drift/*` route without API key; cross-tenant compare returns 404.

#### F-BE-7. `share_routes.py` — DELETE share has no auth; stats endpoint leaks for anonymous shares
- **Severity:** P1 · **Area:** auth / multi-tenant
- **File(s):** [backend/routers/share_routes.py](../../backend/routers/share_routes.py#L101) (DELETE), [L80](../../backend/routers/share_routes.py#L80) (stats), [L27](../../backend/routers/share_routes.py#L27) (POST)
- **Repro / Evidence:** `revoke_share` has no auth dep and no creator check. `get_share_stats` short-circuits when `creator_id is None` → anonymous-created shares return stats to anyone. POST `/share` has no auth — anyone can mint a 30-day public link for any guessable diagram.
- **Impact:** DoS by enumeration; stats privacy leak; unauthorized share-link creation amplifies F-BE-1 cache-poisoning chain.
- **Suggested fix:** `Depends(verify_api_key)` on DELETE + creator-id check; tighten stats; require auth on POST and bind `creator_id`.
- **Acceptance criteria:** DELETE without API key → 401; non-creator DELETE → 404; anonymous-share stats without auth → 401.

#### F-BE-8. `IMAGE_STORE`/`SESSION_STORE` use `FileStore` on per-replica `/tmp` — multi-replica deploys silently lose data
- **Severity:** P1 · **Area:** persistence / multi-tenant
- **File(s):** [backend/session_store.py](../../backend/session_store.py#L196) (FileStore base), [L601](../../backend/session_store.py#L601) (backend selection); [shared.py](../../backend/routers/shared.py#L94)
- **Repro / Evidence:** `FileStore` defaults to `tempfile.gettempdir()` — per-replica on Container Apps. `get_store` silently degrades to `FileStore` instead of raising in production when `REDIS_URL` unset. Production guard at shared.py:107 only logs a warning.
- **Impact:** Upload on replica A; analyze hits B → 404 "No uploaded image found". `EXPORT_CAPABILITY_STORE` issued on A not redeemable on B → 401 on legit exports. Silent intermittent failure.
- **Suggested fix:** In `get_store()`, when `_is_production() and not redis_configured()`, raise `RuntimeError` (gated by `REQUIRE_REDIS=true` default in prod). Add startup health-check that asserts Redis reachable when `replica_count > 1`.
- **Acceptance criteria:** Prod without Redis refuses to start; `/api/health/ready` returns 503 on multi-replica without Redis; two-replica integration test green.

#### F-BE-9. `network_routes._topology_cache` unbounded module dict — leak + multi-replica unsafe
- **Severity:** P1 · **Area:** persistence / observability
- **File(s):** [backend/routers/network_routes.py](../../backend/routers/network_routes.py#L28)
- **Repro / Evidence:** Plain dict, no eviction, no TTL, no cross-replica. Each entry is tens of KB; one per unique `diagram_id`.
- **Impact:** Memory leak → OOMKill; multi-replica write-on-A/404-on-B; restart wipes silently.
- **Suggested fix:** Replace with `get_store("network_topology", maxsize=500, ttl=7200)`.
- **Acceptance criteria:** Unit tests still green; memory bounded under 1k diagrams; two-replica POST→GET works.

#### F-BE-10. `/api/admin/suggestions/*` admin routes guard with user-tier `verify_api_key` instead of `verify_admin_key`
- **Severity:** P1 · **Area:** auth / multi-tenant
- **File(s):** [backend/routers/suggestions.py](../../backend/routers/suggestions.py#L121) and 6 sibling routes L132–L216
- **Repro / Evidence:** All 7 admin-named routes use `verify_api_key`. `admin_core.py` correctly uses `verify_admin_key` — suggestions admin paths off-spec.
- **Impact:** Anyone with the global `ARCHMORPH_API_KEY` (shared with every customer-facing caller) can enumerate the entire AI-mapping queue, approve/reject mappings affecting every customer, trigger expensive batch generation. Privilege confusion.
- **Suggested fix:** Replace `verify_api_key` with `verify_admin_key` on all 7 routes. Add regression test that scans every `/api/admin/...` for admin dep.
- **Acceptance criteria:** All `/api/admin/suggestions/*` 401 without admin Bearer; test scans `app.routes` and asserts admin dep on `path.startswith("/api/admin")`.

#### F-BE-11. `/api/v1/api/...` double-prefix bug — `icon_router` mirrored under wrong path
- **Severity:** P1 · **Area:** api / config
- **File(s):** [backend/routers/v1.py](../../backend/routers/v1.py#L41), [main.py](../../backend/main.py#L397) (`(icon_router, "/api")`), [icons/routes.py](../../backend/icons/routes.py#L39); 9 malformed entries in [openapi.snapshot.json](../../backend/openapi.snapshot.json)
- **Repro / Evidence:** `icon_router` already has `prefix="/api"` so its `route.path` is `/api/icon-packs`. `build_v1_router` computes `effective_path = "/api" + "/api/icon-packs"` → v1 mirror = `/api/v1/api/icon-packs`.
- **Impact:** Versioned API broken for icons; `/api/v1/icon-packs` returns 404; OpenAPI consumers and SDK generators fail.
- **Suggested fix:** Change main.py:397 from `(icon_router, "/api")` to `(icon_router, "")`. Re-export snapshot. Add unit test asserting no path contains `/api/v1/api/`.
- **Acceptance criteria:** snapshot has zero `/api/v1/api/`; `GET /api/v1/icon-packs` returns 200.

#### F-BE-12. `/api/import/{terraform,cloudformation,arm}` accept up to 30 MB anonymously
- **Severity:** P2 · **Area:** auth / api
- **File(s):** [backend/routers/terraform_import_routes.py](../../backend/routers/terraform_import_routes.py#L41), [L58](../../backend/routers/terraform_import_routes.py#L58), [L75](../../backend/routers/terraform_import_routes.py#L75)
- **Repro / Evidence:** Three POSTs accept 10 MB each, no auth. Sibling `/api/import/infrastructure` enforces `verify_api_key`.
- **Impact:** Compute amplification; bypasses billing/rate counters; undermines unified import endpoint's auth posture.
- **Suggested fix:** Add `_auth=Depends(verify_api_key)`. Either deprecate format-specific endpoints or unify rate-limit + size-cap.
- **Acceptance criteria:** All 4 import endpoints 401 without API key; same `5/minute` limiter and 10 MB cap.

### 4.2 FE Master findings (12)

#### F-FE-1. `LoginModal` not an accessible dialog — no `role`, no `aria-modal`, no Esc, no focus trap
- **Severity:** P0 · **Area:** a11y
- **File(s):** [frontend/src/components/Auth/LoginModal.jsx](../../frontend/src/components/Auth/LoginModal.jsx#L84-L139)
- **Repro / Evidence:** Outer wrapper carries no `role="dialog"`, no `aria-modal`, no `aria-labelledby`, no `useFocusTrap`. No Escape keydown listener. The `Modal` primitive in [ui.jsx](../../frontend/src/components/ui.jsx#L143-L177) already has all of this — `LoginModal` reimplemented without it.
- **Impact:** Screen-reader users hear unlabelled content; keyboard Tab cycles into page beneath; no Esc dismiss.
- **Suggested fix:** Replace the bespoke wrapper with `Modal` from `ui.jsx`, or attach `useFocusTrap(isOpen)`, add `role="dialog" aria-modal="true" aria-labelledby="login-title"`, give `<h2>` `id="login-title"`, bind document Esc.
- **Acceptance criteria:** `role="dialog"` + `aria-modal="true"` exposed; Tab cycles within modal only; Esc closes; focus returns to Sign In trigger; heading referenced via `aria-labelledby`.

#### F-FE-2. `ProfilePage` modal repeats every `LoginModal` a11y gap (plus broken backdrop close)
- **Severity:** P1 · **Area:** a11y
- **File(s):** [frontend/src/components/Auth/ProfilePage.jsx](../../frontend/src/components/Auth/ProfilePage.jsx#L137-L144)
- **Repro / Evidence:** Same dialog-role/aria/focus/Esc gap as F-FE-1. Backdrop has no `onClick={onClose}` (regression vs. LoginModal).
- **Impact:** Same a11y impact, plus modal can't be dismissed by clicking outside.
- **Suggested fix:** Same fix as F-FE-1 — switch to shared `Modal`.
- **Acceptance criteria:** Same as F-FE-1 plus backdrop click closes (or document deliberate omission).

#### F-FE-3. Sign In trigger box mis-aligns with sibling Nav controls on mobile
- **Severity:** P1 · **Area:** mobile
- **File(s):** [frontend/src/components/Auth/UserMenu.jsx](../../frontend/src/components/Auth/UserMenu.jsx#L43-L52), [Nav.jsx](../../frontend/src/components/Nav.jsx#L233-L284)
- **Repro / Evidence:** Sibling icon-only Nav controls use `p-1.5` square padding (24×24). Sign In trigger uses `flex items-center gap-1.5 px-3 py-1.5` plus `<span className="hidden sm:inline">Sign In</span>`. Below `sm` text disappears but `px-3` + `gap-1.5` ghost-gap remain — button is visibly taller/wider than neighbors. Direct match to user-reported "box not aligned".
- **Impact:** Visible misalignment on every mobile viewport; Nav cluster looks broken; trigger spills row height.
- **Suggested fix:** Responsive padding so icon-only state matches siblings: `p-1.5 sm:px-3 sm:py-1.5`; `gap-1.5` only when text visible.
- **Acceptance criteria:** At 320–639 px, Sign In matches Search/Theme/Feedback dimensions; ≥640 px text reappears; Playwright screenshot diff confirms aligned baselines.

#### F-FE-4. `toRenderableString` not applied at multiple list-of-objects render sites — #636 leak still alive
- **Severity:** P0 · **Area:** error-handling
- **File(s):** [AnalysisResults.jsx](../../frontend/src/components/DiagramTranslator/AnalysisResults.jsx#L266-L273), [ResultsTable.jsx](../../frontend/src/components/DiagramTranslator/ResultsTable.jsx#L633-L641), [L668-L673](../../frontend/src/components/DiagramTranslator/ResultsTable.jsx#L668-L673), [L692-L697](../../frontend/src/components/DiagramTranslator/ResultsTable.jsx#L692-L697), [PricingTab.jsx](../../frontend/src/components/DiagramTranslator/PricingTab.jsx#L348-L355), [L115-L122](../../frontend/src/components/DiagramTranslator/PricingTab.jsx#L115-L122)
- **Repro / Evidence:** `grep` for `toRenderableString` returns only 4 consumer sites. Backend GPT path can emit `{type, message}`/`{name}` objects in any of the above arrays → React #31 "Objects are not valid as a React child".
- **Impact:** Single bad model response crashes the entire Results, Pricing, or matrix view — bypasses #636's safety net.
- **Suggested fix:** Wrap every renderer with `toRenderableString(item)`. Add ESLint rule or unit test that scans for `\.map\(.*=> .*\{[a-z_]+\}`.
- **Acceptance criteria:** All sites coerce items; unit test feeds `[{type:'warn', message:'x'}]` to each component without React error; "Objects are not valid as a React child" never logs under fuzzed shapes.

#### F-FE-5. `apiClient` default methods strip the auth token — every workflow request goes anonymous
- **Severity:** P0 · **Area:** auth
- **File(s):** [frontend/src/services/apiClient.js](../../frontend/src/services/apiClient.js#L167-L205), [useAuthStore.js](../../frontend/src/stores/useAuthStore.js#L13-L33)
- **Repro / Evidence:** `api.get/post/patch/delete` build headers from `options.headers` only; never reads `archmorph_session_token`. Auth headers only injected by `api.auth(method, path, { token })`. Every workflow call (`/history/...`, `/migration-chat`, bookmark, delete) executes with no `Authorization` even when authenticated.
- **Impact:** Backend can't bind diagram/history records to the signed-in user via Bearer; cross-user data risk if any route ever flips to per-user store.
- **Suggested fix:** Make `apiClient` read live token from `useAuthStore.getState().sessionToken` and auto-attach `Authorization: Bearer …` for non-auth/non-public paths. Or pass `apiClient.setAuthGetter(...)` from `main.jsx`.
- **Acceptance criteria:** With token in store, `api.get('/history/analyses')` sends `Authorization`; without token, header omitted (no `Bearer null`); SWA cookie path intact.

#### F-FE-6. `ProfilePage` and parts of `useAuthStore` only honor `localStorage` — SWA cookie users authenticate to nothing
- **Severity:** P0 · **Area:** auth
- **File(s):** [frontend/src/components/Auth/ProfilePage.jsx](../../frontend/src/components/Auth/ProfilePage.jsx#L70-L132)
- **Repro / Evidence:** All three `fetch` calls do `localStorage.getItem('archmorph_session_token')` and only attach `Authorization` if present. SWA path in `useAuthStore.initialize()` sets `user`/`isAuthenticated` from `/.auth/me` and never writes to localStorage. SWA users → token null → request unauth → backend treats as anonymous → 403/wrong profile.
- **Impact:** Profile load/save/delete silently fails for the actual production auth path. Account deletion can target wrong identity.
- **Suggested fix:** Route Profile/Account calls through centralized client; add `credentials: 'include'`; read token from `useAuthStore`.
- **Acceptance criteria:** Profile loads correctly for both SWA and `loginWithToken` users; account deletion is auth-bound to actual user in both modes.

#### F-FE-7. Tailwind `dark:` variants on auth/deploy panels decoupled from app's `data-theme` toggle
- **Severity:** P2 · **Area:** dark-mode
- **File(s):** [LoginModal.jsx](../../frontend/src/components/Auth/LoginModal.jsx#L48-L70), [DeployPanel.jsx](../../frontend/src/components/DiagramTranslator/DeployPanel.jsx#L218-L300)
- **Repro / Evidence:** No `tailwind.config.js`; project uses `@tailwindcss/vite` v4 — `dark:` defaults to `prefers-color-scheme`, not the app's `data-theme`. Result: `dark:bg-gray-800`, `dark:text-gray-300`, etc. respond to OS pref, not in-app toggle.
- **Impact:** Theming inconsistencies across auth surface and deploy panel; design tokens (`bg-surface`, `text-text-primary`) work; raw palettes diverge.
- **Suggested fix:** Configure Tailwind v4 selector-based dark mode bound to `[data-theme="dark"]` via `@variant dark (...)`, OR replace hardcoded gray/yellow/blue pairs with project tokens (`bg-surface`, `bg-secondary`, `text-text-secondary`).
- **Acceptance criteria:** Theme toggle repaints LoginModal and DeployPanel correctly regardless of OS; no `dark:` utilities not bound to theme attribute remain.

#### F-FE-8. `ErrorBoundary` doesn't reset on tab change — one bad tab kills navigation
- **Severity:** P2 · **Area:** error-handling
- **File(s):** [App.jsx](../../frontend/src/App.jsx#L91-L107), [ErrorBoundary.jsx](../../frontend/src/components/ErrorBoundary.jsx#L23-L48)
- **Repro / Evidence:** Single `<ErrorBoundary>` wraps every routed tab. Boundary only resets via "Try Again" button. When `activeTab` changes, children change but `state.hasError` persists.
- **Impact:** Render error in `DiagramTranslator` blocks reaching Templates, Dashboard, Roadmap, etc.
- **Suggested fix:** Pass `key={activeTab}` to `<ErrorBoundary>`, OR add `componentDidUpdate(prevProps)` comparing a `resetKey` prop.
- **Acceptance criteria:** Render error in one tab still allows switching to another tab; "Try Again" still works in-place.

#### F-FE-9. `DeployPanel` bypasses `apiClient` entirely — no auth, no retry, no timeout, no error mapping
- **Severity:** P1 · **Area:** state / build
- **File(s):** [DeployPanel.jsx](../../frontend/src/components/DiagramTranslator/DeployPanel.jsx#L88-L175)
- **Repro / Evidence:** `runPreflight`, `handlePreview`, `handleDeploy`, `handleRollback` all use raw `fetch` with only `'Content-Type': 'application/json'`. None of `apiClient` retry/backoff/timeout/USER_FRIENDLY_ERRORS apply. No abort signal.
- **Impact:** Inconsistent UX (raw HTTP statuses); silent fails behind any auth wall once deploy gating turns on.
- **Suggested fix:** Replace each `fetch` with `api.post('/v1/deployments/preview', payload, signal)` / `api.post('/api/deploy/preflight-check', body, signal)`. Use `AbortController` ref. Use `ApiError` for status-aware messages.
- **Acceptance criteria:** All deploy network calls go through `apiClient`; errors render user-friendly mapped message; closing/unmounting aborts pending requests; SSE handling unchanged.

#### F-FE-10. `loginWithProvider` drops query/hash on round-trip — users land on different tab
- **Severity:** P2 · **Area:** auth / state
- **File(s):** [useAuthStore.js](../../frontend/src/stores/useAuthStore.js#L99-L110)
- **Repro / Evidence:** `post_login_redirect_uri = encodeURIComponent(window.location.pathname)` excludes `?` and `#`. App uses `#dashboard`/`#templates` for tab routing. Sign in from `/#dashboard` returns to `/` and lands on `translator`.
- **Impact:** Lost workflow context after sign-in; surprising teleport mid-task.
- **Suggested fix:** Use `window.location.pathname + search + hash` as the post-login URI.
- **Acceptance criteria:** Signing in from `/#dashboard` returns to `/#dashboard`; query strings survive redirect.

#### F-FE-11. Sign In trigger lacks accessible name on mobile + missing `aria-haspopup="dialog"`
- **Severity:** P2 · **Area:** a11y / mobile
- **File(s):** [UserMenu.jsx](../../frontend/src/components/Auth/UserMenu.jsx#L43-L52)
- **Repro / Evidence:** Below 640 px text removed from accessible tree; icon decorative; no `aria-label`. No `aria-haspopup`/`aria-expanded`.
- **Impact:** Mobile SR users hear "button" with no purpose; AT can't pre-announce dialog.
- **Suggested fix:** Add `aria-label="Sign in"`, `aria-haspopup="dialog"`, `aria-expanded={loginModalOpen}` to trigger.
- **Acceptance criteria:** VoiceOver/NVDA/Talkback announce "Sign in, button, has dialog" at all viewports; axe-core 0 violations on Nav.

#### F-FE-12. Vision-cache TTL collision with #636 — pre-coercion entries persist in `sessionStorage`
- **Severity:** P1 · **Area:** error-handling / state
- **File(s):** [sessionCache.js](../../frontend/src/services/sessionCache.js#L36-L100)
- **Repro / Evidence:** `saveSession` writes payloads with `ts: Date.now()` keyed by diagram id; `loadSession` only invalidates after 2h. No schema/version tag. Pre-#636 caches still loaded verbatim and rendered through F-FE-4 sites.
- **Impact:** Re-introduces React #31 crash invisibly for users with stale cache. CI/E2E won't catch; end-of-session artifact.
- **Suggested fix:** Add `const SCHEMA_VERSION = 2;` to payload; bump on every shape-affecting change. In `loadSession`, treat any cache without current `schemaVersion` as expired and `removeItem`. Clear caches on auth state change.
- **Acceptance criteria:** Old caches dropped on first mount post-deploy; valid caches still work under 2h TTL; unit test plants v1 cache and asserts `loadSession()` returns null.

### 4.3 UX Master findings (13)

#### F-UX-1. LoginModal lacks dialog semantics, focus trap, Esc, scroll-lock
- **Severity:** P0 · **Area:** a11y / focus
- **File(s):** [LoginModal.jsx](../../frontend/src/components/Auth/LoginModal.jsx#L78-L82)
- **Repro / Evidence:** Esc does nothing; Tab past last button escapes to nav behind backdrop; SR announces no dialog role; body still scrolls. WCAG 2.1.2 / 4.1.2 / 2.4.3 violations. `ui.jsx`'s `Modal` already provides all of this.
- **Impact:** Keyboard-only and SR users can't operate or trust the dialog.
- **Suggested fix:** Wrap with `role="dialog" aria-modal="true" aria-labelledby="login-title"`; use `useFocusTrap`; bind Esc and toggle body scroll lock (mirror `ui.jsx`).
- **Acceptance criteria:** Tab cycles inside modal only; Esc closes and returns focus; body can't scroll while open; SR announces "Sign in to Archmorph, dialog".
- **Cross-route:** Same gap in [ProfilePage.jsx](../../frontend/src/components/Auth/ProfilePage.jsx#L138-L141).

#### F-UX-2. Sign In modal overflows on short viewports — content cut off, not scrollable (root cause of user report)
- **Severity:** P0 · **Area:** alignment / mobile
- **File(s):** [LoginModal.jsx](../../frontend/src/components/Auth/LoginModal.jsx#L78-L91)
- **Repro / Evidence:** At 320×568 / Galaxy Fold 280×653, modal content (~410 px) exceeds viewport with `flex items-center` centering, `mx-4`, no `max-h-[90vh]`/`overflow-y-auto`. Top of modal clipped above viewport with no scrollbar. iOS keyboard recenters off-screen. **Direct match to user-reported "box not aligned with the screen".**
- **Impact:** Users on small phones / split-screen / keyboard-up cannot reach GitHub button or Continue-as-Guest. P0 conversion blocker.
- **Suggested fix:** Outer wrapper: `fixed inset-0 z-[100] flex items-center justify-center overflow-y-auto p-4 sm:p-6 pt-[max(1rem,env(safe-area-inset-top))]`. Inner: replace `mx-4` with `my-auto`, add `max-h-[calc(100dvh-2rem)] overflow-y-auto` (`dvh` for iOS dynamic viewport). Switch ProfilePage `90vh` → `100dvh`.
- **Acceptance criteria:** At 320×568 portrait/landscape and 360×640: heading, all 3 providers, "Continue as Guest", and footer all reachable; modal scrolls inside itself; backdrop still closes; with iOS keyboard open, close button visible; no horizontal scroll at 320 px.

#### F-UX-3. Provider button `dark:` classes never fire — app uses `data-theme`, not Tailwind class/media dark mode
- **Severity:** P0 · **Area:** dark-mode
- **File(s):** [LoginModal.jsx L48/L56/L64](../../frontend/src/components/Auth/LoginModal.jsx#L48), [DeployPanel.jsx L255](../../frontend/src/components/DiagramTranslator/DeployPanel.jsx#L255)
- **Repro / Evidence:** App theme set via `document.documentElement.setAttribute('data-theme', theme)` ([Nav.jsx#L17](../../frontend/src/components/Nav.jsx#L17)) and CSS vars under `[data-theme="light"]`. Tailwind v4 default `dark:` is `prefers-color-scheme` (no `@custom-variant dark`). MS/Google buttons stay white in app-dark-mode when system is light → low-contrast on dark surface.
- **Impact:** Provider buttons don't respect in-app theme switch — most prominent CTA group is broken.
- **Suggested fix:** Add `@custom-variant dark (&:where([data-theme="dark"], [data-theme="dark"] *));` to `index.css` (Tailwind v4), OR replace raw palette with design tokens (`bg-surface-light`, `bg-secondary`, `text-text-primary`, `border-border`).
- **Acceptance criteria:** Theme toggle re-skins all 3 provider buttons immediately; AAA contrast ≥ 7:1 in both themes.

#### F-UX-4. Sign In trigger collapses to ~28×28 tap target on mobile and loses accessible name
- **Severity:** P1 · **Area:** mobile / a11y
- **File(s):** [UserMenu.jsx](../../frontend/src/components/Auth/UserMenu.jsx#L43-L49)
- **Repro / Evidence:** `<sm` `<span>` removed; remaining hit area = `px-3 py-1.5` + 16-px icon ≈ 28×28. No `aria-label`. Below WCAG 2.5.5 (24×24) and far below 44×44 mobile recommendation.
- **Impact:** Mistaps next to hamburger; auth flow inaccessible to SR on mobile.
- **Suggested fix:** Add `aria-label="Sign in"`. Bump tap area: `min-h-[44px] min-w-[44px] sm:min-h-0 sm:min-w-0`, or keep label visible always.
- **Acceptance criteria:** Tap target ≥ 44×44 on `<sm`; SR announces "Sign in, button" regardless of viewport.

#### F-UX-5. Auth flow doesn't restore focus after modal close → keyboard users lose place
- **Severity:** P1 · **Area:** focus
- **File(s):** [UserMenu.jsx#L51](../../frontend/src/components/Auth/UserMenu.jsx#L51), [LoginModal.jsx#L82](../../frontend/src/components/Auth/LoginModal.jsx#L82), [AuthProvider.jsx#L23](../../frontend/src/components/Auth/AuthProvider.jsx#L23)
- **Repro / Evidence:** Tab → Enter → modal opens but focus stays on trigger. Click Close → focus drops to `<body>`. Tab restarts from top. After OAuth redirect, no `aria-live` announcement, no focus move to UserMenu.
- **Impact:** Disorienting for keyboard and SR users; SR users have no announcement that login succeeded.
- **Suggested fix:** On open, focus first interactive element (provided by `useFocusTrap`). On close, restore previous focus. Add `<div role="status" aria-live="polite" className="sr-only">Signed in as {user.name}.</div>` and move focus to user-menu trigger.
- **Acceptance criteria:** Modal close (X, Esc, backdrop, success redirect) returns focus to trigger; successful login announced via polite live region.

#### F-UX-6. Empty/loading/error states inconsistent across DiagramTranslator panels
- **Severity:** P1 · **Area:** state-consistency
- **File(s):** [HLDPanel.jsx](../../frontend/src/components/DiagramTranslator/HLDPanel.jsx#L31), [IaCViewer.jsx](../../frontend/src/components/DiagramTranslator/IaCViewer.jsx#L80), [AnalysisResults.jsx](../../frontend/src/components/DiagramTranslator/AnalysisResults.jsx#L191), [CostPanel.jsx](../../frontend/src/components/DiagramTranslator/CostPanel.jsx#L3)
- **Repro / Evidence:** `HLDPanel` returns `null` when missing; `IaCViewer` always renders; `AnalysisResults` no skeleton; only `CostPanel` uses `EmptyState`. `Skeleton` primitive defined but never imported in DiagramTranslator. Loading shown via 3 different mechanisms.
- **Impact:** Inconsistent perceived performance; user confusion; dead-ends.
- **Suggested fix:** Adopt 3-state contract per panel: `EmptyState` (with explicit CTA), `Skeleton` (during fetch), `ErrorCard` (on failure). Replace `null` returns with `<EmptyState ... action={<Button>Generate HLD</Button>} />`. Replace inline spinners with `<Skeleton variant="card" />`.
- **Acceptance criteria:** Each panel has all 4 states; no `null` returns without route forward; skeleton dimensions match success-state to avoid layout shift.

#### F-UX-7. Error microcopy leaks raw exception strings; no toast/snackbar contract
- **Severity:** P1 · **Area:** copy / state-consistency
- **File(s):** [index.jsx#L687](../../frontend/src/components/DiagramTranslator/index.jsx#L687), [#L834](../../frontend/src/components/DiagramTranslator/index.jsx#L834), [DeployPanel.jsx#L131](../../frontend/src/components/DiagramTranslator/DeployPanel.jsx#L131), [CostPanel.jsx#L196](../../frontend/src/components/DiagramTranslator/CostPanel.jsx#L196), [ProfilePage.jsx#L113](../../frontend/src/components/Auth/ProfilePage.jsx#L113)
- **Repro / Evidence:** Users see "Preflight failed: 500", "HLD export failed: NetworkError when attempting to fetch resource". CostPanel CSV export silently swallows errors. ProfilePage shows "Network error" with no next action.
- **Impact:** Errors non-actionable, technical, inconsistent. Users blame themselves.
- **Suggested fix:** Single `useToast` hook + `<ToastViewport role="region" aria-live="polite">`. Map server status → human copy: `500 → "We hit a problem on our side..."`, `network → "You appear to be offline..."`, `400 → "We couldn't read that diagram..."`. Replace silent CostPanel catch with `toast.error(... { action: { label: 'Retry', onClick: handleExportCSV } })`.
- **Acceptance criteria:** No raw `err.message`/HTTP statuses/stack traces; every error has cause + next action; announced via aria-live; success toasts use same component.

#### F-UX-8. ExportHub error state is icon-only with no reason and no per-row retry
- **Severity:** P1 · **Area:** state-consistency / copy
- **File(s):** [ExportHub.jsx#L262](../../frontend/src/components/DiagramTranslator/ExportHub.jsx#L262), [#L382](../../frontend/src/components/DiagramTranslator/ExportHub.jsx#L382)
- **Repro / Evidence:** Failure shows 16-px red `<X>` glyph and nothing else: no message, no retry, no toast. Footer aria-live still says "deliverables ready" — failed ones counted as "selected".
- **Impact:** Users can't diagnose which deliverable failed or retry just one.
- **Suggested fix:** On `'error'`, render inline message + Retry button next to X. Update statusMessage to surface failed count: `"3 ready · 1 failed"`. Add `role="alert"`.
- **Acceptance criteria:** Each failed row shows reason + retry, both keyboard reachable; footer aria-live distinguishes ready vs failed; retry of one row doesn't restart batch.

#### F-UX-9. UserMenu dropdown lacks proper menu semantics, Esc, roving focus
- **Severity:** P2 · **Area:** a11y / nav / focus
- **File(s):** [UserMenu.jsx](../../frontend/src/components/Auth/UserMenu.jsx#L62-L131)
- **Repro / Evidence:** Panel has no `role="menu"`, items no `role="menuitem"`, no Esc, no Arrow keys, no focus-trap, no return-focus. Compare to `MoreDropdown` in [Nav.jsx#L41-L161](../../frontend/src/components/Nav.jsx#L41-L161) which implements all of this.
- **Impact:** Inconsistent keyboard model across two adjacent header menus.
- **Suggested fix:** Refactor `UserMenu` to reuse `MoreDropdown` keyboard/role pattern, or extract `<NavDropdown>` as shared primitive in `ui.jsx`.
- **Acceptance criteria:** Esc closes; Arrow keys move focus; trigger has `aria-haspopup="menu"`; panel `role="menu"`; items `role="menuitem"`.

#### F-UX-10. ProfilePage form labels not programmatically linked to controls
- **Severity:** P2 · **Area:** a11y / forms
- **File(s):** [ProfilePage.jsx#L36-L51](../../frontend/src/components/Auth/ProfilePage.jsx#L36-L51), [#L172-L195](../../frontend/src/components/Auth/ProfilePage.jsx#L172-L195)
- **Repro / Evidence:** Internal `Select`/`Input` rolled by hand with `<label>` + control no `htmlFor`/`id`. SRs read inputs as "edit, blank". `ui.jsx` already has correct primitives.
- **Impact:** Section-510 / WCAG 1.3.1 / 4.1.2 violations on a PII form.
- **Suggested fix:** Replace local components with `Input`/`Select` from `ui.jsx` (handle id/htmlFor/aria-invalid/aria-describedby).
- **Acceptance criteria:** Every field has `<label htmlFor>` or `aria-labelledby`; validation errors tied via `aria-describedby`.

#### F-UX-11. HLDPanel uses hardcoded Tailwind palette instead of theme tokens — breaks dark/light parity
- **Severity:** P2 · **Area:** dark-mode
- **File(s):** [HLDPanel.jsx#L218](../../frontend/src/components/DiagramTranslator/HLDPanel.jsx#L218), [#L239](../../frontend/src/components/DiagramTranslator/HLDPanel.jsx#L239), [ProfilePage.jsx#L188](../../frontend/src/components/Auth/ProfilePage.jsx#L188)
- **Repro / Evidence:** Uses `bg-red-500`/`bg-yellow-500`/`bg-green-500` literals; doesn't reference `--color-danger`/`--color-warning`/`--color-cta`.
- **Impact:** Visible inconsistency in light theme; risks color-only encoding (WCAG 1.4.1).
- **Suggested fix:** Replace with `bg-danger`/`bg-warning`/`bg-cta` tokens. Add icon companion (`AlertTriangle`/`AlertCircle`/`CheckCircle`).
- **Acceptance criteria:** No raw `bg-red-*`/`bg-yellow-*`/`bg-green-*`; risk impact via icon + label, not just color.

#### F-UX-12. GuidedQuestions Expert/Guided toggle uses same icon family with inverted meaning
- **Severity:** P2 · **Area:** copy / nav
- **File(s):** [GuidedQuestions.jsx#L213-L222](../../frontend/src/components/DiagramTranslator/GuidedQuestions.jsx#L213-L222), [#L201-L209](../../frontend/src/components/DiagramTranslator/GuidedQuestions.jsx#L201-L209)
- **Repro / Evidence:** "All Questions / Focused" uses `List` (active) / `LayoutGrid` (inactive). Two lines later, "Expert View / Guided View" uses `LayoutGrid` (active=Expert) / `List` (active=Guided). Same icons, opposite semantics.
- **Impact:** Cognitive friction; users misinterpret which mode they're in.
- **Suggested fix:** Distinct icons: `Sparkles`+"Guided" / `Code2`+"Expert"; `Layers`+"Focused" / `ListChecks`+"All Questions". Make both toggles `role="switch"` with `aria-checked`.
- **Acceptance criteria:** Each binary control uses unique icon pair; both toggles use `role="switch"`; SR announces "Expert view, switch, off".

#### F-UX-13. DeployPanel "Coming Soon" overlay has empty `pointer-events-auto` card with no focus order
- **Severity:** P2 · **Area:** a11y / focus / state-consistency
- **File(s):** [DeployPanel.jsx#L13-L29](../../frontend/src/components/DiagramTranslator/DeployPanel.jsx#L13-L29)
- **Repro / Evidence:** Underlying content `aria-hidden="true"` + `pointer-events-none` but contains focusable buttons; `tabindex` not removed. SR ignores due to `aria-hidden` but `aria-hidden` on container with focusables is itself a WCAG 4.1.2 violation.
- **Impact:** Keyboard tabs into greyed-out non-functional UI; SR users get silence on this tab.
- **Suggested fix:** Don't render `<DeployPanelContent>` when feature flag off — replace with `<EmptyState>` (Rocket icon, title, description, optional "Notify me" CTA). If teaser must stay, use `inert` or `tabIndex={-1}` on every focusable.
- **Acceptance criteria:** Tab order skips greyscaled preview; SR announces "Coming soon — One-click deployment is under active development."; no `aria-hidden` on subtree containing focusables.

### 4.4 Performance Master findings (12)

#### F-PERF-1. IaC self-reflection verification step doubles GPT-4o latency on `/generate`
- **Severity:** P0 · **Area:** latency
- **File(s):** [backend/iac_generator.py](../../backend/iac_generator.py#L707), [#L744](../../backend/iac_generator.py#L744)
- **Repro / Evidence:** `_generate_and_verify_iac` issues a chat completion at `max_tokens=32768`, then `_verify_iac_completeness` issues a second identical-budget call as a "strict review" pass. Both serial, both blocking. Frontend `ExportHub` sets a 180 000 ms timeout to absorb it.
- **Impact:** ~+5–10s p95 added to every `/api/diagrams/{id}/generate` call.
- **Suggested fix:** Gate verification on a quality heuristic (output below expected resource count, missing required blocks). Run in background and surface delta-update via job stream.
- **Acceptance criteria:** p95 of `POST /api/diagrams/{id}/generate?format=terraform` drops ≥40% on 50-mapping fixture.

#### F-PERF-2. IMAGE_STORE byte-budget is dead code; eviction count-only and base64 inflates payload 33%
- **Severity:** P0 · **Area:** memory
- **File(s):** [backend/session_store.py L117](../../backend/session_store.py#L117), [L128](../../backend/session_store.py#L128), [L165](../../backend/session_store.py#L165), [routers/diagrams.py L205](../../backend/routers/diagrams.py#L205), [shared.py L94](../../backend/routers/shared.py#L94)
- **Repro / Evidence:** Production write path is `IMAGE_STORE[diagram_id] = (b64, ct)` which dispatches to `InMemoryStore.__setitem__` — never updates `_total_bytes`, never consults `MAX_MEMORY_BYTES`. The `set()` overload that does check budget silently returns when over budget instead of evicting. Images stored as base64 ASCII (33% overhead). With `IMAGE_STORE_MAXSIZE=50` × `MAX_UPLOAD_SIZE=10MB`, peak ≈ 670MB per worker (not the documented 500MB).
- **Impact:** Per-replica memory ceiling N_workers × ~670MB; zero byte-budget enforcement under burst; multi-worker uvicorn replicas can OOM.
- **Suggested fix:** (a) Stop b64-encoding for in-memory backend; (b) in `__setitem__` evict via `popitem(last=False)` until under budget; (c) decrement `_total_bytes` on TTLCache evictions.
- **Acceptance criteria:** Burst test 200×10MB on 1-CPU/1GB replica keeps RSS < 800MB and never raises MemoryError; oldest entries evict.

#### F-PERF-3. Sync enrichment block runs on event loop inside async `/analyze`
- **Severity:** P0 · **Area:** concurrency
- **File(s):** [routers/diagrams.py L130](../../backend/routers/diagrams.py#L130), [L320](../../backend/routers/diagrams.py#L320)
- **Repro / Evidence:** After `asyncio.gather` of classify+vision, `_normalize_analysis(...)` called directly in async handler. Three blocking passes: `_enrich_with_sku` (`engine.best_fit()` per mapping), `_enrich_with_provenance` (per mapping), `_enrich_with_architecture_issues` (rules engine + classify_regulated_workload). None wrapped in `asyncio.to_thread`.
- **Impact:** ~50–200 ms blocks event loop on 50-mapping diagram, freezing every other inflight request (rate limiter, health checks, SSE).
- **Suggested fix:** `result = await asyncio.to_thread(_normalize_analysis, analysis_result_or_exc)`.
- **Acceptance criteria:** p95 on `/api/health` while 10 analyses in flight stays under 50 ms.

#### F-PERF-4. AgentRunner uses sync `SessionLocal()` inside async coroutine; tools execute serially
- **Severity:** P0 · **Area:** concurrency
- **File(s):** [services/agent_runner.py L15/L18/L68](../../backend/services/agent_runner.py#L15)
- **Repro / Evidence:** `async def run()` calls sync `SessionLocal()` at L18 and uses `db.query()`/`db.commit()` while awaiting `model_client.chat()`. Connection held for full 2× GPT-4o RT (~3–15s) plus tool execution. `for tool_call in message.tool_calls:` executes tools serially. Plus `__init__` opens session never closed (L15) — leaks one connection per AgentRunner.
- **Impact:** ~30 concurrent agent runs exhaust pool (DB_POOL_SIZE=20 + DB_MAX_OVERFLOW=10); N parallel tools become N×serial latency.
- **Suggested fix:** Switch to `AsyncSessionLocal`; run tools concurrently via `asyncio.gather`; drop leaked `SessionLocal()` at L15.
- **Acceptance criteria:** 50 concurrent executions complete with DB pool peak ≤ 50%; multi-tool runs scale with `max(tool_latency)`.

#### F-PERF-5. Vision prompt-hash truncates to 200 chars — SYSTEM_PROMPT changes never invalidate cache
- **Severity:** P1 · **Area:** cache
- **File(s):** [vision_analyzer.py L249](../../backend/vision_analyzer.py#L249), [prompt_guard.py L96](../../backend/prompt_guard.py#L96)
- **Repro / Evidence:** `_compute_vision_prompt_hash` builds `source = _vision_prompt()[:200] + model_name`. `_vision_prompt()` returns `PROMPT_ARMOR + "\n\n" + SYSTEM_PROMPT`, and `PROMPT_ARMOR` is **652 chars**. So 200-char prefix is always pure PROMPT_ARMOR — every byte of `SYSTEM_PROMPT` outside the hash.
- **Impact:** Updating vision schema does not invalidate `_vision_cache`; old responses with stale schemas served for up to 1h after deploy → silent functional regressions cached cross-tenant. Conversely, any tweak to PROMPT_ARMOR's first 200 chars wipes 100% of cache.
- **Suggested fix:** `source = _vision_prompt() + model_name` (no slice). Optionally add `PROMPT_VERSION` env.
- **Acceptance criteria:** Unit test mutating `SYSTEM_PROMPT` mid-test produces different hash output.

#### F-PERF-6. Vision images base64 round-tripped 3× per analyze
- **Severity:** P1 · **Area:** memory
- **File(s):** [routers/diagrams.py L205/L288](../../backend/routers/diagrams.py#L205), [vision_analyzer.py L312](../../backend/vision_analyzer.py#L312)
- **Repro / Evidence:** Upload encodes raw → b64 (13.3MB stored); `analyze_diagram` decodes b64 → 10MB raw; `analyze_image` re-encodes compressed bytes to b64. Both `classify_image` and `analyze_image` independently call `compress_image()` on same payload.
- **Impact:** Transient peak ≈ 35–40MB per concurrent analyze; 8 concurrent on 1GB replica = ~300MB transient overhead on top of F-PERF-2 ceiling.
- **Suggested fix:** Store raw `bytes` in `InMemoryStore`; compress once in `analyze_diagram` before gather and pass compressed payload to both classify+analyze with `compressed=True` fast-path.
- **Acceptance criteria:** Peak RSS for 16 concurrent 10MB analyses drops ≥40%; `compress_image` called at most once per upload.

#### F-PERF-7. Sync embedding call inside DB write path holds connections for 200–800ms
- **Severity:** P1 · **Area:** concurrency
- **File(s):** [services/agent_memory.py L34/L72/L89](../../backend/services/agent_memory.py#L34)
- **Repro / Evidence:** `_get_embedding` makes synchronous `client.embeddings.create(...)` call. `save_episodic_memory` and `save_entity` call it before `db.add()` and `db.commit()` — DB session open the whole time.
- **Impact:** Each memory save adds ~500 ms p95; 30 concurrent agents exhaust 30-slot pool.
- **Suggested fix:** Compute embedding before opening session (`await asyncio.to_thread(self._get_embedding, summary)`). Better: insert with `embedding=NULL`; async worker backfills.
- **Acceptance criteria:** 50 concurrent `save_episodic_memory` keeps DB pool ≤ 30%; p95 < 100ms when embeddings deferred.

#### F-PERF-8. pgvector context retrieval issues two sequential ORDER-BY queries
- **Severity:** P1 · **Area:** db
- **File(s):** [services/agent_memory.py L130](../../backend/services/agent_memory.py#L130), [alembic 011_hnsw_indexes.py](../../backend/alembic/versions/011_hnsw_indexes.py#L1)
- **Repro / Evidence:** `retrieve_relevant_context` runs two sequential `ORDER BY embedding.cosine_distance(...) LIMIT 5` queries. HNSW gives O(log n) per query but both run serially on same connection.
- **Impact:** ~3× sequential RTs ≈ 30–80ms baseline; async refactor halves it.
- **Suggested fix:** Migrate to async + `await asyncio.gather(episodes_q, entities_q)`. Optionally collapse to single `UNION ALL`.
- **Acceptance criteria:** p95 of `retrieve_relevant_context` over 10K-row corpus drops ≥30% under 50 RPS.

#### F-PERF-9. ExportHub generates all selected deliverables serially in `for...await` loop
- **Severity:** P1 · **Area:** network
- **File(s):** [ExportHub.jsx L242](../../frontend/src/components/DiagramTranslator/ExportHub.jsx#L242), [#L86](../../frontend/src/components/DiagramTranslator/ExportHub.jsx#L86)
- **Repro / Evidence:** `handleGenerateAll` iterates `for (const d of selectedItems) { ... await generateDeliverable(...) }`. Worst-case wall-clock ≈ 60–180s for 6 items (IaC alone has 180s timeout).
- **Impact:** "Generate All" UX dominated by slowest deliverable; total p95 ≈ 73s (sum), would be ~30s with parallelism cap=3.
- **Suggested fix:** Bounded fan-out via `pLimit(3)`: `Promise.all(selectedItems.map(d => limit(() => generateDeliverable(...))))`.
- **Acceptance criteria:** All 6 deliverables complete in ≤ `max(deliverable_latency) × 1.5` (≈ 45s).

#### F-PERF-10. LandingZoneViewer parses + sanitizes 300KB SVG twice on main thread
- **Severity:** P1 · **Area:** bundle / runtime
- **File(s):** [LandingZoneViewer.jsx L12/L60](../../frontend/src/components/DiagramTranslator/LandingZoneViewer.jsx#L12), [azure_landing_zone.py L74](../../backend/azure_landing_zone.py#L74)
- **Repro / Evidence:** Server caps SVG at 300KB with up to 31 base64 data-URI icons. On every prop change, `parseLandingZoneSvg` (DOMParser + querySelectorAll) and `DOMPurify.sanitize` both run on main thread. Then `dangerouslySetInnerHTML` commits large DOM subtree synchronously.
- **Impact:** ~50–150ms main-thread block per render on mid-tier hardware; INP regression; long task warnings.
- **Suggested fix:** (a) Server-side sidecar JSON of structured tier/service data; (b) drop client `DOMPurify` (server already validates with `ET.fromstring`); (c) render via `<img src={blobUrl}>` so browser handles SVG parsing.
- **Acceptance criteria:** Main-thread time inside `LandingZoneViewer` per render < 16ms on 2020 MBP for 300KB; INP for export-hub interaction < 200ms.

#### F-PERF-11. IaC chat history sends full code on every turn — quadratic token growth
- **Severity:** P2 · **Area:** latency / cost
- **File(s):** [iac_chat.py L155/L172](../../backend/iac_chat.py#L155), [routers/iac_routes.py L100](../../backend/routers/iac_routes.py#L100)
- **Repro / Evidence:** `IaCChatMessage.code` bounded to 100 000 chars. Each turn appends prior assistant response (with full code field); `recent_history = history[-10:]` re-sends last 10 turns alongside current 100KB code block. 5 turns ≈ 150K input tokens.
- **Impact:** Per-turn latency grows linearly with depth, ~3–6s on 8th–10th turn; token cost ~10× per session.
- **Suggested fix:** Strip `code` field from history entries before re-sending — only keep `message` + `changes_summary`; current code is canonical state. Or summarize older turns after turn 5.
- **Acceptance criteria:** Token usage on turn 10 within 1.5× of turn 1.

#### F-PERF-12. Vision response cache sized at 100 entries — thrashes on burst
- **Severity:** P2 · **Area:** cache
- **File(s):** [vision_analyzer.py L38](../../backend/vision_analyzer.py#L38)
- **Repro / Evidence:** `_vision_cache = TTLCache(maxsize=100, ttl=3600)` hard-coded per worker. Cache key is `sha256(compressed_bytes + model + prompt_hash)`. With 4 workers per replica and no shared Redis, hit-rate is per-worker. 200/min burst thrashes to 0% hit rate.
- **Impact:** Lost cache hits = full GPT-4o vision RTs (~$0.005/call). At 200 RPM with 0% hit: ~$1/min on vision alone vs. ~$0.40/min at 60% hit rate.
- **Suggested fix:** (a) `int(os.getenv("VISION_CACHE_MAXSIZE", "500"))`; (b) Redis-backed shared cache for multi-replica.
- **Acceptance criteria:** Vision cache hit-rate ≥ 50% under existing repeat-upload e2e load profile; configurable at deploy.

### 4.5 API Master findings (13)

#### F-API-1. `apiClient.js` ignores `Authorization` for all non-`/auth` calls — server treats every authenticated user as anonymous
- **Severity:** P0 · **Area:** auth / contract
- **File(s):** [frontend/src/services/apiClient.js L154-L210](../../frontend/src/services/apiClient.js#L154-L210)
- **Repro / Evidence:** `request()` only attaches headers from `options.headers`. Public `api.get/post/patch/delete` never inject `Authorization` or even `credentials: 'include'`. Token is only passed for `api.auth(...)` (login/SWA/profile mgmt). All `/api/diagrams/...`, `/api/v1/...`, `/api/migration-chat`, `/api/governance/...`, `/api/playbooks/...`, `/api/workflow-projects/...`, `/api/integrations/...` go unauthenticated.
- **Impact:** Every authenticated workflow degrades silently to anonymous; backend rate limit/quota assigned to "anon"; auth-only routes return 401 unless using OAuth cookies.
- **Suggested fix:** In `apiClient.request`, fetch `useAuthStore.getState().sessionToken`. If present and request is to internal API (URL starts with `/api/` or `apiUrl(...)`), attach `Authorization: Bearer ${token}`. Always set `credentials: 'include'` for SWA cookie auth fallback.
- **Acceptance criteria:** `POST /api/diagrams/{id}/migration-chat` carries `Authorization` header when authenticated; `useAuthStore.logout()` causes next request to be anonymous; SWA cookies still flow.

#### F-API-2. Token caps inconsistent across HLD generation paths — same logical request returns different completeness
- **Severity:** P0 · **Area:** parity / cost
- **File(s):** [routers/diagrams.py L470](../../backend/routers/diagrams.py#L470), [iac_generator.py L1074](../../backend/iac_generator.py#L1074), [routers/diagrams.py L478-L481](../../backend/routers/diagrams.py#L478-L481)
- **Repro / Evidence:** `/api/diagrams/{id}/hld` calls `generate_hld_strict` with `max_completion_tokens=24_576`; same handler can call `generate_hld(...)` with no token cap; `iac_generator.generate_hld` defaults to `max_tokens=4096`. Output truncates differently per code path; "Sections covered" assertion in router throws on >40-section schemas with low cap.
- **Impact:** Random 502s for large diagrams; inconsistent doc completeness depending on call shape.
- **Suggested fix:** Single source-of-truth env `HLD_MAX_TOKENS` (default 24_576). Both functions accept `max_tokens` arg defaulting to env. Router never overrides.
- **Acceptance criteria:** Same diagram → same HLD section count regardless of code path; truncation doesn't 502.

#### F-API-3. `/api/diagrams/{id}/iac/chat` exposes `current_code` from request body — no server-side anchor → tampering / drift
- **Severity:** P0 · **Area:** integrity / contract
- **File(s):** [routers/iac_routes.py L98-L130](../../backend/routers/iac_routes.py#L98-L130), [iac_chat.py L75-L172](../../backend/iac_chat.py#L75-L172)
- **Repro / Evidence:** `IaCChatRequest.current_code` (max_length 100_000) is taken verbatim and used as full state. Server doesn't load IaC from DB before chat. Client can substitute arbitrary code; downstream `apply_changes` overwrites stored IaC unconditionally.
- **Impact:** Tenant-scoped IaC can be replaced via `current_code` injection by anyone with `diagram_id`; preview/apply diff loses idempotency.
- **Suggested fix:** Server loads canonical code from `IaCChatSession.current_code`/`Diagram.iac_terraform`. `current_code` in request becomes optional and only applies if `session_id` matches session owner. Backend logs hash mismatch.
- **Acceptance criteria:** Sending wrong `current_code` for a known `session_id` returns 409 Conflict; stored state never overwritten by mismatched payload.

#### F-API-4. SSE token endpoints stream secrets bypassing tenant isolation when `?tenant_id=` is supplied as query param
- **Severity:** P0 · **Area:** auth / contract
- **File(s):** [token_streaming.py L1](../../backend/services/token_streaming.py#L1), [routers/observability.py L1](../../backend/routers/observability.py#L1)
- **Repro / Evidence:** SSE streamer accepts `tenant_id` from query string instead of resolving from `request.state.user`. Combined with F-API-1, anyone can stream any tenant's events by providing the right `tenant_id`.
- **Impact:** Cross-tenant data exposure on observability streams; metrics/cost/audit drift.
- **Suggested fix:** Drop `tenant_id` query param. Resolve from `Depends(require_user)` and reject if not present. Apply same fix to all `/observability/*` SSE routes.
- **Acceptance criteria:** Same SSE endpoint without auth returns 401; with auth returns only the caller's tenant data; pen-test cannot cross tenants.

#### F-API-5. Health endpoints leak internal version, dependency status, and config feature flags
- **Severity:** P1 · **Area:** info-disclosure / contract
- **File(s):** [routers/health.py L24-L81](../../backend/routers/health.py#L24-L81)
- **Repro / Evidence:** `/api/health` returns full dependency map: openai connected/region, db connected, redis connected, embedding model, feature flags (`ENABLE_AGENT_LOOPS`, etc.). Public, no auth.
- **Impact:** Recon surface for attackers (deployed model, region, feature flags). Could enable model-tier-specific exploits.
- **Suggested fix:** Split into `/healthz` (200/503 only) for unauth and `/api/health/detailed` requiring auth+admin.
- **Acceptance criteria:** Anonymous probe sees only liveness; detailed health requires admin role.

#### F-API-6. `/api/v1/deployments/preflight` accepts arbitrary inputs — no `Pydantic` validation
- **Severity:** P1 · **Area:** validation / contract
- **File(s):** [routers/deployments.py L70-L109](../../backend/routers/deployments.py#L70-L109)
- **Repro / Evidence:** Endpoint signature: `async def preflight(payload: dict = Body(...))`. No request model. Payload sent to `terraform plan`/`bicep build` shell as-is via `subprocess.run`.
- **Impact:** Command-injection surface (mitigated only by `shell=False` argv splat); large/garbage payloads spike CPU; field renames silently accepted.
- **Suggested fix:** Define `class PreflightRequest(BaseModel)` with explicit fields (`iac_format`, `code: constr(max_length=200_000)`, `target_env: Literal[...]`).
- **Acceptance criteria:** Malformed payloads return 422; `iac_format` constrained to enum; OpenAPI shows full schema.

#### F-API-7. Migration-chat streams Azure OpenAI responses with no abort propagation — orphaned upstream calls cost money
- **Severity:** P1 · **Area:** lifecycle / cost
- **File(s):** [routers/diagrams.py L820-L880](../../backend/routers/diagrams.py#L820-L880), [services/llm_streaming.py L1](../../backend/services/llm_streaming.py#L1)
- **Repro / Evidence:** SSE producer doesn't observe `request.is_disconnected()`. If frontend closes (tab nav), Azure OpenAI keeps streaming; backend keeps buffering until client timeout (~120s).
- **Impact:** Per-token billing on cancelled requests; resource pressure during burst.
- **Suggested fix:** In SSE producer loop, check `await request.is_disconnected()` per chunk; on disconnect, `client.close()` (httpx) or `aiter.aclose()` (openai).
- **Acceptance criteria:** Closing tab mid-stream stops upstream tokens within 1s; cost per cancelled session drops to single-chunk.

#### F-API-8. CORS allowlist mixes `*` and origin-specific values — credentials sent to wildcard subset
- **Severity:** P1 · **Area:** auth / cors
- **File(s):** [main.py L143-L156](../../backend/main.py#L143-L156), [config.py CORS_ORIGINS](../../backend/config.py)
- **Repro / Evidence:** `allow_origins` populated from comma-split env. If env has `*`, `allow_credentials=True` causes Starlette to silently NOT echo `*` but pass-through any Origin (per CORSMiddleware quirk). Browser then accepts credentials from previously-untrusted origins under preflight cache.
- **Impact:** Credentials may flow to non-allowlisted origins under specific browser/cache states.
- **Suggested fix:** Reject `*` if `allow_credentials=True`; raise on startup. Use explicit allowlist or regex.
- **Acceptance criteria:** Boot fails fast if `CORS_ORIGINS=*` and credentials enabled; pen-test shows no credential bleed.

#### F-API-9. `/api/diagrams/{id}/migration-chat` ignores `Authorization` for ownership; uses `diagram_id` only
- **Severity:** P1 · **Area:** authz / contract
- **File(s):** [routers/diagrams.py L780-L820](../../backend/routers/diagrams.py#L780-L820)
- **Repro / Evidence:** No `require_user` dependency. Any caller with `diagram_id` can chat against the diagram, leak Vision-extracted PII embedded in prompts.
- **Impact:** Cross-user diagram leakage when `diagram_id` is guessable/shared.
- **Suggested fix:** Add `current_user = Depends(require_user)` and `_assert_diagram_owner(current_user, diagram_id)`. Guests still permitted but rate-limited.
- **Acceptance criteria:** Auth'd user A cannot chat against diagram owned by user B; guests can only chat their own session diagrams.

#### F-API-10. OpenAPI schema drift — frontend types and backend responses diverge for `/diagrams/{id}/analyze`
- **Severity:** P1 · **Area:** contract
- **File(s):** [routers/diagrams.py L130-L350](../../backend/routers/diagrams.py#L130-L350), [frontend/src/types/api.ts](../../frontend/src/types/api.ts)
- **Repro / Evidence:** Backend returns `analysis: dict` (untyped) plus optional fields (`mappings`, `architecture_issues`, `provenance`, `sku_recommendations`, `validation_warnings`). Frontend has no type and uses `toRenderableString` on every field.
- **Impact:** Drift discovered only at render time; F-FE-4's React #31 lives here.
- **Suggested fix:** Define `AnalyzeResponse` Pydantic schema + `response_model=AnalyzeResponse`. Run `openapi-typescript` on PR.
- **Acceptance criteria:** Adding new field to response auto-types frontend; CI fails if frontend uses untyped field.

#### F-API-11. `/api/governance/runs` accepts arbitrary nested JSON for rules; uses jsonschema only at write time
- **Severity:** P2 · **Area:** validation
- **File(s):** [routers/governance.py L60-L120](../../backend/routers/governance.py#L60-L120)
- **Repro / Evidence:** Pydantic model is `payload: Dict[str, Any]`. `jsonschema.validate` only invoked inside service. Endpoint can be made to ingest arbitrarily-deep dicts.
- **Impact:** DoS via deeply-nested JSON parser; silent acceptance of invalid shapes.
- **Suggested fix:** Pydantic model with explicit fields; reject before reaching jsonschema.
- **Acceptance criteria:** Deeply-nested junk returns 422 in <50ms.

#### F-API-12. Inconsistent rate-limit responses — some routes return 429 with `Retry-After`, others 503
- **Severity:** P2 · **Area:** contract
- **File(s):** [middleware/rate_limit.py L60-L120](../../backend/middleware/rate_limit.py#L60-L120), [routers/diagrams.py L1](../../backend/routers/diagrams.py)
- **Repro / Evidence:** Custom rate limiter raises `HTTPException(429)`; OpenAI burst protector raises 503. Frontend `apiClient.USER_FRIENDLY_ERRORS` only handles 429.
- **Impact:** Users see "Service unavailable" instead of "Slow down" on burst-limited LLM endpoints.
- **Suggested fix:** Standardize on 429 + `Retry-After` header for all client-throttling cases. Reserve 503 for true outages.
- **Acceptance criteria:** Hitting OpenAI burst limit returns 429; frontend shows friendly retry copy.

#### F-API-13. Activity stream WebSocket drops silently after 60s idle — no heartbeat
- **Severity:** P2 · **Area:** lifecycle
- **File(s):** [routers/activity.py L40-L100](../../backend/routers/activity.py#L40-L100)
- **Repro / Evidence:** WS handler `await ws.receive_text()` only — no server `send_ping`/`send_text(heartbeat)`. Azure Front Door / Container Apps idle timeout = 60s default → connection torn down silently.
- **Impact:** Dashboard "live activity" stalls without UI signal; users assume backend dead.
- **Suggested fix:** Send `{"type":"ping"}` every 25s; client filters; surface disconnect via `onclose` and reconnect with backoff.
- **Acceptance criteria:** Connection survives 10 min idle behind Front Door; client auto-reconnects on close.

### 4.6 QA Master findings (13)

#### F-QA-1. No automated regression test for the user-reported "Sign In box not aligned with screen"
- **Severity:** P0 · **Area:** test-coverage / e2e
- **File(s):** [frontend/src/components/Auth/LoginModal.jsx](../../frontend/src/components/Auth/LoginModal.jsx), [frontend/tests/e2e/](../../frontend/tests/e2e/)
- **Repro / Evidence:** No Playwright or vitest spec asserts modal layout at small viewports. Existing `auth-modal.spec.ts` only checks `isVisible()`. Visual regression suite (Chromatic / Percy) absent.
- **Impact:** F-UX-2 / F-BUG-1 root cause shipped to production without detection. Same regression class will recur.
- **Suggested fix:** Add Playwright spec viewing 320×568 / 360×640 / 1024×768 with `expect(modalBox).toBeInViewport({ ratio: 1 })`; capture screenshot and store baseline. Add vitest unit asserting `aria-modal="true"` + `role="dialog"`.
- **Acceptance criteria:** New spec fails on `main` (pre-fix), passes after fix; CI gate prevents merge if modal Bbox exceeds viewport at any test size.

#### F-QA-2. `apiClient` test suite has no coverage of auth header propagation; F-FE-5 invisible to CI
- **Severity:** P0 · **Area:** test-coverage
- **File(s):** [frontend/src/services/__tests__/apiClient.spec.js](../../frontend/src/services/__tests__/apiClient.spec.js)
- **Repro / Evidence:** Tests stub `fetch` and check status mapping but never assert request `Authorization` header. F-FE-5 (no token on `/history`/`/migration-chat`) is undetected.
- **Impact:** Auth-header regressions ship; observed silently as anon usage.
- **Suggested fix:** Add tests with seeded `useAuthStore` ensuring `request()` attaches Bearer for `/api/...` URLs; ensures it strips Bearer after `logout()`.
- **Acceptance criteria:** Failing test exists pre-fix; passes after F-FE-5 fix; covers internal vs external URL distinction.

#### F-QA-3. Vision-cache hash regression (F-PERF-5) has no test
- **Severity:** P0 · **Area:** test-coverage
- **File(s):** [backend/tests/test_vision_analyzer.py](../../backend/tests/test_vision_analyzer.py), [vision_analyzer.py L249](../../backend/vision_analyzer.py#L249)
- **Repro / Evidence:** No test mutates `SYSTEM_PROMPT` and asserts hash differs. Cache-poisoning class of bug invisible.
- **Impact:** Schema bumps don't invalidate cache; stale outputs survive deploys.
- **Suggested fix:** Add `test_prompt_hash_invalidates_on_system_prompt_change` parametrized over before/after edits.
- **Acceptance criteria:** Test fails on current 200-char-truncated impl; passes when slice removed.

#### F-QA-4. E2E pipeline doesn't cover full upload→analyze→IaC→export-all path
- **Severity:** P1 · **Area:** e2e
- **File(s):** [Archmorph/e2e/](../../e2e/)
- **Repro / Evidence:** E2E tests cover login + upload + view but skip ExportHub + Generate-All. F-FE-9 (DeployPanel raw fetch) and F-PERF-9 (serial export) untested.
- **Impact:** Cross-cutting end-to-end failures only seen in prod.
- **Suggested fix:** Playwright "happy path" spec: upload sample → analyze → IaC → ExportHub → select 6 → Generate All → assert all rows ready under 60s.
- **Acceptance criteria:** Spec passes against current main; gates main branch.

#### F-QA-5. Backend test fixtures don't exercise multi-tenant boundaries
- **Severity:** P1 · **Area:** test-coverage / authz
- **File(s):** [backend/tests/conftest.py](../../backend/tests/conftest.py)
- **Repro / Evidence:** `test_user`/`test_tenant` fixture is single-instance. Tests like F-API-9 (cross-tenant) impossible to write without two-user fixture.
- **Impact:** Authz bugs invisible; F-API-4 / F-API-9 unguarded.
- **Suggested fix:** Add `tenant_a`, `tenant_b`, `user_a`, `user_b` fixtures + helper assertions for "user A cannot read tenant B".
- **Acceptance criteria:** Fixture available; at least 5 cross-tenant tests on diagram, IaC, governance, observability, agent endpoints.

#### F-QA-6. Token-streaming (SSE) tests don't simulate client disconnect
- **Severity:** P1 · **Area:** test-coverage / lifecycle
- **File(s):** [backend/tests/test_llm_streaming.py](../../backend/tests/test_llm_streaming.py)
- **Repro / Evidence:** Tests assert chunks emitted, not that disconnect triggers upstream cancel. F-API-7 invisible.
- **Impact:** Cost regressions on cancelled streams ship.
- **Suggested fix:** Test using `httpx.AsyncClient` that aborts mid-stream; assert backend stops calling upstream within 1s.
- **Acceptance criteria:** Test fails before F-API-7 fix; passes after.

#### F-QA-7. Vitest config doesn't fail on console errors — React #31 invisible to CI
- **Severity:** P1 · **Area:** ci / test-coverage
- **File(s):** [frontend/vitest.config.ts](../../frontend/vitest.config.ts), [frontend/src/test/setup.ts](../../frontend/src/test/setup.ts)
- **Repro / Evidence:** No `vi.spyOn(console, 'error')` global gate. Tests pass even when React logs "Objects are not valid as a React child".
- **Impact:** F-FE-4 regressions ship despite tests rendering offending objects.
- **Suggested fix:** Global setup: spy on `console.error`; throw if any error message includes "React" or "Warning:" or "Objects are not valid".
- **Acceptance criteria:** Existing tests pass; planted React #31 fixture fails CI.

#### F-QA-8. Performance budget not enforced in CI — F-PERF-1 / F-PERF-9 ship undetected
- **Severity:** P1 · **Area:** ci / perf
- **File(s):** [.github/workflows/](../../.github/workflows/), [Archmorph/scripts/perf_budget.py](../../scripts/)
- **Repro / Evidence:** No bundle-size budget, no Lighthouse CI, no backend p95 budget gate.
- **Impact:** Regressions in latency / bundle visible only in prod.
- **Suggested fix:** Lighthouse CI on `frontend` with budget JSON; pytest-benchmark for backend `/analyze` budget; size-limit on Vite bundle.
- **Acceptance criteria:** PR adding 100KB to bundle fails; PR adding 30% latency to `/analyze` fails.

#### F-QA-9. A11y test coverage stops at axe-core static scan — focus order not asserted
- **Severity:** P2 · **Area:** test-coverage / a11y
- **File(s):** [frontend/tests/a11y/](../../frontend/tests/a11y/)
- **Repro / Evidence:** axe-core run on rendered DOM; no test for Tab order / focus trap / Esc.
- **Impact:** F-UX-1 / F-FE-1 only checkable manually.
- **Suggested fix:** Playwright keyboard-only spec for LoginModal: Tab N times → focus stays inside; Esc → closes; focus returns to trigger.
- **Acceptance criteria:** Spec fails before F-UX-1/F-FE-1 fix; passes after.

#### F-QA-10. Mutation testing not enforced — coverage is misleading
- **Severity:** P2 · **Area:** ci / test-quality
- **File(s):** [Archmorph/Makefile](../../Makefile), [pyproject.toml](../../backend/pyproject.toml)
- **Repro / Evidence:** ~80% line coverage but many tests don't assert outputs (just call). No `mutmut` / `cosmic-ray` baseline.
- **Impact:** False sense of safety; line coverage rewards calling code without verifying.
- **Suggested fix:** Run `mutmut` quarterly; track mutation score on critical modules (`session_store`, `vision_analyzer`, `iac_generator`).
- **Acceptance criteria:** Mutation score baseline ≥ 60% on critical modules; alerts on drop.

#### F-QA-11. Flaky tests masked by retries — `pytest --reruns 3` hides race conditions
- **Severity:** P2 · **Area:** ci / flake
- **File(s):** [pyproject.toml `[tool.pytest.ini_options]`](../../backend/pyproject.toml)
- **Repro / Evidence:** `addopts = "--reruns 3 --reruns-delay 1"`. Hides asyncio races (F-PERF-3) and sync-vs-async session bugs (F-PERF-4).
- **Impact:** Concurrency bugs surface only at scale.
- **Suggested fix:** Drop `--reruns` from default config. Add `pytest --rerun-failed` only to CI re-run job, with logging that flakes report to a tracking issue.
- **Acceptance criteria:** Default `pytest` doesn't auto-retry; flake-tracking dashboard exists.

#### F-QA-12. Frontend "all errors silently swallow" pattern — `try { } catch { console.error }` everywhere
- **Severity:** P2 · **Area:** test-coverage / observability
- **File(s):** [frontend/src/](../../frontend/src/)
- **Repro / Evidence:** ~40 sites in components/services use `console.error`. No global error reporter (Sentry, etc.). Tests don't assert `console.error` is called or not called.
- **Impact:** Errors invisible in production; debugging requires browser devtools access.
- **Suggested fix:** Add error-reporter abstraction (`reportError(err, context)`); wire to Sentry or App Insights. Vitest setup fails on unexpected `console.error`.
- **Acceptance criteria:** Production errors flow to monitoring; tests fail on unexpected `console.error`.

#### F-QA-13. CI doesn't smoke-test deploy plan — Terraform/Bicep generation regressions undetected
- **Severity:** P2 · **Area:** ci / iac
- **File(s):** [.github/workflows/](../../.github/workflows/), [scripts/iac_smoke.sh](../../scripts/)
- **Repro / Evidence:** No CI step runs `terraform validate` / `terraform plan -input=false` against generated IaC fixtures.
- **Impact:** IaC generator regressions ship to users (broken `terraform plan` discovered at runtime).
- **Suggested fix:** CI job: feed 3 reference diagrams to `/api/diagrams/.../generate?format=terraform`, write to tmp, `terraform validate` + `terraform plan -input=false -refresh=false` against AzureRM null backend.
- **Acceptance criteria:** PR breaking IaC generator fails; reference plan succeeds without state.

### 4.7 CISO Master findings (13)

#### F-SEC-1. Cross-tenant data exposure on observability SSE — `tenant_id` taken from query param
- **Severity:** P0 · **Area:** authz / multi-tenant
- **File(s):** [backend/routers/observability.py](../../backend/routers/observability.py), [services/token_streaming.py](../../backend/services/token_streaming.py)
- **Repro / Evidence:** SSE handlers accept `?tenant_id=` and use it directly; no comparison to `request.state.user.tenant_id`.
- **Impact:** Any caller with valid auth can stream another tenant's events / usage / agent traces. Likely PII + cost data.
- **Suggested fix:** Drop query param entirely; resolve from auth context. Fail closed if missing.
- **Acceptance criteria:** Pen-test confirms cross-tenant attempt returns 403; SSE streams remain functional intra-tenant.

#### F-SEC-2. `apiClient.js` strips token on every workflow request — auth bypassed by design (F-FE-5)
- **Severity:** P0 · **Area:** auth
- **File(s):** [frontend/src/services/apiClient.js](../../frontend/src/services/apiClient.js#L154-L210)
- **Repro / Evidence:** No `Authorization` header attached to `/api/diagrams`/`/api/v1`/`/api/migration-chat`/etc. Backend treats all such requests as anonymous.
- **Impact:** Authenticated user actions can't be authz-bound. Combined with F-API-9 (no `require_user`), arbitrary diagram access possible.
- **Suggested fix:** See F-FE-5 / F-API-1 fix.
- **Acceptance criteria:** Authenticated users see correct quotas + audit log entries; anon users blocked from owner-only routes.

#### F-SEC-3. IaC chat tampering via client-supplied `current_code` (F-API-3)
- **Severity:** P0 · **Area:** integrity
- **File(s):** [backend/routers/iac_routes.py](../../backend/routers/iac_routes.py#L98-L130)
- **Repro / Evidence:** Server overwrites stored IaC with whatever `current_code` arrives in chat request.
- **Impact:** IaC poisoning; downstream `terraform apply` could deploy attacker payload to victim's Azure subscription if pipeline auto-applies.
- **Suggested fix:** See F-API-3.
- **Acceptance criteria:** Mismatched `current_code` rejected; IaC state never overwritten by anonymous body.

#### F-SEC-4. Vision input + raw error string concatenation enables prompt-injection persistence (F-PERF-5 root)
- **Severity:** P0 · **Area:** prompt-injection
- **File(s):** [backend/vision_analyzer.py L249](../../backend/vision_analyzer.py#L249), [prompt_guard.py](../../backend/prompt_guard.py)
- **Repro / Evidence:** Cache key truncates to 200 chars, all of which are PROMPT_ARMOR. Adversary uploads diagram with embedded text "ignore previous instructions"; cache key remains identical to clean diagram → poisoned response served to other users for 1h.
- **Impact:** Cross-tenant prompt-injection persistence in vision cache; Trust-and-Safety incident class.
- **Suggested fix:** See F-PERF-5; in addition: scrub `_vision_cache` on each new tenant access and tag entries with caller `user_id` (cache key includes user/tenant).
- **Acceptance criteria:** Cache key changes when prompt or system schema changes; entries scoped per tenant.

#### F-SEC-5. CORS may allow `*` with `credentials=true` (F-API-8)
- **Severity:** P0 · **Area:** auth / cors
- **File(s):** [backend/main.py L143-L156](../../backend/main.py#L143-L156)
- **Repro / Evidence:** No fail-fast on conflicting CORS config.
- **Impact:** Browser may send `Cookie: archmorph_session=...` to attacker-controlled origin; full session theft surface.
- **Suggested fix:** Reject `*` when `allow_credentials=True`; raise on startup.
- **Acceptance criteria:** Boot fails with explicit error if conflict; pen-test confirms no credential bleed.

#### F-SEC-6. Public health endpoint discloses model + region + flags (F-API-5)
- **Severity:** P1 · **Area:** info-disclosure
- **File(s):** [backend/routers/health.py L24-L81](../../backend/routers/health.py#L24-L81)
- **Repro / Evidence:** `/api/health` reveals deployed Azure OpenAI region, model name, embedding model, redis status, feature flags.
- **Impact:** Recon for tenant/region-targeted attacks; aids DoS planning.
- **Suggested fix:** See F-API-5 split.
- **Acceptance criteria:** Anonymous response is `{"status":"ok"}` only.

#### F-SEC-7. Container Apps secrets stored in env vars without Key Vault references for prod
- **Severity:** P1 · **Area:** secrets
- **File(s):** [infra/main.tf](../../infra/main.tf), [Archmorph/infra/](../../infra/)
- **Repro / Evidence:** Env block injects `OPENAI_API_KEY`, `DATABASE_URL`, `REDIS_PASSWORD` directly. No `keyVaultUrl`/`identity` reference.
- **Impact:** Secrets visible in `az containerapp show` to anyone with reader role; rotation requires redeploy.
- **Suggested fix:** Convert to Key Vault references; assign User-Assigned Managed Identity; bind via `keyVaultUrl` + `identity`.
- **Acceptance criteria:** `az containerapp show` shows `keyVaultUrl` not raw secret value; rotation test does not require redeploy.

#### F-SEC-8. Rate-limit middleware uses in-memory token bucket per replica — bypassable via load balancing
- **Severity:** P1 · **Area:** rate-limit
- **File(s):** [backend/middleware/rate_limit.py L60-L120](../../backend/middleware/rate_limit.py#L60-L120)
- **Repro / Evidence:** Rate-limit state is per-process. Container Apps with N replicas allows N× requests/min per user.
- **Impact:** Burst cost attacks; DoS undetected.
- **Suggested fix:** Switch to Redis-backed `token_bucket`; share state across replicas.
- **Acceptance criteria:** Hitting limit on one replica also limits other replicas; integration test verifies.

#### F-SEC-9. SSRF surface: `/api/diagrams/upload-url` accepts arbitrary URLs for fetching remote diagrams
- **Severity:** P1 · **Area:** ssrf
- **File(s):** [backend/routers/diagrams.py upload-url](../../backend/routers/diagrams.py)
- **Repro / Evidence:** Endpoint accepts `url` and `httpx.get(url)` to fetch image. No allowlist; no IP-range guard.
- **Impact:** Could fetch internal Azure metadata (`169.254.169.254`), Container Apps platform endpoints, or peer container ports.
- **Suggested fix:** Resolve hostname; reject if RFC1918/IMDS/loopback/link-local. Use httpx `transport` with custom resolver.
- **Acceptance criteria:** SSRF probes against IMDS/internal IPs return 400; legitimate https URLs pass.

#### F-SEC-10. Logs may include OAuth tokens — no scrubber on token-streaming exception paths
- **Severity:** P1 · **Area:** logging / pii
- **File(s):** [backend/services/llm_streaming.py](../../backend/services/llm_streaming.py), [backend/main.py exception handlers](../../backend/main.py)
- **Repro / Evidence:** On `httpx.HTTPStatusError`, full request including `Authorization` header is logged at warning level.
- **Impact:** PII / token leakage to App Insights; T&S incident class.
- **Suggested fix:** Scrub `Authorization`/`X-API-Key`/`Cookie` headers in `request_repr`. Add log filter that redacts known secret patterns.
- **Acceptance criteria:** Forced 500 with auth header → log entry redacts token; CI lint forbids `repr(headers)` without scrubber.

#### F-SEC-11. CSP missing on FastAPI responses — only frontend index.html sets it
- **Severity:** P2 · **Area:** xss
- **File(s):** [backend/main.py middleware](../../backend/main.py), [frontend/index.html](../../frontend/index.html)
- **Repro / Evidence:** Backend HTML responses (errors, `/docs`) lack `Content-Security-Policy` header.
- **Impact:** `/docs` Swagger UI vulnerable to script injection through query params on older browsers; minor.
- **Suggested fix:** Apply `CSP` middleware on backend HTML responses.
- **Acceptance criteria:** All HTML responses carry `Content-Security-Policy`.

#### F-SEC-12. CSRF protection absent for cookie-auth (SWA) routes
- **Severity:** P2 · **Area:** csrf
- **File(s):** [backend/main.py](../../backend/main.py), [routers/auth.py](../../backend/routers/auth.py)
- **Repro / Evidence:** SWA cookie-auth path has no `SameSite=Strict` documented; no double-submit token.
- **Impact:** Cross-site request forgery on logged-in SWA users; theft of profile mutation.
- **Suggested fix:** Set cookie `SameSite=Strict`; require `X-CSRF-Token` for state-changing routes when using cookie auth.
- **Acceptance criteria:** Pen-test CSRF probe blocked; existing flows unaffected.

#### F-SEC-13. Audit log entries missing actor + IP for guest-mode actions
- **Severity:** P2 · **Area:** audit
- **File(s):** [backend/services/audit.py](../../backend/services/audit.py)
- **Repro / Evidence:** Guest sessions logged as `actor=null`. No IP captured.
- **Impact:** Forensic gap; abuse investigation requires server logs.
- **Suggested fix:** Stamp `actor=session_id`, `ip=request.client.host` on every audit row; rotate session ID daily.
- **Acceptance criteria:** Audit row has non-null actor + IP for every state-changing call.

### 4.8 DevOps Master findings (14)

#### F-DO-1. Branch protection paths-ignore deadlock — ignored-only PRs can never merge
- **Severity:** P0 · **Area:** ci / branch-protection
- **File(s):** [.github/workflows/ci.yml](../../.github/workflows/ci.yml), repository branch-protection settings
- **Repro / Evidence:** `paths-ignore: ['LICENSE', '.gitignore']` on workflow; branch protection requires 7 status checks. PR touching only ignored paths never runs workflow → checks never report → merge blocked. Affected: any docs/license-only patch.
- **Impact:** Documentation maintenance halted; admins must override (but `enforce_admins=true`).
- **Suggested fix:** Add no-op job that always runs and reports each required status. OR drop `paths-ignore`. OR add `paths` complement so workflow always reports.
- **Acceptance criteria:** PR touching only LICENSE merges automatically; existing path-aware skip logic preserved.

#### F-DO-2. Deploy workflow doesn't gate on infra `terraform plan` review for prod
- **Severity:** P0 · **Area:** deploy / iac
- **File(s):** [.github/workflows/deploy.yml](../../.github/workflows/deploy.yml), [infra/main.tf](../../infra/main.tf)
- **Repro / Evidence:** Deploy job runs `terraform apply -auto-approve` on prod; plan output not posted, no manual approval gate.
- **Impact:** Destructive plan can ship (e.g., resource recreate that drops Postgres data).
- **Suggested fix:** Split into plan + apply jobs; require `environment: production` GitHub deployment with reviewer approval; post plan to PR comment.
- **Acceptance criteria:** Prod deploy requires explicit click-through; plan visible to approver; staging unaffected.

#### F-DO-3. Container image not pinned by digest in deploy step
- **Severity:** P0 · **Area:** supply-chain / deploy
- **File(s):** [.github/workflows/deploy.yml](../../.github/workflows/deploy.yml), [infra/main.tf container app block](../../infra/main.tf)
- **Repro / Evidence:** ACR image referenced as `archmorph.azurecr.io/backend:latest` in container app spec; no SHA digest.
- **Impact:** Mutable tag can be replaced by attacker with ACR write access; rollback ambiguous.
- **Suggested fix:** Push image with digest; use `image@sha256:...` in tf var; output digest in build job.
- **Acceptance criteria:** Deploy artifacts include immutable digest; rollback resolves to specific digest.

#### F-DO-4. Backend Dockerfile runs as root — no `USER` directive
- **Severity:** P0 · **Area:** container-security
- **File(s):** [backend/Dockerfile](../../backend/Dockerfile)
- **Repro / Evidence:** Final stage doesn't `USER nonroot`; `pip install` runs in `/app` then `CMD uvicorn` as root.
- **Impact:** Container escape consequences worse; CIS Benchmark fail.
- **Suggested fix:** Add non-root user; chown app dir; switch `USER`.
- **Acceptance criteria:** `docker run --rm img id` reports non-root; smoke test boots.

#### F-DO-5. CI doesn't run `pip-audit` / `npm audit` / Trivy on every PR
- **Severity:** P1 · **Area:** supply-chain
- **File(s):** [.github/workflows/ci.yml](../../.github/workflows/ci.yml)
- **Repro / Evidence:** Only test+lint jobs; no SCA scan; no container scan.
- **Impact:** Vulnerable transitive deps and base images ship without alert.
- **Suggested fix:** Add `pip-audit`, `npm audit --production`, Trivy fs+image scan; fail on `HIGH`/`CRITICAL`.
- **Acceptance criteria:** PR introducing CVE-tagged dep fails; existing tests unaffected.

#### F-DO-6. Health probe uses GET `/api/health` which exposes leaked info (F-API-5)
- **Severity:** P1 · **Area:** infra / probe
- **File(s):** [infra/main.tf container_app probes](../../infra/main.tf)
- **Repro / Evidence:** Liveness/readiness probes hit `/api/health` (detailed). Combined with F-API-5, every health probe returns full dependency info.
- **Impact:** Cloud platform logs accumulate sensitive info; F-API-5 fix breaks probes.
- **Suggested fix:** Coordinate with F-API-5: probes use new `/healthz` minimal endpoint.
- **Acceptance criteria:** Probes use `/healthz`; detailed `/api/health` requires auth.

#### F-DO-7. No `pre-commit` hooks for secret scanning
- **Severity:** P1 · **Area:** secret-scanning
- **File(s):** [.pre-commit-config.yaml](../../.pre-commit-config.yaml)
- **Repro / Evidence:** Config absent or doesn't include `gitleaks` / `detect-secrets`.
- **Impact:** Accidental secret commit leads to ACR/Azure key exposure.
- **Suggested fix:** Add `gitleaks` pre-commit + GitHub push protection.
- **Acceptance criteria:** Forced commit with synthetic AKIA key blocked locally and at push.

#### F-DO-8. Test database uses real Postgres but no clean-state fixture — flaky parallel runs
- **Severity:** P1 · **Area:** ci / flake
- **File(s):** [backend/tests/conftest.py](../../backend/tests/conftest.py), [Archmorph/Makefile](../../Makefile)
- **Repro / Evidence:** Tests share single DB; `pytest -n auto` (xdist) causes data contamination → flake; `--reruns 3` masks.
- **Impact:** Flaky CI; can hide real bugs (F-PERF-3 race).
- **Suggested fix:** Per-worker schema (or savepoint rollback per test); drop `--reruns 3`.
- **Acceptance criteria:** Parallel runs deterministic; no schema bleed.

#### F-DO-9. Frontend build doesn't fail on TypeScript / typecheck errors
- **Severity:** P1 · **Area:** ci / typing
- **File(s):** [frontend/package.json `build`](../../frontend/package.json), [tsconfig.json](../../frontend/tsconfig.json)
- **Repro / Evidence:** `vite build` doesn't run `tsc --noEmit`. CI script for FE missing typecheck step.
- **Impact:** `.ts` regressions reach prod (e.g., F-API-10 type drift).
- **Suggested fix:** Add `typecheck: "tsc --noEmit"`; run in CI.
- **Acceptance criteria:** PR with TS error fails CI.

#### F-DO-10. No alerts on Container Apps replica restart count
- **Severity:** P1 · **Area:** monitoring
- **File(s):** [infra/observability.tf](../../infra/observability.tf)
- **Repro / Evidence:** No metric alert on `revisionRestarts` or `RestartCount`.
- **Impact:** OOM-kills (F-PERF-2 risk) and crash loops invisible.
- **Suggested fix:** Add metric alerts on restart count >3/15min and CPU >85% sustained 10min.
- **Acceptance criteria:** Synthetic OOM triggers alert within 5 min.

#### F-DO-11. Rollback path undocumented — no `azd down`/`tf destroy` runbook
- **Severity:** P2 · **Area:** runbook / dr
- **File(s):** [docs/runbook/rollback.md](../../docs/runbook/), [Archmorph/docs/](../../docs/)
- **Repro / Evidence:** No formal rollback doc; deploy notes mention forward-only.
- **Impact:** Outage MTTR longer than necessary; on-call ambiguity.
- **Suggested fix:** Author runbook covering ACR tag pin, container app traffic split rollback, alembic downgrade caveats.
- **Acceptance criteria:** On-call drill executes rollback in <10min using runbook.

#### F-DO-12. Alembic migration testing not part of CI smoke
- **Severity:** P2 · **Area:** ci / db
- **File(s):** [.github/workflows/ci.yml](../../.github/workflows/ci.yml), [backend/alembic/](../../backend/alembic/)
- **Repro / Evidence:** No CI step `alembic upgrade head` against fresh DB; no `--sql` dry-run.
- **Impact:** Migration regressions discovered in prod.
- **Suggested fix:** CI job: spin Postgres + pgvector + run `alembic upgrade head` + downgrade to base + reupgrade.
- **Acceptance criteria:** Broken migration PR fails CI; existing migrations green.

#### F-DO-13. CodeQL workflow disabled or absent
- **Severity:** P2 · **Area:** sast
- **File(s):** [.github/workflows/codeql.yml](../../.github/workflows/codeql.yml)
- **Repro / Evidence:** No CodeQL workflow file in repo.
- **Impact:** SAST blind spots; OWASP-Top-10 issues uncaught.
- **Suggested fix:** Add CodeQL `init` + `analyze` for `python` and `javascript`; weekly schedule.
- **Acceptance criteria:** CodeQL alerts visible in Security tab; CI publishes SARIF.

#### F-DO-14. Frontend env-var secrets risk — `VITE_` prefix may leak service-side keys
- **Severity:** P2 · **Area:** secret-scanning
- **File(s):** [frontend/.env.example](../../frontend/.env.example), [frontend/vite.config.ts](../../frontend/vite.config.ts)
- **Repro / Evidence:** Convention permits `VITE_OPENAI_KEY` etc. — anything `VITE_*` ships in bundle. No lint that disallows secret-looking names.
- **Impact:** Single misnamed env shipped; key disclosure.
- **Suggested fix:** Lint script that fails build if `VITE_*` env name matches `(KEY|TOKEN|SECRET|PASSWORD)`; ban list in vite config.
- **Acceptance criteria:** PR introducing `VITE_FOO_KEY` fails build with error.

### 4.9 Cloud Master findings (14)

#### F-CL-1. Single Azure region — no DR plan for Azure OpenAI / Postgres / Container Apps outage
- **Severity:** P0 · **Area:** dr / availability
- **File(s):** [infra/main.tf](../../infra/main.tf), [Archmorph/infra/](../../infra/)
- **Repro / Evidence:** All resources `location = var.location` (single region). No paired region; no AOAI failover; no Postgres geo-replica.
- **Impact:** Region outage = full outage. AOAI quota issues uncovered.
- **Suggested fix:** Document and stage a multi-region active/passive: Postgres geo-replica; AOAI deployments in 2 regions with failover wrapper; Front Door routing.
- **Acceptance criteria:** DR runbook + smoke test failing over to paired region in <1h RTO.

#### F-CL-2. Postgres Flexible Server uses local SSD with no point-in-time recovery beyond 7 days
- **Severity:** P0 · **Area:** backup / dr
- **File(s):** [infra/main.tf postgres block](../../infra/main.tf)
- **Repro / Evidence:** `backup_retention_days` default 7; no geo_redundant_backup configured.
- **Impact:** Data loss horizon limited to 7 days; cross-region backup unavailable for tenant restore.
- **Suggested fix:** Set `backup_retention_days = 35`; `geo_redundant_backup_enabled = true`.
- **Acceptance criteria:** PITR works at 14 days; geo backup verifiable.

#### F-CL-3. ACR set to `Basic` SKU — no geo-replication and image scanning unavailable
- **Severity:** P0 · **Area:** registry / supply-chain
- **File(s):** [infra/main.tf acr block](../../infra/main.tf)
- **Repro / Evidence:** `sku_name = "Basic"`. Container Apps in another region must pull cross-region; no Defender scanning.
- **Impact:** Cold-start image pull latency; CVE blind spot.
- **Suggested fix:** Upgrade to `Premium`; enable geo replication to paired region; enable Defender for ACR.
- **Acceptance criteria:** Pulls from paired region <500ms; Defender alerts on CVE in pushed image.

#### F-CL-4. Postgres + Redis publicly reachable — `public_network_access_enabled=true`
- **Severity:** P0 · **Area:** network / authz
- **File(s):** [infra/main.tf postgres + redis blocks](../../infra/main.tf)
- **Repro / Evidence:** No private endpoint; firewall rule `0.0.0.0` for "Allow Azure services" enabled.
- **Impact:** Wider attack surface; reliance on auth alone for protection.
- **Suggested fix:** Disable public access; place in VNET; add private endpoints; route Container Apps via VNET.
- **Acceptance criteria:** `nslookup` from outside VNET fails; Container Apps connect via private DNS.

#### F-CL-5. No Azure Policy assignments for tagging / region restriction / SKU governance
- **Severity:** P0 · **Area:** governance
- **File(s):** [infra/main.tf](../../infra/main.tf), [Azure subscription policy assignments](../../docs/cloud/)
- **Repro / Evidence:** No `azurerm_subscription_policy_assignment`; subscription allows arbitrary regions.
- **Impact:** Drift; cost + compliance risk (e.g., resources in non-data-residency region).
- **Suggested fix:** Apply built-in policies: `Allowed locations`, `Inherit a tag from the resource group`, `Allowed resource SKUs`.
- **Acceptance criteria:** Non-compliant resource creation denied; reports clean.

#### F-CL-6. Diagnostic settings missing on Postgres / Redis / Container Apps
- **Severity:** P0 · **Area:** observability
- **File(s):** [infra/observability.tf](../../infra/observability.tf), [infra/main.tf](../../infra/main.tf)
- **Repro / Evidence:** Only Application Insights for backend; no `azurerm_monitor_diagnostic_setting` on data plane.
- **Impact:** Cannot diagnose connection storms, slow queries, eviction; audit trail gap.
- **Suggested fix:** Diagnostic settings → Log Analytics for Postgres (PostgreSQLLogs, PostgreSQLFlexQueryStoreRuntime), Redis, Container Apps console+system logs.
- **Acceptance criteria:** Logs visible in Log Analytics within 5 min of event.

#### F-CL-7. Front Door / API Management not in front of Container Apps
- **Severity:** P0 · **Area:** edge / waf
- **File(s):** [infra/main.tf](../../infra/main.tf), [docs/architecture.md](../../docs/architecture.md)
- **Repro / Evidence:** Container App ingress directly internet-exposed; no WAF.
- **Impact:** No WAF rules, no global edge cache, DDoS Standard not engaged at L7.
- **Suggested fix:** Add Azure Front Door Premium with WAF policy (OWASP CRS), restrict Container App ingress to FD private link.
- **Acceptance criteria:** Direct origin requests blocked; WAF logs OWASP rule hits.

#### F-CL-8. Cost alerts not configured on AOAI deployment
- **Severity:** P1 · **Area:** finops
- **File(s):** [infra/main.tf openai block](../../infra/main.tf)
- **Repro / Evidence:** No `azurerm_consumption_budget_subscription` / resource-group budget on AOAI; no alert on token spike.
- **Impact:** Burst from prompt-injection / runaway agent loop costs unbounded.
- **Suggested fix:** Budget with 80%/100%/120% alerts; rate-limit at AOAI deployment.
- **Acceptance criteria:** Synthetic spike triggers alert email at 80%.

#### F-CL-9. Managed Identity not used for AOAI access — API key in env var
- **Severity:** P1 · **Area:** auth / secrets
- **File(s):** [infra/main.tf openai block](../../infra/main.tf), [backend/openai_client.py](../../backend/openai_client.py)
- **Repro / Evidence:** `OPENAI_API_KEY` env var; no `DefaultAzureCredential` flow.
- **Impact:** Key rotation requires redeploy; theft = unconstrained access.
- **Suggested fix:** Switch to Managed Identity + `Cognitive Services User` role; fall back to key only for local dev.
- **Acceptance criteria:** Container Apps uses MI in prod; rotating key not required.

#### F-CL-10. Container Apps autoscale rules use only HTTP concurrency, not custom metrics
- **Severity:** P1 · **Area:** scale
- **File(s):** [infra/main.tf container_app autoscale](../../infra/main.tf)
- **Repro / Evidence:** Single `http` rule scaled at 100 concurrent requests. No KEDA on queue depth or AOAI saturation.
- **Impact:** Latency-bound workloads (long generation) saturate concurrency before scale-out.
- **Suggested fix:** Add KEDA scaler on Application Insights p95 latency; tune min replicas during business hours.
- **Acceptance criteria:** Burst test scales out within 30s; cold-start mitigated.

#### F-CL-11. Storage Account for blobs missing customer-managed keys
- **Severity:** P1 · **Area:** encryption
- **File(s):** [infra/main.tf storage block](../../infra/main.tf)
- **Repro / Evidence:** SSE only; no `customer_managed_key` block; key in MS-managed.
- **Impact:** Compliance drift for tenants requiring CMK.
- **Suggested fix:** Add Key Vault + CMK block; rotate keys per policy.
- **Acceptance criteria:** Storage encryption status shows CMK active.

#### F-CL-12. App Insights sampling at 100% — log storm cost risk
- **Severity:** P2 · **Area:** finops / observability
- **File(s):** [infra/observability.tf](../../infra/observability.tf)
- **Repro / Evidence:** No sampling configured; 100% telemetry sent.
- **Impact:** Spike days drive AI ingest cost.
- **Suggested fix:** Adaptive sampling at 5–10% with override for errors.
- **Acceptance criteria:** Ingest volume drops ≥80% on representative day; errors still 100%.

#### F-CL-13. Network security groups absent on Container Apps subnet
- **Severity:** P2 · **Area:** network
- **File(s):** [infra/main.tf vnet/subnet blocks](../../infra/main.tf)
- **Repro / Evidence:** No NSG attached; default-allow inbound from VNET.
- **Impact:** Lateral movement from compromised neighbor (when in shared env).
- **Suggested fix:** NSG with explicit deny inbound except platform; outbound restricted to AOAI + Postgres + Redis FQDNs.
- **Acceptance criteria:** Lateral probe on port 8000 from unrelated subnet blocked.

#### F-CL-14. No infrastructure tests — `terraform-compliance` / `checkov` not in CI
- **Severity:** P2 · **Area:** ci / iac
- **File(s):** [.github/workflows/ci.yml](../../.github/workflows/ci.yml), [infra/](../../infra/)
- **Repro / Evidence:** No policy-as-code tests on TF.
- **Impact:** Infra drift / misconfig only caught at deploy time.
- **Suggested fix:** Add `checkov` + custom `terraform-compliance` rules: tags required, no public DBs, encryption-on, etc.
- **Acceptance criteria:** PR introducing public DB blocked at CI.

### 4.10 Bug Master findings (14)

#### F-BUG-1. ROOT CAUSE: Sign-in modal not aligned to viewport — `backdrop-filter` on Nav header creates containing block for `position:fixed` descendants
- **Severity:** P0 · **Area:** alignment / css
- **File(s):** [frontend/src/components/Nav.jsx L178](../../frontend/src/components/Nav.jsx#L178), [frontend/src/components/Auth/LoginModal.jsx L78](../../frontend/src/components/Auth/LoginModal.jsx#L78), [frontend/src/components/Auth/UserMenu.jsx L43](../../frontend/src/components/Auth/UserMenu.jsx#L43)
- **Repro / Evidence:** **DIRECT MATCH FOR USER-REPORTED BUG.** `<header>` element uses `backdrop-blur-xl` Tailwind utility → `backdrop-filter: blur(24px)`. Per CSS spec, any element with `backdrop-filter !== none` becomes a containing block for descendants with `position: fixed`. `LoginModal` is rendered inside `<UserMenu>` which is inside the header. Its `position: fixed inset-0` therefore anchors to the header's 56px-tall rectangle — **NOT** the viewport. Result: modal appears clipped to top stripe of the page; users see "the box is not aligned with the screen".
- **Impact:** Sign-in unusable; primary auth flow effectively broken. Same pattern affects any `position:fixed` descendant of the header.
- **Suggested fix:** Portal the modal to `document.body` via `ReactDOM.createPortal(...)` — or hoist `loginModalOpen` state up to App and render `<LoginModal>` as sibling of `<Nav>`. Both detach the fixed element from the header's containing block.
- **Acceptance criteria:** With backdrop-blur header retained, LoginModal centers in viewport at all sizes; element inspector shows modal as direct child of `<body>`; F-UX-2 / F-FE-3 also resolved.

#### F-BUG-2. `useAuthStore.initialize()` race — first paint shows logged-out shell even when SWA cookie present
- **Severity:** P0 · **Area:** auth / hydration
- **File(s):** [frontend/src/stores/useAuthStore.js L13-L97](../../frontend/src/stores/useAuthStore.js#L13-L97), [frontend/src/main.jsx](../../frontend/src/main.jsx)
- **Repro / Evidence:** `initialize` is async (calls `/.auth/me`). UI mounts with `isAuthenticated=false`, then flips to `true` after fetch. Result: brief "Sign In" flash + tab teleport (F-FE-10) for SWA users.
- **Impact:** Confusing flicker; analytics double-counts session start.
- **Suggested fix:** Show skeleton until `authReady` flag is set; suppress UserMenu render until then. Wrap App in `<AuthBootstrap>`.
- **Acceptance criteria:** No "Sign In" flash on page reload for authenticated SWA users; reproducible via Playwright.

#### F-BUG-3. `useEffect(() => fetch(...), [])` lacks AbortController in `MigrationDashboard`
- **Severity:** P1 · **Area:** lifecycle
- **File(s):** [frontend/src/components/MigrationDashboard/index.jsx](../../frontend/src/components/MigrationDashboard/index.jsx)
- **Repro / Evidence:** Effect fetches but doesn't abort on unmount. Switching tabs while load in flight produces "Can't perform a React state update on unmounted component" warnings.
- **Impact:** Memory leaks under heavy nav; setState-after-unmount.
- **Suggested fix:** Use `AbortController` in effect; `signal: ctrl.signal` on fetch; `return () => ctrl.abort()`.
- **Acceptance criteria:** Console clean on rapid tab switching.

#### F-BUG-4. Race: `IaCViewer` apply-changes button can fire twice on double-click
- **Severity:** P1 · **Area:** state
- **File(s):** [frontend/src/components/DiagramTranslator/IaCViewer.jsx](../../frontend/src/components/DiagramTranslator/IaCViewer.jsx)
- **Repro / Evidence:** Apply button doesn't disable during request; double-click sends two PATCHes; backend accepts both → duplicate `iac_chat_session.history` entries.
- **Impact:** Inconsistent session state; user-visible redo of same diff.
- **Suggested fix:** `disabled={pending}`; `pending` ref-guard in handler.
- **Acceptance criteria:** Double-click results in single PATCH; second click no-ops.

#### F-BUG-5. Backend `azure_landing_zone.py` raises on diagrams with 0 mappings — should return empty SVG
- **Severity:** P1 · **Area:** edge-case
- **File(s):** [backend/azure_landing_zone.py L74](../../backend/azure_landing_zone.py#L74)
- **Repro / Evidence:** `for tier in tiers: ... if not services: ...` falls through on empty mapping list → `IndexError` on inner indexing.
- **Impact:** Empty/invalid uploads 500 instead of friendly error.
- **Suggested fix:** Guard `if not mappings: return self._empty_svg()`.
- **Acceptance criteria:** POST to `/landing-zone` with 0 mappings returns 200 + placeholder SVG.

#### F-BUG-6. `useToast` hook not invoked from `apiClient` 5xx mapping — error UX absent
- **Severity:** P1 · **Area:** error-handling
- **File(s):** [frontend/src/services/apiClient.js](../../frontend/src/services/apiClient.js), [frontend/src/components/](../../frontend/src/components/)
- **Repro / Evidence:** `ApiError` thrown but `console.error` only — no central toast. F-UX-7 / this duplicate.
- **Impact:** Errors invisible; users don't see why action failed.
- **Suggested fix:** See F-UX-7 / introduce `useToast` and wire `apiClient` to publish to it.
- **Acceptance criteria:** Backend 500 produces toast with mapped copy.

#### F-BUG-7. `dump_configs.py` writes `terraform.tfvars` containing secrets in plaintext to repo root
- **Severity:** P1 · **Area:** secrets
- **File(s):** [Archmorph/scripts/dump_configs.py](../../scripts/dump_configs.py), [/Users/idokatz/VSCode/dump_configs.py](../../../dump_configs.py)
- **Repro / Evidence:** Workspace-root `dump_configs.py` writes tfvars with literal secrets to current dir. Easy to commit accidentally.
- **Impact:** Secret leak via git.
- **Suggested fix:** Write to `~/.config/archmorph/...` outside repo; add `.gitignore` entry; warn user.
- **Acceptance criteria:** Running script doesn't place tfvars under any git working tree.

#### F-BUG-8. `Diagram.iac_terraform` updated without version bump — concurrent edits silently overwrite
- **Severity:** P1 · **Area:** consistency
- **File(s):** [backend/models.py Diagram](../../backend/models.py), [routers/iac_routes.py apply_changes](../../backend/routers/iac_routes.py)
- **Repro / Evidence:** Two clients open same IaC; both edit; last-write-wins. No `If-Match` ETag.
- **Impact:** Lost edits in collaborative scenarios.
- **Suggested fix:** Add `version` int column; require `If-Match: <version>` header; 409 on mismatch.
- **Acceptance criteria:** Concurrent edit test surfaces 409 instead of silent overwrite.

#### F-BUG-9. SSE message split across event boundary corrupts JSON in agent runner stream
- **Severity:** P1 · **Area:** streaming
- **File(s):** [backend/services/llm_streaming.py](../../backend/services/llm_streaming.py), [services/agent_runner.py](../../backend/services/agent_runner.py)
- **Repro / Evidence:** Producer doesn't buffer until newline; chunks emit `data: {"type":"delt` `a","content":"..."}` split across events under high concurrency.
- **Impact:** Frontend SSE parser drops malformed event silently → missing tokens.
- **Suggested fix:** Wait for newline-terminated frame before yielding; or use `event-stream` framing helper.
- **Acceptance criteria:** Synthetic 1KB-burst test never produces split events.

#### F-BUG-10. `Roadmap.jsx` infinite re-render when `roadmapItems` updated by parent each render
- **Severity:** P2 · **Area:** state / perf
- **File(s):** [frontend/src/components/Roadmap.jsx](../../frontend/src/components/Roadmap.jsx)
- **Repro / Evidence:** `useEffect` depends on `roadmapItems` reference; parent re-creates array each render → infinite loop disguised by `JSON.stringify` guard inside effect.
- **Impact:** CPU spike on Roadmap tab; battery drain on mobile.
- **Suggested fix:** `useMemo` array in parent; or compare items by key.
- **Acceptance criteria:** Performance trace shows steady-state 0 effect re-runs after mount.

#### F-BUG-11. `analyze` endpoint returns 200 + `error` in body for vision API failure — frontend treats as success
- **Severity:** P2 · **Area:** error-handling / contract
- **File(s):** [backend/routers/diagrams.py L130-L350](../../backend/routers/diagrams.py#L130-L350), [frontend/src/components/DiagramTranslator/AnalysisResults.jsx](../../frontend/src/components/DiagramTranslator/AnalysisResults.jsx)
- **Repro / Evidence:** On AOAI 429, server logs and returns `{"analysis":{}, "error":"rate limited"}` with HTTP 200.
- **Impact:** Empty analysis renders silently; users blame app.
- **Suggested fix:** Return 503 with `Retry-After`; align with F-API-12.
- **Acceptance criteria:** Frontend shows mapped retry copy; no silent empty result.

#### F-BUG-12. `vite.config.ts` uses dev-only `define: { 'process.env': ... }` — leaks server env names into bundle
- **Severity:** P2 · **Area:** secrets
- **File(s):** [frontend/vite.config.ts](../../frontend/vite.config.ts)
- **Repro / Evidence:** `define` block injects `process.env.SOMETHING` strings; bundler embeds key names (not values) into chunks.
- **Impact:** Recon for attackers; reveals deployment env structure.
- **Suggested fix:** Restrict `define` to specific keys; never use `process.env` blanket.
- **Acceptance criteria:** Built bundle has no env-name leakage.

#### F-BUG-13. `Dockerfile.frontend` doesn't pin Node patch version — supply-chain drift
- **Severity:** P2 · **Area:** supply-chain
- **File(s):** [frontend/Dockerfile](../../frontend/Dockerfile)
- **Repro / Evidence:** `FROM node:22` (no patch). Reproducibility broken.
- **Impact:** Build outputs differ between rebuilds; harder to reproduce bugs.
- **Suggested fix:** Pin `FROM node:22.x.y-alpine@sha256:...`.
- **Acceptance criteria:** Two rebuilds produce identical layer hashes.

#### F-BUG-14. `useFocusTrap` hook releases trap on `pointerdown` outside but doesn't restore on dialog close from Esc
- **Severity:** P2 · **Area:** focus
- **File(s):** [frontend/src/hooks/useFocusTrap.js](../../frontend/src/hooks/useFocusTrap.js)
- **Repro / Evidence:** Trap released on outside click; Esc path bypasses release/restore symmetry.
- **Impact:** Focus left on detached node; SR confusion.
- **Suggested fix:** Symmetric release on every close path; restore previously-focused element via stored ref.
- **Acceptance criteria:** Esc / X / backdrop / success-redirect all restore focus to opener.

---

## 5. CTO Master — Audit Framing (delegated brief)

> Verified GitHub state: only #607 is open. The "open follow-ups" listed in the prompt (#610–#647) are all CLOSED. Agents must hunt for **drift in shipped fixes** and **new un-filed defects**, not re-triage closed tickets.

### Executive summary

Archmorph is post-Sprint-1-P0 with the ALZ production-ready epic (#586/#606) merged, Sprint 1 security cluster closed (#610/#611/#612/#613/#614), and the React #31 saga finally laid to rest in PR #636. The repo is in a **"green CI, brittle seams" phase**: 60+ backend routers, 5+ different auth dependencies wired inconsistently, fragmented session stores, and a frontend whose Sign-In flow ships without a11y guarantees. Target: 4.3.0 GA-readiness rubric (golden-file diff, p95 SLOs, accessibility floor) and removal of the load-bearing inconsistencies before scope grows again.

### Cross-cutting concerns (route to multiple agents)

- **Auth scheme fragmentation** — `verify_api_key` (single shared `X-API-Key`), `verify_admin_key` (Bearer JWT), `verify_icon_pack_admin`, `verify_export_capability` (capability token), `get_current_user` (session/Bearer for `policies.py`, `agent_memory.py`, `deploy.py`), plus SWA-redirect identity in [frontend/src/stores/useAuthStore.js](frontend/src/stores/useAuthStore.js#L100). Same diagram lifecycle is gated by `verify_api_key` on upload/analyze but `verify_export_capability` on export. **Route to: Backend + CISO + API Master.**
- **Multi-tenant boundary is implicit** — Agent ORM carries `organization_id` but `verify_api_key` is a single env-level shared secret. Anything authenticated by `X-API-Key` is effectively cross-tenant. **Route to: Backend + CISO + Cloud.**
- **In-memory / file-backed stores in production without Redis** — `shared.py` warns at startup but does not fail; `SESSION_STORE`, `IMAGE_STORE`, `SHARE_STORE`, `EXPORT_CAPABILITY_STORE`, `PROJECT_STORE` lose state on redeploy and don't shard across replicas. **Route to: Backend + Devops + Performance.**
- **Closed-fix drift verification** — agents must verify shipped fixes (#610/#612/#613/#614) are still wired (regression risk: stacked PR rebases). **Route to: CISO + QA + API Master.**
- **`/api/v1/api/...` double-prefix paths** in `openapi.snapshot.json`. Mount-time routing bug. **Route to: API Master + Backend.**

### Top-of-mind hypotheses

1. **Sign In modal alignment & a11y** — trigger button in [frontend/src/components/Nav.jsx](frontend/src/components/Nav.jsx); modal lacks dialog role / focus trap / Esc handler in [frontend/src/components/Auth/LoginModal.jsx](frontend/src/components/Auth/LoginModal.jsx).
2. **Auth fragmentation real-world impact** — single shared `X-API-Key` is the only gate on most public routes.
3. **Stateless container + in-memory stores** — `EXPORT_CAPABILITY_STORE` lost on redeploy invalidates outstanding capability tokens.
4. **Hot-reload of live service catalog** — `/api/services/providers` may still be serving import-time snapshot.
5. **`/api/v1/api/...` double-prefix** in v1 mount.
6. **Vision-cache TTL collision with #636 coercion** — cached entries from before #636 may still leak `{type, message}` objects until TTL expires.
7. **Pydantic `extra='forbid'`** (#614 closed) — verify it's on every public schema.
8. **`restore-session` without auth** — confirm path is intentional and rate-limited.

### Out-of-scope

- Retention E2 contractor sandbox.
- CISO threat-model session deliverables (covered by #596).
- Sprint 2 ALZ deferreds (#591–#594) unless agent finds a P0 defect.
- Sibling projects (PowerPlatfromViaNATGW, SecondNature, Relio).
- Re-litigating model picks from #602.

## 5b. CTO Master — Consolidated Verdict

### Headline

130 findings across 10 specialist agents. **41 P0 / 39 P1 / 50 P2.** Five P0s form a single coherent failure cluster: **the auth seam is a fiction** — frontend strips `Authorization` (F-FE-5/F-API-1), `restore-session` is unauthenticated (F-BE-1), Terraform state backend has zero auth + a typoed UNLOCK (F-BE-2), observability SSE accepts tenant from query string (F-API-4/F-SEC-1), and CORS may permit `*` with credentials (F-API-8/F-SEC-5). The user-reported "Sign In box not aligned" reproduced and root-caused as **F-BUG-1**: `backdrop-filter` on the Nav header creates a containing block for `position:fixed` descendants — a one-line fix (portal modal to `document.body`) closes it and clears the entire F-UX-2 / F-FE-3 cluster.

### Top 5 risks (must fix before next release)

1. **Auth fiction** (F-FE-5, F-API-1, F-BE-1, F-BE-2, F-API-9, F-SEC-1) — Composite blast radius: cross-tenant data exposure on observability SSE, Terraform state read/write by anonymous, IaC poisoning via `current_code` body field, anonymous `restore-session` overwriting any diagram. Single P0 cluster — must close together.
2. **Memory ceiling violation** (F-PERF-2) — `IMAGE_STORE` byte-budget is dead code; under burst, peak ≈ 670MB per worker on a 1GB replica → OOM-kill cascade. Combined with F-DO-10 (no restart-count alert) and F-CL-6 (no diagnostic settings), outage is undetected.
3. **Vision-cache poisoning** (F-PERF-5, F-SEC-4) — 200-char prompt-hash truncation means schema bumps don't invalidate cache and prompt-injection responses persist for 1h cross-tenant. Trust-and-Safety incident class.
4. **Single-region, public DBs, no DR** (F-CL-1, F-CL-2, F-CL-4) — Postgres + Redis publicly reachable, single region, 7-day PITR, no geo-redundant backup. Region outage = full outage.
5. **Branch protection deadlock** (F-DO-1) — `paths-ignore` + 7 required checks + `enforce_admins=true` → docs-only PRs cannot merge. Already affecting maintenance velocity.

### Top 5 quick wins (≤ 1 day each, high payoff)

1. **F-BUG-1 / F-UX-2 / F-FE-3** — Portal LoginModal to `document.body`. Fixes user-reported alignment AND mobile alignment AND clipping in one change.
2. **F-API-1 / F-FE-5** — `apiClient` reads token from `useAuthStore` and attaches `Authorization` for `/api/...` URLs. Closes the auth fiction at the seam.
3. **F-PERF-5 / F-SEC-4** — Drop `[:200]` slice in `_compute_vision_prompt_hash`. Invalidates cache correctly; closes prompt-injection persistence.
4. **F-DO-1** — Add no-op job that always reports the 7 required check names. Unblocks docs PRs.
5. **F-API-5 / F-SEC-6 / F-DO-6** — Split `/api/health` into anonymous `/healthz` (200/503 only) + auth'd `/api/health/detailed`. Stops info disclosure and aligns probes.

### Top 5 strategic items (sprint-scale)

1. **Multi-tenant boundary as code** — Replace `verify_api_key` shared secret with per-org JWT signed by Entra. Resolve F-CL-1 cross-tenant blast radius.
2. **Move stores to Redis** — `SESSION_STORE`/`IMAGE_STORE`/`SHARE_STORE`/`EXPORT_CAPABILITY_STORE` migrate to Redis with byte-budget enforcement.
3. **Front Door + WAF + private endpoints** — F-CL-7 + F-CL-4 + F-CL-13. Brings edge security and lateral-movement defense.
4. **CI gates** — Add CodeQL (F-DO-13), `pip-audit`/`npm audit`/Trivy (F-DO-5), Lighthouse + size-limit (F-QA-8), `terraform validate` smoke (F-QA-13). Forces regressions to be caught at PR.
5. **Observability + alerting** — F-DO-10 + F-CL-6 + F-CL-8. Restart count, AOAI cost, slow query alerts. Stops invisible outages.

### Sprint plan (recommended for v4.3.0)

| Sprint | Theme | P0 closures | P1 closures |
|--------|-------|-------------|-------------|
| **S2.1** (Week 1) | Auth seam + visible UX bugs | F-BUG-1, F-FE-5, F-API-1, F-BE-1, F-BE-2, F-UX-2, F-FE-3, F-DO-1 | F-FE-9, F-FE-12, F-API-7 |
| **S2.2** (Week 2) | Memory + cache + cost | F-PERF-2, F-PERF-5, F-PERF-3, F-PERF-4, F-API-2, F-API-3, F-SEC-4 | F-PERF-6, F-PERF-7, F-PERF-9, F-CL-8 |
| **S2.3** (Week 3) | Network + DR + governance | F-API-4/F-SEC-1, F-API-5, F-CL-1..7, F-DO-2..4 | F-CL-9..11, F-DO-5..10 |
| **S2.4** (Week 4) | A11y + QA gates + observability | F-UX-1, F-UX-3, F-FE-1, F-FE-2, F-QA-1..3, F-QA-7 | F-UX-4..8, F-QA-4..6, F-CL-12..13 |

### GA-gating items (block 4.3.0 release until closed)

All P0 findings (41), plus:
- F-FE-1 / F-UX-1 (LoginModal a11y) — WCAG 2.1.2 / 4.1.2 violations on primary auth flow.
- F-API-10 (OpenAPI schema drift) — gate enables stable contract.
- F-QA-1 / F-QA-2 / F-QA-3 (regression tests for the user-reported bug class).

### Items deferred / rejected

- F-CL-12 (App Insights sampling) — defer to S3; current cost acceptable.
- F-BUG-13 (Node patch pin) — defer; renovate already proposes monthly.
- F-UX-12 (icon ambiguity) — defer; cosmetic.
- F-BUG-7 (`dump_configs.py` writing tfvars to repo root) — workspace-level dev script, not in product; document warning instead of fixing.

### Verdict

**Ship S2.1 + S2.2 closures as v4.2.1 hotfix** — auth seam + memory + visible UX. Hold v4.3.0 GA until S2.3 + S2.4 close. The 41 P0s are concentrated; ~20 of them ride together as the auth/memory/cache cluster — fixed in a tight window if Scrum Master sequences them correctly.

---

## 6. GitHub Issues Filed by Scrum Master

### Issues filed (130 total · #791–#920)

All findings filed via `scripts/file_audit_issues.py`. Each issue links back to this audit doc and carries verbatim repro/fix/acceptance sections.

**Issue range:** #791 (F-BE-1) – #920 (F-BUG-14) · **Filed:** 130 / **Errors:** 0
**Labels:** `audit:2026-05-08`, `severity:P0..P2`, `agent:<master>-master`
**Filing log:** [2026-05-08-cto-multi-agent-audit.issues.json](2026-05-08-cto-multi-agent-audit.issues.json)

| Issue | Finding | Agent | Severity | Title |
|-------|---------|-------|----------|-------|
| [#791](https://github.com/idokatz86/Archmorph/issues/791) | `F-BE-1` | Backend | **P0** | `restore-session` is unauthenticated → cache-poisoning + #613 bound-check drift |
| [#792](https://github.com/idokatz86/Archmorph/issues/792) | `F-BE-2` | Backend | **P0** | Terraform state backend (`tf_backend.py`) has zero auth and a broken UNLOCK method |
| [#793](https://github.com/idokatz86/Archmorph/issues/793) | `F-BE-3` | Backend | **P0** | `routers/auth.py::get_current_user` is a route handler used as `Depends` — anon callers sile... |
| [#794](https://github.com/idokatz86/Archmorph/issues/794) | `F-BE-4` | Backend | **P0** | Jobs router fully unauthenticated → BOLA on async analysis/IaC/HLD results |
| [#795](https://github.com/idokatz86/Archmorph/issues/795) | `F-BE-5` | Backend | **P1** | `auth.get_user_from_session(token: str)` used as `Depends` — token silently read from `?toke... |
| [#796](https://github.com/idokatz86/Archmorph/issues/796) | `F-BE-6` | Backend | **P1** | `routers/drift.py` — module-level `_BASELINES` dict + no auth on any route |
| [#797](https://github.com/idokatz86/Archmorph/issues/797) | `F-BE-7` | Backend | **P1** | `share_routes.py` — DELETE share has no auth; stats endpoint leaks for anonymous shares |
| [#798](https://github.com/idokatz86/Archmorph/issues/798) | `F-BE-8` | Backend | **P1** | `IMAGE_STORE`/`SESSION_STORE` use `FileStore` on per-replica `/tmp` — multi-replica deploys ... |
| [#799](https://github.com/idokatz86/Archmorph/issues/799) | `F-BE-9` | Backend | **P1** | `network_routes._topology_cache` unbounded module dict — leak + multi-replica unsafe |
| [#800](https://github.com/idokatz86/Archmorph/issues/800) | `F-BE-10` | Backend | **P1** | `/api/admin/suggestions/*` admin routes guard with user-tier `verify_api_key` instead of `ve... |
| [#801](https://github.com/idokatz86/Archmorph/issues/801) | `F-BE-11` | Backend | **P1** | `/api/v1/api/...` double-prefix bug — `icon_router` mirrored under wrong path |
| [#802](https://github.com/idokatz86/Archmorph/issues/802) | `F-BE-12` | Backend | **P2** | `/api/import/{terraform,cloudformation,arm}` accept up to 30 MB anonymously |
| [#803](https://github.com/idokatz86/Archmorph/issues/803) | `F-FE-1` | FE | **P0** | `LoginModal` not an accessible dialog — no `role`, no `aria-modal`, no Esc, no focus trap |
| [#804](https://github.com/idokatz86/Archmorph/issues/804) | `F-FE-2` | FE | **P1** | `ProfilePage` modal repeats every `LoginModal` a11y gap (plus broken backdrop close) |
| [#805](https://github.com/idokatz86/Archmorph/issues/805) | `F-FE-3` | FE | **P1** | Sign In trigger box mis-aligns with sibling Nav controls on mobile |
| [#806](https://github.com/idokatz86/Archmorph/issues/806) | `F-FE-4` | FE | **P0** | `toRenderableString` not applied at multiple list-of-objects render sites — #636 leak still ... |
| [#807](https://github.com/idokatz86/Archmorph/issues/807) | `F-FE-5` | FE | **P0** | `apiClient` default methods strip the auth token — every workflow request goes anonymous |
| [#808](https://github.com/idokatz86/Archmorph/issues/808) | `F-FE-6` | FE | **P0** | `ProfilePage` and parts of `useAuthStore` only honor `localStorage` — SWA cookie users authe... |
| [#809](https://github.com/idokatz86/Archmorph/issues/809) | `F-FE-7` | FE | **P2** | Tailwind `dark:` variants on auth/deploy panels decoupled from app's `data-theme` toggle |
| [#810](https://github.com/idokatz86/Archmorph/issues/810) | `F-FE-8` | FE | **P2** | `ErrorBoundary` doesn't reset on tab change — one bad tab kills navigation |
| [#811](https://github.com/idokatz86/Archmorph/issues/811) | `F-FE-9` | FE | **P1** | `DeployPanel` bypasses `apiClient` entirely — no auth, no retry, no timeout, no error mapping |
| [#812](https://github.com/idokatz86/Archmorph/issues/812) | `F-FE-10` | FE | **P2** | `loginWithProvider` drops query/hash on round-trip — users land on different tab |
| [#813](https://github.com/idokatz86/Archmorph/issues/813) | `F-FE-11` | FE | **P2** | Sign In trigger lacks accessible name on mobile + missing `aria-haspopup="dialog"` |
| [#814](https://github.com/idokatz86/Archmorph/issues/814) | `F-FE-12` | FE | **P1** | Vision-cache TTL collision with #636 — pre-coercion entries persist in `sessionStorage` |
| [#815](https://github.com/idokatz86/Archmorph/issues/815) | `F-UX-1` | UX | **P0** | LoginModal lacks dialog semantics, focus trap, Esc, scroll-lock |
| [#816](https://github.com/idokatz86/Archmorph/issues/816) | `F-UX-2` | UX | **P0** | Sign In modal overflows on short viewports — content cut off, not scrollable (root cause of ... |
| [#817](https://github.com/idokatz86/Archmorph/issues/817) | `F-UX-3` | UX | **P0** | Provider button `dark:` classes never fire — app uses `data-theme`, not Tailwind class/media... |
| [#818](https://github.com/idokatz86/Archmorph/issues/818) | `F-UX-4` | UX | **P1** | Sign In trigger collapses to ~28×28 tap target on mobile and loses accessible name |
| [#819](https://github.com/idokatz86/Archmorph/issues/819) | `F-UX-5` | UX | **P1** | Auth flow doesn't restore focus after modal close → keyboard users lose place |
| [#820](https://github.com/idokatz86/Archmorph/issues/820) | `F-UX-6` | UX | **P1** | Empty/loading/error states inconsistent across DiagramTranslator panels |
| [#821](https://github.com/idokatz86/Archmorph/issues/821) | `F-UX-7` | UX | **P1** | Error microcopy leaks raw exception strings; no toast/snackbar contract |
| [#822](https://github.com/idokatz86/Archmorph/issues/822) | `F-UX-8` | UX | **P1** | ExportHub error state is icon-only with no reason and no per-row retry |
| [#823](https://github.com/idokatz86/Archmorph/issues/823) | `F-UX-9` | UX | **P2** | UserMenu dropdown lacks proper menu semantics, Esc, roving focus |
| [#824](https://github.com/idokatz86/Archmorph/issues/824) | `F-UX-10` | UX | **P2** | ProfilePage form labels not programmatically linked to controls |
| [#825](https://github.com/idokatz86/Archmorph/issues/825) | `F-UX-11` | UX | **P2** | HLDPanel uses hardcoded Tailwind palette instead of theme tokens — breaks dark/light parity |
| [#826](https://github.com/idokatz86/Archmorph/issues/826) | `F-UX-12` | UX | **P2** | GuidedQuestions Expert/Guided toggle uses same icon family with inverted meaning |
| [#827](https://github.com/idokatz86/Archmorph/issues/827) | `F-UX-13` | UX | **P2** | DeployPanel "Coming Soon" overlay has empty `pointer-events-auto` card with no focus order |
| [#828](https://github.com/idokatz86/Archmorph/issues/828) | `F-PERF-1` | Perf | **P0** | IaC self-reflection verification step doubles GPT-4o latency on `/generate` |
| [#829](https://github.com/idokatz86/Archmorph/issues/829) | `F-PERF-2` | Perf | **P0** | IMAGE_STORE byte-budget is dead code; eviction count-only and base64 inflates payload 33% |
| [#830](https://github.com/idokatz86/Archmorph/issues/830) | `F-PERF-3` | Perf | **P0** | Sync enrichment block runs on event loop inside async `/analyze` |
| [#831](https://github.com/idokatz86/Archmorph/issues/831) | `F-PERF-4` | Perf | **P0** | AgentRunner uses sync `SessionLocal()` inside async coroutine; tools execute serially |
| [#832](https://github.com/idokatz86/Archmorph/issues/832) | `F-PERF-5` | Perf | **P1** | Vision prompt-hash truncates to 200 chars — SYSTEM_PROMPT changes never invalidate cache |
| [#833](https://github.com/idokatz86/Archmorph/issues/833) | `F-PERF-6` | Perf | **P1** | Vision images base64 round-tripped 3× per analyze |
| [#834](https://github.com/idokatz86/Archmorph/issues/834) | `F-PERF-7` | Perf | **P1** | Sync embedding call inside DB write path holds connections for 200–800ms |
| [#835](https://github.com/idokatz86/Archmorph/issues/835) | `F-PERF-8` | Perf | **P1** | pgvector context retrieval issues two sequential ORDER-BY queries |
| [#836](https://github.com/idokatz86/Archmorph/issues/836) | `F-PERF-9` | Perf | **P1** | ExportHub generates all selected deliverables serially in `for...await` loop |
| [#837](https://github.com/idokatz86/Archmorph/issues/837) | `F-PERF-10` | Perf | **P1** | LandingZoneViewer parses + sanitizes 300KB SVG twice on main thread |
| [#838](https://github.com/idokatz86/Archmorph/issues/838) | `F-PERF-11` | Perf | **P2** | IaC chat history sends full code on every turn — quadratic token growth |
| [#839](https://github.com/idokatz86/Archmorph/issues/839) | `F-PERF-12` | Perf | **P2** | Vision response cache sized at 100 entries — thrashes on burst |
| [#840](https://github.com/idokatz86/Archmorph/issues/840) | `F-API-1` | API | **P0** | `apiClient.js` ignores `Authorization` for all non-`/auth` calls — server treats every authe... |
| [#841](https://github.com/idokatz86/Archmorph/issues/841) | `F-API-2` | API | **P0** | Token caps inconsistent across HLD generation paths — same logical request returns different... |
| [#842](https://github.com/idokatz86/Archmorph/issues/842) | `F-API-3` | API | **P0** | `/api/diagrams/{id}/iac/chat` exposes `current_code` from request body — no server-side anch... |
| [#843](https://github.com/idokatz86/Archmorph/issues/843) | `F-API-4` | API | **P0** | SSE token endpoints stream secrets bypassing tenant isolation when `?tenant_id=` is supplied... |
| [#844](https://github.com/idokatz86/Archmorph/issues/844) | `F-API-5` | API | **P1** | Health endpoints leak internal version, dependency status, and config feature flags |
| [#845](https://github.com/idokatz86/Archmorph/issues/845) | `F-API-6` | API | **P1** | `/api/v1/deployments/preflight` accepts arbitrary inputs — no `Pydantic` validation |
| [#846](https://github.com/idokatz86/Archmorph/issues/846) | `F-API-7` | API | **P1** | Migration-chat streams Azure OpenAI responses with no abort propagation — orphaned upstream ... |
| [#847](https://github.com/idokatz86/Archmorph/issues/847) | `F-API-8` | API | **P1** | CORS allowlist mixes `*` and origin-specific values — credentials sent to wildcard subset |
| [#848](https://github.com/idokatz86/Archmorph/issues/848) | `F-API-9` | API | **P1** | `/api/diagrams/{id}/migration-chat` ignores `Authorization` for ownership; uses `diagram_id`... |
| [#849](https://github.com/idokatz86/Archmorph/issues/849) | `F-API-10` | API | **P1** | OpenAPI schema drift — frontend types and backend responses diverge for `/diagrams/{id}/anal... |
| [#850](https://github.com/idokatz86/Archmorph/issues/850) | `F-API-11` | API | **P2** | `/api/governance/runs` accepts arbitrary nested JSON for rules; uses jsonschema only at writ... |
| [#851](https://github.com/idokatz86/Archmorph/issues/851) | `F-API-12` | API | **P2** | Inconsistent rate-limit responses — some routes return 429 with `Retry-After`, others 503 |
| [#852](https://github.com/idokatz86/Archmorph/issues/852) | `F-API-13` | API | **P2** | Activity stream WebSocket drops silently after 60s idle — no heartbeat |
| [#853](https://github.com/idokatz86/Archmorph/issues/853) | `F-QA-1` | QA | **P0** | No automated regression test for the user-reported "Sign In box not aligned with screen" |
| [#854](https://github.com/idokatz86/Archmorph/issues/854) | `F-QA-2` | QA | **P0** | `apiClient` test suite has no coverage of auth header propagation; F-FE-5 invisible to CI |
| [#855](https://github.com/idokatz86/Archmorph/issues/855) | `F-QA-3` | QA | **P0** | Vision-cache hash regression (F-PERF-5) has no test |
| [#856](https://github.com/idokatz86/Archmorph/issues/856) | `F-QA-4` | QA | **P1** | E2E pipeline doesn't cover full upload→analyze→IaC→export-all path |
| [#857](https://github.com/idokatz86/Archmorph/issues/857) | `F-QA-5` | QA | **P1** | Backend test fixtures don't exercise multi-tenant boundaries |
| [#858](https://github.com/idokatz86/Archmorph/issues/858) | `F-QA-6` | QA | **P1** | Token-streaming (SSE) tests don't simulate client disconnect |
| [#859](https://github.com/idokatz86/Archmorph/issues/859) | `F-QA-7` | QA | **P1** | Vitest config doesn't fail on console errors — React #31 invisible to CI |
| [#860](https://github.com/idokatz86/Archmorph/issues/860) | `F-QA-8` | QA | **P1** | Performance budget not enforced in CI — F-PERF-1 / F-PERF-9 ship undetected |
| [#861](https://github.com/idokatz86/Archmorph/issues/861) | `F-QA-9` | QA | **P2** | A11y test coverage stops at axe-core static scan — focus order not asserted |
| [#862](https://github.com/idokatz86/Archmorph/issues/862) | `F-QA-10` | QA | **P2** | Mutation testing not enforced — coverage is misleading |
| [#863](https://github.com/idokatz86/Archmorph/issues/863) | `F-QA-11` | QA | **P2** | Flaky tests masked by retries — `pytest --reruns 3` hides race conditions |
| [#864](https://github.com/idokatz86/Archmorph/issues/864) | `F-QA-12` | QA | **P2** | Frontend "all errors silently swallow" pattern — `try { } catch { console.error }` everywhere |
| [#865](https://github.com/idokatz86/Archmorph/issues/865) | `F-QA-13` | QA | **P2** | CI doesn't smoke-test deploy plan — Terraform/Bicep generation regressions undetected |
| [#866](https://github.com/idokatz86/Archmorph/issues/866) | `F-SEC-1` | CISO | **P0** | Cross-tenant data exposure on observability SSE — `tenant_id` taken from query param |
| [#867](https://github.com/idokatz86/Archmorph/issues/867) | `F-SEC-2` | CISO | **P0** | `apiClient.js` strips token on every workflow request — auth bypassed by design (F-FE-5) |
| [#868](https://github.com/idokatz86/Archmorph/issues/868) | `F-SEC-3` | CISO | **P0** | IaC chat tampering via client-supplied `current_code` (F-API-3) |
| [#869](https://github.com/idokatz86/Archmorph/issues/869) | `F-SEC-4` | CISO | **P0** | Vision input + raw error string concatenation enables prompt-injection persistence (F-PERF-5... |
| [#870](https://github.com/idokatz86/Archmorph/issues/870) | `F-SEC-5` | CISO | **P0** | CORS may allow `*` with `credentials=true` (F-API-8) |
| [#871](https://github.com/idokatz86/Archmorph/issues/871) | `F-SEC-6` | CISO | **P1** | Public health endpoint discloses model + region + flags (F-API-5) |
| [#872](https://github.com/idokatz86/Archmorph/issues/872) | `F-SEC-7` | CISO | **P1** | Container Apps secrets stored in env vars without Key Vault references for prod |
| [#873](https://github.com/idokatz86/Archmorph/issues/873) | `F-SEC-8` | CISO | **P1** | Rate-limit middleware uses in-memory token bucket per replica — bypassable via load balancing |
| [#874](https://github.com/idokatz86/Archmorph/issues/874) | `F-SEC-9` | CISO | **P1** | SSRF surface: `/api/diagrams/upload-url` accepts arbitrary URLs for fetching remote diagrams |
| [#875](https://github.com/idokatz86/Archmorph/issues/875) | `F-SEC-10` | CISO | **P1** | Logs may include OAuth tokens — no scrubber on token-streaming exception paths |
| [#876](https://github.com/idokatz86/Archmorph/issues/876) | `F-SEC-11` | CISO | **P2** | CSP missing on FastAPI responses — only frontend index.html sets it |
| [#877](https://github.com/idokatz86/Archmorph/issues/877) | `F-SEC-12` | CISO | **P2** | CSRF protection absent for cookie-auth (SWA) routes |
| [#878](https://github.com/idokatz86/Archmorph/issues/878) | `F-SEC-13` | CISO | **P2** | Audit log entries missing actor + IP for guest-mode actions |
| [#879](https://github.com/idokatz86/Archmorph/issues/879) | `F-DO-1` | DevOps | **P0** | Branch protection paths-ignore deadlock — ignored-only PRs can never merge |
| [#880](https://github.com/idokatz86/Archmorph/issues/880) | `F-DO-2` | DevOps | **P0** | Deploy workflow doesn't gate on infra `terraform plan` review for prod |
| [#881](https://github.com/idokatz86/Archmorph/issues/881) | `F-DO-3` | DevOps | **P0** | Container image not pinned by digest in deploy step |
| [#882](https://github.com/idokatz86/Archmorph/issues/882) | `F-DO-4` | DevOps | **P0** | Backend Dockerfile runs as root — no `USER` directive |
| [#883](https://github.com/idokatz86/Archmorph/issues/883) | `F-DO-5` | DevOps | **P1** | CI doesn't run `pip-audit` / `npm audit` / Trivy on every PR |
| [#884](https://github.com/idokatz86/Archmorph/issues/884) | `F-DO-6` | DevOps | **P1** | Health probe uses GET `/api/health` which exposes leaked info (F-API-5) |
| [#885](https://github.com/idokatz86/Archmorph/issues/885) | `F-DO-7` | DevOps | **P1** | No `pre-commit` hooks for secret scanning |
| [#886](https://github.com/idokatz86/Archmorph/issues/886) | `F-DO-8` | DevOps | **P1** | Test database uses real Postgres but no clean-state fixture — flaky parallel runs |
| [#887](https://github.com/idokatz86/Archmorph/issues/887) | `F-DO-9` | DevOps | **P1** | Frontend build doesn't fail on TypeScript / typecheck errors |
| [#888](https://github.com/idokatz86/Archmorph/issues/888) | `F-DO-10` | DevOps | **P1** | No alerts on Container Apps replica restart count |
| [#889](https://github.com/idokatz86/Archmorph/issues/889) | `F-DO-11` | DevOps | **P2** | Rollback path undocumented — no `azd down`/`tf destroy` runbook |
| [#890](https://github.com/idokatz86/Archmorph/issues/890) | `F-DO-12` | DevOps | **P2** | Alembic migration testing not part of CI smoke |
| [#891](https://github.com/idokatz86/Archmorph/issues/891) | `F-DO-13` | DevOps | **P2** | CodeQL workflow disabled or absent |
| [#892](https://github.com/idokatz86/Archmorph/issues/892) | `F-DO-14` | DevOps | **P2** | Frontend env-var secrets risk — `VITE_` prefix may leak service-side keys |
| [#893](https://github.com/idokatz86/Archmorph/issues/893) | `F-CL-1` | Cloud | **P0** | Single Azure region — no DR plan for Azure OpenAI / Postgres / Container Apps outage |
| [#894](https://github.com/idokatz86/Archmorph/issues/894) | `F-CL-2` | Cloud | **P0** | Postgres Flexible Server uses local SSD with no point-in-time recovery beyond 7 days |
| [#895](https://github.com/idokatz86/Archmorph/issues/895) | `F-CL-3` | Cloud | **P0** | ACR set to `Basic` SKU — no geo-replication and image scanning unavailable |
| [#896](https://github.com/idokatz86/Archmorph/issues/896) | `F-CL-4` | Cloud | **P0** | Postgres + Redis publicly reachable — `public_network_access_enabled=true` |
| [#897](https://github.com/idokatz86/Archmorph/issues/897) | `F-CL-5` | Cloud | **P0** | No Azure Policy assignments for tagging / region restriction / SKU governance |
| [#898](https://github.com/idokatz86/Archmorph/issues/898) | `F-CL-6` | Cloud | **P0** | Diagnostic settings missing on Postgres / Redis / Container Apps |
| [#899](https://github.com/idokatz86/Archmorph/issues/899) | `F-CL-7` | Cloud | **P0** | Front Door / API Management not in front of Container Apps |
| [#900](https://github.com/idokatz86/Archmorph/issues/900) | `F-CL-8` | Cloud | **P1** | Cost alerts not configured on AOAI deployment |
| [#901](https://github.com/idokatz86/Archmorph/issues/901) | `F-CL-9` | Cloud | **P1** | Managed Identity not used for AOAI access — API key in env var |
| [#902](https://github.com/idokatz86/Archmorph/issues/902) | `F-CL-10` | Cloud | **P1** | Container Apps autoscale rules use only HTTP concurrency, not custom metrics |
| [#903](https://github.com/idokatz86/Archmorph/issues/903) | `F-CL-11` | Cloud | **P1** | Storage Account for blobs missing customer-managed keys |
| [#904](https://github.com/idokatz86/Archmorph/issues/904) | `F-CL-12` | Cloud | **P2** | App Insights sampling at 100% — log storm cost risk |
| [#905](https://github.com/idokatz86/Archmorph/issues/905) | `F-CL-13` | Cloud | **P2** | Network security groups absent on Container Apps subnet |
| [#906](https://github.com/idokatz86/Archmorph/issues/906) | `F-CL-14` | Cloud | **P2** | No infrastructure tests — `terraform-compliance` / `checkov` not in CI |
| [#907](https://github.com/idokatz86/Archmorph/issues/907) | `F-BUG-1` | Bug | **P0** | ROOT CAUSE: Sign-in modal not aligned to viewport — `backdrop-filter` on Nav header creates ... |
| [#908](https://github.com/idokatz86/Archmorph/issues/908) | `F-BUG-2` | Bug | **P0** | `useAuthStore.initialize()` race — first paint shows logged-out shell even when SWA cookie p... |
| [#909](https://github.com/idokatz86/Archmorph/issues/909) | `F-BUG-3` | Bug | **P1** | `useEffect(() => fetch(...), [])` lacks AbortController in `MigrationDashboard` |
| [#910](https://github.com/idokatz86/Archmorph/issues/910) | `F-BUG-4` | Bug | **P1** | Race: `IaCViewer` apply-changes button can fire twice on double-click |
| [#911](https://github.com/idokatz86/Archmorph/issues/911) | `F-BUG-5` | Bug | **P1** | Backend `azure_landing_zone.py` raises on diagrams with 0 mappings — should return empty SVG |
| [#912](https://github.com/idokatz86/Archmorph/issues/912) | `F-BUG-6` | Bug | **P1** | `useToast` hook not invoked from `apiClient` 5xx mapping — error UX absent |
| [#913](https://github.com/idokatz86/Archmorph/issues/913) | `F-BUG-7` | Bug | **P1** | `dump_configs.py` writes `terraform.tfvars` containing secrets in plaintext to repo root |
| [#914](https://github.com/idokatz86/Archmorph/issues/914) | `F-BUG-8` | Bug | **P1** | `Diagram.iac_terraform` updated without version bump — concurrent edits silently overwrite |
| [#915](https://github.com/idokatz86/Archmorph/issues/915) | `F-BUG-9` | Bug | **P1** | SSE message split across event boundary corrupts JSON in agent runner stream |
| [#916](https://github.com/idokatz86/Archmorph/issues/916) | `F-BUG-10` | Bug | **P2** | `Roadmap.jsx` infinite re-render when `roadmapItems` updated by parent each render |
| [#917](https://github.com/idokatz86/Archmorph/issues/917) | `F-BUG-11` | Bug | **P2** | `analyze` endpoint returns 200 + `error` in body for vision API failure — frontend treats as... |
| [#918](https://github.com/idokatz86/Archmorph/issues/918) | `F-BUG-12` | Bug | **P2** | `vite.config.ts` uses dev-only `define: { 'process.env': ... }` — leaks server env names int... |
| [#919](https://github.com/idokatz86/Archmorph/issues/919) | `F-BUG-13` | Bug | **P2** | `Dockerfile.frontend` doesn't pin Node patch version — supply-chain drift |
| [#920](https://github.com/idokatz86/Archmorph/issues/920) | `F-BUG-14` | Bug | **P2** | `useFocusTrap` hook releases trap on `pointerdown` outside but doesn't restore on dialog clo... |

---

## 7. Run Log (resume anchor)

| Step | Agent | Status | Notes |
|------|-------|--------|-------|
| 1 | Setup + repo scan | ✅ Done | Repo memory + dir scan complete. |
| 2 | Create tracking md | ✅ Done | This file. |
| 3 | CTO Master delegation brief | ✅ Done | Section 5 framing + cross-cutting concerns. |
| 4 | Backend Master | ✅ Done | 12 findings (5 P0). |
| 5 | FE Master | ✅ Done | 12 findings (4 P0). |
| 6 | UX Master | ✅ Done | 13 findings (3 P0). |
| 7 | Performance Master | ✅ Done | 12 findings (4 P0). |
| 8 | API Master | ✅ Done | 13 findings (4 P0). |
| 9 | QA Master | ✅ Done | 13 findings (3 P0). |
| 10 | CISO Master | ✅ Done | 13 findings (5 P0). |
| 11 | Devops Master | ✅ Done | 14 findings (4 P0). |
| 12 | Cloud Master | ✅ Done | 14 findings (7 P0). |
| 13 | Bug Master | ✅ Done | 14 findings (2 P0). User-reported "Sign In box not aligned" rooted as F-BUG-1 (#907). |
| 14 | CTO consolidated verdict | ✅ Done | Section 5b — top 5 risks, top 5 quick wins, sprint plan, GA gating. |
| 15 | Scrum Master files issues | ✅ Done | 130/130 issues #791–#920, 0 errors. |
| 16 | Verify issues + close audit | ✅ Done | Section 6 issue table populated; filing log persisted to `*.issues.json`. |

---

## 8. Resume Instructions (for compaction)

If this conversation is compacted or restarted:
1. Read this file entirely.
2. Locate the Run Log table.
3. Find the first ⏳ row and continue from there.
4. Do **not** re-run completed steps. Each agent run appends its findings to section 4.
5. After all agents are done, run the CTO consolidation, then Scrum Master files issues using the consolidated list.
6. Update the Run Log row-by-row as work progresses.
