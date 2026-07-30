#!/usr/bin/env python3
"""Build and validate the sole runtime argument for controlled migrations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, Sequence


MAX_RUNTIME_ENVELOPE_BYTES = 4096
MAX_ACCEPTED_REVISIONS = 16
_REVISION_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_EXECUTION_MARKER_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")
_IMAGE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_MODE_FIELDS = {
    "preflight": frozenset(
        {
            "mode",
            "accept_current",
            "bootstrap",
            "execution_marker",
            "image_digest",
        }
    ),
    "migrate": frozenset(
        {
            "mode",
            "expected_head",
            "bootstrap",
            "execution_marker",
            "image_digest",
        }
    ),
}


class RuntimeEnvelopeError(ValueError):
    """The migration runtime envelope is malformed or unsafe."""


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise RuntimeEnvelopeError(
                f"migration runtime envelope contains duplicate key: {key}"
            )
        payload[key] = value
    return payload


def _reject_json_constant(value: str) -> object:
    raise RuntimeEnvelopeError(
        f"migration runtime envelope contains unsupported JSON constant: {value}"
    )


def validate_revision(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or not _REVISION_RE.fullmatch(value)
        or value.lower() in {"base", "head", "heads"}
    ):
        raise RuntimeEnvelopeError(
            f"migration runtime envelope {field} must be one exact safe revision"
        )
    return value


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _normalize_payload(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise RuntimeEnvelopeError("migration runtime envelope must be a JSON object")
    mode = payload.get("mode")
    if not isinstance(mode, str):
        raise RuntimeEnvelopeError("migration runtime envelope mode must be a string")
    expected_fields = _MODE_FIELDS.get(mode)
    if expected_fields is None:
        raise RuntimeEnvelopeError("migration runtime envelope mode is unsupported")
    actual_fields = set(payload)
    if actual_fields != expected_fields:
        missing = sorted(expected_fields - actual_fields)
        unknown = sorted(actual_fields - expected_fields)
        details: list[str] = []
        if missing:
            details.append("missing " + ",".join(missing))
        if unknown:
            details.append("unknown " + ",".join(unknown))
        raise RuntimeEnvelopeError(
            "migration runtime envelope fields are invalid: " + "; ".join(details)
        )

    bootstrap = payload["bootstrap"]
    if type(bootstrap) is not bool:
        raise RuntimeEnvelopeError(
            "migration runtime envelope bootstrap must be a boolean"
        )
    execution_marker = payload["execution_marker"]
    if not isinstance(execution_marker, str) or not _EXECUTION_MARKER_RE.fullmatch(
        execution_marker
    ):
        raise RuntimeEnvelopeError(
            "migration runtime envelope execution_marker is invalid"
        )
    image_digest = payload["image_digest"]
    if not isinstance(image_digest, str) or not _IMAGE_DIGEST_RE.fullmatch(
        image_digest
    ):
        raise RuntimeEnvelopeError(
            "migration runtime envelope image_digest must be immutable"
        )

    normalized: dict[str, object] = {
        "mode": mode,
        "bootstrap": bootstrap,
        "execution_marker": execution_marker,
        "image_digest": image_digest,
    }
    if mode == "preflight":
        accepted_payload = payload["accept_current"]
        if not isinstance(accepted_payload, list) or not (
            1 <= len(accepted_payload) <= MAX_ACCEPTED_REVISIONS
        ):
            raise RuntimeEnvelopeError(
                "migration runtime envelope accept_current must be a bounded nonempty list"
            )
        accepted = [
            validate_revision(item, field="accept_current")
            for item in accepted_payload
        ]
        if len(accepted) != len(set(accepted)):
            raise RuntimeEnvelopeError(
                "migration runtime envelope accept_current must be unique"
            )
        normalized["accept_current"] = accepted
    else:
        normalized["expected_head"] = validate_revision(
            payload["expected_head"], field="expected_head"
        )
    return normalized


def parse_runtime_envelope(raw: object) -> dict[str, object]:
    """Parse one canonical, duplicate-free, mode-specific runtime envelope."""
    if not isinstance(raw, str):
        raise RuntimeEnvelopeError("migration runtime envelope must be one string")
    try:
        encoded = raw.encode("utf-8")
    except UnicodeEncodeError as error:
        raise RuntimeEnvelopeError(
            "migration runtime envelope must be valid UTF-8"
        ) from error
    if not encoded or len(encoded) > MAX_RUNTIME_ENVELOPE_BYTES:
        raise RuntimeEnvelopeError("migration runtime envelope size is invalid")
    if not raw.startswith("{"):
        raise RuntimeEnvelopeError(
            "migration runtime envelope must begin with a JSON object"
        )
    try:
        payload = json.loads(
            raw,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_json_constant,
        )
    except RuntimeEnvelopeError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RuntimeEnvelopeError(
            "migration runtime envelope is not valid JSON"
        ) from error
    normalized = _normalize_payload(payload)
    if raw != _canonical_json(normalized):
        raise RuntimeEnvelopeError(
            "migration runtime envelope must use canonical JSON encoding"
        )
    return normalized


def build_runtime_envelope(
    *,
    mode: str,
    execution_marker: str,
    image_digest: str,
    bootstrap: bool = False,
    expected_head: str = "",
    accepted_current: Sequence[str] = (),
) -> str:
    """Build canonical JSON through typed values rather than shell interpolation."""
    payload: dict[str, object] = {
        "mode": mode,
        "bootstrap": bootstrap,
        "execution_marker": execution_marker,
        "image_digest": image_digest,
    }
    if mode == "preflight":
        if expected_head:
            raise RuntimeEnvelopeError(
                "preflight runtime envelope must not contain expected_head"
            )
        payload["accept_current"] = list(accepted_current)
    elif mode == "migrate":
        if accepted_current:
            raise RuntimeEnvelopeError(
                "migrate runtime envelope must not contain accept_current"
            )
        payload["expected_head"] = expected_head
    else:
        raise RuntimeEnvelopeError("migration runtime envelope mode is unsupported")
    canonical = _canonical_json(_normalize_payload(payload))
    parse_runtime_envelope(canonical)
    return canonical


def parse_container_args(payload: object) -> dict[str, object]:
    """Require an ACA/Kubernetes container to receive exactly one runtime arg."""
    if (
        not isinstance(payload, list)
        or len(payload) != 1
        or not isinstance(payload[0], str)
    ):
        raise RuntimeEnvelopeError(
            "migration container args must contain exactly one JSON envelope"
        )
    return parse_runtime_envelope(payload[0])


def containerapp_job_start_argv(
    *,
    job_name: str,
    resource_group: str,
    runtime_envelope: str,
    container_name: str = "",
    command: Sequence[str] = (),
) -> list[str]:
    """Construct the parser-sensitive Azure CLI argv without joining tokens."""
    if not job_name or not resource_group or any(
        character in job_name + resource_group for character in ("\0", "\n", "\r")
    ):
        raise ValueError("Container Apps Job identity is invalid")
    canonical = _canonical_json(parse_runtime_envelope(runtime_envelope))
    argv = [
        "az",
        "containerapp",
        "job",
        "start",
        "--name",
        job_name,
        "--resource-group",
        resource_group,
    ]
    if container_name:
        argv.extend(["--container-name", container_name])
    if command:
        if any(not isinstance(token, str) or not token for token in command):
            raise ValueError("Container Apps Job command is invalid")
        argv.extend(["--command", *command])
    argv.extend(["--args", canonical, "--query", "name", "--output", "tsv"])
    return argv


def _read_container_args(path: Path) -> object:
    raw = path.read_text(encoding="utf-8")
    if len(raw.encode("utf-8")) > MAX_RUNTIME_ENVELOPE_BYTES * 2:
        raise RuntimeEnvelopeError("migration container args document is oversized")
    try:
        return json.loads(
            raw,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_json_constant,
        )
    except RuntimeEnvelopeError:
        raise
    except json.JSONDecodeError as error:
        raise RuntimeEnvelopeError(
            "migration container args document is not valid JSON"
        ) from error


def _assert_expected_envelope(
    envelope: dict[str, object], arguments: argparse.Namespace
) -> None:
    expected: dict[str, Any] = {"mode": arguments.mode}
    if arguments.expected_head is not None:
        expected["expected_head"] = arguments.expected_head
    if arguments.accept_current:
        expected["accept_current"] = arguments.accept_current
    if arguments.execution_marker is not None:
        expected["execution_marker"] = arguments.execution_marker
    if arguments.image_digest is not None:
        expected["image_digest"] = arguments.image_digest
    if arguments.expected_bootstrap is not None:
        expected["bootstrap"] = arguments.expected_bootstrap == "true"
    mismatches = [
        field for field, value in expected.items() if envelope.get(field) != value
    ]
    if mismatches:
        raise RuntimeEnvelopeError(
            "migration runtime envelope provenance mismatch: "
            + ",".join(sorted(mismatches))
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build")
    build.add_argument("--mode", required=True, choices=tuple(_MODE_FIELDS))
    build.add_argument("--expected-head", default="")
    build.add_argument("--accept-current", action="append", default=[])
    build.add_argument("--bootstrap-empty-database", action="store_true")
    build.add_argument("--execution-marker", required=True)
    build.add_argument("--image-digest", required=True)

    validate = commands.add_parser("validate-container-args")
    validate.add_argument("--args-json", required=True, type=Path)
    validate.add_argument("--mode", required=True, choices=tuple(_MODE_FIELDS))
    validate.add_argument("--expected-head")
    validate.add_argument("--accept-current", action="append", default=[])
    validate.add_argument(
        "--expected-bootstrap",
        required=True,
        choices=("true", "false"),
    )
    validate.add_argument("--execution-marker")
    validate.add_argument("--image-digest", required=True)

    arguments = parser.parse_args(argv)
    if arguments.command == "build":
        if arguments.mode == "migrate" and (
            not arguments.expected_head or arguments.accept_current
        ):
            raise RuntimeEnvelopeError(
                "migrate envelope construction requires only expected_head"
            )
        if arguments.mode == "preflight" and (
            arguments.expected_head or not arguments.accept_current
        ):
            raise RuntimeEnvelopeError(
                "preflight envelope construction requires only accept_current"
            )
        print(
            build_runtime_envelope(
                mode=arguments.mode,
                expected_head=arguments.expected_head,
                accepted_current=arguments.accept_current,
                bootstrap=arguments.bootstrap_empty_database,
                execution_marker=arguments.execution_marker,
                image_digest=arguments.image_digest,
            )
        )
        return 0
    if arguments.execution_marker is None:
        raise RuntimeEnvelopeError(
            "migration runtime provenance validation requires an execution marker"
        )
    if arguments.mode == "migrate" and (
        arguments.expected_head is None or arguments.accept_current
    ):
        raise RuntimeEnvelopeError(
            "migrate provenance validation requires only expected_head"
        )
    if arguments.mode == "preflight" and (
        arguments.expected_head is not None or not arguments.accept_current
    ):
        raise RuntimeEnvelopeError(
            "preflight provenance validation requires only accept_current"
        )
    envelope = parse_container_args(_read_container_args(arguments.args_json))
    _assert_expected_envelope(envelope, arguments)
    print(_canonical_json(envelope))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())