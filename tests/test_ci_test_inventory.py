import json
from pathlib import Path

from scripts.check_ci_test_inventory import validate_inventory


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _inventory(entries: list[dict]) -> str:
    return json.dumps({"version": 1, "test_directories": entries})


def test_inventory_rejects_unmapped_test_directory(tmp_path):
    _write(
        tmp_path / ".github/workflows/ci.yml",
        "jobs:\n  unit-tests:\n    runs-on: ubuntu-latest\n",
    )
    inventory = tmp_path / "inventory.json"
    inventory.write_text(_inventory([]), encoding="utf-8")

    errors = validate_inventory(
        tmp_path,
        inventory,
        files={"backend/tests/test_example.py"},
    )

    assert errors == ["unmapped tracked test directory: backend/tests"]


def test_inventory_rejects_missing_job_and_nonexistent_directory(tmp_path):
    _write(
        tmp_path / ".github/workflows/ci.yml",
        "jobs:\n  another-job:\n    runs-on: ubuntu-latest\n",
    )
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        _inventory(
            [
                {
                    "directory": "backend/tests",
                    "workflow": ".github/workflows/ci.yml",
                    "job": "unit-tests",
                }
            ]
        ),
        encoding="utf-8",
    )

    errors = validate_inventory(tmp_path, inventory, files=set())

    assert "test_directories[0].job does not exist in .github/workflows/ci.yml: unit-tests" in errors
    assert "inventory references nonexistent test directory: backend/tests" in errors


def test_inventory_validates_explicit_exclusion_command(tmp_path):
    _write(
        tmp_path / ".github/workflows/ci.yml",
        "jobs:\n  unit-tests:\n    runs-on: ubuntu-latest\n",
    )
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        _inventory(
            [
                {
                    "directory": "tests",
                    "workflow": ".github/workflows/ci.yml",
                    "job": "unit-tests",
                    "test_file_exceptions": [
                        {
                            "file": "tests/load_test.py",
                            "classification": "separately-collected",
                            "reason": "Collected separately.",
                            "workflow": ".github/workflows/ci.yml",
                            "job": "unit-tests",
                            "command": "python -m locust --list",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    errors = validate_inventory(
        tmp_path,
        inventory,
        files={"tests/load_test.py"},
    )

    assert (
        "test_directories[0].test_file_exceptions[0].command is not present "
        "in its referenced CI job"
    ) in errors
