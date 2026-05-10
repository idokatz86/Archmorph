#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


FROM_RE = re.compile(r"^\s*FROM\s+(?:--platform=\S+\s+)?(?P<image>\S+)", re.IGNORECASE)
ARG_RE = re.compile(r"^\s*ARG\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:=(?P<value>\S+))?", re.IGNORECASE)
NODE_PATCH_TAG_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[A-Za-z0-9_.-]+)?$")


def _git_files(repo_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "*Dockerfile*", "*.Dockerfile"],
        cwd=repo_root,
        check=True,
        text=True,
        capture_output=True,
    )
    return [repo_root / line for line in result.stdout.splitlines() if line]


def _is_node_image(image: str) -> bool:
    without_digest = image.split("@", 1)[0]
    repository = without_digest.rsplit(":", 1)[0] if ":" in without_digest else without_digest
    return repository == "node" or repository.endswith("/node")


def _has_pinned_node_patch_digest(image: str) -> bool:
    if not _is_node_image(image):
        return True
    if "@sha256:" not in image:
        return False
    image_without_digest, digest = image.split("@sha256:", 1)
    if not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
        return False
    if ":" not in image_without_digest:
        return False
    tag = image_without_digest.rsplit(":", 1)[1]
    return bool(NODE_PATCH_TAG_RE.match(tag))


def _resolve_image_token(image: str, args: dict[str, str]) -> str:
    for name, value in args.items():
        image = image.replace(f"${{{name}}}", value).replace(f"${name}", value)
    return image


def _looks_like_node_image_variable(image: str) -> bool:
    if not image.startswith("$"):
        return False
    name = image.strip("${}").upper()
    return "NODE" in name


def find_violations(paths: list[Path]) -> list[str]:
    violations: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        docker_args: dict[str, str] = {}
        for line_number, line in enumerate(content.splitlines(), start=1):
            arg_match = ARG_RE.match(line)
            if arg_match and arg_match.group("value") is not None:
                docker_args[arg_match.group("name")] = arg_match.group("value")
                continue
            match = FROM_RE.match(line)
            if not match:
                continue
            raw_image = match.group("image")
            image = _resolve_image_token(raw_image, docker_args)
            if _looks_like_node_image_variable(image) or (_is_node_image(image) and not _has_pinned_node_patch_digest(image)):
                violations.append(
                    f"{path}:{line_number}: Node base image '{raw_image}' must pin a full patch tag and sha256 digest"
                )
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reject floating Node Docker base images.")
    parser.add_argument("paths", nargs="*", type=Path, help="Dockerfiles to scan. Defaults to git-tracked Dockerfiles.")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    paths = args.paths or _git_files(repo_root)
    violations = find_violations(paths)
    if violations:
        print("Docker base image guard failed:")
        for violation in violations:
            print(f"- {violation}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())