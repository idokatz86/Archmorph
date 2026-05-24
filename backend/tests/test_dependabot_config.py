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


def test_frontend_dependabot_ignores_only_eslint_10_major_until_react_plugin_supports_it():
    update = _frontend_npm_update()
    eslint_rules = [rule for rule in update.get("ignore", []) if rule.get("dependency-name") == "eslint"]

    assert eslint_rules == [{"dependency-name": "eslint", "versions": ["10.x"]}]
    assert "update-types" not in eslint_rules[0]