from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "terraform-prod.yml"


def _step_by_name(steps: list[dict], name: str) -> dict:
    for step in steps:
        if step.get("name") == name:
            return step
    raise AssertionError(f'Expected workflow step "{name}"')


def test_prod_plan_encrypts_binary_plan_and_uploads_integrity_metadata():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    plan_steps = workflow["jobs"]["prod-plan"]["steps"]

    collect_step = _step_by_name(plan_steps, "Collect plan integrity metadata")
    collect_script = collect_step["run"]
    assert "hashlib.sha256" in collect_script
    assert 'Path("tfplan.sha256").write_text' in collect_script
    assert "terraform state pull > tfstate.snapshot.json" in collect_script
    assert "provider_lock_sha256" in collect_script

    encrypt_step = _step_by_name(plan_steps, "Encrypt reviewed production plan bundle")
    encrypt_script = encrypt_step["run"]
    assert "TFPLAN_ARTIFACT_PASSPHRASE" in encrypt_step["env"]
    assert "tar -czf prod-reviewed-plan.tar.gz" in encrypt_script
    assert "openssl enc -aes-256-cbc -pbkdf2 -salt" in encrypt_script
    assert "tfplan" in encrypt_script
    assert ".terraform.lock.hcl" in encrypt_script

    upload_steps = [
        step
        for step in plan_steps
        if step.get("name") == "Upload reviewed production plan artifact"
        and step.get("uses") == "actions/upload-artifact@v7"
    ]
    assert len(upload_steps) == 1
    upload_step = upload_steps[0]
    upload_paths = upload_step["with"]["path"]
    assert upload_paths == "infra/prod-reviewed-plan.tar.gz.enc"
    assert upload_step["with"]["retention-days"] == 1

    render_step = _step_by_name(plan_steps, "Render plan for encrypted review bundle")
    assert render_step["run"] == "terraform show -no-color tfplan > tfplan.txt"
    assert "tfplan.txt" in encrypt_script
    assert "tee tfplan.txt" not in WORKFLOW.read_text(encoding="utf-8")


def test_prod_plan_preflights_remote_state_blob_rbac_before_init():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    plan_steps = workflow["jobs"]["prod-plan"]["steps"]

    preflight_step = _step_by_name(plan_steps, "Preflight: verify remote-state Blob data-plane RBAC")
    preflight_script = preflight_step["run"]
    assert "az storage blob list" in preflight_script
    assert "--auth-mode login" in preflight_script
    assert "Storage Blob Data Contributor" in preflight_script
    assert "private backend scope" in preflight_script
    assert "STATE_CONTAINER_SCOPE" not in preflight_script
    assert "STATE_STORAGE_SCOPE" not in preflight_script
    assert "sed 's/^/az storage blob list: /'" not in preflight_script
    assert 'STATE_RESOURCE_GROUP="${TFSTATE_RESOURCE_GROUP:-}"' in preflight_script
    assert 'STATE_STORAGE_ACCOUNT="${TFSTATE_STORAGE_ACCOUNT:-}"' in preflight_script
    assert "Required private Terraform backend setting" in preflight_script
    assert "BACKEND_CONFIG_FILE" not in preflight_script

    init_step = _step_by_name(plan_steps, "Terraform Init")
    assert '-backend-config="resource_group_name=${TFSTATE_RESOURCE_GROUP}"' in init_step["run"]
    assert '-backend-config="storage_account_name=${TFSTATE_STORAGE_ACCOUNT}"' in init_step["run"]
    assert '-backend-config="container_name=${TFSTATE_CONTAINER}"' in init_step["run"]
    assert '-backend-config="key=${TFSTATE_KEY}"' in init_step["run"]

    preflight_index = plan_steps.index(preflight_step)
    login_index = plan_steps.index(_step_by_name(plan_steps, "Azure Login (OIDC)"))
    init_index = plan_steps.index(_step_by_name(plan_steps, "Terraform Init"))
    assert login_index < preflight_index
    assert preflight_index < init_index


def test_prod_plan_preflights_state_stack_contract_before_plan():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    plan_steps = workflow["jobs"]["prod-plan"]["steps"]

    stack_preflight_step = _step_by_name(plan_steps, "Preflight: verify Terraform state stack contract")
    stack_preflight_script = stack_preflight_step["run"]
    assert "STACK_ENVIRONMENT=\"${TF_VAR_resource_group_environment:-${TF_VAR_environment}}\"" in stack_preflight_script
    assert "EXPECTED_RESOURCE_GROUP=\"archmorph-rg-${STACK_ENVIRONMENT}\"" in stack_preflight_script
    assert "az group exists" in stack_preflight_script
    assert "terraform state pull" in stack_preflight_script
    assert "azurerm_resource_group" in stack_preflight_script
    assert "Refusing to plan because this would replace the stack" in stack_preflight_script

    init_index = plan_steps.index(_step_by_name(plan_steps, "Terraform Init"))
    stack_preflight_index = plan_steps.index(stack_preflight_step)
    plan_index = plan_steps.index(_step_by_name(plan_steps, "Terraform Plan (production)"))
    assert init_index < stack_preflight_index < plan_index


def test_prod_plan_blocks_existing_live_resource_creates_until_imported():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    plan_steps = workflow["jobs"]["prod-plan"]["steps"]

    adoption_step = _step_by_name(
        plan_steps,
        "Preflight: block unsafe live-resource creates and review PostgreSQL firewall-rule destroy",
    )
    adoption_script = adoption_step["run"]
    assert "terraform show -json tfplan > tfplan.json" in adoption_script
    assert "terraform state pull > tfstate.snapshot.json" in adoption_script
    assert 'STACK_ENVIRONMENT="${TF_VAR_resource_group_environment:-${TF_VAR_environment}}"' in adoption_script
    assert '"azurerm_container_app_environment.main"' in adoption_script
    assert '"azurerm_container_app.backend"' in adoption_script
    assert '"azurerm_user_assigned_identity.container_app"' in adoption_script
    assert '"azurerm_storage_account.main"' in adoption_script
    assert '"azurerm_redis_cache.main"' in adoption_script
    assert 'redis_name = os.environ.get("TF_VAR_redis_name_override") or f"archmorph-redis-{name_suffix}"' in adoption_script
    assert '"legacy_resource_ids": [' not in adoption_script
    assert "TF_VAR_redis_name_override must identify any existing cache" in adoption_script
    assert "Do not import blindly" in adoption_script
    assert '"azurerm_static_web_app.frontend"' in adoption_script
    assert '"resource"' in adoption_script
    assert '"show"' in adoption_script
    assert "Import with:" not in adoption_script
    assert "conflicts with existing live resource" not in adoption_script
    assert "existing resource adoption gap(s) detected" in adoption_script
    assert "Full resource inventory is available only in the encrypted reviewed-plan bundle" in adoption_script
    assert "Terraform live-resource adoption preflight found no known existing resources planned as creates." in adoption_script
    assert "GITHUB_STEP_SUMMARY" in adoption_script

    show_plan_index = plan_steps.index(_step_by_name(plan_steps, "Render plan for encrypted review bundle"))
    adoption_index = plan_steps.index(adoption_step)
    collect_index = plan_steps.index(_step_by_name(plan_steps, "Collect plan integrity metadata"))
    assert show_plan_index < adoption_index < collect_index


def test_prod_plan_reviews_legacy_postgresql_firewall_rule_destroy_before_artifact_upload():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    plan_steps = workflow["jobs"]["prod-plan"]["steps"]

    adoption_step = _step_by_name(
        plan_steps,
        "Preflight: block unsafe live-resource creates and review PostgreSQL firewall-rule destroy",
    )
    adoption_script = adoption_step["run"]
    assert '"azurerm_postgresql_flexible_server_firewall_rule.allow_azure[0]"' in adoption_script
    assert '"postgres"' in adoption_script
    assert '"flexible-server"' in adoption_script
    assert '"show"' in adoption_script
    assert '"network.publicNetworkAccess"' in adoption_script
    assert "AllowAzureServices firewall rule" in adoption_script
    assert "publicNetworkAccess is Disabled" in adoption_script


def test_prod_plan_diagnoses_oidc_principal_without_blocking_init():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    plan_steps = workflow["jobs"]["prod-plan"]["steps"]

    diagnostic_step = _step_by_name(plan_steps, "Diagnose Azure OIDC principal")
    diagnostic_script = diagnostic_step["run"]
    assert "az account show --query user.name" in diagnostic_script
    assert "az ad sp show" in diagnostic_script
    assert "objectId:id" in diagnostic_script
    assert "AZURE_CLIENT_ID" not in diagnostic_script
    assert "|| true" in diagnostic_script

    login_index = plan_steps.index(_step_by_name(plan_steps, "Azure Login (OIDC)"))
    diagnostic_index = plan_steps.index(diagnostic_step)
    preflight_index = plan_steps.index(_step_by_name(plan_steps, "Preflight: verify remote-state Blob data-plane RBAC"))
    init_index = plan_steps.index(_step_by_name(plan_steps, "Terraform Init"))
    assert login_index < diagnostic_index < preflight_index < init_index


def test_prod_workflow_supplies_legacy_openai_secret_variable():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    env = workflow["env"]

    assert env["TF_VAR_preserve_legacy_openai_key"] is True
    assert env["TF_VAR_openai_api_key"] == "${{ secrets.AZURE_OPENAI_API_KEY }}"


def test_prod_workflow_uses_private_prod_stack_inventory():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    env = workflow["env"]

    assert env["TF_VAR_environment"] == "prod"
    assert env["TFSTATE_RESOURCE_GROUP"] == "${{ secrets.TFSTATE_RESOURCE_GROUP }}"
    assert env["TFSTATE_STORAGE_ACCOUNT"] == "${{ secrets.TFSTATE_STORAGE_ACCOUNT }}"
    assert env["TFSTATE_CONTAINER"] == "${{ secrets.TFSTATE_CONTAINER }}"
    assert env["TFSTATE_KEY"] == "${{ secrets.TFSTATE_KEY }}"
    assert env["TF_VAR_resource_group_environment"] == "${{ secrets.TF_RESOURCE_GROUP_ENVIRONMENT }}"
    assert env["TF_VAR_enable_production_infra_hardening"] is False
    assert env["TF_VAR_redis_name_override"] == "${{ secrets.TF_REDIS_NAME_OVERRIDE }}"
    assert env["TF_VAR_workbook_id_override"] == "${{ secrets.TF_WORKBOOK_ID }}"


def test_prod_apply_downloads_and_applies_reviewed_plan_only():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    apply_steps = workflow["jobs"]["prod-apply"]["steps"]

    download_step = _step_by_name(apply_steps, "Download reviewed production plan artifact")
    assert download_step["uses"] == "actions/download-artifact@v8"
    assert download_step["with"]["name"] == "prod-reviewed-plan"
    assert download_step["with"]["path"] == "infra/reviewed-plan"

    decrypt_step = _step_by_name(apply_steps, "Decrypt reviewed production plan bundle")
    decrypt_script = decrypt_step["run"]
    assert "TFPLAN_ARTIFACT_PASSPHRASE" in decrypt_step["env"]
    assert "openssl enc -d -aes-256-cbc -pbkdf2" in decrypt_script
    assert "tar -xzf reviewed-plan/prod-reviewed-plan.tar.gz -C reviewed-plan" in decrypt_script
    assert "cp reviewed-plan/.terraform.lock.hcl .terraform.lock.hcl" in decrypt_script

    decrypt_index = apply_steps.index(decrypt_step)
    init_step = _step_by_name(apply_steps, "Terraform Init")
    init_index = apply_steps.index(init_step)
    assert decrypt_index < init_index
    assert '-backend-config="resource_group_name=${TFSTATE_RESOURCE_GROUP}"' in init_step["run"]
    assert '-backend-config="storage_account_name=${TFSTATE_STORAGE_ACCOUNT}"' in init_step["run"]

    verify_step = _step_by_name(apply_steps, "Verify reviewed plan artifact integrity and assumptions")
    verify_script = verify_step["run"]
    assert 'Path("reviewed-plan/plan-metadata.json")' in verify_script
    assert 'Path("reviewed-plan/tfplan")' in verify_script
    assert 'Path(".terraform.lock.hcl")' in verify_script
    assert 'metadata.get("plan_commit_sha") != os.environ.get("GITHUB_SHA")' in verify_script
    assert 'metadata.get("provider_lock_sha256")' in verify_script
    assert 'state.get("serial") != metadata.get("state_serial")' in verify_script

    apply_step = _step_by_name(apply_steps, "Terraform Apply (reviewed plan artifact)")
    assert apply_step["run"] == "terraform apply -input=false reviewed-plan/tfplan"

    approval_step = _step_by_name(apply_steps, "Record approval metadata")
    assert '"workflow_actor": os.environ["GITHUB_ACTOR"]' in approval_step["run"]
    assert "approved_by" not in approval_step["run"]

    assert all(step.get("name") != "Terraform Plan (post-approval)" for step in apply_steps)
