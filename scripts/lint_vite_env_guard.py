#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


SECRET_LIKE_VITE_ENV = re.compile(r"\bVITE_[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*\b")
PROCESS_ENV_DEFINE = re.compile(r"define\s*:\s*\{[^}]*['\"]process\.env['\"]\s*:", re.DOTALL)
VITE_CONFIG_NAMES = {"vite.config.js", "vite.config.mjs", "vite.config.ts", "vite.config.mts"}
SKIP_PARTS = {"node_modules", "dist", "build", ".git", ".vite", ".lighthouseci"}
TEXT_SUFFIXES = {
    ".env",
    ".example",
    ".js",
    ".jsx",
    ".json",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".mjs",
    ".mts",
    ".ts",
    ".tsx",
    ".yml",
    ".yaml",
}


def _is_scannable(path: Path) -> bool:
    if any(part in SKIP_PARTS for part in path.parts):
        return False
    if path.name.startswith(".env"):
        return True
    return path.suffix in TEXT_SUFFIXES


def _git_files(repo_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return [repo_root / line for line in result.stdout.splitlines() if line]


def find_violations(paths: list[Path]) -> list[str]:
    violations: list[str] = []
    for path in paths:
        if not path.exists() or not path.is_file() or not _is_scannable(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for match in sorted(set(SECRET_LIKE_VITE_ENV.findall(text))):
            violations.append(
                f"{path}: secret-like client env var {match!r}; use a server-only env name without the VITE_ prefix"
            )

        if path.name in VITE_CONFIG_NAMES and PROCESS_ENV_DEFINE.search(text):
            violations.append(
                f"{path}: blanket define for 'process.env' is not allowed in Vite config; define explicit public keys only"
            )
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reject Vite env patterns that can expose server-side secrets")
    parser.add_argument("paths", nargs="*", type=Path, help="Optional files to scan instead of git-tracked files")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    paths = args.paths or _git_files(repo_root)
    violations = find_violations(paths)
    if violations:
        print("Vite environment guard failed:", file=sys.stderr)
        for violation in violations:
            print(f"- {violation}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())