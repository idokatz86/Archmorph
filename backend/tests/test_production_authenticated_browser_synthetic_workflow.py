from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "production-authenticated-browser-synthetic.yml"


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
    assert "labels: ['bug', 'production', 'critical', 'priority:P0']" in script
