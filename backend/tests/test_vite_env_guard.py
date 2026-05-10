import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parents[2]
VITE_ENV_GUARD = REPO_ROOT / "scripts" / "lint_vite_env_guard.py"


def _load_guard_module():
    spec = importlib.util.spec_from_file_location("lint_vite_env_guard", VITE_ENV_GUARD)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


find_violations = _load_guard_module().find_violations


def test_vite_env_guard_allows_public_api_base(tmp_path: Path):
    config = tmp_path / "vite.config.js"
    config.write_text("const apiBase = import.meta.env.VITE_API_BASE\n", encoding="utf-8")

    assert find_violations([config]) == []


@pytest.mark.parametrize(
    "env_name",
    ["VITE_OPENAI_KEY", "VITE_SERVICE_TOKEN", "VITE_CLIENT_SECRET", "VITE_DB_PASSWORD"],
)
def test_vite_env_guard_rejects_secret_like_vite_names(tmp_path: Path, env_name: str):
    workflow = tmp_path / "workflow.yml"
    workflow.write_text(f"env:\n  {env_name}: fake\n", encoding="utf-8")

    violations = find_violations([workflow])

    assert len(violations) == 1
    assert env_name in violations[0]

def test_rejects_secret_like_vite_env_names_in_shell_scripts(tmp_path):
    source = tmp_path / "scripts" / "deploy.sh"
    source.parent.mkdir(parents=True)
    source.write_text("export VITE_DEPLOY_TOKEN=value\n", encoding="utf-8")

    violations = find_violations([source])

    assert len(violations) == 1
    assert "VITE_DEPLOY_TOKEN" in violations[0]


def test_vite_env_guard_rejects_blanket_process_env_define(tmp_path: Path):
    config = tmp_path / "vite.config.ts"
    config.write_text("export default { define: { 'process.env': process.env } }\n", encoding="utf-8")

    violations = find_violations([config])

    assert len(violations) == 1
    assert "blanket define" in violations[0]