from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "terraform-prod.yml"


def _step_by_name(steps: list[dict], name: str) -> dict:
    for step in steps:
        if step.get("name") == name:
            return step
    raise AssertionError(f'Expected workflow step "{name}"')


def test_prod_plan_uploads_binary_plan_and_integrity_metadata():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    plan_steps = workflow["jobs"]["prod-plan"]["steps"]

    collect_step = _step_by_name(plan_steps, "Collect plan integrity metadata")
    collect_script = collect_step["run"]
    assert "sha256sum tfplan" in collect_script
    assert "terraform state pull > tfstate.snapshot.json" in collect_script
    assert "provider_lock_sha256" in collect_script

    upload_step = _step_by_name(plan_steps, "Upload reviewed production plan artifact")
    upload_paths = upload_step["with"]["path"]
    assert "infra/tfplan\n" in upload_paths
    assert "infra/tfplan.sha256" in upload_paths
    assert "infra/.terraform.lock.hcl" in upload_paths
    assert "infra/plan-metadata.json" in upload_paths


def test_prod_apply_downloads_and_applies_reviewed_plan_only():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    apply_steps = workflow["jobs"]["prod-apply"]["steps"]

    download_step = _step_by_name(apply_steps, "Download reviewed production plan artifact")
    assert download_step["uses"] == "actions/download-artifact@v8"
    assert download_step["with"]["name"] == "prod-reviewed-plan"

    verify_step = _step_by_name(apply_steps, "Verify reviewed plan artifact integrity and assumptions")
    verify_script = verify_step["run"]
    assert 'metadata.get("plan_commit_sha") != os.environ.get("GITHUB_SHA")' in verify_script
    assert 'metadata.get("provider_lock_sha256")' in verify_script
    assert 'state.get("serial") != metadata.get("state_serial")' in verify_script

    apply_step = _step_by_name(apply_steps, "Terraform Apply (reviewed plan artifact)")
    assert apply_step["run"] == "terraform apply -input=false tfplan"

    assert all(step.get("name") != "Terraform Plan (post-approval)" for step in apply_steps)
