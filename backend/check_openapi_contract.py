#!/usr/bin/env python3
"""Fail CI when the generated OpenAPI contract drifts from the committed snapshot."""

import difflib
import sys
from pathlib import Path

from export_openapi import export_schema


ROOT = Path(__file__).resolve().parent
SNAPSHOT_PATH = ROOT / "openapi.snapshot.json"


def main() -> int:
    try:
        expected = _normalized_lines(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except OSError as exc:
        sys.stderr.write(f"OpenAPI snapshot not found or unreadable: {SNAPSHOT_PATH}\n")
        sys.stderr.write("Generate it with: cd backend && python export_openapi.py > openapi.snapshot.json\n")
        sys.stderr.write(f"Original error: {exc}\n")
        return 1

    current = _normalized_lines(_read_current_schema())

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


def _read_current_schema() -> str:
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).read_text(encoding="utf-8")
    return export_schema()


def _normalized_lines(value: str) -> list[str]:
    return f"{value.rstrip()}\n".splitlines(keepends=True)


if __name__ == "__main__":
    raise SystemExit(main())