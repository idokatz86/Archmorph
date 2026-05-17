from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
SECURITY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "security.yml"


def test_dependency_audit_covers_root_and_frontend_npm_manifests():
    workflow = yaml.safe_load(SECURITY_WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["dependency-audit"]["steps"]

    setup_node = next(step for step in steps if step.get("name") == "Setup Node")
    assert "package-lock.json" in setup_node["with"]["cache-dependency-path"]
    assert "frontend/package-lock.json" in setup_node["with"]["cache-dependency-path"]

    root_audit = next(step for step in steps if step.get("name") == "Run root npm audit")
    assert "PUPPETEER_SKIP_DOWNLOAD=1 npm ci --no-audit --no-fund" in root_audit["run"]
    assert "npm audit --audit-level=high" in root_audit["run"]

    frontend_audit = next(step for step in steps if step.get("name") == "Run npm audit")
    assert frontend_audit["working-directory"] == "frontend"
    assert "npm ci --no-audit --no-fund" in frontend_audit["run"]
    assert "npm audit --audit-level=high" in frontend_audit["run"]