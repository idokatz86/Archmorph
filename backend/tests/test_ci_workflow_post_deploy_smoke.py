from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DEPLOYMENT_SMOKE = REPO_ROOT / "scripts" / "deployment_smoke.sh"


def test_post_deploy_smoke_passes_health_api_key_from_service_api_secret():
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))

    steps = workflow["jobs"]["post-deploy-smoke"]["steps"]
    smoke_step = next(step for step in steps if step.get("name") == "Run deployed app smoke checks")

    assert smoke_step["env"]["HEALTH_API_KEY"] == "${{ secrets.ARCHMORPH_API_KEY || secrets.API_KEY }}"


def test_deployment_smoke_checks_frontend_security_headers():
    smoke_script = DEPLOYMENT_SMOKE.read_text(encoding="utf-8")

    assert "check_frontend_security_headers() {" in smoke_script
    assert 'curl -sSL -D "$headers_file" -o /tmp/archmorph-frontend-shell --max-time 30 "$FRONTEND_URL"' in smoke_script
    assert "Frontend shell is missing Content-Security-Policy" in smoke_script
    assert "frame-ancestors 'none'" in smoke_script
    assert "x-frame-options:[[:space:]]*deny" in smoke_script
    assert "object-src 'none'" in smoke_script
    assert "permissions-policy:[[:space:]]*camera=(), microphone=(), geolocation=()" in smoke_script
    assert "Frontend shell security headers OK" in smoke_script


def test_production_traffic_movement_jobs_are_environment_gated():
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))

    assert workflow["jobs"]["deploy-backend"]["environment"] == "production"
    assert workflow["jobs"]["deploy-frontend"]["environment"] == "production"
    assert workflow["jobs"]["post-deploy-smoke"]["environment"] == "production"


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


def test_backend_deploy_can_read_terraform_front_door_outputs():
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))

    deploy_job = workflow["jobs"]["deploy-backend"]
    assert deploy_job["env"]["TRUSTED_FRONT_DOOR_FDID"] == "${{ secrets.TRUSTED_FRONT_DOOR_FDID }}"
    assert deploy_job["env"]["TRUSTED_FRONT_DOOR_HOSTS"] == "${{ secrets.TRUSTED_FRONT_DOOR_HOSTS }}"
    assert deploy_job["env"]["REQUIRE_FRONT_DOOR_ORIGIN_LOCK"] == "${{ vars.REQUIRE_FRONT_DOOR_ORIGIN_LOCK || 'false' }}"
    assert deploy_job["env"]["ARM_USE_OIDC"] is True
    assert deploy_job["env"]["ARM_CLIENT_ID"] == "${{ secrets.AZURE_CLIENT_ID }}"
    assert deploy_job["env"]["ARM_TENANT_ID"] == "${{ secrets.AZURE_TENANT_ID }}"
    assert deploy_job["env"]["ARM_SUBSCRIPTION_ID"] == "${{ secrets.AZURE_SUBSCRIPTION_ID }}"
    assert any(
        step.get("name") == "Set up Terraform"
        and step.get("uses") == "hashicorp/setup-terraform@v4"
        and step.get("with", {}).get("terraform_wrapper") is False
        for step in deploy_job["steps"]
    )


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


def test_backend_storage_validation_classifies_pending_terraform_migration():
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))

    validate_step = next(
        step
        for step in workflow["jobs"]["deploy-backend"]["steps"]
        if step.get("name") == "Validate Terraform-managed metrics storage"
    )
    validate_script = validate_step["run"]

    assert 'if [ "$STORAGE_NAME" = "archmorphmetrics" ]; then' in validate_script
    assert "Terraform storage migration pending" in validate_script
    assert "Run the Terraform Production workflow" in validate_script
    assert "grant AZURE_CLIENT_ID Blob data-plane access on the tfstate storage account/container" in validate_script


def test_backend_storage_validation_accepts_system_identity_until_user_identity_migration():
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))

    validate_step = next(
        step
        for step in workflow["jobs"]["deploy-backend"]["steps"]
        if step.get("name") == "Validate Terraform-managed metrics storage"
    )
    validate_script = validate_step["run"]

    assert "CONTAINER_APP_JSON=$(az containerapp show" in validate_script
    assert "Using Container App user-assigned managed identity for storage validation" in validate_script
    assert "Container App AZURE_CLIENT_ID is not set; using the system-assigned managed identity" in validate_script
    assert "Container App is missing AZURE_CLIENT_ID and has no system-assigned identity principal" in validate_script
    assert 'jq -r \'.identity.principalId // ""\'' in validate_script
    assert "Container App identity is missing Storage Blob Data Contributor" in validate_script


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
    assert 'REQUIRE_FRONT_DOOR_ORIGIN_LOCK=$(echo "${REQUIRE_FRONT_DOOR_ORIGIN_LOCK:-false}" | tr' in smoke_script
    assert 'if [ "$REQUIRE_FRONT_DOOR_ORIGIN_LOCK" = "true" ]; then' in smoke_script
    assert 'TRUSTED_ORIGIN_CURL_ARGS=(-H "X-Azure-FDID: $TRUSTED_FRONT_DOOR_FDID" -H "Host: $TRUSTED_FRONT_DOOR_HOST")' in smoke_script
    assert 'echo "::warning::Front Door origin-lock settings are missing; direct-origin rejection check will be skipped"' in smoke_script
    assert 'if [ -n "$GREEN_FQDN" ] && [ ${#TRUSTED_ORIGIN_CURL_ARGS[@]} -gt 0 ]; then' in smoke_script
    assert 'DIRECT_ORIGIN_CODE=$(curl -sS -o direct-origin-response.json -w "%{http_code}"' in smoke_script
    assert 'echo "::error::Direct green revision origin-lock check returned HTTP ${DIRECT_ORIGIN_CODE}"' in smoke_script
    assert 'echo "Direct green revision access correctly blocked (${DIRECT_ORIGIN_CODE})"' in smoke_script
    assert 'echo "::warning::Skipping direct green revision origin-lock rejection check because no trusted Front Door contract is configured"' in smoke_script
    assert 'HEALTH_BODY=$(curl_health "$TEST_URL$HEALTH_PATH" || true)' in smoke_script
    assert 'HEALTH_BODY="$HEALTH_BODY" HEALTH_RETRIES=1 HEALTH_RETRY_SECONDS=0 ./scripts/health_gate.sh' in smoke_script


def test_backend_green_revision_deploy_wires_front_door_origin_lock_contract():
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))

    deploy_step = next(
        step
        for step in workflow["jobs"]["deploy-backend"]["steps"]
        if step.get("name") == "Deploy green revision"
    )
    deploy_script = deploy_step["run"]

    assert 'TRUSTED_FRONT_DOOR_FDID="${TRUSTED_FRONT_DOOR_FDID:-}"' in deploy_script
    assert 'TRUSTED_FRONT_DOOR_HOSTS="${TRUSTED_FRONT_DOOR_HOSTS:-}"' in deploy_script
    assert 'REQUIRE_FRONT_DOOR_ORIGIN_LOCK=$(echo "${REQUIRE_FRONT_DOOR_ORIGIN_LOCK:-false}" | tr' in deploy_script
    assert 'terraform -chdir=infra init -input=false' in deploy_script
    assert 'TERRAFORM_FRONT_DOOR_FDID=$(terraform -chdir=infra output -raw front_door_profile_resource_guid' in deploy_script
    assert 'TERRAFORM_FRONT_DOOR_HOSTS=$(terraform -chdir=infra output -raw front_door_api_hostname' in deploy_script
    assert 'TRUSTED_FRONT_DOOR_FDID=$(terraform -chdir=infra output' not in deploy_script
    assert 'TRUSTED_FRONT_DOOR_HOSTS=$(terraform -chdir=infra output' not in deploy_script
    assert 'if [ -n "$TERRAFORM_FRONT_DOOR_FDID" ]; then' in deploy_script
    assert 'if [ -n "$TERRAFORM_FRONT_DOOR_HOSTS" ]; then' in deploy_script
    assert 'EXISTING_ENV_JSON=$(az containerapp show' in deploy_script
    assert 'select(.name == "TRUSTED_FRONT_DOOR_FDID")' in deploy_script
    assert 'select(.name == "TRUSTED_FRONT_DOOR_HOSTS")' in deploy_script
    assert 'EXISTING_FRONT_DOOR_FDID=$(echo "$EXISTING_ENV_JSON"' in deploy_script
    assert 'EXISTING_FRONT_DOOR_HOSTS=$(echo "$EXISTING_ENV_JSON"' in deploy_script
    assert 'if [ -z "$TRUSTED_FRONT_DOOR_FDID" ] && [ -n "$EXISTING_FRONT_DOOR_FDID" ]; then' in deploy_script
    assert 'if [ -z "$TRUSTED_FRONT_DOOR_HOSTS" ] && [ -n "$EXISTING_FRONT_DOOR_HOSTS" ]; then' in deploy_script
    assert 'CONTAINER_APP_FQDN=$(az containerapp show' in deploy_script
    assert 'az extension show --name front-door' in deploy_script
    assert 'az extension add --name front-door --upgrade --only-show-errors' in deploy_script
    assert 'AFD_PROFILES_JSON=$(az afd profile list' in deploy_script
    assert 'AFD_PROFILES_JSON=$(az resource list' in deploy_script
    assert 'az afd origin-group list' in deploy_script
    assert 'az afd origin list' in deploy_script
    assert '.originHostHeader // .properties.originHostHeader' in deploy_script
    assert 'az afd endpoint list' in deploy_script
    assert 'show_afd_resource()' in deploy_script
    assert 'az resource show --ids "$resource_id" --api-version 2024-02-01' in deploy_script
    assert 'front_door_profile_targets_container "$candidate_profile_name" "$candidate_profile_group" "$CONTAINER_APP_FQDN"' in deploy_script
    assert 'front_door_profile_fdid "$candidate_profile_json" "$candidate_profile_id" "$candidate_profile_name" "$candidate_profile_group"' in deploy_script
    assert 'front_door_endpoint_host "$candidate_profile_name" "$candidate_profile_group" "$prefer_api_endpoint"' in deploy_script
    assert 'AFD_CONTRACT=$(resolve_front_door_contract_from_afd_cli true || true)' in deploy_script
    assert 'AFD_CONTRACT=$(resolve_front_door_contract_from_afd_cli false || true)' in deploy_script
    assert 'FRONT_DOOR_PROFILES_JSON=$(az resource list' in deploy_script
    assert deploy_script.index('AFD_PROFILES_JSON=$(az afd profile list') < deploy_script.index('FRONT_DOOR_PROFILES_JSON=$(az resource list')
    assert '--resource-type Microsoft.Cdn/profiles' in deploy_script
    assert '--resource-type Microsoft.Cdn/profiles/afdEndpoints' in deploy_script
    assert '--resource-type Microsoft.Cdn/profiles/originGroups/origins' in deploy_script
    assert '--resource-group ${{ env.AZURE_RESOURCE_GROUP }}' not in deploy_script.split('FRONT_DOOR_PROFILES_JSON=$(az resource list', 1)[1].split('FRONT_DOOR_ENDPOINTS_JSON=', 1)[0]
    assert '--resource-group ${{ env.AZURE_RESOURCE_GROUP }}' not in deploy_script.split('FRONT_DOOR_ENDPOINTS_JSON=$(az resource list', 1)[1].split('FRONT_DOOR_ORIGINS_JSON=', 1)[0]
    assert 'origin_matches_container=$(echo "$FRONT_DOOR_ORIGINS_JSON" | jq' in deploy_script
    assert '(.properties.hostName // "") == $container_host' in deploy_script
    assert 'candidate_host=$(echo "$FRONT_DOOR_ENDPOINTS_JSON" | jq' in deploy_script
    assert 'contains("api")' in deploy_script
    assert 'if [ -z "$TRUSTED_FRONT_DOOR_FDID" ] || [ -z "$TRUSTED_FRONT_DOOR_HOSTS" ]; then' in deploy_script
    assert 'Unable to resolve Front Door FDID/hostname for required origin-lock contract' in deploy_script
    assert 'deploying without origin-lock because REQUIRE_FRONT_DOOR_ORIGIN_LOCK is not true' in deploy_script
    assert deploy_script.index('contains("api")') < deploy_script.index('[.[] | select((.id // "") | startswith($profile_id + "/")) | .properties.hostName][0] // ""')
    assert 'TRUSTED_FRONT_DOOR_FDID="$candidate_fdid"' in deploy_script
    assert 'TRUSTED_FRONT_DOOR_HOSTS="$candidate_host"' in deploy_script
    assert deploy_script.count('if [ -n "$candidate_host" ] && [ -n "$candidate_fdid" ]; then') >= 3
    assert 'TRUSTED_FRONT_DOOR_FDID="$TRUSTED_FRONT_DOOR_FDID"' in deploy_script
    assert 'TRUSTED_FRONT_DOOR_HOSTS="$TRUSTED_FRONT_DOOR_HOSTS"' in deploy_script
