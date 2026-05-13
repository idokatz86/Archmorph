from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_post_deploy_smoke_passes_health_api_key_from_admin_secret():
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))

    steps = workflow["jobs"]["post-deploy-smoke"]["steps"]
    smoke_step = next(step for step in steps if step.get("name") == "Run deployed app smoke checks")

    assert smoke_step["env"]["HEALTH_API_KEY"] == "${{ secrets.ADMIN_KEY }}"


def test_backend_deploy_wires_jwt_secret_to_container_app_revision():
    workflow_text = CI_WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)

    deploy_job = workflow["jobs"]["deploy-backend"]
    assert deploy_job["env"]["JWT_SECRET"] == "${{ secrets.JWT_SECRET || secrets.ADMIN_KEY }}"

    deploy_step = next(step for step in deploy_job["steps"] if step.get("name") == "Deploy green revision")
    deploy_script = deploy_step["run"]

    assert 'jwt-secret="${{ env.JWT_SECRET }}"' in deploy_script
    assert "JWT_SECRET=secretref:jwt-secret" in deploy_script
    assert "2>/dev/null || true" not in deploy_script


def test_backend_readiness_accepts_azure_provisioned_state():
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))

    readiness_step = next(
        step
        for step in workflow["jobs"]["deploy-backend"]["steps"]
        if step.get("name") == "Wait for green revision readiness"
    )
    readiness_script = readiness_step["run"]

    assert '[ "$PROVISIONING_STATE" = "Provisioned" ]' in readiness_script
    assert '[ "$PROVISIONING_STATE" = "Succeeded" ]' in readiness_script
    assert '[ "$RUNNING_STATE" = "Running" ]' in readiness_script
