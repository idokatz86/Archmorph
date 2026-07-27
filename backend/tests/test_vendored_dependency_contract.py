import gzip
import json
from pathlib import Path
import subprocess
import sys

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_frontend_uses_immutable_compatibility_archive_without_install_mutation():
    package = json.loads((REPO_ROOT / "frontend" / "package.json").read_text())

    assert "postinstall" not in package["scripts"]
    assert package["scripts"]["test:security-packages"].endswith(
        "scripts/security-packages.check.mjs"
    )
    assert package["devDependencies"]["brace-expansion"] == (
        "file:../vendor/brace-expansion-5.0.8-compat.tgz"
    )
    assert package["overrides"]["brace-expansion"] == "$brace-expansion"


def test_required_frontend_ci_uses_frozen_installs_and_security_behavior_checks():
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    )

    frontend_steps = workflow["jobs"]["frontend-build"]["steps"]
    install = next(
        step for step in frontend_steps if step.get("name") == "Install dependencies"
    )
    verify = next(
        step
        for step in frontend_steps
        if step.get("name") == "Verify vendored dependency behavior"
    )
    assert install["run"] == "npm ci --no-fund --no-audit"
    assert verify["run"] == "npm run test:security-packages"

    drift_steps = workflow["jobs"]["openapi-client-drift"]["steps"]
    drift_install = next(
        step
        for step in drift_steps
        if step.get("name") == "Install frontend dependencies"
    )
    assert drift_install["run"] == "npm ci --no-fund --no-audit"


def test_compose_frontend_matches_node_baseline_and_mounts_vendor_read_only():
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())
    frontend = compose["services"]["frontend"]

    assert frontend["image"] == "node:22.13.0-slim"
    assert "./vendor:/vendor:ro" in frontend["volumes"]
    assert frontend["command"][2].startswith("npm ci &&")


def test_compatibility_archive_check_rejects_different_gzip_bytes(tmp_path):
    archive = REPO_ROOT / "vendor" / "brace-expansion-5.0.8-compat.tgz"
    repacked = tmp_path / archive.name
    repacked.write_bytes(
        gzip.compress(gzip.decompress(archive.read_bytes()), compresslevel=1, mtime=1)
    )
    assert repacked.read_bytes() != archive.read_bytes()

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "build_brace_expansion_compat.py"),
            "--check",
            "--output",
            str(repacked),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode != 0
    assert "not the byte-reproducible compatibility archive" in result.stderr
