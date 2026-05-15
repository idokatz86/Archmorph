from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "live-export-full-spine-smoke.yml"
SMOKE_SCRIPT = REPO_ROOT / "scripts" / "architecture_package_smoke.sh"


def _load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _step_by_name(steps: list[dict], name: str) -> dict:
    for step in steps:
        if step.get("name") == name:
            return step
    raise AssertionError(f'Expected workflow step "{name}"')


def test_live_export_smoke_has_pull_request_path_filters_for_live_export_surfaces():
    workflow = _load()
    trigger = workflow.get("on", workflow.get(True))
    paths = trigger["pull_request"]["paths"]

    assert "backend/**/*export*.py" in paths
    assert "backend/routers/**" in paths
    assert "backend/**/*iac*.py" in paths
    assert "backend/**/*hld*.py" in paths
    assert "backend/**/*cost*.py" in paths
    assert "backend/**/*auth*.py" in paths
    assert "backend/**/*capab*.py" in paths
    assert "backend/ci_smoke.py" in paths
    assert "backend/architecture_package.py" in paths
    assert "backend/azure_landing_zone.py" in paths
    assert "backend/services/azure_pricing.py" in paths
    assert "frontend/src/**" in paths


def test_live_export_smoke_runs_architecture_package_script_and_desktop_mobile_playwright():
    workflow = _load()
    steps = workflow["jobs"]["smoke"]["steps"]

    env_step = _step_by_name(steps, "Use fallback environment variables")
    assert "ARCHMORPH_EXPORT_CAPABILITY_REQUIRED=true" in env_step["run"]
    assert "ENVIRONMENT=test" in env_step["run"]

    package_step = _step_by_name(steps, "Run Architecture Package full-spine smoke")
    assert package_step["run"] == "./scripts/architecture_package_smoke.sh"
    assert package_step["env"]["ENVIRONMENT"] == "test"
    assert package_step["env"]["SECONDARY_FORMAT_SMOKE"] is False

    playwright_step = _step_by_name(steps, "Run Live funnel hard-assertion smoke (desktop + mobile)")
    run_script = playwright_step["run"]
    assert "e2e/core-funnel.spec.ts" in run_script
    assert '--project=chromium' in run_script
    assert '--project=mobile-chromium' in run_script


def test_architecture_package_script_rotates_capability_from_response_header():
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")

    assert "x-export-capability-next" in script
    assert "EXPORT_CAPABILITY=\"$next_capability\"" in script
