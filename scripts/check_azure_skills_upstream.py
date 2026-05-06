#!/usr/bin/env python3
"""Validate the managed microsoft/azure-skills upstream dependency."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCKFILE = REPO_ROOT / "infra" / "skills-upstream" / "azure-skills.lock.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class Finding:
    level: str
    code: str
    message: str


def main() -> int:
    args = _parse_args()
    lock = _load_lock(args.lockfile)
    upstream_dir = _resolve_path(args.upstream_dir or lock["upstream"]["path"])
    upstream_skills_dir = upstream_dir / lock["upstream"].get("skills_path", "skills")
    local_skills_dir = Path(args.local_skills_dir).expanduser()

    findings = evaluate_config(
        lock,
        upstream_skill_names=_list_skill_dirs(upstream_skills_dir),
        local_skill_names=_list_skill_dirs(local_skills_dir),
        submodule_sha=_git_head(upstream_dir),
        telemetry_env=os.environ.get(lock["telemetry"]["env"]),
        require_local_skills=args.require_local_skills,
        check_telemetry_env=args.check_telemetry_env,
    )
    if args.diff_local_upstream:
        findings.extend(
            diff_local_upstream(
                upstream_skills_dir,
                local_skills_dir,
                expected_skill_names=set(lock["upstream"].get("expected_skill_names") or []),
            )
        )
    _print_findings(findings)
    return 1 if any(f.level == "error" for f in findings) else 0


def evaluate_config(
    lock: dict[str, Any],
    *,
    upstream_skill_names: set[str] | None,
    local_skill_names: set[str] | None,
    submodule_sha: str | None,
    telemetry_env: str | None = None,
    require_local_skills: bool = False,
    check_telemetry_env: bool = False,
) -> list[Finding]:
    findings: list[Finding] = []
    upstream = lock.get("upstream") or {}
    pinned_sha = str(upstream.get("pinned_sha", "")).strip()
    expected_names = set(upstream.get("expected_skill_names") or [])
    expected_count = upstream.get("expected_skill_count")

    if not SHA_RE.fullmatch(pinned_sha):
        findings.append(Finding("error", "invalid-pin", "Pinned azure-skills SHA must be a 40-character lowercase git SHA."))

    if submodule_sha is None:
        findings.append(Finding("error", "missing-submodule", "azure-skills submodule is not checked out or is not a git worktree."))
    elif submodule_sha != pinned_sha:
        findings.append(
            Finding(
                "error",
                "submodule-drift",
                f"azure-skills submodule HEAD {submodule_sha} does not match pinned SHA {pinned_sha}.",
            )
        )

    if upstream_skill_names is None:
        findings.append(Finding("error", "missing-upstream-skills", "Upstream azure-skills/skills directory is unavailable."))
    else:
        if expected_count is not None and len(upstream_skill_names) != int(expected_count):
            findings.append(
                Finding(
                    "error",
                    "upstream-count-drift",
                    f"Expected {expected_count} upstream skills, found {len(upstream_skill_names)}.",
                )
            )
        missing = sorted(expected_names - upstream_skill_names)
        added = sorted(upstream_skill_names - expected_names)
        if missing or added:
            findings.append(
                Finding(
                    "error",
                    "upstream-skill-drift",
                    "Upstream skill list differs from lock file; review diff before updating. "
                    f"missing={missing}; added={added}",
                )
            )

    local_names = local_skill_names or set()
    if require_local_skills and local_skill_names is None:
        findings.append(Finding("error", "missing-local-skills", "Local ~/.agents/skills directory is unavailable."))

    for custom in lock.get("custom_skills") or []:
        legacy_name = custom["legacy_name"]
        protected_name = custom["protected_name"]
        if upstream_skill_names and protected_name in upstream_skill_names:
            findings.append(
                Finding(
                    "error",
                    "protected-name-collision",
                    f"Upstream now contains protected custom skill name {protected_name!r}; choose a new Archmorph namespace.",
                )
            )
        if local_skill_names is not None:
            if legacy_name in local_names:
                findings.append(
                    Finding(
                        "error",
                        "legacy-local-skill",
                        f"Local custom skill {legacy_name!r} must be renamed to {protected_name!r}.",
                    )
                )
            if protected_name not in local_names:
                findings.append(
                    Finding(
                        "warning",
                        "missing-protected-local-skill",
                        f"Protected custom skill {protected_name!r} is not installed locally.",
                    )
                )

    if check_telemetry_env:
        telemetry = lock.get("telemetry") or {}
        env_name = telemetry.get("env", "AZURE_MCP_COLLECT_TELEMETRY")
        expected = str(telemetry.get("default", "false")).lower()
        if (telemetry_env or "").lower() != expected:
            findings.append(
                Finding(
                    "error",
                    "telemetry-default",
                    f"{env_name} must be set to {expected!r} for azure-skills governance checks.",
                )
            )

    return findings


def diff_local_upstream(
    upstream_skills_dir: Path,
    local_skills_dir: Path,
    *,
    expected_skill_names: set[str],
) -> list[Finding]:
    findings: list[Finding] = []
    if not upstream_skills_dir.exists():
        return [Finding("error", "missing-upstream-skills", "Upstream skills directory is unavailable for diff.")]
    if not local_skills_dir.exists():
        return [Finding("error", "missing-local-skills", "Local skills directory is unavailable for diff.")]

    for skill_name in sorted(expected_skill_names):
        upstream_path = upstream_skills_dir / skill_name
        local_path = local_skills_dir / skill_name
        if not upstream_path.exists():
            findings.append(Finding("error", "missing-upstream-skill", f"Pinned upstream skill {skill_name!r} is missing."))
            continue
        if not local_path.exists():
            findings.append(Finding("warning", "missing-local-upstream-skill", f"Local upstream skill {skill_name!r} is not installed."))
            continue

        result = subprocess.run(
            ["diff", "-qr", str(upstream_path), str(local_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode == 0:
            continue
        if result.returncode == 1:
            findings.append(
                Finding(
                    "error",
                    "local-upstream-content-drift",
                    f"Local installed upstream skill {skill_name!r} differs from pinned submodule. "
                    f"Review with: diff -ru {upstream_path} {local_path}",
                )
            )
            continue
        findings.append(
            Finding(
                "error",
                "local-upstream-diff-failed",
                f"Unable to diff local upstream skill {skill_name!r}: {result.stderr.strip()}",
            )
        )

    return findings


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lockfile", type=Path, default=DEFAULT_LOCKFILE)
    parser.add_argument("--upstream-dir", type=Path)
    parser.add_argument("--local-skills-dir", default="~/.agents/skills")
    parser.add_argument("--require-local-skills", action="store_true")
    parser.add_argument("--check-telemetry-env", action="store_true")
    parser.add_argument("--diff-local-upstream", action="store_true")
    return parser.parse_args()


def _load_lock(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _resolve_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return REPO_ROOT / candidate


def _list_skill_dirs(path: Path) -> set[str] | None:
    if not path.exists() or not path.is_dir():
        return None
    return {child.name for child in path.iterdir() if child.is_dir()}


def _git_head(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _print_findings(findings: list[Finding]) -> None:
    if not findings:
        print("azure-skills upstream governance passed")
        return
    for finding in findings:
        stream = sys.stderr if finding.level == "error" else sys.stdout
        print(f"{finding.level.upper()}: {finding.code}: {finding.message}", file=stream)


if __name__ == "__main__":
    sys.exit(main())