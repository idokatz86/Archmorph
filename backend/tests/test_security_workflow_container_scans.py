from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
SECURITY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "security.yml"


def _load() -> dict:
    return yaml.safe_load(SECURITY_WORKFLOW.read_text(encoding="utf-8"))


def _step_by_name(steps: list[dict], name: str) -> dict:
    for step in steps:
        if step.get("name") == name:
            return step
    raise AssertionError(f'Expected workflow step "{name}"')


def test_security_workflow_scans_all_production_runtime_images():
    workflow = _load()
    trivy_job = workflow["jobs"]["trivy-container"]

    image_matrix = trivy_job["strategy"]["matrix"]["image"]
    names = {item["name"] for item in image_matrix}

    assert names == {"backend", "mcp-gateway"}
    assert _step_by_name(trivy_job["steps"], "Build ${{ matrix.image.name }} image for scanning")
    assert _step_by_name(trivy_job["steps"], "Container healthcheck smoke (${{ matrix.image.name }})")


def test_security_workflow_uses_distinct_sarif_category_per_runtime_image():
    workflow = _load()
    upload_step = _step_by_name(workflow["jobs"]["trivy-container"]["steps"], "Upload Trivy SARIF to GitHub Security")
    assert upload_step["with"]["category"] == "trivy-container-${{ matrix.image.name }}"


def test_security_workflow_keeps_required_trivy_status_context():
    workflow = _load()
    required_job = workflow["jobs"]["trivy-container-required"]

    assert required_job["name"] == "Container Scan — Trivy"
    assert required_job["needs"] == "trivy-container"
