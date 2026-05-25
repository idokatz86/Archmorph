from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "production-authenticated-browser-synthetic.yml"
SYNTHETIC_SPEC = REPO_ROOT / "e2e" / "production-authenticated-synthetic.spec.ts"


def _load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _step_by_name(steps: list[dict], name: str) -> dict:
    for step in steps:
        if step.get("name") == name:
            return step
    raise AssertionError(f'Expected workflow step "{name}"')


def test_workflow_runs_on_schedule_dispatch_and_workflow_call():
    workflow = _load()
    on_section = workflow.get("on", workflow.get(True))

    assert "workflow_call" in on_section
    assert "workflow_dispatch" in on_section
    assert on_section["schedule"] == [{"cron": "0 */4 * * *"}]


def test_workflow_executes_production_playwright_synthetic_and_collects_evidence():
    workflow = _load()
    job = workflow["jobs"]["production-browser-synthetic"]

    assert job["environment"] == "production"
    run_step = _step_by_name(job["steps"], "Run production authenticated browser synthetic")
    assert run_step["env"]["PRODUCTION_BROWSER_SYNTHETIC"] == "1"
    assert run_step["env"]["PRODUCTION_SYNTHETIC_ARTIFACT_ROOT"] == "smoke-artifacts/production-browser/${{ github.run_id }}"
    assert "npx playwright test e2e/production-authenticated-synthetic.spec.ts --project=chromium" in run_step["run"]

    upload_step = _step_by_name(job["steps"], "Upload production browser synthetic artifacts")
    assert "smoke-artifacts/production-browser/${{ github.run_id }}/" in upload_step["with"]["path"]
    assert "playwright-report/" in upload_step["with"]["path"]
    assert "test-results/" in upload_step["with"]["path"]


def test_workflow_opens_p0_issue_when_synthetic_fails():
    workflow = _load()
    job = workflow["jobs"]["production-browser-synthetic"]
    issue_step = _step_by_name(job["steps"], "Open P0 triage issue on failure")

    assert issue_step["if"] == "failure()"
    script = issue_step["with"]["script"]
    assert "[P0] Production authenticated browser synthetic failed" in script
    assert "Run URL" in script
    assert "Revision SHA" in script
    assert "Production endpoints: configured via GitHub secrets (redacted)" in script
    assert "Frontend URL" not in script
    assert "API base" not in script
    assert "labels: ['bug', 'production', 'critical', 'priority:P0']" in script


def test_synthetic_evidence_does_not_persist_live_endpoint_urls():
    spec = SYNTHETIC_SPEC.read_text(encoding="utf-8")

    assert "frontend_url: FRONTEND_URL" not in spec
    assert "api_base: API_BASE" not in spec
    assert "frontend_url_configured: Boolean(FRONTEND_URL)" in spec
    assert "api_base_configured: Boolean(API_BASE)" in spec


def test_synthetic_can_fall_back_to_trusted_backend_auth_bridge_without_leaking_secret_values():
    spec = SYNTHETIC_SPEC.read_text(encoding="utf-8")

    assert "authBridgeMode = 'swa-managed-function'" in spec
    assert "authBridgeMode = 'backend-api-key-fallback'" in spec
    assert "`${API_BASE}/auth/swa-session`" in spec
    assert "'X-API-Key': HEALTH_API_KEY" in spec
    assert "data: { client_principal: syntheticPrincipal }" in spec
    assert "auth_bridge_mode: authBridgeMode" in spec
    assert "auth_bridge_http_status: bridgeResponse.status()" in spec
    assert "HEALTH_API_KEY:" not in spec


def test_synthetic_uploads_generated_png_not_svg_favicon():
    spec = SYNTHETIC_SPEC.read_text(encoding="utf-8")

    assert "createSyntheticDiagramPng" in spec
    assert "production-synthetic-diagram.png" in spec
    assert "frontend/public/favicon.svg" not in spec
    assert "favicon.svg" not in spec


def test_synthetic_does_not_block_bearer_export_on_export_all_button_visibility():
    spec = SYNTHETIC_SPEC.read_text(encoding="utf-8")

    assert "Export All" not in spec
    assert not ("Export All" in spec and "toBeVisible" in spec)
    assert "/export-diagram?format=drawio" in spec
    assert "Authorization: `Bearer ${sessionToken}`" in spec
