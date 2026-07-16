import json
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DEPENDABOT_CONFIG = REPO_ROOT / ".github" / "dependabot.yml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SECURITY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "security.yml"
ROOT_PACKAGE = REPO_ROOT / "package.json"
FRONTEND_PACKAGE = REPO_ROOT / "frontend" / "package.json"
FRONTEND_LOCK = REPO_ROOT / "frontend" / "package-lock.json"
NODE_VERSION = REPO_ROOT / ".nvmrc"


def _frontend_npm_update() -> dict:
    config = yaml.safe_load(DEPENDABOT_CONFIG.read_text(encoding="utf-8"))
    for update in config["updates"]:
        if update.get("package-ecosystem") == "npm" and update.get("directory") == "/frontend":
            return update
    raise AssertionError("Expected frontend npm Dependabot update config")


def _backend_pip_update() -> dict:
    config = yaml.safe_load(DEPENDABOT_CONFIG.read_text(encoding="utf-8"))
    for update in config["updates"]:
        if update.get("package-ecosystem") == "pip" and update.get("directory") == "/backend":
            return update
    raise AssertionError("Expected backend pip Dependabot update config")


def _all_updates() -> list[dict]:
    config = yaml.safe_load(DEPENDABOT_CONFIG.read_text(encoding="utf-8"))
    return config["updates"]


def test_dependabot_config_does_not_define_empty_registries():
    config = yaml.safe_load(DEPENDABOT_CONFIG.read_text(encoding="utf-8"))

    assert config.get("registries", {}) is not None


def test_frontend_dependabot_ignores_only_eslint_10_major_until_react_plugin_supports_it():
    update = _frontend_npm_update()
    eslint_rules = [rule for rule in update.get("ignore", []) if rule.get("dependency-name") == "eslint"]

    assert eslint_rules == [{"dependency-name": "eslint", "versions": ["10.x"]}]
    assert "update-types" not in eslint_rules[0]


def test_backend_security_update_group_has_required_patterns_selector():
    update = _backend_pip_update()
    security_group = update["groups"]["security"]

    assert security_group["applies-to"] == "security-updates"
    assert security_group["patterns"] == ["*"]


def test_dependabot_commit_prefixes_satisfy_semantic_pr_title_policy():
    allowed_types = {"feat", "fix", "chore", "docs", "style", "refactor", "perf", "test", "build", "ci", "revert"}

    for update in _all_updates():
        prefix = update.get("commit-message", {}).get("prefix", "")
        semantic_type = prefix.split("(", 1)[0]
        assert semantic_type in allowed_types, (
            f"Dependabot prefix {prefix!r} for {update['package-ecosystem']} "
            "will fail the semantic pull-request title gate"
        )


def test_node_runtime_contract_matches_current_toolchain_engines():
    root_package = json.loads(ROOT_PACKAGE.read_text(encoding="utf-8"))
    frontend_package = json.loads(FRONTEND_PACKAGE.read_text(encoding="utf-8"))
    node_version = NODE_VERSION.read_text(encoding="utf-8").strip()

    assert node_version == "22.13.0"
    assert root_package["engines"]["node"] == ">=22.13.0"
    assert frontend_package["engines"]["node"] == ">=22.13.0"

    for workflow in (CI_WORKFLOW, SECURITY_WORKFLOW):
        definition = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        configured_versions = [
            str(step.get("with", {}).get("node-version"))
            for job in definition["jobs"].values()
            for step in job.get("steps", [])
            if str(step.get("uses", "")).startswith("actions/setup-node@")
        ]
        assert configured_versions, f"Expected at least one setup-node step in {workflow}"
        assert set(configured_versions) == {node_version}, (
            f"{workflow} setup-node versions {configured_versions} must match .nvmrc ({node_version})"
        )


def test_frontend_lock_uses_patched_public_registry_packages():
    lock = json.loads(FRONTEND_LOCK.read_text(encoding="utf-8"))
    packages = lock["packages"]

    expected = {
        "node_modules/dompurify": "3.4.12",
        "node_modules/undici": "7.28.0",
    }
    for package_path, minimum_version in expected.items():
        package = packages[package_path]
        actual = tuple(int(part) for part in package["version"].split("."))
        minimum = tuple(int(part) for part in minimum_version.split("."))
        assert actual >= minimum
        assert package["resolved"].startswith("https://registry.npmjs.org/")
        assert package["integrity"].startswith("sha512-")
