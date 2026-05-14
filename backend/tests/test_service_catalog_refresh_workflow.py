from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "service-catalog-refresh.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _verify_freshness_step() -> dict:
    workflow = _workflow()
    steps = workflow["jobs"]["refresh"]["steps"]
    for step in steps:
        if step.get("name") == "Verify freshness via /api/health":
            return step
    raise AssertionError('Expected workflow step "Verify freshness via /api/health"')


def _trigger_refresh_step() -> dict:
    workflow = _workflow()
    steps = workflow["jobs"]["refresh"]["steps"]
    for step in steps:
        if step.get("name") == "Trigger refresh":
            return step
    raise AssertionError('Expected workflow step "Trigger refresh"')


def test_workflow_wires_api_key_secret():
    workflow = _workflow()

    assert workflow["env"]["ARCHMORPH_API_KEY"] == "${{ secrets.ARCHMORPH_API_KEY }}"


def test_trigger_refresh_uses_api_key_secret_for_api_auth():
    run_script = _trigger_refresh_step()["run"]

    assert "API_URL or ARCHMORPH_API_KEY secret missing" in run_script
    assert 'X-API-Key: ${ARCHMORPH_API_KEY}' in run_script
    assert 'X-API-Key: ${ADMIN_KEY}' not in run_script


def test_verify_freshness_does_not_receive_admin_key_secret():
    step = _verify_freshness_step()

    assert "ADMIN_KEY" not in step.get("env", {})


def test_verify_freshness_uses_api_key_for_health_auth():
    run_script = _verify_freshness_step()["run"]

    assert "ARCHMORPH_API_KEY secret missing" in run_script
    assert 'X-API-Key: ${ARCHMORPH_API_KEY}' in run_script
    assert "ADMIN_KEY" not in run_script


def test_verify_freshness_reports_health_http_status():
    run_script = _verify_freshness_step()["run"]

    assert 'HTTP_CODE=$(curl "${_CURL_ARGS[@]}" -o health.json -w "%{http_code}"' in run_script
    assert "check ARCHMORPH_API_KEY secret" in run_script
