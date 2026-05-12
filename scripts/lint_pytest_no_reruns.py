#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


BLOCKED_PATTERNS = (
    re.compile(r"(?<!\S)--reruns(?:=|\s|$)"),
    re.compile(r"(?<!\S)--reruns-delay(?:=|\s|$)"),
    re.compile(r"\bpytest-rerunfailures\b"),
)

DEFAULT_PATTERNS = (
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    "pyproject.toml",
    "pytest.ini",
    "tox.ini",
    "setup.cfg",
    "backend/pyproject.toml",
    "backend/pytest.ini",
    "backend/tox.ini",
    "backend/setup.cfg",
    "backend/requirements*.txt",
)


def _git_files(repo_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", *DEFAULT_PATTERNS],
        cwd=repo_root,
        check=True,
        text=True,
        capture_output=True,
    )
    return [repo_root / line for line in result.stdout.splitlines() if line]


def find_violations(paths: list[Path]) -> list[str]:
    violations: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(lines, start=1):
            if any(pattern.search(line) for pattern in BLOCKED_PATTERNS):
                violations.append(
                    f"{path}:{line_number}: remove default pytest rerun configuration: {line.strip()}"
                )
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reject default pytest rerun configuration that can mask flakes.")
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files to scan. Defaults to tracked pytest config, workflow, and requirement files.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    paths = args.paths or _git_files(repo_root)
    violations = find_violations(paths)
    if violations:
        print("Default pytest rerun guard failed:")
        for violation in violations:
            print(f"- {violation}")
        print("Use the flake tracking process in docs/testing/flake-tracking.md instead of automatic retries.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())