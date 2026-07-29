import json
import re
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
ROLLBACK_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "rollback.yml"
MONITORING_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "monitoring.yml"
MIGRATION_BOOTSTRAP = REPO_ROOT / "infra" / "migration-bootstrap" / "main.tf"
MAIN_TERRAFORM = REPO_ROOT / "infra" / "main.tf"
HELM_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "helm-release.yml"
TERRAFORM_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "terraform-prod.yml"
MIGRATION_ALERT_SPECS = REPO_ROOT / "infra" / "monitoring" / "migration-alert-specs.json"
ROLLOUT_HELPER = REPO_ROOT / "scripts" / "containerapp_rollout.py"
RELEASE_CHECKLIST = REPO_ROOT / "docs" / "RELEASE_CHECKLIST.md"
ROLLBACK_RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "rollback.md"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _step_by_name(steps: list[dict], name: str) -> dict:
    for step in steps:
        if step.get("name") == name:
            return step
    raise AssertionError(f'Expected workflow step "{name}"')


def _canonical_kql(query: str) -> str:
    return "\n".join(
        " ".join(line.strip().split())
        for line in query.splitlines()
        if line.strip()
    )


def _terraform_alert_block(terraform: str, resource_name: str) -> str:
    marker = (
        'resource "azurerm_monitor_scheduled_query_rules_alert_v2" '
        f'"{resource_name}" {{'
    )
    start = terraform.index(marker)
    depth = 0
    for index in range(start + len(marker) - 1, len(terraform)):
        if terraform[index] == "{":
            depth += 1
        elif terraform[index] == "}":
            depth -= 1
            if depth == 0:
                return terraform[start : index + 1]
    raise AssertionError(f"Unterminated Terraform alert resource {resource_name}")


def test_ci_includes_pgvector_empty_schema_structural_migration_cycle():
    workflow = _load(CI_WORKFLOW)
    job = workflow["jobs"]["alembic-migration-smoke"]
    rollout_job = workflow["jobs"]["rollout-contracts"]

    assert job["services"]["postgres"]["image"] == "pgvector/pgvector:pg16"
    assert job["services"]["redis"]["image"] == "redis:7.4-alpine"
    assert job["env"]["POSTGRES_USER"] == "archmorph"
    assert job["env"]["POSTGRES_DB"] == "archmorph"
    assert job["env"]["ARCHMORPH_TEST_REDIS_URL"] == "redis://127.0.0.1:6379/15"
    rollout_contracts = _step_by_name(
        rollout_job["steps"],
        "Run deterministic rollout contracts",
    )["run"]
    assert "backend/tests/test_rollout_telemetry.py" in rollout_contracts
    assert "backend/tests/test_run_migrations.py" in rollout_contracts
    assert "backend/tests/test_helm_release_contract.py" in rollout_contracts
    assert "backend/tests/test_kubernetes_lease.py" in rollout_contracts
    assert "backend/tests/test_azure_rollout_lease.py" in rollout_contracts
    assert "backend/tests/test_release_provenance.py" in rollout_contracts
    assert "backend/tests/test_containerapp_revision_builder.py" in rollout_contracts
    assert "backend/tests/test_bridge_overlay.py" in rollout_contracts

    run_script = _step_by_name(
        job["steps"],
        "Run empty-schema structural migration compatibility cycle",
    )["run"]
    assert "python -m alembic heads" in run_script
    assert "python -m alembic upgrade head --sql" in run_script
    assert "python -m alembic upgrade head" in run_script
    assert "python -m alembic downgrade 013" in run_script
    assert "python -m alembic upgrade 014" in run_script
    assert "python -m alembic downgrade base" not in run_script
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


def test_release_docs_call_downgrade_cycle_structural_and_require_fix_forward():
    checklist = RELEASE_CHECKLIST.read_text(encoding="utf-8")
    runbook = ROLLBACK_RUNBOOK.read_text(encoding="utf-8")
    for document in (checklist, runbook):
        assert "empty-schema" in document
        assert "production" in document
        assert "fix-forward" in document
    assert "not production\nrollback" in runbook
    assert "nonempty-data regression" in runbook


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
    prepare_migration = _step_by_name(
        deploy["steps"],
        "Prepare exact-head production migration",
    )["run"]
    start_migration = _step_by_name(
        deploy["steps"],
        "Start exact-head production migration",
    )["run"]
    supervision = _step_by_name(
        deploy["steps"],
        "Supervise exact-head production migration",
    )["run"]
    migration = prepare_migration + start_migration + supervision
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
    assert '-backend-config="storage_account_name=${MIGRATION_TFSTATE_STORAGE_ACCOUNT}"' in plan
    assert '-backend-config="container_name=${MIGRATION_TFSTATE_CONTAINER}"' in plan
    assert "terraform -chdir=infra/migration-bootstrap validate -no-color" in plan
    assert "terraform -chdir=infra/migration-bootstrap plan" in plan
    assert "terraform -chdir=infra/migration-bootstrap show -json" in plan
    assert "verify_migration_bootstrap.py plan" in plan
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
    assert "az containerapp job start" in start_migration
    job_start = start_migration.split("az containerapp job start", 1)[1].split(")", 1)[0]
    assert "--image " not in job_start
    assert "--query name --output tsv" in job_start
    assert "EXPECTED_ALEMBIC_HEAD" in migration
    assert "MIGRATION_IMAGE_REFERENCE" in migration
    assert "properties.template.containers[0].image" in migration
    assert "EXPECTED_ALEMBIC_HEAD" in migration
    assert "did not preserve exact-head evidence" in migration
    assert "az containerapp job execution show" in migration
    assert "--job-execution-name" in migration
    assert "--query properties.status --output tsv" in preflight
    assert "Succeeded)" in migration
    assert "Failed|Stopped|Cancelled)" in migration
    assert "mark-migration-starting" in prepare_migration
    assert "known-migration-executions.json" in prepare_migration
    assert "--execution-marker" in prepare_migration
    assert "record-migration-execution" in start_migration
    assert '--execution-marker "$MIGRATION_EXECUTION_MARKER"' in start_migration
    assert start_migration.index("record-migration-execution") < start_migration.index(
        "--event migration_started"
    )
    assert "supervise-migration" in supervision
    assert "az containerapp job start" in preflight
    assert '--preflight-only --accept-current 013 --accept-current "$EXPECTED_ALEMBIC_HEAD"' in preflight
    assert "Same-identity database preflight failed" in preflight
    assert "Same-identity database preflight timed out" in preflight
    assert "/api/schema-compatibility" in preflight
    assert "current-schema-compatibility.json" in preflight

    assert "az containerapp logs show" not in migration
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
        "Prepare exact-head production migration"
    )
    assert step_names.index("Prepare exact-head production migration") < step_names.index(
        "Persist signed migration start boundary"
    )
    assert step_names.index("Persist signed migration start boundary") < step_names.index(
        "Start exact-head production migration"
    )
    assert step_names.index("Start exact-head production migration") < step_names.index(
        "Persist signed migration execution state"
    )
    assert step_names.index("Persist signed migration execution state") < step_names.index(
        "Supervise exact-head production migration"
    )
    assert step_names.index("Supervise exact-head production migration") < step_names.index(
        "Deploy green revision"
    )
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


def test_rollout_coordination_storage_is_private_and_managed_identity_only():
    terraform = MAIN_TERRAFORM.read_text(encoding="utf-8")
    variables = (REPO_ROOT / "infra" / "variables.tf").read_text(encoding="utf-8")
    assert 'resource "azurerm_storage_container" "rollout_coordination"' in terraform
    coordination = terraform.split(
        'resource "azurerm_storage_container" "rollout_coordination"',
        1,
    )[1].split("# ─", 1)[0]
    assert 'container_access_type = "private"' in coordination
    release_role = terraform.split(
        'resource "azurerm_role_assignment" "rollout_coordination_release"',
        1,
    )[1].split(
        'resource "azurerm_role_assignment" "rollout_coordination_priority"', 1
    )[0]
    priority_role = terraform.split(
        'resource "azurerm_role_assignment" "rollout_coordination_priority"',
        1,
    )[1].split("# Grant Container App identity access to ACR", 1)[0]
    for role in (release_role, priority_role):
        assert "azurerm_storage_container.rollout_coordination.id" in role
        assert 'role_definition_name = "Storage Blob Data Contributor"' in role
    assert "var.release_automation_principal_id" in release_role
    assert "var.rollout_priority_principal_id" in priority_role
    assert 'variable "release_automation_principal_id"' in variables
    assert 'variable "rollout_priority_principal_id"' in variables
    assert "sensitive   = true" in variables
    assert "account_key" not in coordination.lower()
    assert "sas" not in coordination.lower()


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

    assert "Unknown" in phase_a
    assert "Succeeded" in phase_a
    assert "Cancelled" in phase_a
    assert "nonterminal migration execution is active" in phase_a
    assert "recovery_required" in phase_a
    assert "az containerapp update" not in phase_a
    assert "az containerapp revision" not in phase_a
    assert "az containerapp ingress traffic" not in phase_a


def test_phase_a_enforces_backend_tuple_plan_allowlist_and_integrity_before_apply():
    workflow = _load(CI_WORKFLOW)
    steps = workflow["jobs"]["deploy-backend"]["steps"]
    plan = _step_by_name(steps, "Plan migration bootstrap (Phase A)")["run"]
    apply = _step_by_name(steps, "Apply migration bootstrap (Phase A)")["run"]
    assert "verify_migration_bootstrap.py backend" in plan
    assert "MIGRATION_TFSTATE_STORAGE_ACCOUNT" in plan
    assert "MIGRATION_TFSTATE_CONTAINER" in plan
    assert "terraform -chdir=infra/migration-bootstrap show -json" in plan
    assert "verify_migration_bootstrap.py plan" in plan
    assert "write-metadata" in plan
    assert "primary-state-before-bootstrap.json" in plan
    assert "state-before-apply.json" in plan
    assert "verify-metadata" in apply
    assert apply.index("verify-metadata") < apply.index("terraform -chdir=infra/migration-bootstrap apply")


def test_alert_attestation_precedes_every_migration_job_start():
    workflow = _load(CI_WORKFLOW)
    steps = workflow["jobs"]["deploy-backend"]["steps"]
    names = [step.get("name") for step in steps]
    attest = _step_by_name(steps, "Attest applied migration alerts before Job execution")["run"]
    assert "terraform -chdir=infra output -json" in attest
    assert "verify_migration_alerts.py" in attest
    assert "migration_failure_alert_id" in attest
    assert "migration_timeout_alert_id" in attest
    assert "migration_missing_evidence_alert_id" in attest
    assert "bridge_customer_degraded_alert_id" in attest
    assert "application_insights_resource_id" in attest
    assert "critical_action_group_id" in attest
    assert "--spec infra/monitoring/migration-alert-specs.json" in attest
    assert "--application-insights-id" in attest
    assert "--customer-degraded-alert-id" in attest
    assert names.index("Attest applied migration alerts before Job execution") < names.index(
        "Discover schema with same-identity database preflight"
    )
    assert names.index("Attest applied migration alerts before Job execution") < names.index(
        "Prepare exact-head production migration"
    )


def test_cleanup_is_manifest_and_stage_gated_without_obscuring_original_failure():
    workflow = _load(CI_WORKFLOW)
    steps = workflow["jobs"]["deploy-backend"]["steps"]
    recovery = _step_by_name(steps, "Recover exact schema-safe traffic after rollout failure")
    assert "steps.rollout_state.outcome == 'success'" in recovery["if"]
    assert "recover-release" in recovery["run"]
    assert "|| RESTORE_STATUS=$?" in recovery["run"]
    assert "rollout-recovery-evidence.json" in recovery["run"]
    assert "|| true" in recovery["run"]
    deactivate = _step_by_name(
        steps, "Deactivate superseded revisions after final evidence"
    )
    assert deactivate["if"] == "steps.final_release_evidence.outcome == 'success'"
    assert "properties.active" in deactivate["run"]
    assert "remained active after cleanup" in deactivate["run"]
    assemble = _step_by_name(steps, "Assemble complete backend final release evidence")
    assert assemble["id"] == "final_evidence_bundle"
    assert assemble["if"] == (
        "always() && steps.final_release_evidence.outcome == 'success'"
    )
    assert "REQUIRED_EVIDENCE" in assemble["run"]
    assert "Required backend release evidence is missing or empty" in assemble["run"]
    upload = _step_by_name(steps, "Upload complete backend final release evidence")
    assert upload["if"] == (
        "always() && steps.final_evidence_bundle.outcome == 'success'"
    )
    assert "github.run_id" in upload["with"]["name"]
    diagnostics = _step_by_name(steps, "Assemble explicit failed-rollout diagnostics")
    assert "partial:true" in diagnostics["run"]


def test_migration_execution_is_persisted_and_quiesced_before_recovery_decisions():
    workflow = _load(CI_WORKFLOW)
    steps = workflow["jobs"]["deploy-backend"]["steps"]
    names = [step.get("name") for step in steps]
    load = _step_by_name(
        steps,
        "Load signed migration execution evidence from a prior run attempt",
    )["run"]
    reject = _step_by_name(steps, "Reject concurrent production migration execution")["run"]
    prepare = _step_by_name(steps, "Prepare exact-head production migration")["run"]
    start_boundary = _step_by_name(steps, "Persist signed migration start boundary")
    start = _step_by_name(steps, "Start exact-head production migration")["run"]
    persist = _step_by_name(steps, "Persist signed migration execution state")
    supervise = _step_by_name(steps, "Supervise exact-head production migration")["run"]
    terminal = _step_by_name(steps, "Persist terminal migration execution state")
    recovery = _step_by_name(
        steps,
        "Recover exact schema-safe traffic after rollout failure",
    )["run"]

    assert "gh api" in load
    assert 'gh run download "$GITHUB_RUN_ID"' in load
    assert "migration-terminal-state|migration-execution-state|migration-start-boundary" in load
    assert "verify-release-state" in load
    assert "resolve-migration-start" in reject
    assert "cannot be bound to one exact reviewed execution" in reject
    assert "quiesce-migration" in reject
    assert "retaining current schema-compatible traffic" in reject
    assert "traffic remains unchanged" in reject
    assert "mark-migration-starting" in prepare
    assert "known-migration-executions.json" in prepare
    assert "az containerapp job start" in start
    assert start_boundary["with"]["name"] == (
        "migration-start-boundary-${{ github.run_id }}-${{ github.run_attempt }}"
    )
    assert start_boundary["with"]["path"] == "rollout-state.json"
    assert "record-migration-execution" in start
    assert start.index("record-migration-execution") < start.index(
        "--event migration_started"
    )
    assert persist["with"]["name"] == (
        "migration-execution-state-${{ github.run_id }}-${{ github.run_attempt }}"
    )
    assert persist["with"]["path"] == "rollout-state.json\nrollout-telemetry.ndjson\n"
    assert terminal["if"].startswith("always() && steps.start_migration.outcome == 'success'")
    assert terminal["with"]["name"] == (
        "migration-terminal-state-${{ github.run_id }}-${{ github.run_attempt }}"
    )
    assert "migration-execution-evidence.json" in terminal["with"]["path"]
    assert "supervise-migration" in supervise
    assert names.index("Prepare exact-head production migration") < names.index(
        "Persist signed migration start boundary"
    ) < names.index("Start exact-head production migration") < names.index(
        "Persist signed migration execution state"
    ) < names.index("Supervise exact-head production migration") < names.index(
        "Persist terminal migration execution state"
    )
    assert recovery.index("resolve-migration-start") < recovery.index(
        "quiesce-migration"
    )
    assert recovery.index("quiesce-migration") < recovery.index(
        "/api/schema-compatibility"
    ) < recovery.index("recover-release")
    assert "recovery_required" in recovery
    assert "traffic remains on bridge/green" in recovery
    assert "migration-quiescence-evidence.json" in recovery


def test_touched_workflow_never_streams_raw_container_application_logs():
    workflow_text = CI_WORKFLOW.read_text(encoding="utf-8")
    rollback_text = ROLLBACK_WORKFLOW.read_text(encoding="utf-8")
    assert "az containerapp logs show" not in workflow_text
    assert "az containerapp logs show" not in rollback_text
    assert "APPLICATIONINSIGHTS_CONNECTION_STRING is required" not in workflow_text
    assert "rollout-telemetry.ndjson" in workflow_text


def test_exact_execution_helper_uses_official_show_stop_forms_without_unrelated_stop():
    helper = ROLLOUT_HELPER.read_text(encoding="utf-8")
    show_contract = (
        '"execution",\n            "show",\n            "--job-execution-name",\n'
        '            execution_name,\n            "--name",\n            job_name,\n'
        '            "--resource-group",\n            resource_group,\n'
        '            "--query",\n            "properties.status",\n'
        '            "--output",\n            "tsv",'
    )
    stop_contract = (
        '"job",\n            "stop",\n            "--name",\n'
        '            binding["job_name"],\n            "--resource-group",\n'
        '            binding["resource_group"],\n            "--job-execution-name",\n'
        '            binding["execution_name"],'
    )
    assert show_contract in helper
    assert stop_contract in helper
    assert "job stop --name" not in helper


def test_all_production_mutations_use_durable_external_ownership_and_rollback_is_independent():
    ci = _load(CI_WORKFLOW)
    rollback = _load(ROLLBACK_WORKFLOW)
    terraform = _load(TERRAFORM_WORKFLOW)
    helm = _load(HELM_WORKFLOW)
    assert ci["jobs"]["deploy-backend"]["concurrency"]["cancel-in-progress"] is False
    assert "concurrency" not in rollback["jobs"]["rollback"]
    assert "concurrency" not in terraform
    assert "concurrency" not in helm
    for workflow in (CI_WORKFLOW, ROLLBACK_WORKFLOW, TERRAFORM_WORKFLOW, HELM_WORKFLOW):
        text = workflow.read_text(encoding="utf-8")
        assert "azure_rollout_lease.py" in text
        assert "ROLLOUT_COORDINATION_STORAGE_ACCOUNT" in text
        assert "ROLLOUT_COORDINATION_CONTAINER" in text
    assert ci["jobs"]["deploy-backend"]["runs-on"] == (
        "${{ fromJSON(vars.PRODUCTION_RUNNER_LABELS) }}"
    )
    assert rollback["jobs"]["rollback"]["runs-on"] == (
        "${{ fromJSON(vars.PRODUCTION_RUNNER_LABELS) }}"
    )
    priority_job = rollback["jobs"]["publish-priority"]
    assert priority_job["runs-on"] == (
        "${{ fromJSON(vars.ROLLBACK_PRIORITY_RUNNER_LABELS) }}"
    )
    assert "environment" not in priority_job
    assert "needs" not in priority_job
    priority_names = [step.get("name") for step in priority_job["steps"]]
    assert priority_names == [
        None,
        "Azure Login for rollout coordination (OIDC)",
        "Publish and maintain emergency rollback priority",
    ]
    priority_script = _step_by_name(
        priority_job["steps"],
        "Publish and maintain emergency rollback priority",
    )["run"]
    assert "maintain-priority" in priority_script
    assert "--max-seconds 3300" in priority_script
    priority_login = _step_by_name(
        priority_job["steps"],
        "Azure Login for rollout coordination (OIDC)",
    )
    assert priority_login["with"]["client-id"] == (
        "${{ env.ROLLOUT_COORDINATION_CLIENT_ID }}"
    )
    assert rollback["env"]["ROLLOUT_COORDINATION_CLIENT_ID"] == (
        "${{ secrets.ROLLOUT_COORDINATION_CLIENT_ID }}"
    )
    assert helm["jobs"]["release"]["runs-on"] == (
        "${{ fromJSON(vars.PRODUCTION_RUNNER_LABELS) }}"
    )
    assert terraform["jobs"]["prod-apply"]["runs-on"] == (
        "${{ fromJSON(vars.PRODUCTION_RUNNER_LABELS) }}"
    )
    rollback_names = [step.get("name") for step in rollback["jobs"]["rollback"]["steps"]]
    assert rollback_names.index("Claim independently published emergency rollback priority") < rollback_names.index(
        "Wait boundedly for migration execution quiescence"
    ) < rollback_names.index("Acquire exclusive emergency rollout ownership")
    assert rollback_names.index("Acquire exclusive emergency rollout ownership") < rollback_names.index(
        "Reconfirm migration quiescence under exclusive ownership"
    ) < rollback_names.index("Shift traffic to rollback revision")
    backend_names = [step.get("name") for step in ci["jobs"]["deploy-backend"]["steps"]]
    assert backend_names.index("Validate rollout coordination inputs") < backend_names.index(
        "Azure Login (OIDC)"
    ) < backend_names.index("Acquire durable production rollout ownership")
    for checkpoint in (
        "Yield to emergency rollback after safe build checkpoint",
        "Yield to emergency rollback before bootstrap mutation",
        "Yield to emergency rollback before bridge traffic mutation",
        "Yield to emergency rollback before migration start boundary",
        "Yield to emergency rollback after migration quiescence",
        "Yield to emergency rollback before final traffic mutation",
        "Yield to emergency rollback before frontend mutation",
    ):
        assert checkpoint in backend_names
    migration_start = backend_names.index("Start exact-head production migration")
    migration_terminal = backend_names.index("Persist terminal migration execution state")
    assert migration_start < backend_names.index("Supervise exact-head production migration")
    assert backend_names.index("Supervise exact-head production migration") < migration_terminal
    assert not any(
        name and name.startswith("Yield to emergency rollback")
        for name in backend_names[migration_start + 1 : migration_terminal]
    )
    assert migration_terminal < backend_names.index(
        "Yield to emergency rollback after migration quiescence"
    )
    assert "Configure Static Web Apps API bridge settings" in backend_names
    assert "Deploy frontend under production mutation lock" in backend_names
    assert "Verify frontend under production mutation lock" in backend_names
    assert backend_names.index("Verify production deployment") < backend_names.index(
        "Download and verify previous frontend recovery bundle"
    )
    assert backend_names.index("Download and verify previous frontend recovery bundle") < backend_names.index(
        "Configure Static Web Apps API bridge settings"
    )
    assert backend_names.index("Configure Static Web Apps API bridge settings") < backend_names.index(
        "Deploy frontend under production mutation lock"
    )
    assert backend_names.index("Deploy frontend under production mutation lock") < backend_names.index(
        "Verify frontend under production mutation lock"
    )


def test_backend_image_and_schema_contract_are_immutable_and_fail_closed():
    workflow = _load(CI_WORKFLOW)
    deploy = workflow["jobs"]["deploy-backend"]
    capture = _step_by_name(deploy["steps"], "Capture immutable image and schema contract")["run"]
    green = _step_by_name(deploy["steps"], "Deploy green revision")["run"]
    provenance = _step_by_name(
        deploy["steps"],
        "Verify built image provenance labels and embedded schema contracts",
    )["run"]

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
    assert "gh attestation verify" in provenance
    assert "--signer-workflow" in provenance
    assert "--source-digest" in provenance
    assert "--deny-self-hosted-runners" in provenance
    assert "verify-attestation" in provenance
    assert "docker image inspect" in provenance
    assert "/app/release/schema-contract.json" in provenance
    assert "verify-image" in provenance
    workflow_text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "actions/attest-build-provenance@v3" in workflow_text
    assert "attestations: write" in workflow_text
    assert "--build-provenance final-build-provenance.json" in workflow_text
    assert "--build-provenance bridge-build-provenance.json" in workflow_text


def test_migration_and_bootstrap_failures_stop_before_live_revision_or_traffic_changes():
    workflow = _load(CI_WORKFLOW)
    deploy_steps = workflow["jobs"]["deploy-backend"]["steps"]
    names = [step.get("name") for step in deploy_steps]
    guarded_steps = (
        "Plan migration bootstrap (Phase A)",
        "Apply migration bootstrap (Phase A)",
        "Wait for migration identity, RBAC, and secret propagation",
        "Discover schema with same-identity database preflight",
        "Prepare exact-head production migration",
        "Start exact-head production migration",
        "Supervise exact-head production migration",
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
    capture = _step_by_name(steps, "Capture exact original production traffic")["run"]
    state = _step_by_name(steps, "Create branch-specific rollout state")["run"]
    explicit = _step_by_name(steps, "Make dynamic latest traffic explicit")["run"]
    bridge = _step_by_name(steps, "Stage schema bridge rollout script")["run"]
    green = _step_by_name(steps, "Deploy green revision")["run"]
    shift = _step_by_name(steps, "Shift traffic to green (100%)")["run"]
    verify_step = _step_by_name(steps, "Verify production deployment")
    verify = verify_step["run"]
    restore_step = _step_by_name(
        steps,
        "Recover exact schema-safe traffic after rollout failure",
    )
    restore = restore_step["run"]
    retain = _step_by_name(
        steps, "Deactivate superseded revisions after final evidence"
    )["run"]

    assert "blue-traffic-original.json" in capture
    assert "explicit-traffic" in capture
    assert "--container-app containerapp-before-rollout.json" in capture
    assert "az containerapp revision list" in capture
    assert "--all" in capture
    assert "--revisions revisions-before-rollout.json" in capture
    assert "eval " not in capture
    assert names.index("Capture exact original production traffic") < names.index(
        "Plan migration bootstrap (Phase A)"
    )
    assert "create-release-state" in state
    assert "--original-traffic" not in state
    assert "--baseline-traffic blue-traffic-manifest.json" in state
    failed_state_restore = _step_by_name(
        steps,
        "Restore original traffic if rollout state creation fails",
    )["run"]
    assert "--input blue-traffic-manifest.json" in failed_state_restore
    assert "--input blue-traffic-original.json" not in failed_state_restore
    assert "apply-traffic" in explicit
    assert "BRIDGE_WEIGHT" in bridge and '!= "0"' in bridge
    assert "BRIDGE_ROLE" in bridge
    assert "missing explicit release-role metadata" in bridge
    assert 'BRIDGE_IMAGE_REF' in bridge
    assert "required_secret in db-connection redis-url" in bridge
    assert "--secret-env DATABASE_URL=db-connection" in bridge
    assert "--secret-env REDIS_URL=redis-url" in bridge
    assert "--secret-env JWT_SECRET=jwt-secret" in bridge
    assert '.current_revision == $current' in bridge
    assert 'bridge_read_only' in bridge
    assert '"https://${BRIDGE_FQDN}/api/workspaces"' in bridge
    assert "-X POST" in bridge
    assert "retry-after: 30" in bridge
    assert "write-release-manifest" in bridge
    assert "--required-role bridge" in bridge
    assert "GREEN_WEIGHT" in green and '!= "0"' in green
    assert "pre-green-traffic-manifest.json" in green
    smoke = _step_by_name(steps, "Smoke test green revision")["run"]
    assert "does not identify as the final release role" in smoke
    assert ".minimum_revision == $minimum" in smoke
    assert ".migration_target_revision == $target" in smoke
    assert "pre-shift-traffic-manifest.json" in shift
    assert "green-target-traffic-manifest.json" in shift
    assert "apply-traffic" in shift
    assert verify_step["id"] == "verify_production"
    assert "health_gate.sh" in verify
    assert "always()" in restore_step["if"]
    assert "steps.rollout_state.outcome == 'success'" in restore_step["if"]
    assert "steps.verify_production.outcome != 'success'" in restore_step["if"]
    assert "recover-release" in restore
    assert "rollout-recovery-evidence.json" in restore
    assert "RESTORE_STATUS" in restore
    assert restore.index("recover-release") < restore.index("az containerapp revision show")
    assert "eval " not in restore
    assert "--field branch" in retain
    assert "ROLLBACK_REVISIONS" in retain
    assert "Migration bridge is recovery-only" in retain
    workflow_text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "BRIDGE_BASE_IMAGE=${{ env.ACR_LOGIN_SERVER }}/archmorph-api@${{ steps.build_backend.outputs.digest }}" in workflow_text
    assert "backend/bridge_overlay/Dockerfile" in workflow_text
    assert "context: ./backend" in workflow_text
    assert "archmorph-api-bridge@${{ steps.build_bridge.outputs.digest }}" in workflow_text
    detect = _step_by_name(steps, "Discover schema with same-identity database preflight")["run"]
    resolve = _step_by_name(steps, "Resolve verified bridge for discovered schema")["run"]
    route_bridge = _step_by_name(
        steps,
        "Route production to verified bridge before migration",
    )["run"]
    assert "--accept-current 013" in detect
    assert "/api/schema-compatibility" in detect
    assert "Stage signed bridge reuse script" not in names
    assert "reuse-signed-bridge.sh" not in CI_WORKFLOW.read_text(encoding="utf-8")
    assert "BRIDGE_REVISION=" in resolve
    assert '[ "$CURRENT_SCHEMA_REVISION" = "013" ]' in resolve
    assert "export CURRENT_SCHEMA_REVISION" in resolve
    assert "pre-green-traffic-manifest.json" in route_bridge
    assert "apply-traffic" in route_bridge
    assert '.release_role == "bridge"' in route_bridge
    assert "routed-bridge-health.json" in route_bridge
    assert "routed-bridge-write-denial.json" in route_bridge
    assert '.status == "healthy"' in route_bridge
    assert 'Routine schema-${EXPECTED_ALEMBIC_HEAD} release preserves current production traffic' in resolve
    assert "set-bridge" in resolve
    final = _step_by_name(steps, "Create signed immutable final release evidence")["run"]
    assert "final-release-manifest.json" in final
    assert "--role final" in final
    assert "--schema-contract backend/schema-contract.json" in final
    assert "--observed-schema" in final
    assert "--run-attempt" in final
    assert "verify-runtime-compatibility" in final
    assert "verify-revision-target" in final
    assemble = _step_by_name(steps, "Assemble complete backend final release evidence")[
        "run"
    ]
    assert "final-release-manifest.json" in assemble
    assert "blue-traffic-original.json" in assemble
    assert "blue-traffic-manifest.json" in assemble


def test_frontend_waits_for_backend_and_has_previous_artifact_rollback():
    workflow = _load(CI_WORKFLOW)
    backend = workflow["jobs"]["deploy-backend"]
    steps = backend["steps"]
    download = _step_by_name(steps, "Download and verify previous frontend recovery bundle")["run"]
    require = _step_by_name(steps, "Require verified frontend recovery before mutation")["run"]
    deploy = _step_by_name(steps, "Deploy frontend under production mutation lock")
    verify = _step_by_name(steps, "Verify frontend under production mutation lock")
    restore = _step_by_name(
        steps,
        "Restore frontend settings and artifact after any mutation failure",
    )
    assert "gh run download" in download
    assert "frontend-recovery-bundle" in download
    assert "frontend-dist" in download
    assert "frontend_release.py verify" in download
    assert "No successful prior frontend artifact exists" in download
    assert "verified-manifest.json" in require
    assert deploy["id"] == "deploy_frontend_locked"
    assert verify["id"] == "verify_frontend_locked"
    assert "curl -fsS" in verify["run"]
    assert "always()" in restore["if"]
    assert "capture_swa_settings" in restore["if"]
    assert "swa-mutation-attempted" in restore["if"]
    assert "--method put" in restore["run"]
    assert "@frontend/live-settings-before-mutation.json" in restore["run"]
    assert "restored-settings.json" in restore["run"]
    assert "cmp frontend/expected-settings.json frontend/actual-settings.json" in restore["run"]
    assert "RESTORE_IMAGE" in restore["run"]
    assert "INPUT_API_LOCATION=/api" in restore["run"]
    assert "rollback-dist/dist:/app:ro" in restore["run"]
    assert "rollback-dist/api:/api:ro" in restore["run"]
    assert backend["concurrency"]["group"] == "production-backend-rollout"


def test_migration_alerts_use_action_group_and_explicit_platform_owner():
    terraform = MAIN_TERRAFORM.read_text(encoding="utf-8")
    outputs = (REPO_ROOT / "infra" / "outputs.tf").read_text(encoding="utf-8")
    assert 'resource "azurerm_monitor_scheduled_query_rules_alert_v2" "migration_job_failure"' in terraform
    assert 'resource "azurerm_monitor_scheduled_query_rules_alert_v2" "migration_job_timeout"' in terraform
    assert 'resource "azurerm_monitor_scheduled_query_rules_alert_v2" "migration_missing_evidence"' in terraform
    assert 'resource "azurerm_monitor_scheduled_query_rules_alert_v2" "bridge_customer_degraded"' in terraform
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
    assert "bridge_customer_degraded" in terraform
    assert "azurerm_monitor_action_group.critical.id" in terraform
    assert 'owner = "platform-engineering"' in terraform
    for name in (
        "application_insights_resource_id",
        "migration_failure_alert_id",
        "migration_timeout_alert_id",
        "migration_missing_evidence_alert_id",
        "bridge_customer_degraded_alert_id",
        "critical_action_group_id",
    ):
        assert f'output "{name}"' in outputs


def test_reviewed_migration_alert_specs_match_terraform_exactly():
    terraform = MAIN_TERRAFORM.read_text(encoding="utf-8")
    specifications = json.loads(MIGRATION_ALERT_SPECS.read_text(encoding="utf-8"))[
        "alerts"
    ]
    resources = {
        "failure": "migration_job_failure",
        "timeout": "migration_job_timeout",
        "missing_evidence": "migration_missing_evidence",
        "customer_degraded": "bridge_customer_degraded",
    }

    for role, resource_name in resources.items():
        block = _terraform_alert_block(terraform, resource_name)
        specification = specifications[role]
        criteria = specification["criteria"]
        periods = criteria["failing_periods"]
        query = re.search(r"query\s*=\s*<<-KQL\n(.*?)\n\s*KQL", block, re.DOTALL)
        assert query is not None
        assert _canonical_kql(query.group(1)) == _canonical_kql(specification["query"])
        assert re.search(rf"severity\s*=\s*{specification['severity']}\b", block)
        assert re.search(
            rf"enabled\s*=\s*{str(specification['enabled']).lower()}\b", block
        )
        assert 'scopes               = [azurerm_application_insights.main.id]' in block
        assert (
            f'evaluation_frequency = "{specification["evaluation_frequency"]}"'
            in block
        )
        assert f'window_duration      = "{specification["window_duration"]}"' in block
        assert (
            f'time_aggregation_method = "{criteria["time_aggregation_method"]}"'
            in block
        )
        assert f'operator                = "{criteria["operator"]}"' in block
        assert re.search(rf"threshold\s*=\s*{criteria['threshold']}\b", block)
        assert (
            f'metric_measure_column   = "{criteria["metric_measure_column"]}"'
            in block
        )
        assert re.search(
            rf"minimum_failing_periods_to_trigger_alert\s*=\s*"
            rf"{periods['minimum_failing_periods_to_trigger_alert']}\b",
            block,
        )
        assert re.search(
            rf"number_of_evaluation_periods\s*=\s*"
            rf"{periods['number_of_evaluation_periods']}\b",
            block,
        )
        assert "action_groups = [azurerm_monitor_action_group.critical.id]" in block


def test_rollback_health_verification_uses_authenticated_api_health():
    workflow = _load(ROLLBACK_WORKFLOW)
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    assert "traffic_percentage" not in inputs
    assert inputs["release_run_id"]["required"] is False
    assert inputs["release_run_attempt"]["required"] is False
    assert inputs["signed_final_manifest_base64"]["required"] is False
    assert workflow["env"]["ARCHMORPH_API_KEY"] == "${{ secrets.ARCHMORPH_API_KEY }}"
    assert workflow["env"]["ADMIN_KEY"] == "${{ secrets.ADMIN_KEY }}"
    assert workflow["env"]["MIGRATION_JOB_NAME"] == "${{ secrets.MIGRATION_JOB_NAME }}"
    assert workflow["env"]["RELEASE_MANIFEST_HMAC_KEY"] == (
        "${{ secrets.RELEASE_MANIFEST_HMAC_KEY }}"
    )
    assert workflow["env"]["RELEASE_WORKFLOW_NAME"] == "CI/CD"
    assert workflow["permissions"]["actions"] == "read"
    assert workflow["jobs"]["rollback"]["environment"] == "production"

    steps = workflow["jobs"]["rollback"]["steps"]
    assert "concurrency" not in workflow["jobs"]["rollback"]
    compatibility_step = _step_by_name(steps, "Verify target schema compatibility before activation")
    compatibility_script = compatibility_step["run"]
    step_names = [step.get("name") for step in steps]
    quiescence = _step_by_name(
        steps,
        "Wait boundedly for migration execution quiescence",
    )["run"]
    assert "MIGRATION_JOB_NAME is required" in quiescence
    assert "az containerapp job list" in quiescence
    assert "identity is absent or ambiguous" in quiescence
    assert "az containerapp job execution list" in quiescence
    assert "Unknown" in quiescence
    assert "within five minutes" in quiescence
    priority = _step_by_name(
        steps,
        "Claim independently published emergency rollback priority",
    )["run"]
    ownership = _step_by_name(steps, "Acquire exclusive emergency rollout ownership")["run"]
    assert "claim-intent" in priority
    assert "heartbeat --mode rollback" in priority
    assert "wait-turn" in ownership
    assert "acquire --mode rollback" in ownership
    assert step_names.index(
        "Claim independently published emergency rollback priority"
    ) < step_names.index("Wait boundedly for migration execution quiescence")
    assert step_names.index(
        "Wait boundedly for migration execution quiescence"
    ) < step_names.index("Acquire exclusive emergency rollout ownership")
    assert step_names.index("Reconfirm migration quiescence under exclusive ownership") < step_names.index(
        "Verify target schema compatibility before activation"
    )
    assert "verify-revision-target" in compatibility_script
    assert "--require-zero-traffic" in compatibility_script
    assert "verify-runtime-compatibility" in compatibility_script
    assert "/api/schema-compatibility" in compatibility_script
    assert "traffic remains unchanged" in compatibility_script
    assert "Rollback target supports current schema" in compatibility_script
    assert "activating it at zero traffic for schema preflight" in compatibility_script
    assert "az containerapp revision activate" in compatibility_script
    assert "az containerapp revision deactivate" in compatibility_script
    assert "az containerapp ingress traffic set" not in compatibility_script
    assert step_names.index("Capture exact prior traffic and rollback target") < step_names.index(
        "Verify target schema compatibility before activation"
    )
    assert step_names.index("Verify target schema compatibility before activation") < step_names.index(
        "Shift traffic to rollback revision"
    )
    assert "Activate rollback revision" not in step_names
    resolve = _step_by_name(steps, "Resolve explicit signed final rollback target")["run"]
    assert "RELEASE_MANIFEST_HMAC_KEY must contain at least 32 bytes" in resolve
    assert "backend-release-evidence-${RELEASE_RUN_ID}-${RELEASE_RUN_ATTEMPT}" in resolve
    assert (
        'actions/runs/${RELEASE_RUN_ID}/attempts/${RELEASE_RUN_ATTEMPT}' in resolve
    )
    assert '.run_attempt == $attempt' in resolve
    assert '.conclusion == "success"' in resolve
    assert "SIGNED_SOURCE_SHA" in resolve
    assert "SELECTED_SOURCE_SHA" in resolve
    assert "signed_final_manifest_base64" in resolve
    assert "unavailable or expired" in resolve
    assert "final-release-manifest.json" in resolve
    assert "--required-role final" in resolve
    assert "--expected-repository" in resolve
    assert "--expected-workflow" in resolve
    assert "--expected-run-attempt" in resolve
    verify_step = _step_by_name(steps, "Verify rollback health")
    run_script = verify_step["run"]

    assert 'HEALTH_API_KEY="${ARCHMORPH_API_KEY:-${ADMIN_KEY:-}}"' in run_script
    assert 'X-API-Key: ${HEALTH_API_KEY}' in run_script
    assert '"${BASE}/api/health"' in run_script
    assert '"${BASE}/api/schema-compatibility"' in run_script
    assert "verify-runtime-compatibility" in run_script
    assert "verify-revision-target" in run_script
    assert "--required-role final" in run_script
    assert '[ "$HTTP_CODE" = "200" ]' in run_script
    assert ".status == \"healthy\"" in run_script
    shift = _step_by_name(steps, "Shift traffic to rollback revision")["run"]
    assert "rollback-target-traffic-manifest.json" in shift
    assert "apply-traffic" in shift
    restore = _step_by_name(steps, "Restore exact prior traffic after rollback failure")
    capture = _step_by_name(steps, "Capture exact prior traffic and rollback target")["run"]
    assert "explicit-traffic" in capture
    assert "--container-app containerapp-before-rollback.json" in capture
    assert "--revisions revisions-before-rollback.json" in capture
    assert "always()" in restore["if"]
    assert "rollback-shift-attempted" in restore["if"]
    assert "verify_rollback.outcome != 'success'" in restore["if"]
    assert "apply-traffic" in restore["run"]
    assert "RESTORE_STATUS" in restore["run"]


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
