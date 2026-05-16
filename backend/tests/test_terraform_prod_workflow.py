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
    assert "infra/prod-reviewed-plan.tar.gz.enc" in upload_paths
    assert "infra/tfplan.txt" in upload_paths
    assert "infra/tfplan\n" not in upload_paths
    assert "infra/.terraform.lock.hcl" not in upload_paths
    assert upload_step["with"]["retention-days"] == 1


def test_prod_plan_preflights_remote_state_blob_rbac_before_init():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    plan_steps = workflow["jobs"]["prod-plan"]["steps"]

    preflight_step = _step_by_name(plan_steps, "Preflight: verify remote-state Blob data-plane RBAC")
    preflight_script = preflight_step["run"]
    assert "az storage blob list" in preflight_script
    assert "--auth-mode login" in preflight_script
    assert "Storage Blob Data Contributor" in preflight_script
    assert "Least-privilege scope (container)" in preflight_script
    assert "AZURE_CLIENT_ID=${ARM_CLIENT_ID}" in preflight_script

    preflight_index = plan_steps.index(preflight_step)
    login_index = plan_steps.index(_step_by_name(plan_steps, "Azure Login (OIDC)"))
    init_index = plan_steps.index(_step_by_name(plan_steps, "Terraform Init"))
    assert login_index < preflight_index
    assert preflight_index < init_index


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
    init_index = apply_steps.index(_step_by_name(apply_steps, "Terraform Init"))
    assert decrypt_index < init_index

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
