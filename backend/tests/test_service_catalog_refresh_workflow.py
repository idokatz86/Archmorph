from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "service-catalog-refresh.yml"


def _verify_freshness_step() -> dict:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["refresh"]["steps"]
    for step in steps:
        if step.get("name") == "Verify freshness via /api/health":
            return step
    raise AssertionError('Expected workflow step "Verify freshness via /api/health"')


def test_verify_freshness_receives_admin_key_secret():
    step = _verify_freshness_step()

    assert step["env"]["ADMIN_KEY"] == "${{ secrets.ADMIN_KEY }}"


def test_verify_freshness_falls_back_to_admin_key_for_health_auth():
    run_script = _verify_freshness_step()["run"]

    assert 'HEALTH_API_KEY="${ARCHMORPH_API_KEY:-${ADMIN_KEY:-}}"' in run_script
    assert 'X-API-Key: ${HEALTH_API_KEY}' in run_script


def test_verify_freshness_reports_health_http_status():
    run_script = _verify_freshness_step()["run"]

    assert 'HTTP_CODE=$(curl "${_CURL_ARGS[@]}" -o health.json -w "%{http_code}"' in run_script
    assert "check ARCHMORPH_API_KEY/ADMIN_KEY secrets" in run_script
