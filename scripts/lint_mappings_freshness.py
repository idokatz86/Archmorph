#!/usr/bin/env python3
"""Check service mapping rows for freshness review metadata."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
DEFAULT_MAX_AGE_DAYS = int(os.getenv("MAPPINGS_FRESHNESS_MAX_AGE_DAYS", "180"))


@dataclass(frozen=True)
class Finding:
    level: str
    row_id: str
    message: str


def main() -> int:
    args = _parse_args()
    rows = _load_rows()
    findings = evaluate_rows(
        rows,
        today=date.fromisoformat(args.today) if args.today else date.today(),
        max_age_days=args.max_age_days,
    )
    _print_findings(findings, output_format=args.output)
    return 1 if any(f.level == "error" for f in findings) else 0


def evaluate_rows(
    rows: list[dict[str, Any]],
    *,
    today: date,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> list[Finding]:
    findings: list[Finding] = []
    for index, row in enumerate(rows, start=1):
        row_id = _row_id(row, index)
        confidence = float(row.get("confidence", 0))
        last_reviewed = row.get("last_reviewed")

        if not last_reviewed:
            level = "error" if confidence < 0.8 else "warning"
            findings.append(Finding(level, row_id, "missing last_reviewed"))
            continue

        try:
            reviewed_on = date.fromisoformat(str(last_reviewed))
        except ValueError:
            findings.append(Finding("error", row_id, f"invalid last_reviewed={last_reviewed!r}"))
            continue

        if reviewed_on > today:
            findings.append(Finding("error", row_id, f"last_reviewed {reviewed_on} is in the future"))
            continue

        age_days = (today - reviewed_on).days
        if age_days > max_age_days:
            level = "error" if confidence < 0.8 else "warning"
            findings.append(
                Finding(
                    level,
                    row_id,
                    f"last_reviewed {reviewed_on} is {age_days} days old "
                    f"(max {max_age_days})",
                )
            )

    return findings


def _load_rows() -> list[dict[str, Any]]:
    sys.path.insert(0, str(BACKEND_ROOT))
    from services.mappings import CROSS_CLOUD_MAPPINGS  # noqa: PLC0415

    return list(CROSS_CLOUD_MAPPINGS)


def _row_id(row: dict[str, Any], index: int) -> str:
    source = row.get("aws") or row.get("source") or f"row {index}"
    target = row.get("azure") or row.get("target") or "?"
    return f"{source} -> {target}"


def _print_findings(findings: list[Finding], *, output_format: str) -> None:
    errors = [f for f in findings if f.level == "error"]
    warnings = [f for f in findings if f.level == "warning"]

    if output_format == "markdown":
        print("# Mappings Freshness Review")
        print()
        print(f"Errors: {len(errors)}")
        print(f"Warnings: {len(warnings)}")
        print()
        if not findings:
            print("All mapping rows are fresh.")
            return
        print("| Level | Row | Message |")
        print("| --- | --- | --- |")
        for finding in findings:
            print(f"| {finding.level} | {finding.row_id} | {finding.message} |")
        return

    if not findings:
        print("Mappings freshness lint passed")
        return

    for finding in findings:
        stream = sys.stderr if finding.level == "error" else sys.stdout
        print(f"{finding.level.upper()}: {finding.row_id}: {finding.message}", file=stream)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=DEFAULT_MAX_AGE_DAYS,
        help="Maximum acceptable age for last_reviewed dates.",
    )
    parser.add_argument(
        "--today",
        help="Override today's date as YYYY-MM-DD for tests or scheduled reports.",
    )
    parser.add_argument(
        "--output",
        choices=("text", "markdown"),
        default="text",
        help="Output format.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
