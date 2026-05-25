from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DEPENDABOT_CONFIG = REPO_ROOT / ".github" / "dependabot.yml"


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