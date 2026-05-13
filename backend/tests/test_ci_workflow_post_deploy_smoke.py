from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_post_deploy_smoke_passes_health_api_key_from_service_api_secret():
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))

    steps = workflow["jobs"]["post-deploy-smoke"]["steps"]
    smoke_step = next(step for step in steps if step.get("name") == "Run deployed app smoke checks")

    assert smoke_step["env"]["HEALTH_API_KEY"] == "${{ secrets.ARCHMORPH_API_KEY || secrets.API_KEY }}"


def test_backend_deploy_wires_jwt_secret_to_container_app_revision():
    workflow_text = CI_WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)

    deploy_job = workflow["jobs"]["deploy-backend"]
    assert deploy_job["env"]["JWT_SECRET"] == "${{ secrets.JWT_SECRET }}"
    assert "secrets.JWT_SECRET || secrets.ADMIN_KEY" not in workflow_text

    deploy_step = next(step for step in deploy_job["steps"] if step.get("name") == "Deploy green revision")
    deploy_script = deploy_step["run"]

    assert 'jwt-secret="${{ env.JWT_SECRET }}"' in deploy_script
    assert "JWT_SECRET=secretref:jwt-secret" in deploy_script
    assert "2>/dev/null || true" not in deploy_script


def test_backend_deploy_uses_distinct_api_key_secret_reference():
    workflow_text = CI_WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)

    deploy_job = workflow["jobs"]["deploy-backend"]
    assert deploy_job["env"]["ARCHMORPH_API_KEY"] == "${{ secrets.ARCHMORPH_API_KEY || secrets.API_KEY }}"

    deploy_step = next(step for step in deploy_job["steps"] if step.get("name") == "Deploy green revision")
    deploy_script = deploy_step["run"]

    assert 'api-key="${{ env.ARCHMORPH_API_KEY }}"' in deploy_script
    assert "ARCHMORPH_API_KEY=secretref:api-key" in deploy_script
    assert "ARCHMORPH_API_KEY=secretref:admin-key" not in workflow_text


def test_backend_deploy_keeps_acs_connection_string_in_container_app_secret():
    workflow_text = CI_WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)

    deploy_job = workflow["jobs"]["deploy-backend"]
    deploy_step = next(step for step in deploy_job["steps"] if step.get("name") == "Deploy green revision")
    deploy_script = deploy_step["run"]

    assert 'acs-connection-string="${{ secrets.ACS_CONNECTION_STRING }}"' in deploy_script
    assert "ACS_CONNECTION_STRING=secretref:acs-connection-string" in deploy_script
    assert 'ACS_CONNECTION_STRING="${{ secrets.ACS_CONNECTION_STRING }}"' not in workflow_text


def test_backend_deploy_limits_workers_for_fast_container_app_activation():
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))

    deploy_step = next(
        step
        for step in workflow["jobs"]["deploy-backend"]["steps"]
        if step.get("name") == "Deploy green revision"
    )
    deploy_script = deploy_step["run"]

    assert 'WEB_CONCURRENCY="1"' in deploy_script


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


def test_backend_green_revision_healthz_is_retried_before_failure():
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))

    smoke_step = next(
        step
        for step in workflow["jobs"]["deploy-backend"]["steps"]
        if step.get("name") == "Smoke test green revision"
    )
    smoke_script = smoke_step["run"]

    assert "HEALTHZ_MAX_ATTEMPTS=12" in smoke_script
    assert 'HEALTHZ_URL="${TEST_URL%/api}/healthz"' in smoke_script
    assert 'echo "Checking green revision liveness: $HEALTHZ_URL"' in smoke_script
    assert 'for attempt in $(seq 1 "$HEALTHZ_MAX_ATTEMPTS"); do' in smoke_script
    assert ": > healthz-response.json" in smoke_script
    assert '--max-time 20 "$HEALTHZ_URL"' in smoke_script
    assert 'Green revision /healthz attempt ${attempt} returned HTTP ${HEALTHZ_CODE}' in smoke_script
    assert 'if [ "$attempt" -lt "$HEALTHZ_MAX_ATTEMPTS" ]; then' in smoke_script
    assert "sleep 15" in smoke_script
    assert 'dump_green_revision_diagnostics "healthz-${HEALTHZ_CODE}"' in smoke_script


def test_backend_green_revision_smoke_checks_origin_lock_and_reuses_front_door_contract():
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))

    smoke_step = next(
        step
        for step in workflow["jobs"]["deploy-backend"]["steps"]
        if step.get("name") == "Smoke test green revision"
    )
    smoke_script = smoke_step["run"]

    assert "TRUSTED_FRONT_DOOR_FDID=$(az containerapp show" in smoke_script
    assert "TRUSTED_FRONT_DOOR_HOST=$(az containerapp show" in smoke_script
    assert 'TRUSTED_ORIGIN_CURL_ARGS=(-H "X-Azure-FDID: $TRUSTED_FRONT_DOOR_FDID" -H "Host: $TRUSTED_FRONT_DOOR_HOST")' in smoke_script
    assert 'DIRECT_ORIGIN_CODE=$(curl -sS -o direct-origin-response.json -w "%{http_code}"' in smoke_script
    assert 'echo "::error::Direct green revision origin-lock check returned HTTP ${DIRECT_ORIGIN_CODE}"' in smoke_script
    assert 'echo "Direct green revision access correctly blocked (${DIRECT_ORIGIN_CODE})"' in smoke_script
