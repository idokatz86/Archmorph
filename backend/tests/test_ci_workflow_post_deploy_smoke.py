from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_post_deploy_smoke_passes_health_api_key_from_admin_secret():
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))

    steps = workflow["jobs"]["post-deploy-smoke"]["steps"]
    smoke_step = next(step for step in steps if step.get("name") == "Run deployed app smoke checks")

    assert smoke_step["env"]["HEALTH_API_KEY"] == "${{ secrets.ADMIN_KEY }}"
