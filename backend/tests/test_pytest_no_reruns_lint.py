from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import textwrap


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "lint_pytest_no_reruns.py"
SPEC = spec_from_file_location("lint_pytest_no_reruns", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
lint_pytest_no_reruns = module_from_spec(SPEC)
sys.modules[SPEC.name] = lint_pytest_no_reruns
SPEC.loader.exec_module(lint_pytest_no_reruns)


def test_rejects_default_rerun_flags(tmp_path):
    config = tmp_path / "pyproject.toml"
    config.write_text(
        textwrap.dedent(
            """
            [tool.pytest.ini_options]
            addopts = "--reruns 3 --reruns-delay 1"
            """
        ),
        encoding="utf-8",
    )

    violations = lint_pytest_no_reruns.find_violations([config])

    assert len(violations) == 1
    assert "remove default pytest rerun configuration" in violations[0]


def test_rejects_rerun_plugin_dependency(tmp_path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("pytest-rerunfailures==14.0\n", encoding="utf-8")

    violations = lint_pytest_no_reruns.find_violations([requirements])

    assert len(violations) == 1
    assert "pytest-rerunfailures" in violations[0]


def test_allows_plain_pytest_commands(tmp_path):
    workflow = tmp_path / "ci.yml"
    workflow.write_text("run: python -m pytest --tb=short -q\n", encoding="utf-8")

    assert lint_pytest_no_reruns.find_violations([workflow]) == []