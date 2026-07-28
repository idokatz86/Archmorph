#!/usr/bin/env python3
"""Deterministic Container Apps traffic and release-manifest helpers."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import shlex
import subprocess
from pathlib import Path


_DIGEST_RE = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")
_SCHEMA_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def canonical_traffic(items: list[dict]) -> list[dict[str, object]]:
    """Normalize an ingress traffic list without losing labels or weights."""
    normalized: list[dict[str, object]] = []
    for item in items:
        weight = int(item.get("weight", 0))
        label = str(item.get("label") or "")
        revision = str(item.get("revisionName") or "")
        latest = bool(item.get("latestRevision", False))
        if not 0 <= weight <= 100:
            raise ValueError("traffic weights must be between 0 and 100")
        if latest:
            if revision:
                raise ValueError("latest traffic entries must not name a revision")
            normalized.append({"latestRevision": True, "weight": weight, "label": label})
        else:
            if not _REVISION_RE.fullmatch(revision):
                raise ValueError("explicit traffic entries require a valid revision name")
            normalized.append({"revisionName": revision, "weight": weight, "label": label})
    normalized.sort(
        key=lambda item: (
            str(item.get("revisionName") or "latest"),
            str(item.get("label") or ""),
        )
    )
    if sum(int(item["weight"]) for item in normalized) != 100:
        raise ValueError("traffic weights must sum to 100")
    targets = [
        (
            str(item.get("revisionName") or "latest"),
            str(item.get("label") or ""),
        )
        for item in normalized
    ]
    labels = [str(item["label"]) for item in normalized if item.get("label")]
    if len(targets) != len(set(targets)) or len(labels) != len(set(labels)):
        raise ValueError("traffic revisions and labels must be unique")
    return normalized


def explicit_traffic(items: list[dict], *, latest_revision: str) -> list[dict[str, object]]:
    """Resolve latestRevision traffic to an immutable blue revision."""
    if not _REVISION_RE.fullmatch(latest_revision):
        raise ValueError("latest_revision must be an explicit Container Apps revision")
    resolved = []
    for item in canonical_traffic(items):
        if item.get("latestRevision"):
            item = {
                "revisionName": latest_revision,
                "weight": item["weight"],
                "label": item["label"],
            }
        resolved.append(item)
    return canonical_traffic(resolved)


def traffic_command(items: list[dict]) -> str:
    """Render one shell-safe exact traffic-set argument list."""
    revisions: list[str] = []
    labels: list[str] = []
    for item in canonical_traffic(items):
        target = "latest" if item.get("latestRevision") else str(item["revisionName"])
        argument = f"{target}={item['weight']}"
        label = str(item.get("label") or "")
        if label:
            labels.append(f"{label}={item['weight']}")
        else:
            revisions.append(argument)
    if not revisions and not labels:
        raise ValueError("traffic manifest cannot be empty")
    parts: list[str] = []
    if revisions:
        parts.extend(["--revision-weight", *revisions])
    if labels:
        parts.extend(["--label-weight", *labels])
    return " ".join(shlex.quote(part) for part in parts)


def apply_traffic(
    items: list[dict],
    *,
    name: str,
    resource_group: str,
    actual_output: Path | None = None,
) -> None:
    """Apply and verify an exact traffic manifest using argument-safe commands."""
    expected = canonical_traffic(items)
    command = [
        "az",
        "containerapp",
        "ingress",
        "traffic",
        "set",
        "--name",
        name,
        "--resource-group",
        resource_group,
    ]
    revisions: list[str] = []
    labels: list[str] = []
    for item in expected:
        target = "latest" if item.get("latestRevision") else str(item["revisionName"])
        weight = str(item["weight"])
        if item.get("label"):
            labels.append(f"{item['label']}={weight}")
        else:
            revisions.append(f"{target}={weight}")
    if revisions:
        command.extend(("--revision-weight", *revisions))
    if labels:
        command.extend(("--label-weight", *labels))
    subprocess.run(command, check=True)

    result = subprocess.run(
        [
            "az",
            "containerapp",
            "show",
            "--name",
            name,
            "--resource-group",
            resource_group,
            "--query",
            "properties.configuration.ingress.traffic",
            "-o",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    actual = json.loads(result.stdout)
    if canonical_traffic(actual) != expected:
        raise RuntimeError("traffic manifest mismatch after apply")
    if actual_output is not None:
        actual_output.write_text(json.dumps(actual, indent=2) + "\n", encoding="utf-8")


def write_manifest(
    path: Path,
    *,
    role: str,
    revision: str,
    image: str,
    source_sha: str,
    accepted_revisions: list[str],
) -> None:
    if role not in {"bridge", "final"}:
        raise ValueError("release role must be bridge or final")
    if not _REVISION_RE.fullmatch(revision) or not _DIGEST_RE.fullmatch(image):
        raise ValueError("release manifest requires an explicit revision and immutable image")
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("source_sha must be a full Git commit SHA")
    accepted = sorted(set(accepted_revisions))
    if not accepted or any(not _SCHEMA_RE.fullmatch(item) for item in accepted):
        raise ValueError("accepted schema revisions must be explicit")
    payload = {
        "schema_version": 1,
        "role": role,
        "revision": revision,
        "image": image,
        "source_sha": source_sha,
        "accepted_revisions": accepted,
    }
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    key = os.environ.get("RELEASE_MANIFEST_HMAC_KEY", "").encode()
    if len(key) < 32:
        raise ValueError("RELEASE_MANIFEST_HMAC_KEY must contain at least 32 bytes")
    payload["signature"] = "sha256=" + hmac.new(key, canonical, hashlib.sha256).hexdigest()
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify_manifest(path: Path, *, required_role: str) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    signature = str(payload.pop("signature", ""))
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    key = os.environ.get("RELEASE_MANIFEST_HMAC_KEY", "").encode()
    expected = "sha256=" + hmac.new(key, canonical, hashlib.sha256).hexdigest()
    if len(key) < 32 or not hmac.compare_digest(signature, expected):
        raise ValueError("release manifest signature is invalid")
    if payload.get("role") != required_role:
        raise ValueError("release manifest role is not allowed for this operation")
    if not _REVISION_RE.fullmatch(str(payload.get("revision") or "")):
        raise ValueError("release manifest revision is invalid")
    if not _DIGEST_RE.fullmatch(str(payload.get("image") or "")):
        raise ValueError("release manifest image is not immutable")
    if not re.fullmatch(r"[0-9a-f]{40}", str(payload.get("source_sha") or "")):
        raise ValueError("release manifest source SHA is invalid")
    accepted = payload.get("accepted_revisions")
    if (
        not isinstance(accepted, list)
        or not accepted
        or accepted != sorted(set(accepted))
        or any(not _SCHEMA_RE.fullmatch(str(item)) for item in accepted)
    ):
        raise ValueError("release manifest accepted revisions are invalid")
    return payload


def _json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    explicit = subparsers.add_parser("explicit-traffic")
    explicit.add_argument("--input", required=True, type=Path)
    explicit.add_argument("--latest-revision", required=True)
    explicit.add_argument("--output", required=True, type=Path)

    command = subparsers.add_parser("traffic-command")
    command.add_argument("--input", required=True, type=Path)

    apply = subparsers.add_parser("apply-traffic")
    apply.add_argument("--input", required=True, type=Path)
    apply.add_argument("--name", required=True)
    apply.add_argument("--resource-group", required=True)
    apply.add_argument("--actual-output", type=Path)

    compare = subparsers.add_parser("assert-traffic")
    compare.add_argument("--expected", required=True, type=Path)
    compare.add_argument("--actual", required=True, type=Path)

    manifest = subparsers.add_parser("write-release-manifest")
    manifest.add_argument("--output", required=True, type=Path)
    manifest.add_argument("--role", required=True)
    manifest.add_argument("--revision", required=True)
    manifest.add_argument("--image", required=True)
    manifest.add_argument("--source-sha", required=True)
    manifest.add_argument("--accepted-revision", action="append", required=True)

    verify = subparsers.add_parser("verify-release-manifest")
    verify.add_argument("--input", required=True, type=Path)
    verify.add_argument("--required-role", required=True)
    verify.add_argument("--field", choices=("revision", "image", "source_sha"))

    args = parser.parse_args()
    if args.command == "explicit-traffic":
        result = explicit_traffic(_json(args.input), latest_revision=args.latest_revision)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    elif args.command == "traffic-command":
        print(traffic_command(_json(args.input)))
    elif args.command == "apply-traffic":
        apply_traffic(
            _json(args.input),
            name=args.name,
            resource_group=args.resource_group,
            actual_output=args.actual_output,
        )
    elif args.command == "assert-traffic":
        if canonical_traffic(_json(args.expected)) != canonical_traffic(_json(args.actual)):
            raise SystemExit("traffic manifest mismatch")
    elif args.command == "write-release-manifest":
        write_manifest(
            args.output,
            role=args.role,
            revision=args.revision,
            image=args.image,
            source_sha=args.source_sha,
            accepted_revisions=args.accepted_revision,
        )
    else:
        payload = verify_manifest(args.input, required_role=args.required_role)
        print(payload[args.field] if args.field else json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())