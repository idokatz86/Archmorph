#!/usr/bin/env python3
"""Fail CI on OpenAPI drift and unapproved breaking changes.

Checks:
- Generated schema must match the committed snapshot.
- Snapshot must remain compatible with base-branch snapshot for PRs.
- Breaking changes against base require explicit approval metadata.
"""

import argparse
import difflib
import json
import os
import sys
from pathlib import Path

from export_openapi import export_schema


ROOT = Path(__file__).resolve().parent
SNAPSHOT_PATH = ROOT / "openapi.snapshot.json"
DEFAULT_BREAKING_METADATA_PATH = ROOT / "openapi.breaking-change.json"
REQUIRED_BREAKING_METADATA_FIELDS = ("approved_by", "review_url", "reason")


def main() -> int:
    args = _parse_args()

    try:
        expected = _normalized_lines(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except OSError as exc:
        sys.stderr.write(f"OpenAPI snapshot not found or unreadable: {SNAPSHOT_PATH}\n")
        sys.stderr.write("Generate it with: cd backend && python export_openapi.py > openapi.snapshot.json\n")
        sys.stderr.write(f"Original error: {exc}\n")
        return 1

    current_schema_raw = _read_current_schema(args.generated_schema_path)
    current = _normalized_lines(current_schema_raw)

    expected_schema = json.loads("".join(expected))
    # CI sets ARCHMORPH_OPENAPI_BASE_SNAPSHOT on pull_request runs to enforce
    # compatibility between the base branch snapshot and this branch snapshot.
    base_snapshot_path = args.base_snapshot_path or os.getenv("ARCHMORPH_OPENAPI_BASE_SNAPSHOT")
    if base_snapshot_path:
        base_path = Path(base_snapshot_path)
        if base_path.exists():
            base_schema = json.loads(base_path.read_text(encoding="utf-8"))
            breaking_changes = detect_breaking_changes(base_schema, expected_schema)
            if breaking_changes:
                metadata_errors = validate_breaking_change_metadata(Path(args.breaking_metadata_path))
                if metadata_errors:
                    _write_breaking_change_failure(breaking_changes, metadata_errors, base_path)
                    return 1
        else:
            sys.stderr.write(
                f"Warning: ARCHMORPH_OPENAPI_BASE_SNAPSHOT not found: {base_path}. "
                "Skipping base-branch compatibility check.\n"
            )

    if current == expected:
        print("OpenAPI contract matches backend/openapi.snapshot.json")
        return 0

    diff = difflib.unified_diff(
        expected,
        current,
        fromfile="backend/openapi.snapshot.json",
        tofile="generated-openapi.json",
        n=3,
    )
    sys.stderr.write("OpenAPI contract drift detected.\n")
    sys.stderr.write("If this API change is intentional, regenerate the snapshot with:\n")
    sys.stderr.write("  cd backend && python export_openapi.py > openapi.snapshot.json\n\n")
    sys.stderr.writelines(diff)
    return 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "generated_schema_path",
        nargs="?",
        help="Optional path to a generated OpenAPI schema JSON file.",
    )
    parser.add_argument(
        "--base-snapshot-path",
        dest="base_snapshot_path",
        default=None,
        help=(
            "Optional path to a base-branch OpenAPI snapshot. "
            "When provided, breaking changes from base->snapshot require metadata."
        ),
    )
    parser.add_argument(
        "--breaking-metadata-path",
        dest="breaking_metadata_path",
        default=str(DEFAULT_BREAKING_METADATA_PATH),
        help="Path to breaking change approval metadata JSON.",
    )
    return parser.parse_args()


def _read_current_schema(schema_path: str | None) -> str:
    if schema_path:
        return Path(schema_path).read_text(encoding="utf-8")
    return export_schema()


def _normalized_lines(value: str) -> list[str]:
    return f"{value.rstrip()}\n".splitlines(keepends=True)


def detect_breaking_changes(base_schema: dict, target_schema: dict) -> list[str]:
    """Detect coarse breaking changes between two OpenAPI schemas."""
    breaks: list[str] = []
    base_paths = base_schema.get("paths", {})
    target_paths = target_schema.get("paths", {})
    http_methods = {"get", "post", "put", "patch", "delete", "options", "head"}

    for path, base_ops in base_paths.items():
        target_ops = target_paths.get(path)
        if target_ops is None:
            breaks.append(f"Removed path: {path}")
            continue

        for method, base_op in base_ops.items():
            if method not in http_methods:
                continue
            target_op = target_ops.get(method)
            if target_op is None:
                breaks.append(f"Removed operation: {method.upper()} {path}")
                continue

            base_success = _extract_success_codes(base_op)
            target_success = _extract_success_codes(target_op)
            removed_success = sorted(base_success - target_success)
            if removed_success:
                breaks.append(
                    f"Removed success response(s) on {method.upper()} {path}: {', '.join(removed_success)}"
                )

    base_components = base_schema.get("components", {}).get("schemas", {})
    target_components = target_schema.get("components", {}).get("schemas", {})
    for schema_name, base_def in base_components.items():
        target_def = target_components.get(schema_name)
        if target_def is None:
            breaks.append(f"Removed component schema: {schema_name}")
            continue
        if not isinstance(base_def, dict) or not isinstance(target_def, dict):
            continue
        if base_def.get("type") != "object" or target_def.get("type") != "object":
            continue

        base_props = set((base_def.get("properties") or {}).keys())
        target_props = set((target_def.get("properties") or {}).keys())
        removed_props = sorted(base_props - target_props)
        if removed_props:
            breaks.append(f"Removed schema properties from {schema_name}: {', '.join(removed_props)}")

        base_required = set(base_def.get("required") or [])
        target_required = set(target_def.get("required") or [])
        removed_required = sorted(base_required - target_required)
        if removed_required:
            breaks.append(
                f"Removed required properties from {schema_name}: {', '.join(removed_required)}"
            )

    return breaks


def validate_breaking_change_metadata(metadata_path: Path) -> list[str]:
    if not metadata_path.exists():
        return [f"Missing metadata file: {metadata_path}"]

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Unreadable metadata file {metadata_path}: {exc}"]

    errors: list[str] = []
    if not isinstance(metadata, dict):
        return [f"Metadata file must contain a JSON object: {metadata_path}"]
    for field in REQUIRED_BREAKING_METADATA_FIELDS:
        value = metadata.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"Missing required metadata field: {field}")
    return errors


def _extract_success_codes(operation: dict) -> set[str]:
    return {str(code) for code in operation.get("responses", {}) if str(code).startswith("2")}


def _write_breaking_change_failure(
    breaking_changes: list[str], metadata_errors: list[str], base_snapshot_path: Path
) -> None:
    sys.stderr.write(
        "OpenAPI breaking changes detected against base snapshot "
        f"({base_snapshot_path}).\n"
    )
    for item in breaking_changes:
        sys.stderr.write(f"  - {item}\n")
    sys.stderr.write(
        "\nBreaking changes require explicit approval metadata in "
        f"{DEFAULT_BREAKING_METADATA_PATH.name}.\n"
    )
    for error in metadata_errors:
        sys.stderr.write(f"  - {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
