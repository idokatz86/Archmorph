#!/usr/bin/env python3
"""Validate that tracked test directories and explicit exclusions map to CI jobs."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

TEST_DIRECTORY_NAMES = {"test", "tests", "__tests__"}
EXCEPTION_CLASSIFICATIONS = {"manual-local-path", "separately-collected"}


def tracked_files(repo_root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return set(result.stdout.splitlines())


def tracked_test_directories(files: Iterable[str]) -> set[str]:
    directories: set[str] = set()
    for tracked_file in files:
        parts = Path(tracked_file).parts
        for index, part in enumerate(parts[:-1]):
            if part in TEST_DIRECTORY_NAMES:
                directories.add(Path(*parts[: index + 1]).as_posix())
    return directories


def workflow_job(workflow: str, job_name: str) -> str | None:
    match = re.search(
        rf"(?ms)^  {re.escape(job_name)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
        workflow,
    )
    return match.group("body") if match else None


def validate_inventory(
    repo_root: Path,
    inventory_path: Path,
    *,
    files: set[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot load CI test inventory: {exc}"]
    if not isinstance(inventory, dict):
        return ["CI test inventory root must be an object"]
    if inventory.get("version") != 1:
        errors.append("CI test inventory version must be 1")
    entries = inventory.get("test_directories")
    if not isinstance(entries, list):
        return [*errors, "test_directories must be a list"]

    current_files = tracked_files(repo_root) if files is None else files
    expected_directories = tracked_test_directories(current_files)
    configured_directories: set[str] = set()
    for index, entry in enumerate(entries):
        label = f"test_directories[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{label} must be an object")
            continue
        directory = entry.get("directory")
        workflow_name = entry.get("workflow")
        job_name = entry.get("job")
        for field, value in (
            ("directory", directory),
            ("workflow", workflow_name),
            ("job", job_name),
        ):
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{label}.{field} must be a non-empty string")
        if not isinstance(directory, str) or not directory:
            continue
        if directory in configured_directories:
            errors.append(f"duplicate test directory: {directory}")
        configured_directories.add(directory)

        job = _validate_workflow_job(
            repo_root, workflow_name, job_name, label, errors
        )
        _validate_exceptions(
            repo_root,
            entry.get("test_file_exceptions", []),
            directory,
            current_files,
            job,
            label,
            errors,
        )

    for directory in sorted(expected_directories - configured_directories):
        errors.append(f"unmapped tracked test directory: {directory}")
    for directory in sorted(configured_directories - expected_directories):
        errors.append(f"inventory references nonexistent test directory: {directory}")
    return errors


def _validate_workflow_job(
    repo_root: Path,
    workflow_name: object,
    job_name: object,
    label: str,
    errors: list[str],
) -> str | None:
    if not isinstance(workflow_name, str) or not isinstance(job_name, str):
        return None
    workflow_path = repo_root / workflow_name
    if not workflow_path.is_file():
        errors.append(f"{label}.workflow does not exist: {workflow_name}")
        return None
    workflow = workflow_path.read_text(encoding="utf-8")
    job = workflow_job(workflow, job_name)
    if job is None:
        errors.append(f"{label}.job does not exist in {workflow_name}: {job_name}")
    return job


def _validate_exceptions(
    repo_root: Path,
    exceptions: object,
    directory: str,
    files: set[str],
    default_job: str | None,
    label: str,
    errors: list[str],
) -> None:
    if not isinstance(exceptions, list):
        errors.append(f"{label}.test_file_exceptions must be a list")
        return
    seen: set[str] = set()
    for index, exception in enumerate(exceptions):
        exception_label = f"{label}.test_file_exceptions[{index}]"
        if not isinstance(exception, dict):
            errors.append(f"{exception_label} must be an object")
            continue
        file_name = exception.get("file")
        classification = exception.get("classification")
        reason = exception.get("reason")
        if not isinstance(file_name, str) or not file_name:
            errors.append(f"{exception_label}.file must be a non-empty string")
            continue
        if file_name in seen:
            errors.append(f"duplicate test-file exception: {file_name}")
        seen.add(file_name)
        if file_name not in files:
            errors.append(f"{exception_label}.file is not tracked: {file_name}")
        if not Path(file_name).is_relative_to(Path(directory)):
            errors.append(f"{exception_label}.file is outside {directory}: {file_name}")
        if classification not in EXCEPTION_CLASSIFICATIONS:
            errors.append(
                f"{exception_label}.classification must be one of "
                f"{sorted(EXCEPTION_CLASSIFICATIONS)}"
            )
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"{exception_label}.reason must be a non-empty string")
        if classification != "separately-collected":
            continue
        exception_job = _validate_workflow_job(
            repo_root,
            exception.get("workflow"),
            exception.get("job"),
            exception_label,
            errors,
        )
        command = exception.get("command")
        if not isinstance(command, str) or not command.strip():
            errors.append(f"{exception_label}.command must be a non-empty string")
        elif command not in (exception_job or default_job or ""):
            errors.append(
                f"{exception_label}.command is not present in its referenced CI job"
            )


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=repo_root)
    parser.add_argument(
        "--inventory",
        type=Path,
        default=repo_root / "docs" / "testing" / "ci-test-inventory.json",
    )
    args = parser.parse_args()
    errors = validate_inventory(args.root.resolve(), args.inventory.resolve())
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("CI test inventory maps every tracked test directory to a valid job")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
