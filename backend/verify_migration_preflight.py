"""Verify exact-execution database preflight evidence from Container Apps logs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Iterable


EVIDENCE_PREFIX = "ARCHMORPH_MIGRATION_PREFLIGHT_EVIDENCE="


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _log_strings(raw_logs: str) -> Iterable[str]:
    try:
        yield from _strings(json.loads(raw_logs))
        return
    except json.JSONDecodeError:
        pass

    for line in raw_logs.splitlines():
        try:
            yield from _strings(json.loads(line))
        except json.JSONDecodeError:
            yield line


def _evidence_objects(raw_logs: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    evidence: list[dict[str, Any]] = []
    for line in _log_strings(raw_logs):
        start = 0
        while (position := line.find(EVIDENCE_PREFIX, start)) >= 0:
            payload = line[position + len(EVIDENCE_PREFIX) :].lstrip()
            try:
                record, _ = decoder.raw_decode(payload)
            except json.JSONDecodeError as error:
                raise ValueError("preflight log contains malformed evidence") from error
            if not isinstance(record, dict):
                raise ValueError("preflight evidence must be a JSON object")
            evidence.append(record)
            start = position + len(EVIDENCE_PREFIX) + len(payload)
    return evidence


def verify_preflight_logs(
    raw_logs: str,
    *,
    execution_marker: str,
    image_digest: str,
    accepted_revisions: tuple[str, ...],
) -> str:
    """Return one verified revision; reject absent, duplicate, or stale evidence."""
    records = _evidence_objects(raw_logs)
    if len(records) != 1:
        raise ValueError("expected exactly one database preflight evidence record")

    record = records[0]
    revision = record.get("current_revision")
    image_reference = record.get("image_reference")
    if record.get("status") != "preflight_succeeded":
        raise ValueError("database preflight did not report success")
    if record.get("execution_marker") != execution_marker:
        raise ValueError("database preflight evidence belongs to another execution")
    if record.get("image_digest") != image_digest:
        raise ValueError("database preflight evidence belongs to another image")
    if record.get("accepted_revisions") != list(accepted_revisions):
        raise ValueError("database preflight evidence has an unexpected schema allow-list")
    if not isinstance(revision, str) or revision not in accepted_revisions:
        raise ValueError("database preflight discovered an unsupported schema revision")
    if not isinstance(image_reference, str) or not image_reference.endswith(
        f"@{image_digest}"
    ):
        raise ValueError("database preflight image reference does not match its digest")
    return revision


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--execution-marker", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--accepted-revision", action="append", required=True)
    parser.add_argument("--github-output", required=True, type=Path)
    arguments = parser.parse_args(argv)

    try:
        revision = verify_preflight_logs(
            arguments.input.read_text(encoding="utf-8"),
            execution_marker=arguments.execution_marker,
            image_digest=arguments.image_digest,
            accepted_revisions=tuple(arguments.accepted_revision),
        )
        with arguments.github_output.open("a", encoding="utf-8") as output:
            output.write(f"revision={revision}\n")
    except (OSError, ValueError) as error:
        print(f"Migration preflight evidence verification failed: {error}", file=sys.stderr)
        return 1

    print(f"Verified database preflight schema revision {revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
