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
    assert "tests/test_helm_secret_contract.py" in contracts
    assert 'DATABASE_SCHEME="postgresql"' in contracts
    assert "printf -v DATABASE_URL '%s://%s:%s@127.0.0.1:5432/%s'" in contracts


def test_backend_deploy_runs_isolated_bootstrap_and_exact_head_migration_before_green():
    workflow = _load(CI_WORKFLOW)
    deploy = workflow["jobs"]["deploy-backend"]

    assert "alembic-migration-smoke" in deploy["needs"]
    assert deploy["concurrency"] == {
        "group": "production-backend-rollout",
        "cancel-in-progress": False,
    }
    assert deploy["env"]["MIGRATION_TFSTATE_KEY"] == "${{ secrets.MIGRATION_TFSTATE_KEY }}"

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
    assert "Bootstrap state is empty while the migration Job already exists" in plan
    assert "terraform -chdir=infra/migration-bootstrap apply" in apply
    assert "migration-bootstrap.tfplan" in apply
    assert "-target" not in apply
    assert "continue-on-error" not in _step_by_name(
        deploy["steps"], "Apply migration bootstrap (Phase A)"
    )
    assert "az role assignment list" in propagation
    assert "properties.provisioningState" in propagation
    assert "DATABASE_URL" in propagation
    assert "db-connection" in propagation
    assert "MIGRATION_IMAGE_REFERENCE" in propagation

    assert "az containerapp job update" not in migration
    assert "az containerapp job start" in migration
    assert "--image" not in migration
    assert "EXPECTED_ALEMBIC_HEAD" in migration
    assert "MIGRATION_IMAGE_REFERENCE" in migration
    assert "properties.template.containers[0].image" in migration
    assert "EXPECTED_ALEMBIC_HEAD" in migration
    assert "did not preserve exact-head evidence" in migration
    assert "az containerapp job execution show" in migration
    assert "Succeeded)" in migration
    assert "Failed|Stopped|Cancelled)" in migration

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
        "Run exact-head production migration",
    )
    for name in guarded_steps:
        step = _step_by_name(deploy_steps, name)
        assert not step.get("continue-on-error", False)
        assert names.index(name) < names.index("Deploy green revision")
        assert names.index(name) < names.index("Shift traffic to green (100%)")


def test_rollback_health_verification_uses_authenticated_api_health():
    workflow = _load(ROLLBACK_WORKFLOW)
    assert workflow["env"]["ARCHMORPH_API_KEY"] == "${{ secrets.ARCHMORPH_API_KEY }}"
    assert workflow["env"]["ADMIN_KEY"] == "${{ secrets.ADMIN_KEY }}"
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
    verify_step = _step_by_name(steps, "Verify rollback health")
    run_script = verify_step["run"]

    assert 'HEALTH_API_KEY="${ARCHMORPH_API_KEY:-${ADMIN_KEY:-}}"' in run_script
    assert 'X-API-Key: ${HEALTH_API_KEY}' in run_script
    assert '"${BASE}/api/health"' in run_script
    assert 'if ! HTTP_CODE=$(curl "${_CURL_ARGS[@]}" -o health.json -w "%{http_code}"' in run_script


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
