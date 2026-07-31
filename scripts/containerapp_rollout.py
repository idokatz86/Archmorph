#!/usr/bin/env python3
"""Deterministic Container Apps traffic and release-manifest helpers."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


_DIGEST_RE = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
_CONTAINER_APP_RE = re.compile(r"^[a-z][a-z0-9-]{0,30}[a-z0-9]$")
_REVISION_SUFFIX_RE = re.compile(r"^[a-z][a-z0-9-]{0,61}[a-z0-9]$")
_REVISION_RE = re.compile(r"^[a-z][a-z0-9-]{0,61}[a-z0-9]$")
_SCHEMA_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_CONTROL_PLANE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._()/-]{0,259}$")
_EXECUTION_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,199}$")
_EXECUTION_MARKER_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")
_CONTROL_PLANE_TIMEOUT_SECONDS = 15
_TRAFFIC_TIMEOUT_SECONDS = 60
_TERMINAL_EXECUTION_STATUSES = {
    "succeeded": "Succeeded",
    "failed": "Failed",
    "stopped": "Stopped",
    "cancelled": "Cancelled",
    "canceled": "Cancelled",
}
_RELEASE_MANIFEST_SCHEMA_VERSION = 3
_SCHEMA_CONTRACT_FIELDS = (
    "contract_version",
    "migration_target_revision",
    "minimum_revision",
    "maximum_revision",
    "accepted_revisions",
    "alias_read_through_until",
)
_RELEASE_MANIFEST_FIELDS = {
    "schema_version",
    "role",
    "revision",
    "image",
    "image_digest",
    "source_sha",
    "observed_schema",
    "schema_contract",
    "schema_contract_digest",
    "build_provenance",
    "build_provenance_digest",
    "platform",
    "release_identity",
}
_RELEASE_STAGES = (
    "captured",
    "baseline_attempted",
    "bridge_prepare_attempted",
    "bridge_route_attempted",
    "migration_attempted",
    "green_shift_attempted",
    "complete",
)


def _release_provenance_module():
    """Load the sibling verifier when this file is imported by path in tests."""
    name = "archmorph_release_provenance"
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).with_name("release_provenance.py")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("release provenance verifier is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _migration_runtime_module():
    """Load the backend's stdlib-only runtime contract for workflow recovery."""
    name = "archmorph_migration_runtime_contract"
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).resolve().parents[1] / "backend" / "migration_runtime_contract.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("migration runtime contract verifier is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def canonical_traffic(items: list[dict]) -> list[dict[str, object]]:
    """Validate and normalize a complete ACA traffic response or manifest."""
    if not isinstance(items, list) or not items:
        raise ValueError("traffic must be a nonempty JSON list")
    normalized: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("traffic entries must be JSON objects")
        raw_weight = item.get("weight")
        if isinstance(raw_weight, bool) or not isinstance(raw_weight, int):
            raise ValueError("traffic entries require an integer weight")
        weight = raw_weight
        raw_label = item.get("label", "")
        if raw_label is not None and not isinstance(raw_label, str):
            raise ValueError("traffic labels must be strings")
        label = raw_label or ""
        raw_revision = item.get("revisionName", "")
        if raw_revision is not None and not isinstance(raw_revision, str):
            raise ValueError("traffic revision names must be strings")
        revision = raw_revision or ""
        raw_latest = item.get("latestRevision", False)
        if not isinstance(raw_latest, bool):
            raise ValueError("latestRevision must be a boolean")
        latest = raw_latest
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
    if total_weight != 100:
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


def containerapp_revision_name(app_name: str, revision_suffix: str) -> str:
    """Return the exact ACA revision identity or reject an unrepresentable suffix."""
    if not _CONTAINER_APP_RE.fullmatch(app_name) or "--" in app_name:
        raise ValueError("Container App name is invalid")
    if not _REVISION_SUFFIX_RE.fullmatch(revision_suffix) or "--" in revision_suffix:
        raise ValueError("Container Apps revision suffix is invalid")
    revision = f"{app_name}--{revision_suffix}"
    if len(revision) > 63 or not _REVISION_RE.fullmatch(revision):
        raise ValueError("Container Apps full revision name exceeds the 63-character contract")
    return revision


def resolve_exact_revision(expected: str, revision_states: object) -> dict[str, Any]:
    """Resolve one exact revision; substring and arbitrary-first discovery are forbidden."""
    if not _REVISION_RE.fullmatch(expected) or not isinstance(revision_states, list):
        raise ValueError("exact revision discovery input is invalid")
    matches = [
        state
        for state in revision_states
        if isinstance(state, dict) and state.get("name") == expected
    ]
    if len(matches) != 1:
        raise ValueError("exact Container Apps revision is absent or duplicated")
    return matches[0]


def effective_traffic(items: list[dict]) -> list[dict[str, object]]:
    """Return only traffic-bearing routes while still validating inert entries."""
    return [item for item in canonical_traffic(items) if int(item["weight"]) > 0]


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
    try:
        state = resolve_exact_revision(revision, revision_states)
    except ValueError as error:
        raise ValueError(
            "authoritative latest-ready revision is absent or duplicated in revision state"
        ) from error
    state_properties = state.get("properties")
    if not isinstance(state_properties, dict):
        raise ValueError("authoritative latest-ready revision state is missing properties")
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
        if value in (None, ""):
            raise ValueError(
                f"authoritative latest-ready revision is missing required {field} evidence"
            )
        if str(value).strip().lower() not in accepted:
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
        "schema_version": 3,
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


def _release_state_key() -> bytes:
    key = os.environ.get("RELEASE_MANIFEST_HMAC_KEY", "").encode()
    if len(key) < 32:
        raise ValueError("RELEASE_MANIFEST_HMAC_KEY must contain at least 32 bytes")
    return key


def sign_release_state(state: dict[str, Any]) -> dict[str, Any]:
    """Sign restart-critical rollout state with the release evidence key."""
    payload = {key: value for key, value in state.items() if key != "signature"}
    if payload.get("schema_version") != 3:
        raise ValueError("release state schema is not supported")
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    payload["signature"] = (
        "sha256=" + hmac.new(_release_state_key(), canonical, hashlib.sha256).hexdigest()
    )
    return payload


def verify_release_state(state: dict[str, Any]) -> dict[str, Any]:
    """Verify signed rollout state before any restart or recovery decision."""
    if not isinstance(state, dict):
        raise ValueError("release state must be a JSON object")
    payload = dict(state)
    signature = str(payload.pop("signature", ""))
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    expected = "sha256=" + hmac.new(
        _release_state_key(), canonical, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("release state signature is invalid")
    if payload.get("schema_version") != 3:
        raise ValueError("release state schema is not supported")
    if payload.get("stage") not in _RELEASE_STAGES:
        raise ValueError("release state contains an invalid stage")
    if payload.get("branch") not in {"migration", "routine"}:
        raise ValueError("release state contains an invalid branch")
    _explicit_traffic_manifest(
        payload.get("baseline_traffic", []),
        purpose="release recovery baseline",
    )
    pre_green = payload.get("pre_green_traffic", [])
    if pre_green:
        _explicit_traffic_manifest(pre_green, purpose="pre-green traffic")
    execution = payload.get("migration_execution")
    if execution is not None:
        if not isinstance(execution, dict):
            raise ValueError("migration execution evidence is malformed")
        _validate_control_plane_identity(
            job_name=str(execution.get("job_name") or ""),
            resource_group=str(execution.get("resource_group") or ""),
            execution_name=str(execution.get("execution_name") or ""),
        )
        image_digest = str(execution.get("image_digest") or "")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest):
            raise ValueError("migration execution image digest is invalid")
        terminal_status = str(execution.get("terminal_status") or "")
        if terminal_status and terminal_status not in set(
            _TERMINAL_EXECUTION_STATUSES.values()
        ):
            raise ValueError("migration terminal evidence is invalid")
        if not isinstance(execution.get("quiescence_verified", False), bool):
            raise ValueError("migration quiescence evidence is invalid")
    starting = payload.get("migration_starting")
    if starting is not None:
        if execution is not None or not isinstance(starting, dict):
            raise ValueError("migration start boundary is malformed")
        job_name = str(starting.get("job_name") or "")
        resource_group = str(starting.get("resource_group") or "")
        image_digest = str(starting.get("image_digest") or "")
        execution_marker = str(starting.get("execution_marker") or "")
        known_executions = starting.get("known_executions")
        if not _CONTROL_PLANE_NAME_RE.fullmatch(job_name):
            raise ValueError("migration Job name is invalid")
        if not _CONTROL_PLANE_NAME_RE.fullmatch(resource_group):
            raise ValueError("migration resource group is invalid")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest):
            raise ValueError("migration start boundary image digest is invalid")
        if not _EXECUTION_MARKER_RE.fullmatch(execution_marker):
            raise ValueError("migration execution marker is invalid")
        if (
            not isinstance(known_executions, list)
            or len(known_executions) > 1000
            or known_executions != sorted(set(known_executions))
            or any(
                not isinstance(name, str) or not _EXECUTION_NAME_RE.fullmatch(name)
                for name in known_executions
            )
        ):
            raise ValueError("migration start execution inventory is invalid")
    return payload


def _validate_control_plane_identity(
    *, job_name: str, resource_group: str, execution_name: str
) -> None:
    if not _CONTROL_PLANE_NAME_RE.fullmatch(job_name):
        raise ValueError("migration Job name is invalid")
    if not _CONTROL_PLANE_NAME_RE.fullmatch(resource_group):
        raise ValueError("migration resource group is invalid")
    if not _EXECUTION_NAME_RE.fullmatch(execution_name):
        raise ValueError("migration execution name is invalid")


def mark_migration_starting(
    state: dict[str, Any],
    *,
    job_name: str,
    resource_group: str,
    image_digest: str,
    execution_marker: str,
    known_executions: list[str],
) -> dict[str, Any]:
    """Persist a signed pre-start boundary before the irreversible CLI call."""
    if state.get("branch") != "migration" or state.get("stage") != "migration_attempted":
        raise ValueError("migration start boundary requires migration_attempted state")
    if not _CONTROL_PLANE_NAME_RE.fullmatch(job_name):
        raise ValueError("migration Job name is invalid")
    if not _CONTROL_PLANE_NAME_RE.fullmatch(resource_group):
        raise ValueError("migration resource group is invalid")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest):
        raise ValueError("migration start boundary requires an immutable image digest")
    if not _EXECUTION_MARKER_RE.fullmatch(execution_marker):
        raise ValueError("migration execution marker is invalid")
    if (
        len(known_executions) > 1000
        or any(
            not isinstance(name, str) or not _EXECUTION_NAME_RE.fullmatch(name)
            for name in known_executions
        )
    ):
        raise ValueError("migration start execution inventory is invalid")
    if state.get("migration_execution") is not None:
        raise ValueError("migration execution is already bound")
    updated = dict(state)
    updated["migration_starting"] = {
        "job_name": job_name,
        "resource_group": resource_group,
        "image_digest": image_digest,
        "execution_marker": execution_marker,
        "known_executions": sorted(set(known_executions)),
    }
    return updated


def resolve_migration_start_boundary(
    state_path: Path,
    *,
    evidence_output: Path,
) -> str:
    """Resolve a cancelled start only from exact marker/image/head evidence."""
    state = _read_release_state(state_path)
    starting = state.get("migration_starting")
    if not isinstance(starting, dict):
        raise ValueError("release state has no unresolved migration start boundary")
    job_name = str(starting["job_name"])
    resource_group = str(starting["resource_group"])
    marker = str(starting["execution_marker"])
    image_digest = str(starting["image_digest"])
    known = set(starting["known_executions"])
    listing = _control_plane_run(
        [
            "az",
            "containerapp",
            "job",
            "execution",
            "list",
            "--name",
            job_name,
            "--resource-group",
            resource_group,
            "--query",
            "[].name",
            "--output",
            "json",
        ]
    )
    if listing.returncode != 0:
        candidates: list[str] = []
        failure = "execution_inventory_query_failed"
    else:
        try:
            names = json.loads(listing.stdout)
        except json.JSONDecodeError:
            names = None
        if (
            not isinstance(names, list)
            or any(not isinstance(name, str) for name in names)
            or len(names) > 1000
        ):
            candidates = []
            failure = "execution_inventory_malformed"
        else:
            candidates = sorted(set(names) - known)
            failure = ""
    matches: list[str] = []
    if not failure and len(candidates) <= 10:
        for execution_name in candidates:
            if not _EXECUTION_NAME_RE.fullmatch(execution_name):
                failure = "execution_inventory_malformed"
                break
            details = _control_plane_run(
                [
                    "az",
                    "containerapp",
                    "job",
                    "execution",
                    "show",
                    "--job-execution-name",
                    execution_name,
                    "--name",
                    job_name,
                    "--resource-group",
                    resource_group,
                    "--query",
                    "{args:properties.template.containers[0].args,image:properties.template.containers[0].image}",
                    "--output",
                    "json",
                ]
            )
            if details.returncode != 0:
                failure = "execution_details_query_failed"
                break
            try:
                payload = json.loads(details.stdout)
            except json.JSONDecodeError:
                failure = "execution_details_malformed"
                break
            arguments = payload.get("args") if isinstance(payload, dict) else None
            image = payload.get("image") if isinstance(payload, dict) else None
            if not isinstance(arguments, list) or not isinstance(image, str):
                failure = "execution_details_malformed"
                break
            try:
                envelope = _migration_runtime_module().parse_container_args(arguments)
            except ValueError:
                failure = "execution_details_malformed"
                break
            if (
                envelope["mode"] == "migrate"
                and envelope["execution_marker"] == marker
                and envelope["expected_head"] == str(state["target_schema"])
                and envelope["image_digest"] == image_digest
                and envelope["bootstrap"] is False
                and image.endswith("@" + image_digest)
            ):
                matches.append(execution_name)
    elif not failure:
        failure = "too_many_new_executions"

    if failure or len(matches) != 1:
        evidence = {
            "schema_version": 1,
            "status": "recovery_required_start_outcome_ambiguous",
            "reason_class": failure or "exact_marker_match_not_unique",
            "candidate_count": len(candidates),
            "exact_match_count": len(matches),
        }
        _write_json_atomic(evidence_output, evidence)
        raise RuntimeError(
            "migration start outcome cannot be bound to one exact reviewed execution"
        )
    execution_name = matches[0]
    updated = set_migration_execution(
        state,
        job_name=job_name,
        resource_group=resource_group,
        execution_name=execution_name,
        image_digest=image_digest,
    )
    _write_release_state(state_path, updated)
    _write_json_atomic(
        evidence_output,
        {
            "schema_version": 1,
            "status": "exact_execution_resolved",
            "job_name": job_name,
            "execution_name": execution_name,
        },
    )
    return execution_name


def set_migration_execution(
    state: dict[str, Any],
    *,
    job_name: str,
    resource_group: str,
    execution_name: str,
    image_digest: str,
) -> dict[str, Any]:
    """Bind one exact execution to migration state before telemetry or polling."""
    if state.get("branch") != "migration" or state.get("stage") != "migration_attempted":
        raise ValueError("migration execution can only bind at migration_attempted")
    _validate_control_plane_identity(
        job_name=job_name,
        resource_group=resource_group,
        execution_name=execution_name,
    )
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest):
        raise ValueError("migration execution requires an immutable image digest")
    binding = {
        "job_name": job_name,
        "resource_group": resource_group,
        "execution_name": execution_name,
        "image_digest": image_digest,
        "terminal_status": "",
        "quiescence_verified": False,
    }
    existing = state.get("migration_execution")
    if existing is not None and existing != binding:
        raise ValueError("release state is already bound to a different migration execution")
    updated = dict(state)
    updated.pop("migration_starting", None)
    updated["migration_execution"] = binding
    return updated


def mark_migration_terminal(state: dict[str, Any], status: str) -> dict[str, Any]:
    """Persist exact terminal evidence used when ACA retention later omits execution."""
    canonical_status = _TERMINAL_EXECUTION_STATUSES.get(status.strip().lower())
    if canonical_status is None:
        raise ValueError("only an observed terminal execution status can be persisted")
    execution = state.get("migration_execution")
    if not isinstance(execution, dict):
        raise ValueError("release state has no exact migration execution")
    existing = str(execution.get("terminal_status") or "")
    if existing and existing != canonical_status:
        raise ValueError("migration terminal evidence cannot change")
    updated = dict(state)
    updated_execution = dict(execution)
    updated_execution["terminal_status"] = canonical_status
    updated["migration_execution"] = updated_execution
    return updated


def recovery_decision(state: dict[str, Any], *, observed_schema: str) -> tuple[str, list[dict]]:
    """Choose the only schema-safe traffic action after an interrupted release."""
    stage = str(state.get("stage") or "")
    branch = str(state.get("branch") or "")
    if stage not in _RELEASE_STAGES or branch not in {"migration", "routine"}:
        raise ValueError("invalid release recovery state")
    if stage in {"captured", "complete"}:
        return "none", []
    execution = state.get("migration_execution")
    if state.get("migration_starting") is not None:
        raise RuntimeError(
            "migration start outcome is ambiguous; retaining schema-compatible traffic"
        )
    if isinstance(execution, dict) and not execution.get("terminal_status"):
        raise RuntimeError(
            "migration execution quiescence is not proven; retaining schema-compatible traffic"
        )
    if isinstance(execution, dict) and execution.get("quiescence_verified") is not True:
        raise RuntimeError(
            "concurrent migration quiescence is not proven; retaining schema-compatible traffic"
        )
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
    status = {
        "restore_original": "recovered",
        "retain_bridge": "bridge_retained",
        "none": "no_action",
    }.get(action)
    if status is None:
        raise RuntimeError("release recovery selected an unsupported action")
    evidence = {
        "schema_version": 1,
        "status": status,
        "action": action,
        "branch": state["branch"],
        "stage": state["stage"],
        "observed_schema": observed_schema,
        "verified_traffic": target,
        "customer_mode": (
            "degraded_read_only" if action == "retain_bridge" else "normal"
        ),
        "page_owner": "platform-engineering" if action == "retain_bridge" else None,
    }
    evidence_output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return evidence


def _execution_binding(state: dict[str, Any]) -> dict[str, str] | None:
    execution = state.get("migration_execution")
    if execution is None:
        return None
    if not isinstance(execution, dict):
        raise ValueError("migration execution evidence is malformed")
    binding = {
        "job_name": str(execution.get("job_name") or ""),
        "resource_group": str(execution.get("resource_group") or ""),
        "execution_name": str(execution.get("execution_name") or ""),
        "image_digest": str(execution.get("image_digest") or ""),
        "terminal_status": str(execution.get("terminal_status") or ""),
    }
    _validate_control_plane_identity(
        job_name=binding["job_name"],
        resource_group=binding["resource_group"],
        execution_name=binding["execution_name"],
    )
    return binding


def _control_plane_run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            text=True,
            timeout=_CONTROL_PLANE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(arguments, 124, stdout="", stderr="")


def _status_from_output(output: str) -> str | None:
    values = [line.strip() for line in output.splitlines() if line.strip()]
    if not values:
        return None
    if len(values) != 1 or any(character.isspace() for character in values[0]):
        raise ValueError("execution status response is ambiguous")
    return values[0]


def observe_exact_execution(
    *, job_name: str, resource_group: str, execution_name: str
) -> dict[str, str]:
    """Read only one named execution, with an exact-name list fallback."""
    _validate_control_plane_identity(
        job_name=job_name,
        resource_group=resource_group,
        execution_name=execution_name,
    )
    show = _control_plane_run(
        [
            "az",
            "containerapp",
            "job",
            "execution",
            "show",
            "--job-execution-name",
            execution_name,
            "--name",
            job_name,
            "--resource-group",
            resource_group,
            "--query",
            "properties.status",
            "--output",
            "tsv",
        ]
    )
    if show.returncode == 0:
        try:
            status = _status_from_output(show.stdout)
        except ValueError:
            return {"kind": "cli_error", "error_class": "AmbiguousStatusResponse"}
        if status:
            return {"kind": "status", "status": status, "source": "show"}

    listing = _control_plane_run(
        [
            "az",
            "containerapp",
            "job",
            "execution",
            "list",
            "--name",
            job_name,
            "--resource-group",
            resource_group,
            "--query",
            f"[?name=='{execution_name}'].properties.status",
            "--output",
            "tsv",
        ]
    )
    if listing.returncode != 0:
        return {"kind": "cli_error", "error_class": "AzureCliExecutionQueryError"}
    try:
        status = _status_from_output(listing.stdout)
    except ValueError:
        return {"kind": "cli_error", "error_class": "AmbiguousStatusResponse"}
    if status is None:
        return {"kind": "missing"}
    return {"kind": "status", "status": status, "source": "list"}


def _terminal_status(observation: dict[str, str]) -> str | None:
    if observation.get("kind") != "status":
        return None
    return _TERMINAL_EXECUTION_STATUSES.get(
        str(observation.get("status") or "").strip().lower()
    )


def _safe_observation(observation: dict[str, str]) -> dict[str, str]:
    safe = {"kind": str(observation.get("kind") or "unknown")}
    if observation.get("status"):
        safe["status"] = str(observation["status"])
    if observation.get("error_class"):
        safe["error_class"] = str(observation["error_class"])
    return safe


def _write_execution_evidence(
    path: Path,
    *,
    status: str,
    binding: dict[str, str],
    observation: dict[str, str],
    stop_result: str = "not_required",
) -> dict[str, object]:
    evidence: dict[str, object] = {
        "schema_version": 1,
        "status": status,
        "job_name": binding["job_name"],
        "execution_name": binding["execution_name"],
        "observation": _safe_observation(observation),
        "stop_result": stop_result,
    }
    _write_json_atomic(path, evidence)
    return evidence


def supervise_migration_execution(
    state_path: Path,
    *,
    evidence_output: Path,
    max_attempts: int,
    poll_seconds: float,
) -> str:
    """Poll the bound execution and persist its exact terminal status."""
    if max_attempts < 1 or poll_seconds < 0:
        raise ValueError("migration supervision bounds are invalid")
    state = _read_release_state(state_path)
    binding = _execution_binding(state)
    if binding is None:
        raise ValueError("release state has no migration execution to supervise")
    last_observation: dict[str, str] = {"kind": "unknown"}
    for attempt in range(1, max_attempts + 1):
        last_observation = observe_exact_execution(
            job_name=binding["job_name"],
            resource_group=binding["resource_group"],
            execution_name=binding["execution_name"],
        )
        terminal = _terminal_status(last_observation)
        if terminal:
            state = mark_migration_terminal(state, terminal)
            _write_release_state(state_path, state)
            _write_execution_evidence(
                evidence_output,
                status="terminal_observed",
                binding=binding,
                observation=last_observation,
            )
            return terminal
        if (
            last_observation.get("kind") == "missing"
            and binding.get("terminal_status")
        ):
            _write_execution_evidence(
                evidence_output,
                status="terminal_retention_expired",
                binding=binding,
                observation=last_observation,
            )
            return binding["terminal_status"]
        if attempt < max_attempts and poll_seconds:
            time.sleep(poll_seconds)
    _write_execution_evidence(
        evidence_output,
        status="supervision_timed_out",
        binding=binding,
        observation=last_observation,
    )
    raise TimeoutError("exact migration execution did not reach a proven terminal state")


def _assert_no_unrelated_nonterminal_execution(binding: dict[str, str]) -> None:
    result = _control_plane_run(
        [
            "az",
            "containerapp",
            "job",
            "execution",
            "list",
            "--name",
            binding["job_name"],
            "--resource-group",
            binding["resource_group"],
            "--query",
            "[].{name:name,status:properties.status}",
            "--output",
            "json",
        ]
    )
    if result.returncode != 0:
        raise RuntimeError("concurrent migration execution state could not be queried")
    try:
        executions = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("concurrent migration execution response is malformed") from error
    if not isinstance(executions, list):
        raise RuntimeError("concurrent migration execution response is malformed")
    blockers = 0
    for execution in executions:
        if not isinstance(execution, dict):
            raise RuntimeError("concurrent migration execution response is malformed")
        name = execution.get("name")
        status = execution.get("status")
        if not isinstance(name, str) or not isinstance(status, str):
            raise RuntimeError("concurrent migration execution response is malformed")
        if name == binding["execution_name"]:
            continue
        if status.strip().lower() not in _TERMINAL_EXECUTION_STATUSES:
            blockers += 1
    if blockers:
        raise RuntimeError(
            "unrelated nonterminal migration execution exists; it was not stopped"
        )


def _complete_quiescence(
    state_path: Path,
    *,
    state: dict[str, Any],
    binding: dict[str, str],
    evidence_output: Path,
    observation: dict[str, str],
    stop_result: str,
) -> dict[str, object]:
    try:
        _assert_no_unrelated_nonterminal_execution(binding)
    except RuntimeError:
        evidence = _write_execution_evidence(
            evidence_output,
            status="recovery_required_concurrent_execution_not_quiescent",
            binding=binding,
            observation=observation,
            stop_result=stop_result,
        )
        evidence["concurrent_execution_status"] = "nonterminal_or_unknown"
        _write_json_atomic(evidence_output, evidence)
        raise
    updated = dict(state)
    execution = dict(updated["migration_execution"])
    execution["quiescence_verified"] = True
    updated["migration_execution"] = execution
    _write_release_state(state_path, updated)
    return _write_execution_evidence(
        evidence_output,
        status="quiesced",
        binding=binding,
        observation=observation,
        stop_result=stop_result,
    )


def quiesce_migration_execution(
    state_path: Path,
    *,
    evidence_output: Path,
    max_attempts: int,
    poll_seconds: float,
) -> dict[str, object]:
    """Stop only the bound execution and prove terminal state before recovery."""
    if max_attempts < 1 or poll_seconds < 0:
        raise ValueError("migration quiescence bounds are invalid")
    state = _read_release_state(state_path)
    if state.get("migration_starting") is not None:
        evidence = {
            "schema_version": 1,
            "status": "recovery_required_start_outcome_ambiguous",
            "stop_result": "not_attempted_without_exact_execution",
        }
        _write_json_atomic(evidence_output, evidence)
        raise RuntimeError(
            "migration start outcome is ambiguous; exact execution quiescence cannot be proven"
        )
    binding = _execution_binding(state)
    if binding is None:
        evidence = {
            "schema_version": 1,
            "status": "migration_not_started",
            "stop_result": "not_required",
        }
        _write_json_atomic(evidence_output, evidence)
        return evidence

    observation = observe_exact_execution(
        job_name=binding["job_name"],
        resource_group=binding["resource_group"],
        execution_name=binding["execution_name"],
    )
    terminal = _terminal_status(observation)
    if terminal:
        state = mark_migration_terminal(state, terminal)
        return _complete_quiescence(
            state_path,
            state=state,
            binding=binding,
            evidence_output=evidence_output,
            observation=observation,
            stop_result="not_required",
        )
    if observation.get("kind") == "missing" and binding.get("terminal_status"):
        result = _complete_quiescence(
            state_path,
            state=state,
            binding=binding,
            evidence_output=evidence_output,
            observation=observation,
            stop_result="not_required",
        )
        result["status"] = "quiesced_from_durable_terminal_evidence"
        _write_json_atomic(evidence_output, result)
        return result

    stop = _control_plane_run(
        [
            "az",
            "containerapp",
            "job",
            "stop",
            "--name",
            binding["job_name"],
            "--resource-group",
            binding["resource_group"],
            "--job-execution-name",
            binding["execution_name"],
        ]
    )
    stop_result = "accepted" if stop.returncode == 0 else "command_error"
    last_observation = observation
    for attempt in range(1, max_attempts + 1):
        last_observation = observe_exact_execution(
            job_name=binding["job_name"],
            resource_group=binding["resource_group"],
            execution_name=binding["execution_name"],
        )
        terminal = _terminal_status(last_observation)
        if terminal:
            state = mark_migration_terminal(state, terminal)
            return _complete_quiescence(
                state_path,
                state=state,
                binding=binding,
                evidence_output=evidence_output,
                observation=last_observation,
                stop_result=stop_result,
            )
        if (
            last_observation.get("kind") == "missing"
            and binding.get("terminal_status")
        ):
            result = _complete_quiescence(
                state_path,
                state=state,
                binding=binding,
                evidence_output=evidence_output,
                observation=last_observation,
                stop_result=stop_result,
            )
            result["status"] = "quiesced_from_durable_terminal_evidence"
            _write_json_atomic(evidence_output, result)
            return result
        if attempt < max_attempts and poll_seconds:
            time.sleep(poll_seconds)

    _write_execution_evidence(
        evidence_output,
        status="recovery_required_execution_not_quiesced",
        binding=binding,
        observation=last_observation,
        stop_result=stop_result,
    )
    raise RuntimeError(
        "exact migration execution quiescence could not be proven; recovery required"
    )


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            json.dump(payload, temporary, indent=2)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
        directory_fd = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _read_release_state(path: Path) -> dict[str, Any]:
    return verify_release_state(_json(path))


def _write_release_state(path: Path, state: dict[str, Any]) -> None:
    _write_json_atomic(path, sign_release_state(state))


def _strict_json(path: Path) -> object:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        payload: dict[str, object] = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError(f"JSON object contains duplicate key: {key}")
            payload[key] = value
        return payload

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_keys,
    )


def normalize_schema_contract(payload: object) -> dict[str, object]:
    """Validate and canonicalize the immutable application schema contract."""
    if not isinstance(payload, dict) or set(payload) != set(_SCHEMA_CONTRACT_FIELDS):
        raise ValueError("schema contract fields are incomplete or unexpected")
    if payload.get("contract_version") != 1:
        raise ValueError("schema contract version is unsupported")
    accepted_payload = payload.get("accepted_revisions")
    if not isinstance(accepted_payload, list) or not accepted_payload:
        raise ValueError("schema contract accepted revisions are missing")
    accepted = [str(item) for item in accepted_payload]
    if accepted != sorted(set(accepted)) or any(
        not _SCHEMA_RE.fullmatch(item) for item in accepted
    ):
        raise ValueError("schema contract accepted revisions are invalid")
    normalized: dict[str, object] = {
        "contract_version": 1,
        "migration_target_revision": str(
            payload.get("migration_target_revision") or ""
        ),
        "minimum_revision": str(payload.get("minimum_revision") or ""),
        "maximum_revision": str(payload.get("maximum_revision") or ""),
        "accepted_revisions": accepted,
        "alias_read_through_until": str(payload.get("alias_read_through_until") or ""),
    }
    for field in (
        "migration_target_revision",
        "minimum_revision",
        "maximum_revision",
        "alias_read_through_until",
    ):
        revision = str(normalized[field])
        if not _SCHEMA_RE.fullmatch(revision) or revision not in accepted:
            raise ValueError(f"schema contract {field} is not an accepted revision")
    return normalized


def schema_contract_digest(payload: object) -> str:
    """Return the canonical digest bound into release and runtime evidence."""
    contract = normalize_schema_contract(payload)
    canonical = json.dumps(contract, separators=(",", ":"), sort_keys=True).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _release_identity(
    *, repository: str, workflow: str, run_id: str, run_attempt: int
) -> dict[str, object]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("release repository identity is invalid")
    if (
        not workflow.strip()
        or len(workflow) > 256
        or any(character in workflow for character in "\r\n\0")
    ):
        raise ValueError("release workflow identity is invalid")
    if not re.fullmatch(r"[1-9][0-9]*", run_id):
        raise ValueError("release run ID is invalid")
    if (
        isinstance(run_attempt, bool)
        or not isinstance(run_attempt, int)
        or run_attempt < 1
    ):
        raise ValueError("release run attempt is invalid")
    return {
        "provider": "github-actions",
        "repository": repository,
        "workflow": workflow,
        "run_id": run_id,
        "run_attempt": run_attempt,
    }


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
    """Apply and verify exact traffic-bearing routes using argument-safe commands."""
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
        timeout=_TRAFFIC_TIMEOUT_SECONDS,
    )
    try:
        current_payload = json.loads(current_result.stdout)
        current = canonical_traffic(current_payload)
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise RuntimeError("current traffic response is malformed") from error
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
    def command_target(item: dict[str, object]) -> tuple[str, str]:
        label = str(item.get("label") or "")
        if label:
            return "label", label
        target = "latest" if item.get("latestRevision") else str(item["revisionName"])
        return "revision", target

    expected_targets = {command_target(item): int(item["weight"]) for item in expected}
    current_positive_targets = {
        command_target(item)
        for item in current
        if int(item["weight"]) > 0
    }
    current_labels = {
        str(item.get("label") or ""): (
            "latest" if item.get("latestRevision") else str(item.get("revisionName") or "")
        )
        for item in current
        if item.get("label") and int(item["weight"]) > 0
    }
    expected_labels = {
        str(item.get("label") or ""): (
            "latest" if item.get("latestRevision") else str(item.get("revisionName") or "")
        )
        for item in expected
        if item.get("label")
    }
    if any(
        current_labels[label] != expected_labels[label]
        for label in current_labels.keys() & expected_labels.keys()
    ):
        raise RuntimeError("traffic label binding changed ambiguously")
    for target_type, target in sorted(current_positive_targets | set(expected_targets)):
        weight = str(expected_targets.get((target_type, target), 0))
        if target_type == "label":
            labels.append(f"{target}={weight}")
        else:
            revisions.append(f"{target}={weight}")
    if revisions:
        command.extend(("--revision-weight", *revisions))
    if labels:
        command.extend(("--label-weight", *labels))
    subprocess.run(command, check=True, timeout=_TRAFFIC_TIMEOUT_SECONDS)

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
        timeout=_TRAFFIC_TIMEOUT_SECONDS,
    )
    try:
        actual = json.loads(result.stdout)
        actual_effective = effective_traffic(actual)
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise RuntimeError("post-apply traffic response is malformed") from error
    if actual_effective != effective_traffic(expected):
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
    schema_contract: object,
    observed_schema: str,
    repository: str,
    workflow: str,
    run_id: str,
    run_attempt: int,
    build_provenance: Path,
) -> None:
    if role not in {"bridge", "final"}:
        raise ValueError("release role must be bridge or final")
    if not _REVISION_RE.fullmatch(revision) or not _DIGEST_RE.fullmatch(image):
        raise ValueError(
            "release manifest requires an explicit revision and immutable image"
        )
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("source_sha must be a full Git commit SHA")
    contract = normalize_schema_contract(schema_contract)
    accepted = contract["accepted_revisions"]
    if not _SCHEMA_RE.fullmatch(observed_schema) or observed_schema not in accepted:
        raise ValueError("observed schema is not accepted by the release contract")
    if role == "final" and observed_schema != contract["migration_target_revision"]:
        raise ValueError("final release must observe its migration target revision")
    identity = _release_identity(
        repository=repository,
        workflow=workflow,
        run_id=run_id,
        run_attempt=run_attempt,
    )
    provenance_module = _release_provenance_module()
    build = provenance_module.verify_build_provenance(
        build_provenance,
        expected_role=role,
        expected_source_sha=source_sha,
        expected_repository=repository,
        expected_workflow="CI/CD",
        expected_workflow_path=".github/workflows/ci.yml",
        expected_contract=contract,
    )
    if build["image_digest"] != image.rsplit("@", 1)[1]:
        raise ValueError("release image digest does not match attested build provenance")
    payload = {
        "schema_version": _RELEASE_MANIFEST_SCHEMA_VERSION,
        "role": role,
        "revision": revision,
        "image": image,
        "image_digest": image.rsplit("@", 1)[1],
        "source_sha": source_sha,
        "observed_schema": observed_schema,
        "schema_contract": contract,
        "schema_contract_digest": schema_contract_digest(contract),
        "build_provenance": build,
        "build_provenance_digest": provenance_module.provenance_digest(build),
        "platform": build["platform"],
        "release_identity": identity,
    }
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    payload["signature"] = (
        "sha256="
        + hmac.new(_release_state_key(), canonical, hashlib.sha256).hexdigest()
    )
    _write_json_atomic(path, payload)


def verify_manifest(
    path: Path,
    *,
    required_role: str,
    expected_run_id: str | None = None,
    expected_run_attempt: int | None = None,
    expected_repository: str | None = None,
    expected_workflow: str | None = None,
) -> dict:
    loaded = _strict_json(path)
    if not isinstance(loaded, dict):
        raise ValueError("release manifest must be a JSON object")
    payload = dict(loaded)
    signature = str(payload.pop("signature", ""))
    if set(payload) != _RELEASE_MANIFEST_FIELDS:
        raise ValueError("release manifest fields are incomplete or unexpected")
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    expected = (
        "sha256="
        + hmac.new(_release_state_key(), canonical, hashlib.sha256).hexdigest()
    )
    if not hmac.compare_digest(signature, expected):
        raise ValueError("release manifest signature is invalid")
    if payload.get("schema_version") != _RELEASE_MANIFEST_SCHEMA_VERSION:
        raise ValueError("release manifest schema version is unsupported")
    if required_role not in {"bridge", "final"}:
        raise ValueError("required release manifest role is invalid")
    if payload.get("role") != required_role:
        raise ValueError("release manifest role is not allowed for this operation")
    if not _REVISION_RE.fullmatch(str(payload.get("revision") or "")):
        raise ValueError("release manifest revision is invalid")
    if not _DIGEST_RE.fullmatch(str(payload.get("image") or "")):
        raise ValueError("release manifest image is not immutable")
    if payload.get("image_digest") != str(payload["image"]).rsplit("@", 1)[1]:
        raise ValueError("release manifest image digest does not match its image")
    if not re.fullmatch(r"[0-9a-f]{40}", str(payload.get("source_sha") or "")):
        raise ValueError("release manifest source SHA is invalid")
    contract = normalize_schema_contract(payload.get("schema_contract"))
    if payload.get("schema_contract") != contract:
        raise ValueError("release manifest schema contract is not canonical")
    if payload.get("schema_contract_digest") != schema_contract_digest(contract):
        raise ValueError("release manifest schema contract digest is invalid")
    provenance_module = _release_provenance_module()
    build = provenance_module.validate_unsigned_build_provenance(
        payload.get("build_provenance")
    )
    if payload.get("build_provenance_digest") != provenance_module.provenance_digest(
        build
    ):
        raise ValueError("release manifest build provenance digest is invalid")
    if payload.get("platform") != build["platform"]:
        raise ValueError("release manifest platform does not match build provenance")
    if build["role"] != required_role:
        raise ValueError("release manifest build role does not match release role")
    if build["image_digest"] != payload["image_digest"]:
        raise ValueError("release manifest image digest does not match build provenance")
    if build["source_sha"] != payload["source_sha"]:
        raise ValueError("release manifest source SHA does not match build provenance")
    if build["schema_contract"] != contract:
        raise ValueError("release manifest schema contract does not match build provenance")
    observed = str(payload.get("observed_schema") or "")
    if observed not in contract["accepted_revisions"]:
        raise ValueError("release manifest observed schema is incompatible")
    if required_role == "final" and observed != contract["migration_target_revision"]:
        raise ValueError("final release manifest did not observe its target schema")
    identity_payload = payload.get("release_identity")
    if not isinstance(identity_payload, dict):
        raise ValueError("release manifest identity is missing")
    identity = _release_identity(
        repository=str(identity_payload.get("repository") or ""),
        workflow=str(identity_payload.get("workflow") or ""),
        run_id=str(identity_payload.get("run_id") or ""),
        run_attempt=identity_payload.get("run_attempt"),
    )
    if identity_payload != identity:
        raise ValueError("release manifest identity is not canonical")
    if build["source_repository"] != identity["repository"]:
        raise ValueError("release repository does not match build provenance")
    if build["workflow"] != "CI/CD" or build["workflow_path"] != ".github/workflows/ci.yml":
        raise ValueError("release build provenance workflow is not trusted")
    if expected_repository is not None and identity["repository"] != expected_repository:
        raise ValueError("release manifest repository does not match the selected source")
    if expected_workflow is not None and identity["workflow"] != expected_workflow:
        raise ValueError("release manifest workflow does not match the selected source")
    if expected_run_id is not None and identity["run_id"] != expected_run_id:
        raise ValueError("release manifest run ID does not match the selected run")
    if (
        expected_run_attempt is not None
        and identity["run_attempt"] != expected_run_attempt
    ):
        raise ValueError(
            "release manifest run attempt does not match the selected artifact"
        )
    return payload


def verify_runtime_compatibility(manifest: dict, runtime: object) -> str:
    """Verify runtime schema evidence against a signed manifest, not itself."""
    if not isinstance(runtime, dict):
        raise ValueError("runtime schema compatibility evidence must be an object")
    if runtime.get("status") != "compatible":
        raise ValueError("runtime reports an incompatible schema")
    if runtime.get("release_role") != manifest.get("role"):
        raise ValueError("runtime release role does not match signed evidence")
    contract = normalize_schema_contract(manifest.get("schema_contract"))
    for field in (
        "migration_target_revision",
        "minimum_revision",
        "maximum_revision",
        "accepted_revisions",
        "alias_read_through_until",
    ):
        if runtime.get(field) != contract[field]:
            raise ValueError(
                f"runtime schema contract field does not match evidence: {field}"
            )
    current = str(runtime.get("current_revision") or "")
    if current not in contract["accepted_revisions"]:
        raise ValueError("runtime current schema is outside the signed contract")
    return current


def verify_revision_target(
    manifest: dict,
    revision_payload: object,
    *,
    require_zero_traffic: bool,
) -> str:
    """Bind an ACA revision's immutable image/source/contract to signed evidence."""
    if not isinstance(revision_payload, dict):
        raise ValueError("revision evidence must be a JSON object")
    if revision_payload.get("name") != manifest.get("revision"):
        raise ValueError("revision name does not match signed evidence")
    properties = revision_payload.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("revision evidence is missing properties")
    template = properties.get("template")
    containers = template.get("containers") if isinstance(template, dict) else None
    if not isinstance(containers, list) or len(containers) != 1:
        raise ValueError("revision evidence must contain exactly one container")
    container = containers[0]
    if not isinstance(container, dict) or container.get("image") != manifest.get(
        "image"
    ):
        raise ValueError("revision image does not match signed evidence")
    env_payload = container.get("env")
    if not isinstance(env_payload, list):
        raise ValueError("revision environment metadata is missing")
    env: dict[str, str] = {}
    for item in env_payload:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError("revision environment metadata is malformed")
        name = item["name"]
        if name in env:
            raise ValueError("revision environment metadata contains duplicate names")
        if "value" in item:
            env[name] = str(item.get("value") or "")
    contract = normalize_schema_contract(manifest.get("schema_contract"))
    expected_env = {
        "ARCHMORPH_RELEASE_ROLE": str(manifest["role"]),
        "ARCHMORPH_SOURCE_SHA": str(manifest["source_sha"]),
        "ARCHMORPH_SCHEMA_CONTRACT_DIGEST": str(manifest["schema_contract_digest"]),
        "APP_SCHEMA_MIN_REVISION": str(contract["minimum_revision"]),
        "APP_SCHEMA_MAX_REVISION": str(contract["maximum_revision"]),
    }
    for name, value in expected_env.items():
        if env.get(name) != value:
            raise ValueError(
                f"revision metadata does not match signed evidence: {name}"
            )
    weight = properties.get("trafficWeight", 0)
    if require_zero_traffic and (
        isinstance(weight, bool) or not isinstance(weight, int) or weight != 0
    ):
        raise ValueError("rollback target must have zero traffic before preflight")
    fqdn = str(properties.get("fqdn") or "")
    if not fqdn or any(character.isspace() for character in fqdn):
        raise ValueError("revision evidence is missing a valid FQDN")
    return fqdn


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
    manifest.add_argument("--schema-contract", required=True, type=Path)
    manifest.add_argument("--observed-schema", required=True)
    manifest.add_argument("--repository", required=True)
    manifest.add_argument("--workflow", required=True)
    manifest.add_argument("--run-id", required=True)
    manifest.add_argument("--run-attempt", required=True, type=int)
    manifest.add_argument("--build-provenance", required=True, type=Path)

    verify = subparsers.add_parser("verify-release-manifest")
    verify.add_argument("--input", required=True, type=Path)
    verify.add_argument("--required-role", required=True)
    verify.add_argument("--expected-run-id")
    verify.add_argument("--expected-run-attempt", type=int)
    verify.add_argument("--expected-repository")
    verify.add_argument("--expected-workflow")
    verify.add_argument(
        "--field",
        choices=(
            "revision",
            "image",
            "image_digest",
            "source_sha",
            "observed_schema",
            "schema_contract_digest",
        ),
    )

    contract_digest = subparsers.add_parser("schema-contract-digest")
    contract_digest.add_argument("--input", required=True, type=Path)

    revision_name = subparsers.add_parser("revision-name")
    revision_name.add_argument("--app-name", required=True)
    revision_name.add_argument("--suffix", required=True)

    exact_revision = subparsers.add_parser("resolve-exact-revision")
    exact_revision.add_argument("--expected", required=True)
    exact_revision.add_argument("--revisions", required=True, type=Path)

    runtime = subparsers.add_parser("verify-runtime-compatibility")
    runtime.add_argument("--manifest", required=True, type=Path)
    runtime.add_argument("--runtime", required=True, type=Path)
    runtime.add_argument("--required-role", required=True)

    revision_target = subparsers.add_parser("verify-revision-target")
    revision_target.add_argument("--manifest", required=True, type=Path)
    revision_target.add_argument("--revision-json", required=True, type=Path)
    revision_target.add_argument("--required-role", required=True)
    revision_target.add_argument("--require-zero-traffic", action="store_true")

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

    verify_state = subparsers.add_parser("verify-release-state")
    verify_state.add_argument("--state", required=True, type=Path)
    verify_state.add_argument(
        "--field",
        choices=(
            "branch",
            "stage",
            "execution_name",
            "image_digest",
            "terminal_status",
            "start_boundary",
        ),
    )

    execution = subparsers.add_parser("record-migration-execution")
    execution.add_argument("--state", required=True, type=Path)
    execution.add_argument("--job-name", required=True)
    execution.add_argument("--resource-group", required=True)
    execution.add_argument("--execution-name", required=True)
    execution.add_argument("--image-digest", required=True)

    starting = subparsers.add_parser("mark-migration-starting")
    starting.add_argument("--state", required=True, type=Path)
    starting.add_argument("--job-name", required=True)
    starting.add_argument("--resource-group", required=True)
    starting.add_argument("--image-digest", required=True)
    starting.add_argument("--execution-marker", required=True)
    starting.add_argument("--known-executions", required=True, type=Path)

    resolve_start = subparsers.add_parser("resolve-migration-start")
    resolve_start.add_argument("--state", required=True, type=Path)
    resolve_start.add_argument("--evidence-output", required=True, type=Path)

    supervise = subparsers.add_parser("supervise-migration")
    supervise.add_argument("--state", required=True, type=Path)
    supervise.add_argument("--evidence-output", required=True, type=Path)
    supervise.add_argument("--max-attempts", type=int, default=90)
    supervise.add_argument("--poll-seconds", type=float, default=10)

    quiesce = subparsers.add_parser("quiesce-migration")
    quiesce.add_argument("--state", required=True, type=Path)
    quiesce.add_argument("--evidence-output", required=True, type=Path)
    quiesce.add_argument("--max-attempts", type=int, default=60)
    quiesce.add_argument("--poll-seconds", type=float, default=5)

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
        if effective_traffic(_json(args.expected)) != effective_traffic(_json(args.actual)):
            raise SystemExit("traffic manifest mismatch")
    elif args.command == "write-release-manifest":
        write_manifest(
            args.output,
            role=args.role,
            revision=args.revision,
            image=args.image,
            source_sha=args.source_sha,
            schema_contract=_json(args.schema_contract),
            observed_schema=args.observed_schema,
            repository=args.repository,
            workflow=args.workflow,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            build_provenance=args.build_provenance,
        )
    elif args.command == "schema-contract-digest":
        print(schema_contract_digest(_json(args.input)))
    elif args.command == "revision-name":
        print(containerapp_revision_name(args.app_name, args.suffix))
    elif args.command == "resolve-exact-revision":
        print(json.dumps(resolve_exact_revision(args.expected, _json(args.revisions))))
    elif args.command == "verify-runtime-compatibility":
        signed = verify_manifest(args.manifest, required_role=args.required_role)
        print(verify_runtime_compatibility(signed, _json(args.runtime)))
    elif args.command == "verify-revision-target":
        signed = verify_manifest(args.manifest, required_role=args.required_role)
        print(
            verify_revision_target(
                signed,
                _json(args.revision_json),
                require_zero_traffic=args.require_zero_traffic,
            )
        )
    elif args.command == "create-release-state":
        payload = create_release_state(
            current_schema=args.current_schema,
            migration_from=args.migration_from,
            target_schema=args.target_schema,
            baseline_traffic=_json(args.baseline_traffic),
            bridge_revision=args.bridge_revision,
        )
        _write_release_state(args.output, payload)
        _write_json_atomic(args.pre_green_output, payload["pre_green_traffic"])
    elif args.command == "mark-stage":
        _write_release_state(
            args.state,
            mark_release_stage(_read_release_state(args.state), args.stage),
        )
    elif args.command == "set-bridge":
        payload = set_release_bridge(_read_release_state(args.state), args.revision)
        _write_release_state(args.state, payload)
        _write_json_atomic(args.pre_green_output, payload["pre_green_traffic"])
    elif args.command == "recover-release":
        recover_release(
            _read_release_state(args.state),
            observed_schema=args.observed_schema,
            name=args.name,
            resource_group=args.resource_group,
            evidence_output=args.evidence_output,
        )
    elif args.command == "verify-release-state":
        payload = _read_release_state(args.state)
        if args.field == "start_boundary":
            print("true" if payload.get("migration_starting") is not None else "false")
        elif args.field in {"execution_name", "image_digest", "terminal_status"}:
            execution_payload = _execution_binding(payload) or {}
            print(execution_payload.get(args.field, ""))
        elif args.field:
            print(payload[args.field])
        else:
            print(json.dumps(payload, sort_keys=True))
    elif args.command == "record-migration-execution":
        payload = set_migration_execution(
            _read_release_state(args.state),
            job_name=args.job_name,
            resource_group=args.resource_group,
            execution_name=args.execution_name,
            image_digest=args.image_digest,
        )
        _write_release_state(args.state, payload)
    elif args.command == "mark-migration-starting":
        known_executions = _json(args.known_executions)
        if not isinstance(known_executions, list):
            raise ValueError("known migration executions must be a JSON list")
        payload = mark_migration_starting(
            _read_release_state(args.state),
            job_name=args.job_name,
            resource_group=args.resource_group,
            image_digest=args.image_digest,
            execution_marker=args.execution_marker,
            known_executions=known_executions,
        )
        _write_release_state(args.state, payload)
    elif args.command == "resolve-migration-start":
        print(
            resolve_migration_start_boundary(
                args.state,
                evidence_output=args.evidence_output,
            )
        )
    elif args.command == "supervise-migration":
        print(
            supervise_migration_execution(
                args.state,
                evidence_output=args.evidence_output,
                max_attempts=args.max_attempts,
                poll_seconds=args.poll_seconds,
            )
        )
    elif args.command == "quiesce-migration":
        print(
            json.dumps(
                quiesce_migration_execution(
                    args.state,
                    evidence_output=args.evidence_output,
                    max_attempts=args.max_attempts,
                    poll_seconds=args.poll_seconds,
                ),
                sort_keys=True,
            )
        )
    else:
        payload = verify_manifest(
            args.input,
            required_role=args.required_role,
            expected_run_id=args.expected_run_id,
            expected_run_attempt=args.expected_run_attempt,
            expected_repository=args.expected_repository,
            expected_workflow=args.expected_workflow,
        )
        print(payload[args.field] if args.field else json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
