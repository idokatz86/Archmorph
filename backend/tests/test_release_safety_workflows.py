from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
ROLLBACK_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "rollback.yml"
MONITORING_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "monitoring.yml"
MIGRATION_BOOTSTRAP = REPO_ROOT / "infra" / "migration-bootstrap" / "main.tf"
MAIN_TERRAFORM = REPO_ROOT / "infra" / "main.tf"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _step_by_name(steps: list[dict], name: str) -> dict:
    for step in steps:
        if step.get("name") == name:
            return step
    raise AssertionError(f'Expected workflow step "{name}"')


def test_ci_includes_pgvector_alembic_migration_cycle():
    workflow = _load(CI_WORKFLOW)
    job = workflow["jobs"]["alembic-migration-smoke"]

    assert job["services"]["postgres"]["image"] == "pgvector/pgvector:pg16"
    assert job["services"]["redis"]["image"] == "redis:7.4-alpine"
    assert job["env"]["POSTGRES_USER"] == "archmorph"
    assert job["env"]["POSTGRES_DB"] == "archmorph"
    assert job["env"]["ARCHMORPH_TEST_REDIS_URL"] == "redis://127.0.0.1:6379/15"

    run_script = _step_by_name(job["steps"], "Run Alembic migration cycle")["run"]
    assert "python -m alembic heads" in run_script
    assert "python -m alembic upgrade head --sql" in run_script
    assert "python -m alembic upgrade head" in run_script
    assert "python -m alembic downgrade base" in run_script
    assert 'DATABASE_SCHEME="postgresql"' in run_script
    assert "printf -v DATABASE_URL '%s://%s:%s@127.0.0.1:5432/%s'" in run_script
    assert 'export DATABASE_URL ARCHMORPH_TEST_POSTGRES_URL="$DATABASE_URL"' in run_script

    contracts = _step_by_name(
        job["steps"],
        "Run canonical PostgreSQL, Redis, migration, and Helm contracts",
    )["run"]
    assert "tests/test_workspace_store_postgres.py" in contracts
    assert "tests/test_canonical_state_migration_postgres.py" in contracts
    assert "tests/test_bridge_overlay_postgres.py" in contracts
    assert "tests/test_helm_secret_contract.py" in contracts
    assert 'DATABASE_SCHEME="postgresql"' in contracts
    assert "printf -v DATABASE_URL '%s://%s:%s@127.0.0.1:5432/%s'" in contracts


def test_backend_deploy_runs_isolated_bootstrap_and_exact_head_migration_before_green():
    workflow = _load(CI_WORKFLOW)
    deploy = workflow["jobs"]["deploy-backend"]

    assert "alembic-migration-smoke" in deploy["needs"]
    assert "terraform-config-validate" in deploy["needs"]
    assert "terraform-policy-as-code" in deploy["needs"]
    assert deploy["concurrency"] == {
        "group": "production-backend-rollout",
        "cancel-in-progress": False,
    }
    assert deploy["env"]["MIGRATION_TFSTATE_KEY"] == "${{ secrets.MIGRATION_TFSTATE_KEY }}"
    assert deploy["outputs"]["initial_schema"] == "${{ steps.current_schema.outputs.revision }}"

    plan = _step_by_name(deploy["steps"], "Plan migration bootstrap (Phase A)")["run"]
    apply = _step_by_name(deploy["steps"], "Apply migration bootstrap (Phase A)")["run"]
    propagation = _step_by_name(
        deploy["steps"],
        "Wait for migration identity, RBAC, and secret propagation",
    )["run"]
    migration = _step_by_name(
        deploy["steps"],
        "Run exact-head production migration",
    )["run"]
    preflight = _step_by_name(
        deploy["steps"],
        "Discover schema with same-identity database preflight",
    )["run"]

    assert "terraform -chdir=infra/migration-bootstrap init" in plan
    assert "terraform -chdir=infra init" in plan
    assert "terraform -chdir=infra state list" in plan
    assert "Legacy application state still owns the migration Job" in plan
    assert "reviewed non-destructive removed block" in plan
    assert '-backend-config="key=${MIGRATION_TFSTATE_KEY}"' in plan
    assert "terraform -chdir=infra/migration-bootstrap validate -no-color" in plan
    assert "terraform -chdir=infra/migration-bootstrap plan" in plan
    assert "-out=migration-bootstrap.tfplan" in plan
    assert "-target" not in plan
    assert "state list" in plan
    assert "azurerm_user_assigned_identity.database_migration" in plan
    assert "azurerm_role_assignment.acr_pull" in plan
    assert "azurerm_role_assignment.database_secret_reader" in plan
    assert "RBAC-mode vault is missing" in plan
    assert "Access-policy-mode vault is missing" in plan
    assert "azurerm_key_vault_access_policy.database_secret_reader[0]" in plan
    assert "Bootstrap state is empty while the migration Job already exists" in plan
    assert "terraform -chdir=infra/migration-bootstrap apply" in apply
    assert "migration-bootstrap.tfplan" in apply
    assert "-target" not in apply
    assert "continue-on-error" not in _step_by_name(
        deploy["steps"], "Apply migration bootstrap (Phase A)"
    )
    assert "az role assignment list" in propagation
    assert "key_vault_authorization_mode" in propagation
    assert "az keyvault show" in propagation
    assert "properties.provisioningState" in propagation
    assert "DATABASE_URL" in propagation
    assert "db-connection" in propagation
    assert "MIGRATION_IMAGE_REFERENCE" in propagation

    assert "az containerapp job update" not in migration
    assert "az containerapp job start" in migration
    job_start = migration.split("az containerapp job start", 1)[1].split(")", 1)[0]
    assert "--image " not in job_start
    assert "EXPECTED_ALEMBIC_HEAD" in migration
    assert "MIGRATION_IMAGE_REFERENCE" in migration
    assert "properties.template.containers[0].image" in migration
    assert "EXPECTED_ALEMBIC_HEAD" in migration
    assert "did not preserve exact-head evidence" in migration
    assert "az containerapp job execution show" in migration
    assert "Succeeded)" in migration
    assert "Failed|Stopped|Cancelled)" in migration
    assert "az containerapp job start" in preflight
    assert '--preflight-only --accept-current 013 --accept-current "$EXPECTED_ALEMBIC_HEAD"' in preflight
    assert "Same-identity database preflight failed" in preflight
    assert "Same-identity database preflight timed out" in preflight
    assert "ARCHMORPH_MIGRATION_PREFLIGHT_EVIDENCE=" in preflight
    assert "completed without required evidence" in preflight

    assert "ARCHMORPH_MIGRATION_EVIDENCE=" in migration
    assert "completed without required success evidence" in migration
    for event in (
        "migration_started",
        "migration_succeeded",
        "migration_failed",
        "migration_timed_out",
    ):
        assert f"--event {event}" in migration

    step_names = [step.get("name") for step in deploy["steps"]]
    assert step_names.index("Trivy container security gate") < step_names.index(
        "Plan migration bootstrap (Phase A)"
    )
    assert step_names.index("Plan migration bootstrap (Phase A)") < step_names.index(
        "Apply migration bootstrap (Phase A)"
    )
    assert step_names.index("Apply migration bootstrap (Phase A)") < step_names.index(
        "Wait for migration identity, RBAC, and secret propagation"
    )
    assert step_names.index("Wait for migration identity, RBAC, and secret propagation") < step_names.index(
        "Discover schema with same-identity database preflight"
    )
    assert step_names.index("Discover schema with same-identity database preflight") < step_names.index(
        "Resolve verified bridge for discovered schema"
    )
    assert step_names.index("Resolve verified bridge for discovered schema") < step_names.index(
        "Route production to verified bridge before migration"
    )
    assert step_names.index("Route production to verified bridge before migration") < step_names.index(
        "Run exact-head production migration"
    )
    assert step_names.index("Run exact-head production migration") < step_names.index("Deploy green revision")
    assert step_names.index("Smoke test green revision") < step_names.index("Shift traffic to green (100%)")


def test_phase_a_bootstrap_is_separate_state_and_cannot_mutate_live_app():
    terraform = MIGRATION_BOOTSTRAP.read_text(encoding="utf-8")
    main_terraform = MAIN_TERRAFORM.read_text(encoding="utf-8")

    assert 'resource "azurerm_container_app_job" "database_migration"' in terraform
    assert 'resource "azurerm_user_assigned_identity" "database_migration"' in terraform
    assert 'resource "azurerm_role_assignment" "acr_pull"' in terraform
    assert 'resource "azurerm_role_assignment" "database_secret_reader"' in terraform
    assert 'resource "azurerm_key_vault_access_policy" "database_secret_reader"' in terraform
    assert 'count = local.key_vault_rbac_mode ? 1 : 0' in terraform
    assert 'count = local.key_vault_rbac_mode ? 0 : 1' in terraform
    assert 'secret_permissions = ["Get"]' in terraform
    assert 'scope                            = local.database_secret_scope' in terraform
    assert 'key_vault_secret_id = local.database_secret_uri' in terraform
    assert 'data "azurerm_key_vault_secret"' not in terraform
    assert "database_secret_uri" in terraform
    assert "database_secret_scope" in terraform
    assert ".value" not in terraform
    assert 'identity_ids = [azurerm_user_assigned_identity.database_migration.id]' in terraform
    assert 'command = ["python", "run_migrations.py"]' in terraform
    assert 'args    = ["--expect-head", var.expected_alembic_head]' in terraform
    assert 'name        = "DATABASE_URL"\n        secret_name = "db-connection"' in terraform
    assert 'name  = "AZURE_CLIENT_ID"' in terraform
    assert 'value = azurerm_user_assigned_identity.database_migration.client_id' in terraform
    assert 'name  = "MIGRATION_IMAGE_REFERENCE"' in terraform
    assert "parallelism              = 1" in terraform
    assert "replica_completion_count = 1" in terraform
    assert "replica_retry_limit          = 0" in terraform
    assert 'resource "time_sleep" "rbac_propagation"' in terraform
    assert 'resource "azurerm_container_app"' not in terraform
    assert "traffic_weight" not in terraform
    assert "readiness_probe" not in terraform
    assert ":latest" not in terraform
    assert 'backend "azurerm"' in terraform
    assert 'removed {\n  from = azurerm_container_app_job.database_migration' in main_terraform
    assert "destroy = false" in main_terraform
    assert 'resource "azurerm_container_app_job" "database_migration"' not in main_terraform
    variables = (REPO_ROOT / "infra" / "variables.tf").read_text(encoding="utf-8")
    assert 'variable "key_vault_rbac_authorization_enabled"' in variables
    assert 'default     = true' in variables
    assert 'rbac_authorization_enabled = var.key_vault_rbac_authorization_enabled' in main_terraform
    assert 'count = var.key_vault_rbac_authorization_enabled ? 0 : 1' in main_terraform
    assert 'count = var.key_vault_rbac_authorization_enabled ? 1 : 0' in main_terraform


def test_phase_a_workflow_rejects_concurrency_and_uses_only_job_control_plane():
    workflow = _load(CI_WORKFLOW)
    steps = workflow["jobs"]["deploy-backend"]["steps"]
    phase_a_names = {
        "Reject concurrent production migration execution",
        "Plan migration bootstrap (Phase A)",
        "Apply migration bootstrap (Phase A)",
        "Wait for migration identity, RBAC, and secret propagation",
    }
    phase_a = "\n".join(step.get("run", "") for step in steps if step.get("name") in phase_a_names)

    assert "Running" in phase_a
    assert "Processing" in phase_a
    assert "Another production migration execution is already active" in phase_a
    assert "az containerapp update" not in phase_a
    assert "az containerapp revision" not in phase_a
    assert "az containerapp ingress traffic" not in phase_a


def test_backend_image_and_schema_contract_are_immutable_and_fail_closed():
    workflow = _load(CI_WORKFLOW)
    deploy = workflow["jobs"]["deploy-backend"]
    capture = _step_by_name(deploy["steps"], "Capture immutable image and schema contract")["run"]
    green = _step_by_name(deploy["steps"], "Deploy green revision")["run"]

    assert "@${{ steps.build_backend.outputs.digest }}" in capture
    assert "^.+@sha256:[0-9a-f]{64}$" in capture
    assert "backend/schema-contract.json" in capture
    assert "APP_SCHEMA_MIN_REVISION" in capture
    assert "APP_SCHEMA_MAX_REVISION" in capture
    assert "EXPECTED_ALEMBIC_HEAD" in capture
    assert 'APP_SCHEMA_MIN_REVISION="$APP_SCHEMA_MIN_REVISION"' in green
    assert 'APP_SCHEMA_MAX_REVISION="$APP_SCHEMA_MAX_REVISION"' in green
    assert "build_containerapp_revision.py" in green
    assert "--readiness-path /readyz" in green
    assert "--secret-env DATABASE_URL=db-connection" in green
    assert "--secret-env REDIS_URL=redis-url" in green
    assert "az containerapp update" in green
    assert "--yaml green-revision.json" in green
    assert ":latest" not in capture


def test_migration_and_bootstrap_failures_stop_before_live_revision_or_traffic_changes():
    workflow = _load(CI_WORKFLOW)
    deploy_steps = workflow["jobs"]["deploy-backend"]["steps"]
    names = [step.get("name") for step in deploy_steps]
    guarded_steps = (
        "Plan migration bootstrap (Phase A)",
        "Apply migration bootstrap (Phase A)",
        "Wait for migration identity, RBAC, and secret propagation",
        "Discover schema with same-identity database preflight",
        "Run exact-head production migration",
    )
    for name in guarded_steps:
        step = _step_by_name(deploy_steps, name)
        assert not step.get("continue-on-error", False)
        assert names.index(name) < names.index("Deploy green revision")
        assert names.index(name) < names.index("Shift traffic to green (100%)")
    preflight_index = names.index("Discover schema with same-identity database preflight")
    resolve_index = names.index("Resolve verified bridge for discovered schema")
    assert preflight_index < resolve_index
    preflight = _step_by_name(
        deploy_steps,
        "Discover schema with same-identity database preflight",
    )["run"]
    for mutation in (
        "az containerapp update",
        "az containerapp ingress traffic set",
        "az containerapp revision activate",
    ):
        assert mutation not in preflight
    resolve = _step_by_name(
        deploy_steps,
        "Resolve verified bridge for discovered schema",
    )["run"]
    assert "deploy-schema-bridge.sh" in resolve


def test_rollout_captures_exact_traffic_bridges_first_and_restores_post_shift_failure():
    workflow = _load(CI_WORKFLOW)
    steps = workflow["jobs"]["deploy-backend"]["steps"]
    names = [step.get("name") for step in steps]
    capture = _step_by_name(steps, "Capture blue traffic and make latest routing explicit")["run"]
    bridge = _step_by_name(steps, "Stage schema bridge rollout script")["run"]
    green = _step_by_name(steps, "Deploy green revision")["run"]
    shift = _step_by_name(steps, "Shift traffic to green (100%)")["run"]
    verify_step = _step_by_name(steps, "Verify production deployment")
    verify = verify_step["run"]
    restore_step = _step_by_name(
        steps,
        "Restore exact prior traffic after routed verification failure",
    )
    restore = restore_step["run"]
    retain = _step_by_name(steps, "Deactivate old revisions (keep blue for rollback)")["run"]

    assert "blue-traffic-original.json" in capture
    assert "explicit-traffic" in capture
    assert "apply-traffic" in capture
    assert "properties.trafficWeight >" in capture
    assert "No explicit routed revision" in capture
    assert "eval " not in capture
    assert names.index("Capture blue traffic and make latest routing explicit") < names.index(
        "Stage schema bridge rollout script"
    )
    assert "BRIDGE_WEIGHT" in bridge and '!= "0"' in bridge
    assert "BRIDGE_ROLE" in bridge
    assert "missing explicit release-role metadata" in bridge
    assert 'BRIDGE_IMAGE_REF' in bridge
    assert "required_secret in db-connection redis-url" in bridge
    assert "--secret-env DATABASE_URL=db-connection" in bridge
    assert "--secret-env REDIS_URL=redis-url" in bridge
    assert '.current_revision == $current' in bridge
    assert 'bridge_read_only' in bridge
    assert '"https://${BRIDGE_FQDN}/api/health"' in bridge
    assert "write-release-manifest" in bridge
    assert "--required-role bridge" in bridge
    assert "GREEN_WEIGHT" in green and '!= "0"' in green
    assert "bridge-only-traffic.json" in green
    smoke = _step_by_name(steps, "Smoke test green revision")["run"]
    assert "does not identify as the final release role" in smoke
    assert ".minimum_revision == $minimum" in smoke
    assert ".migration_target_revision == $target" in smoke
    assert "pre-shift-traffic-manifest.json" in shift
    assert verify_step["id"] == "verify_production"
    assert "health_gate.sh" in verify
    assert restore_step["if"] == "always() && steps.verify_production.outcome != 'success'"
    assert "apply-traffic" in restore
    assert "restored-traffic.json" in restore
    assert "RESTORE_STATUS" in restore
    assert restore.index("apply-traffic") < restore.index("az containerapp revision show")
    assert "eval " not in restore
    assert "bridge-release-manifest.json" in retain
    assert "Keeping signed bridge revision" in retain
    assert "ROLLBACK_REVISIONS" in retain
    assert "Keeping exact prior traffic revision" in retain
    workflow_text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "BRIDGE_BASE_IMAGE=${{ env.ACR_LOGIN_SERVER }}/archmorph-api@${{ steps.build_backend.outputs.digest }}" in workflow_text
    assert "backend/bridge_overlay/Dockerfile" in workflow_text
    assert "context: ./backend/bridge_overlay" in workflow_text
    assert "archmorph-api-bridge@${{ steps.build_bridge.outputs.digest }}" in workflow_text
    detect = _step_by_name(steps, "Discover schema with same-identity database preflight")["run"]
    rerun = _step_by_name(steps, "Stage signed bridge reuse script")["run"]
    resolve = _step_by_name(steps, "Resolve verified bridge for discovered schema")["run"]
    route_bridge = _step_by_name(
        steps,
        "Route production to verified bridge before migration",
    )["run"]
    assert "--accept-current 013" in detect
    assert "ARCHMORPH_MIGRATION_PREFLIGHT_EVIDENCE=" in detect
    assert "gh run download" in rerun
    assert "--required-role bridge" in rerun
    assert 'BRIDGE_ROLE" = "bridge"' in rerun
    assert "rerun-bridge-read-only.json" in rerun
    assert "BRIDGE_REVISION=" in resolve
    assert 'CURRENT_SCHEMA_REVISION" = "013"' in resolve
    assert "export CURRENT_SCHEMA_REVISION" in resolve
    assert "bridge-routed-traffic.json" in route_bridge
    assert "assert-traffic" in route_bridge
    assert '.release_role == "bridge"' in route_bridge
    assert "routed-bridge-read-only.json" in route_bridge


def test_frontend_waits_for_backend_and_has_previous_artifact_rollback():
    workflow = _load(CI_WORKFLOW)
    frontend = workflow["jobs"]["deploy-frontend"]
    assert frontend["needs"] == ["deploy-backend", "frontend-build"]
    steps = frontend["steps"]
    download = _step_by_name(steps, "Download previous frontend rollback artifact")["run"]
    deploy = _step_by_name(steps, "Deploy to Azure Static Web Apps")
    verify = _step_by_name(steps, "Verify frontend and automatically restore previous artifact")
    restore = _step_by_name(
        steps,
        "Restore prior frontend artifact after deploy or verification failure",
    )
    assert "gh run download" in download
    assert "frontend-dist" in download
    assert "rollback-dist" in download
    assert "rollback-dist/dist/index.html" in download
    assert "rollback-dist/api" in download
    assert deploy["id"] == "deploy_frontend"
    assert verify["id"] == "verify_frontend"
    assert "curl -fsS" in verify["run"]
    assert restore["if"] == (
        "always() && needs.deploy-backend.outputs.initial_schema != '013' && "
        "(steps.deploy_frontend.outcome != 'success' || "
        "steps.verify_frontend.outcome != 'success')"
    )
    assert "staticappsclient:stable" in restore["run"]
    assert "INPUT_API_LOCATION=/api" in restore["run"]
    assert "rollback-dist/dist:/app:ro" in restore["run"]
    assert "rollback-dist/api:/api:ro" in restore["run"]


def test_migration_alerts_use_action_group_and_explicit_platform_owner():
    terraform = MAIN_TERRAFORM.read_text(encoding="utf-8")
    assert 'resource "azurerm_monitor_scheduled_query_rules_alert_v2" "migration_job_failure"' in terraform
    assert 'resource "azurerm_monitor_scheduled_query_rules_alert_v2" "migration_missing_evidence"' in terraform
    migration_alerts = terraform.split(
        'resource "azurerm_monitor_scheduled_query_rules_alert_v2" "migration_job_failure"',
        1,
    )[1].split("# Slow API Response Alert", 1)[0]
    assert "count =" not in migration_alerts
    assert "AppEvents" in terraform
    assert "migration_started" in terraform
    assert "migration_succeeded" in terraform
    assert "migration_failed" in terraform
    assert "migration_timed_out" in terraform
    assert "azurerm_monitor_action_group.critical.id" in terraform
    assert 'owner = "platform-engineering"' in terraform


def test_rollback_health_verification_uses_authenticated_api_health():
    workflow = _load(ROLLBACK_WORKFLOW)
    assert "traffic_percentage" not in workflow[True]["workflow_dispatch"]["inputs"]
    assert workflow["env"]["ARCHMORPH_API_KEY"] == "${{ secrets.ARCHMORPH_API_KEY }}"
    assert workflow["env"]["ADMIN_KEY"] == "${{ secrets.ADMIN_KEY }}"
    assert workflow["env"]["RELEASE_MANIFEST_HMAC_KEY"] == (
        "${{ secrets.RELEASE_MANIFEST_HMAC_KEY }}"
    )
    assert workflow["jobs"]["rollback"]["environment"] == "production"

    steps = workflow["jobs"]["rollback"]["steps"]
    assert workflow["jobs"]["rollback"]["concurrency"] == {
        "group": "production-backend-rollout",
        "cancel-in-progress": False,
    }
    compatibility_step = _step_by_name(steps, "Verify target schema compatibility before activation")
    compatibility_script = compatibility_step["run"]
    step_names = [step.get("name") for step in steps]
    assert "APP_SCHEMA_MIN_REVISION" in compatibility_script
    assert "APP_SCHEMA_MAX_REVISION" in compatibility_script
    assert "/api/schema-compatibility" in compatibility_script
    assert "Target revision is incompatible with the current database schema" in compatibility_script
    assert "traffic remains unchanged" in compatibility_script
    assert "Rollback target supports current schema" in compatibility_script
    assert "activating it at zero traffic for schema preflight" in compatibility_script
    assert "az containerapp revision activate" in compatibility_script
    assert "az containerapp revision deactivate" in compatibility_script
    assert "az containerapp ingress traffic set" not in compatibility_script
    assert step_names.index("Verify target schema compatibility before activation") < step_names.index(
        "Activate rollback revision"
    )
    assert step_names.index("Verify target schema compatibility before activation") < step_names.index(
        "Shift traffic to rollback revision"
    )
    resolve = _step_by_name(steps, "Resolve explicit signed bridge rollback target")["run"]
    assert "RELEASE_MANIFEST_HMAC_KEY must contain at least 32 bytes" in resolve
    verify_step = _step_by_name(steps, "Verify rollback health")
    run_script = verify_step["run"]

    assert 'HEALTH_API_KEY="${ARCHMORPH_API_KEY:-${ADMIN_KEY:-}}"' in run_script
    assert 'X-API-Key: ${HEALTH_API_KEY}' in run_script
    assert '"${BASE}/api/health"' in run_script
    assert '"${BASE}/api/schema-compatibility"' in run_script
    assert '.release_role == "bridge"' in run_script
    assert '[ "$HTTP_CODE" = "503" ]' in run_script
    assert 'bridge_read_only' in run_script
    shift = _step_by_name(steps, "Shift traffic to rollback revision")["run"]
    assert '--revision-weight "$ROLLBACK_TARGET=100"' in shift
    assert "restore_status" in run_script
    assert "az containerapp logs show" in run_script
    assert "original_exit=$?" in run_script
    assert 'exit "$original_exit"' in run_script


def test_monitoring_health_check_uses_authenticated_health_endpoint():
    workflow = _load(MONITORING_WORKFLOW)
    assert workflow["env"]["ARCHMORPH_API_KEY"] == "${{ secrets.ARCHMORPH_API_KEY }}"

    steps = workflow["jobs"]["api-health-check"]["steps"]
    health_step = _step_by_name(steps, "Check API Health")
    assert health_step["env"]["ADMIN_KEY"] == "${{ secrets.ADMIN_KEY }}"

    run_script = health_step["run"]
    assert 'HEALTH_API_KEY="${ARCHMORPH_API_KEY:-${ADMIN_KEY:-}}"' in run_script
    assert 'X-API-Key: ${HEALTH_API_KEY}' in run_script
    assert '"${{ env.API_URL }}/health"' in run_script
