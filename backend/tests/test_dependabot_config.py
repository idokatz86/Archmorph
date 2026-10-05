import json
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DEPENDABOT_CONFIG = REPO_ROOT / ".github" / "dependabot.yml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SECURITY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "security.yml"
ROOT_PACKAGE = REPO_ROOT / "package.json"
FRONTEND_PACKAGE = REPO_ROOT / "frontend" / "package.json"
ROOT_LOCK = REPO_ROOT / "package-lock.json"
FRONTEND_LOCK = REPO_ROOT / "frontend" / "package-lock.json"
NODE_VERSION = REPO_ROOT / ".nvmrc"
MICROSOFT_PUBLIC_NPM = (
    "https://ms-feed-25.pkgs.visualstudio.com/1es-public/"
    "_packaging/npm-public/npm/registry/"
)
PUBLIC_NPM_SOURCES = ("https://registry.npmjs.org/", MICROSOFT_PUBLIC_NPM)


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


def test_dependabot_uses_codeowners_instead_of_retired_reviewers_option():
    assert "* @idokatz86" in (REPO_ROOT / ".github" / "CODEOWNERS").read_text()
    for update in _all_updates():
        assert "reviewers" not in update


def test_dependabot_covers_every_dependency_manifest_and_runtime_image():
    covered = {
        (update["package-ecosystem"], directory)
        for update in _all_updates()
        for directory in update.get("directories", [update.get("directory")])
    }
    assert {
        ("npm", "/"),
        ("npm", "/frontend"),
        ("npm", "/frontend/api"),
        ("pip", "/backend"),
        ("pip", "/cli"),
        ("pip", "/mcp-gateway"),
        ("docker", "/backend"),
        ("docker", "/mcp-gateway"),
        ("github-actions", "/"),
        ("terraform", "/infra"),
    } <= covered


def test_npm_projects_and_dependabot_use_the_approved_public_feed():
    config = yaml.safe_load(DEPENDABOT_CONFIG.read_text(encoding="utf-8"))
    assert config["registries"]["microsoft-public-npm"] == {
        "type": "npm-registry",
        "url": MICROSOFT_PUBLIC_NPM,
    }
    for directory in (REPO_ROOT, REPO_ROOT / "frontend", REPO_ROOT / "frontend/api"):
        assert (directory / ".npmrc").read_text().strip() == (
            f"registry={MICROSOFT_PUBLIC_NPM}"
        )
    for update in _all_updates():
        if update["package-ecosystem"] == "npm":
            assert update["registries"] == ["microsoft-public-npm"]


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


@pytest.mark.parametrize(
    ("lock_path", "expected"),
    [
        (ROOT_LOCK, {"js-yaml": "4.3.2"}),
        (
            FRONTEND_LOCK,
            {
                "dompurify": "3.4.16",
                "undici": "7.30.0",
                "js-yaml": "4.3.2",
                "nanoid": "3.3.18",
                "postcss": "8.5.23",
                "vitest": "4.1.11",
                "@vitest/mocker": "4.1.11",
                "@vitest/coverage-v8": "4.1.11",
                "browserslist": "4.28.7",
                "baseline-browser-mapping": "2.11.0",
            },
        ),
    ],
)
def test_locks_use_patched_public_registry_packages(lock_path, expected):
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    packages = lock["packages"]

    for path, package in packages.items():
        if "resolved" in package:
            assert package.get("integrity", "").startswith("sha512-"), (
                f"{path} in {lock_path} needs a SHA-512 archive pin"
            )

    for name, minimum_version in expected.items():
        matching = [
            package
            for path, package in packages.items()
            if path == f"node_modules/{name}" or path.endswith(f"/node_modules/{name}")
        ]
        assert matching, f"{name} missing from {lock_path}"
        minimum = tuple(int(part) for part in minimum_version.split("."))
        for package in matching:
            actual = tuple(int(part) for part in package["version"].split("."))
            assert actual >= minimum, f"{name} {package['version']} is below {minimum_version}"
            assert package["resolved"].startswith(PUBLIC_NPM_SOURCES)
            assert package["integrity"].startswith("sha512-")
