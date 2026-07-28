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
from typing import Any


_DIGEST_RE = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")
_SCHEMA_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_RELEASE_STAGES = (
    "captured",
    "baseline_attempted",
    "bridge_prepare_attempted",
    "bridge_route_attempted",
    "migration_attempted",
    "green_shift_attempted",
    "complete",
)


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
    total_weight = sum(int(item["weight"]) for item in normalized)
    if total_weight not in {0, 100}:
        raise ValueError("traffic weights must sum to 0 or 100")
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


def _explicit_traffic_manifest(
    items: list[dict], *, purpose: str
) -> list[dict[str, object]]:
    """Require a nonempty immutable traffic manifest for an executable action."""
    manifest = canonical_traffic(items)
    if not manifest:
        raise ValueError(f"{purpose} must not be empty")
    if any(item.get("latestRevision") for item in manifest):
        raise ValueError(f"{purpose} must not contain dynamic latest traffic")
    return manifest


def explicit_traffic(items: list[dict], *, latest_revision: str) -> list[dict[str, object]]:
    """Resolve latestRevision traffic to an immutable blue revision."""
    canonical = canonical_traffic(items)
    if any(item.get("latestRevision") for item in canonical) and not _REVISION_RE.fullmatch(
        latest_revision
    ):
        raise ValueError("latest_revision must be an explicit Container Apps revision")
    resolved: list[dict[str, object]] = []
    for item in canonical:
        if item.get("latestRevision"):
            item = {
                "revisionName": latest_revision,
                "weight": item["weight"],
                "label": item["label"],
            }
        existing = next(
            (
                candidate
                for candidate in resolved
                if candidate.get("revisionName") == item.get("revisionName")
                and candidate.get("label") == item.get("label")
            ),
            None,
        )
        if existing is None:
            resolved.append(item)
        else:
            existing["weight"] = int(existing["weight"]) + int(item["weight"])
    return canonical_traffic(resolved)


def authoritative_latest_revision(
    container_app: dict[str, Any],
    revision_states: list[dict[str, Any]],
) -> str:
    """Resolve latest traffic only from a corroborated latest-ready revision."""
    properties = container_app.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("Container App management response is missing properties")
    revision = str(properties.get("latestReadyRevisionName") or "")
    if not _REVISION_RE.fullmatch(revision):
        raise ValueError(
            "Container App management response has no authoritative latest-ready revision"
        )
    if not isinstance(revision_states, list):
        raise ValueError("Container App revision state must be a JSON list")
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for state in revision_states:
        if not isinstance(state, dict):
            continue
        state_properties = state.get("properties")
        if not isinstance(state_properties, dict):
            state_properties = {}
        state_name = str(state.get("name") or state_properties.get("name") or "")
        if state_name == revision:
            matches.append((state, state_properties))
    if len(matches) != 1:
        raise ValueError(
            "authoritative latest-ready revision is absent or duplicated in revision state"
        )
    state, state_properties = matches[0]
    active = state_properties.get("active", state.get("active"))
    if active is not True:
        raise ValueError("authoritative latest-ready revision is not active")
    readiness_contract = {
        "provisioningState": {"succeeded", "provisioned"},
        "runningState": {"running"},
        "healthState": {"healthy"},
    }
    for field, accepted in readiness_contract.items():
        value = state_properties.get(field, state.get(field))
        if value not in (None, "") and str(value).strip().lower() not in accepted:
            raise ValueError(
                f"authoritative latest-ready revision has unready {field}={value}"
            )
    return revision


def create_release_state(
    *,
    current_schema: str,
    migration_from: str,
    target_schema: str,
    baseline_traffic: list[dict],
    bridge_revision: str = "",
) -> dict[str, Any]:
    """Build the explicit branch contract used by rollout and cleanup steps."""
    for revision in (current_schema, migration_from, target_schema):
        if not _SCHEMA_RE.fullmatch(revision):
            raise ValueError("release state requires explicit schema revisions")
    baseline = _explicit_traffic_manifest(
        baseline_traffic,
        purpose="release recovery baseline",
    )
    if current_schema == migration_from and migration_from != target_schema:
        branch = "migration"
        if bridge_revision:
            if not _REVISION_RE.fullmatch(bridge_revision):
                raise ValueError("migration branch bridge revision is invalid")
            pre_green = canonical_traffic(
                [{"revisionName": bridge_revision, "weight": 100, "label": ""}]
            )
        else:
            pre_green = []
    elif current_schema == target_schema:
        if bridge_revision:
            raise ValueError("routine branch must not resolve or route a schema bridge")
        branch = "routine"
        pre_green = baseline
    else:
        raise ValueError("current schema is outside the reviewed rollout state machine")
    return {
        "schema_version": 2,
        "branch": branch,
        "initial_schema": current_schema,
        "migration_from": migration_from,
        "target_schema": target_schema,
        "bridge_revision": bridge_revision,
        "stage": "captured",
        "baseline_traffic": baseline,
        "pre_green_traffic": pre_green,
    }


def set_release_bridge(state: dict[str, Any], revision: str) -> dict[str, Any]:
    """Bind the verified immutable bridge to a captured migration branch."""
    if state.get("branch") != "migration":
        raise ValueError("only a migration release can bind a bridge")
    if not _REVISION_RE.fullmatch(revision):
        raise ValueError("bridge revision must be an explicit Container Apps revision")
    updated = dict(state)
    updated["bridge_revision"] = revision
    updated["pre_green_traffic"] = canonical_traffic(
        [{"revisionName": revision, "weight": 100, "label": ""}]
    )
    return updated


def mark_release_stage(state: dict[str, Any], stage: str) -> dict[str, Any]:
    """Advance a rollout state atomically; stage regressions are rejected."""
    if stage not in _RELEASE_STAGES:
        raise ValueError(f"unknown release stage: {stage}")
    current = str(state.get("stage") or "")
    if current not in _RELEASE_STAGES:
        raise ValueError("release state contains an invalid stage")
    if _RELEASE_STAGES.index(stage) < _RELEASE_STAGES.index(current):
        raise ValueError("release stage cannot move backwards")
    updated = dict(state)
    updated["stage"] = stage
    return updated


def recovery_decision(state: dict[str, Any], *, observed_schema: str) -> tuple[str, list[dict]]:
    """Choose the only schema-safe traffic action after an interrupted release."""
    stage = str(state.get("stage") or "")
    branch = str(state.get("branch") or "")
    if stage not in _RELEASE_STAGES or branch not in {"migration", "routine"}:
        raise ValueError("invalid release recovery state")
    if stage in {"captured", "complete"}:
        return "none", []
    baseline = _explicit_traffic_manifest(
        state.get("baseline_traffic", []),
        purpose="release recovery baseline",
    )
    if branch == "routine":
        if observed_schema and observed_schema != state.get("target_schema"):
            raise RuntimeError("routine release schema changed unexpectedly; retaining current traffic")
        return "restore_original", baseline
    if _RELEASE_STAGES.index(stage) < _RELEASE_STAGES.index("migration_attempted"):
        return "restore_original", baseline
    if observed_schema == state.get("migration_from"):
        return "restore_original", baseline
    if observed_schema == state.get("target_schema"):
        return "retain_bridge", _explicit_traffic_manifest(
            state.get("pre_green_traffic", []),
            purpose="bridge recovery target",
        )
    raise RuntimeError("migration outcome schema is unknown; retaining current traffic")


def recover_release(
    state: dict[str, Any],
    *,
    observed_schema: str,
    name: str,
    resource_group: str,
    evidence_output: Path,
) -> dict[str, Any]:
    """Apply and verify the schema-safe recovery target and record incident evidence."""
    try:
        action, target = recovery_decision(state, observed_schema=observed_schema)
    except Exception as error:
        evidence = {
            "schema_version": 1,
            "status": "manual_intervention_required",
            "action": "retain_current",
            "branch": state.get("branch"),
            "stage": state.get("stage"),
            "observed_schema": observed_schema or "unknown",
            "reason": str(error),
        }
        evidence_output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        raise
    if target:
        try:
            apply_traffic(target, name=name, resource_group=resource_group)
        except Exception as error:
            evidence = {
                "schema_version": 1,
                "status": "recovery_failed",
                "action": action,
                "branch": state["branch"],
                "stage": state["stage"],
                "observed_schema": observed_schema,
                "intended_traffic": target,
                "reason": str(error),
            }
            evidence_output.write_text(
                json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
            )
            raise
    evidence = {
        "schema_version": 1,
        "status": "recovered" if action == "restore_original" else "bridge_retained",
        "action": action,
        "branch": state["branch"],
        "stage": state["stage"],
        "observed_schema": observed_schema,
        "verified_traffic": target,
    }
    evidence_output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return evidence


def _write_json_atomic(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


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
    expected = _explicit_traffic_manifest(
        items,
        purpose="executable traffic manifest",
    )
    current_result = subprocess.run(
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
    current = canonical_traffic(json.loads(current_result.stdout))
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
    expected_targets = {
        (
            "latest" if item.get("latestRevision") else str(item["revisionName"]),
            str(item.get("label") or ""),
        ): int(item["weight"])
        for item in expected
    }
    current_targets = {
        (
            "latest" if item.get("latestRevision") else str(item["revisionName"]),
            str(item.get("label") or ""),
        )
        for item in current
    }
    for target, label in sorted(current_targets | set(expected_targets)):
        weight = str(expected_targets.get((target, label), 0))
        if label:
            labels.append(f"{label}={weight}")
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
    latest_source = explicit.add_mutually_exclusive_group(required=True)
    latest_source.add_argument("--latest-revision")
    latest_source.add_argument("--container-app", type=Path)
    explicit.add_argument("--revisions", type=Path)
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

    state = subparsers.add_parser("create-release-state")
    state.add_argument("--current-schema", required=True)
    state.add_argument("--migration-from", required=True)
    state.add_argument("--target-schema", required=True)
    state.add_argument("--baseline-traffic", required=True, type=Path)
    state.add_argument("--bridge-revision", default="")
    state.add_argument("--output", required=True, type=Path)
    state.add_argument("--pre-green-output", required=True, type=Path)

    mark = subparsers.add_parser("mark-stage")
    mark.add_argument("--state", required=True, type=Path)
    mark.add_argument("--stage", required=True, choices=_RELEASE_STAGES)

    bridge = subparsers.add_parser("set-bridge")
    bridge.add_argument("--state", required=True, type=Path)
    bridge.add_argument("--revision", required=True)
    bridge.add_argument("--pre-green-output", required=True, type=Path)

    recover = subparsers.add_parser("recover-release")
    recover.add_argument("--state", required=True, type=Path)
    recover.add_argument("--observed-schema", default="")
    recover.add_argument("--name", required=True)
    recover.add_argument("--resource-group", required=True)
    recover.add_argument("--evidence-output", required=True, type=Path)

    args = parser.parse_args()
    if args.command == "explicit-traffic":
        source_traffic = _json(args.input)
        if not isinstance(source_traffic, list):
            raise ValueError("traffic input must be a JSON list")
        latest_revision = args.latest_revision
        if args.container_app is not None:
            if args.revisions is None:
                raise ValueError(
                    "--revisions is required with --container-app to corroborate latest-ready state"
                )
            latest_revision = authoritative_latest_revision(
                _json(args.container_app),
                _json(args.revisions),
            )
        result = explicit_traffic(source_traffic, latest_revision=latest_revision)
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
    elif args.command == "create-release-state":
        payload = create_release_state(
            current_schema=args.current_schema,
            migration_from=args.migration_from,
            target_schema=args.target_schema,
            baseline_traffic=_json(args.baseline_traffic),
            bridge_revision=args.bridge_revision,
        )
        _write_json_atomic(args.output, payload)
        _write_json_atomic(args.pre_green_output, payload["pre_green_traffic"])
    elif args.command == "mark-stage":
        _write_json_atomic(args.state, mark_release_stage(_json(args.state), args.stage))
    elif args.command == "set-bridge":
        payload = set_release_bridge(_json(args.state), args.revision)
        _write_json_atomic(args.state, payload)
        _write_json_atomic(args.pre_green_output, payload["pre_green_traffic"])
    elif args.command == "recover-release":
        recover_release(
            _json(args.state),
            observed_schema=args.observed_schema,
            name=args.name,
            resource_group=args.resource_group,
            evidence_output=args.evidence_output,
        )
    else:
        payload = verify_manifest(args.input, required_role=args.required_role)
        print(payload[args.field] if args.field else json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())