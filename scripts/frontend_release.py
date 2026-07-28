#!/usr/bin/env python3
"""Verify an immutable Static Web Apps rollback bundle before any mutation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import yaml


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_snapshot(root: Path, manifest_path: Path) -> dict:
    """Require the prior frontend/API artifact and pinned restore image."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("frontend rollback manifest schema is unsupported")
    image = str(manifest.get("restore_image") or "")
    if not re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", image):
        raise ValueError("frontend restore image must be pinned by immutable digest")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("frontend rollback manifest has no artifact files")
    for relative, expected_hash in files.items():
        if not isinstance(relative, str) or relative.startswith(("/", "../")):
            raise ValueError("frontend rollback manifest contains an unsafe path")
        if not _SHA256_RE.fullmatch(str(expected_hash)):
            raise ValueError("frontend rollback manifest contains an invalid file hash")
        path = root / relative
        if not path.is_file() or _file_hash(path) != expected_hash:
            raise ValueError(f"frontend rollback artifact failed integrity check: {relative}")
    if "dist/index.html" not in files:
        raise ValueError("frontend rollback artifact does not contain dist/index.html")
    if not any(relative.startswith("api/") for relative in files):
        raise ValueError("frontend rollback artifact does not contain the API snapshot")
    return manifest


def write_manifest(root: Path, restore_image: str, output: Path) -> None:
    if not re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", restore_image):
        raise ValueError("frontend restore image must be pinned by immutable digest")
    files = {
        str(path.relative_to(root)): _file_hash(path)
        for directory in (root / "dist", root / "api")
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }
    manifest = {
        "schema_version": 1,
        "restore_image": restore_image,
        "files": files,
    }
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def chart_schema_contract(path: Path) -> dict:
    values = yaml.safe_load(path.read_text(encoding="utf-8"))
    migrations = values.get("migrations", {}) if isinstance(values, dict) else {}
    head = str(migrations.get("expectedAlembicHead") or "")
    accepted = migrations.get("acceptedCurrentAlembicRevisions")
    def valid(value: str) -> bool:
        return bool(value) and all(
            character.isalnum() or character in "_-" for character in value
        )
    if not valid(head) or not isinstance(accepted, list) or not accepted:
        raise ValueError("chart migration schema contract is incomplete")
    accepted = [str(item) for item in accepted]
    if any(not valid(item) for item in accepted):
        raise ValueError("chart migration schema contract contains an invalid revision")
    if len(accepted) != len(set(accepted)) or head not in accepted:
        raise ValueError("chart migration schema contract must be unique and include head")
    return {"expected_head": head, "accepted_current": accepted}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--root", required=True, type=Path)
    verify.add_argument("--manifest", required=True, type=Path)
    write = subparsers.add_parser("write")
    write.add_argument("--root", required=True, type=Path)
    write.add_argument("--restore-image", required=True)
    write.add_argument("--output", required=True, type=Path)
    chart = subparsers.add_parser("chart-schema")
    chart.add_argument("--values", required=True, type=Path)
    chart.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "verify":
        print(json.dumps(verify_snapshot(args.root, args.manifest), sort_keys=True))
    elif args.command == "write":
        write_manifest(args.root, args.restore_image, args.output)
    else:
        args.output.write_text(
            json.dumps(chart_schema_contract(args.values), indent=2) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
