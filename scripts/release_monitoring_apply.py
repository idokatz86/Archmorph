#!/usr/bin/env python3
"""Validate exact monitoring apply evidence, live queries, and email test results."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
from typing import Any

from verify_migration_alerts import attest_alerts
from verify_migration_bootstrap import _state_identity
from verify_release_monitoring import (
    ACTION_GROUP_NAME,
    ALERT_NAMES,
    OUTPUT_NAMES,
    _digest,
    _id,
    _load,
    _one,
    empty_monitoring_identity,
    validate_backend,
    validate_live_absence,
    validate_plan,
    validate_primary_ownership,
    validate_telemetry,
)


PLAN_WORKFLOW = ".github/workflows/release-monitoring-plan.yml"
PLAN_FILES = {
    "primary-init.log", "primary-state.json", "migration-init.log", "migration-state.json",
    "telemetry.json", "workspace.json", "live-resource-inventory.json", "monitoring-state-exists.json",
    "monitoring-before-init.json", "monitoring-init.log", "monitoring-state.json", "plan.log",
    "release-monitoring.tfplan", "plan.json", "plan.txt", "primary-current.json",
    "migration-current.json", "monitoring-current.json", "plan-metadata.json",
    "redacted-summary.json", "provider.lock.hcl", "migration-alert-specs.json", "query-evidence.json",
}


def approval() -> dict[str, str]:
    values = {
        "source_sha": os.environ["APPROVED_SOURCE_SHA"],
        "plan_sha256": os.environ["APPROVED_PLAN_SHA256"],
        "bundle_sha256": os.environ["APPROVED_BUNDLE_SHA256"],
        "run_id": os.environ["APPROVED_PLAN_RUN_ID"],
        "run_attempt": os.environ["APPROVED_PLAN_RUN_ATTEMPT"],
    }
    patterns = {
        "source_sha": r"[0-9a-f]{40}", "plan_sha256": r"[0-9a-f]{64}",
        "bundle_sha256": r"[0-9a-f]{64}", "run_id": r"[1-9][0-9]*", "run_attempt": r"[1-9][0-9]*",
    }
    if any(not re.fullmatch(patterns[key], value) for key, value in values.items()):
        raise ValueError("Exact monitoring plan approval identifiers are required")
    if (
        os.environ.get("CONFIRM_MONITORING_APPLY") != "true"
        or os.environ.get("GITHUB_REF") != "refs/heads/main"
        or os.environ.get("GITHUB_SHA") != values["source_sha"]
    ):
        raise ValueError("Monitoring apply requires explicit approval on the exact protected source")
    return values


def verify_bundle(path: Path, run: dict[str, Any]) -> None:
    expected = approval()
    if (
        str(run.get("id")) != expected["run_id"]
        or str(run.get("run_attempt")) != expected["run_attempt"]
        or run.get("head_sha") != expected["source_sha"]
        or run.get("head_branch") != "main"
        or run.get("path") != PLAN_WORKFLOW
        or run.get("event") != "workflow_dispatch"
        or run.get("status") != "completed" or run.get("conclusion") != "success"
    ):
        raise ValueError("Approved artifact must come from the exact successful protected planning run")
    if _digest(path) != expected["bundle_sha256"]:
        raise ValueError("Encrypted monitoring bundle does not match the approved hash")


def unpack_plan(archive_path: Path, destination: Path) -> None:
    """Only extract bounded, flat, regular files after ciphertext verification."""
    with tarfile.open(archive_path, "r:gz") as archive:
        files = []
        names: set[str] = set()
        size = 0
        for member in archive:
            path = PurePosixPath(member.name)
            if member.isdir() and str(path) == ".":
                continue
            if (
                not member.isfile() or member.issparse()
                or path.is_absolute() or ".." in path.parts
                or len(path.parts) != 1 or path.name not in PLAN_FILES
                or path.name in names
            ):
                raise ValueError("Monitoring review archive contains an unexpected or unsafe entry")
            names.add(path.name)
            size += member.size
            if member.size < 0 or size > 100 * 1024 * 1024 or len(names) > len(PLAN_FILES):
                raise ValueError("Monitoring review archive exceeds its size bound")
            files.append((member, path.name))
        required = {
            "release-monitoring.tfplan", "plan-metadata.json", "provider.lock.hcl",
            "migration-alert-specs.json", "query-evidence.json",
        }
        if not required <= names:
            raise ValueError("Monitoring review archive is missing required approval evidence")
        destination.mkdir(mode=0o700)
        for member, name in files:
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("Monitoring review archive entry could not be read")
            with source, (destination / name).open("xb") as target:
                shutil.copyfileobj(source, target)


def az_json(arguments: list[str], *, label: str) -> Any:
    try:
        result = subprocess.run(
            ["az", *arguments, "--only-show-errors", "--output", "json"],
            capture_output=True, text=True, check=False, timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"{label} did not complete: {type(exc).__name__}") from None
    if result.returncode:
        evidence_dir = os.environ.get("MONITORING_EVIDENCE_DIR")
        if evidence_dir:
            with (Path(evidence_dir) / "azure-errors.log").open("a", encoding="utf-8") as handle:
                handle.write(f"{label}: exit {result.returncode}\n{result.stderr}\n")
        raise RuntimeError(f"{label} failed with exit {result.returncode}; private diagnostics retained")
    return json.loads(result.stdout)


def query_count(payload: dict[str, Any], column: str) -> int:
    if not isinstance(payload, dict) or payload.get("error"):
        raise ValueError("Live monitoring query returned an error or partial result")
    tables = payload.get("tables")
    if not isinstance(tables, list):
        raise ValueError("Live monitoring query has no result tables")
    primary = _one([item for item in tables if item.get("name") == "PrimaryResult"], "query result")
    if primary.get("columns") != [{"name": column, "type": "long"}]:
        raise ValueError("Live monitoring query does not return the approved metric shape")
    rows = primary.get("rows")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], list) or len(rows[0]) != 1:
        raise ValueError("Live monitoring query must return one aggregate count")
    count = rows[0][0]
    if type(count) is not int or count < 0:
        raise ValueError("Live monitoring query count is invalid")
    return count


def _synthetic_events() -> str:
    records = []
    for event, execution, owner, application in (
        ("migration_failed", "failed", "platform-engineering", "archmorph"),
        ("migration_timed_out", "timeout", "platform-engineering", "archmorph"),
        ("bridge_customer_degraded", "degraded", "platform-engineering", "archmorph"),
        ("migration_started", "missing", "platform-engineering", "archmorph"),
        ("migration_started", "completed", "platform-engineering", "archmorph"),
        ("migration_succeeded", "completed", "platform-engineering", "archmorph"),
        ("migration_failed", "unrelated", "platform-engineering", "unrelated"),
        ("migration_timed_out", "unrelated", "unrelated", "archmorph"),
        ("bridge_customer_degraded", "unrelated", "unrelated", "archmorph"),
        ("migration_started", "unrelated", "unrelated", "archmorph"),
    ):
        dimensions = json.dumps({"application": application, "owner": owner, "execution": execution})
        records.append(f"{json.dumps(event)}, dynamic({dimensions})")
    return "let customEvents = datatable(name:string, customDimensions:dynamic)[" + ",".join(records) + "];\n"


def validate_queries(app: dict[str, Any], workspace: dict[str, Any], spec: Path) -> dict[str, Any]:
    validate_telemetry(app, workspace)
    specifications = _load(spec)["alerts"]
    if set(specifications) != set(ALERT_NAMES):
        raise ValueError("All four canonical monitoring queries must be validated")
    results = {}
    for role, definition in specifications.items():
        values = {}
        for kind, prefix in (("live", ""), ("synthetic", _synthetic_events())):
            response = az_json([
                "rest", "--method", "post", "--resource", "https://api.loganalytics.io",
                "--url", f"https://api.loganalytics.azure.com/v1{app['id']}/query",
                "--body", json.dumps({
                    "query": prefix + definition["query"], "timespan": definition["window_duration"],
                }),
            ], label=f"{role} {kind} monitoring query")
            values[kind] = query_count(response, definition["criteria"]["metric_measure_column"])
        if values["synthetic"] != 1:
            raise ValueError("Monitoring query did not preserve matched/excluded synthetic event semantics")
        results[role] = values
    return {"spec_sha256": _digest(spec), "scope": "application_insights", "queries": results}


def verify_saved_plan(evidence: Path, current: Path, root: Path) -> dict[str, Any]:
    expected = approval()
    validate_backend()
    metadata = _load(evidence / "plan-metadata.json")
    if (
        metadata.get("schema_version") != 2
        or metadata.get("purpose") != "review-only-not-approved-for-apply"
        or any(metadata.get(field) != expected[field] for field in ("source_sha", "plan_sha256", "run_id", "run_attempt"))
    ):
        raise ValueError("Saved monitoring plan metadata does not match explicit approval")
    planned_at = datetime.fromisoformat(metadata["planned_at"])
    now = datetime.now(timezone.utc)
    if planned_at.tzinfo is None or planned_at > now or now - planned_at > timedelta(days=7):
        raise ValueError("Monitoring plan approval evidence is expired or invalid")
    binary = evidence / "release-monitoring.tfplan"
    spec = root / "infra/monitoring/migration-alert-specs.json"
    lock = root / "infra/release-monitoring/.terraform.lock.hcl"
    if (
        _digest(binary) != expected["plan_sha256"]
        or _digest(lock) != metadata.get("provider_lock_sha256")
        or _digest(evidence / "provider.lock.hcl") != _digest(lock)
        or _digest(spec) != metadata.get("spec_sha256")
        or _digest(evidence / "migration-alert-specs.json") != _digest(spec)
    ):
        raise ValueError("Saved plan, provider lock, or canonical alert specification changed")
    backend_hash = hashlib.sha256(json.dumps([
        os.environ["MIGRATION_TFSTATE_STORAGE_ACCOUNT"],
        os.environ["MIGRATION_TFSTATE_CONTAINER"], os.environ["MONITORING_TFSTATE_KEY"],
    ]).encode()).hexdigest()
    if backend_hash != metadata.get("monitoring_backend_sha256"):
        raise ValueError("Approved monitoring state backend changed")
    for name in ("primary", "migration", "monitoring"):
        state_path = current / f"{name}-state.json"
        identity = _state_identity(state_path)
        if identity != metadata.get(f"{name}_state"):
            raise ValueError(f"{name} state changed after monitoring plan approval")
        if name == "monitoring":
            empty_monitoring_identity(state_path)
    validate_primary_ownership(_load(current / "primary-state.json"))
    validate_live_absence(_load(current / "live-resource-inventory.json"))
    query_evidence = _load(current / "query-evidence.json")
    if query_evidence.get("spec_sha256") != _digest(spec) or set(query_evidence.get("queries", {})) != set(ALERT_NAMES):
        raise ValueError("Current live query validation is missing")
    for value in query_evidence["queries"].values():
        if value.get("synthetic") != 1 or type(value.get("live")) is not int or value["live"] < 0:
            raise ValueError("Current live query validation failed")
    plan = _load(current / "plan.json")
    version = _load(current / "terraform-version.json")["terraform_version"]
    if plan.get("terraform_version") != version:
        raise ValueError("Terraform executable differs from the saved plan version")
    changes = validate_plan(
        plan, app=_load(current / "telemetry.json"), workspace=_load(current / "workspace.json"),
        expected_email=os.environ["TF_VAR_alert_email"], specification_path=spec,
    )
    if changes != metadata.get("changes"):
        raise ValueError("Saved monitoring plan change set differs from approval")
    return {
        "source_sha": expected["source_sha"], "plan_sha256": expected["plan_sha256"],
        "bundle_sha256": expected["bundle_sha256"], "changes": changes,
        "approved_by": os.environ["GITHUB_ACTOR"], "apply_run_id": os.environ["GITHUB_RUN_ID"],
    }


def expected_resource_ids(app: dict[str, Any]) -> dict[str, str]:
    prefix = _id(app["id"]).split("/providers/", 1)[0]
    return {
        "application_insights_resource_id": _id(app["id"]),
        "critical_action_group_id": prefix + "/providers/microsoft.insights/actiongroups/" + ACTION_GROUP_NAME,
        **{
            output: prefix + "/providers/microsoft.insights/scheduledqueryrules/" + ALERT_NAMES[role]
            for output, role in (
                ("migration_failure_alert_id", "failure"), ("migration_timeout_alert_id", "timeout"),
                ("migration_missing_evidence_alert_id", "missing_evidence"),
                ("bridge_customer_degraded_alert_id", "customer_degraded"),
            )
        },
    }


def validate_action_group(group: dict[str, Any], expected_id: str, email: str) -> None:
    properties = group.get("properties", {})
    if _id(group.get("id")) != expected_id or properties.get("enabled") is not True:
        raise ValueError("Applied action group identity or enabled state differs from approval")
    receiver = _one(properties.get("emailReceivers"), "approved email receiver")
    if (
        receiver.get("name") != "admin" or receiver.get("emailAddress") != email
        or receiver.get("useCommonAlertSchema") is not True
        or receiver.get("status") not in (None, "Enabled")
        or properties.get("groupShortName") != "archcrit"
    ):
        raise ValueError("Applied notification receiver differs from approval")
    if any(value for key, value in properties.items() if key.endswith("Receivers") and key != "emailReceivers"):
        raise ValueError("Applied action group has unapproved additional notification routes")


def attest_live(outputs: Path, app: dict[str, Any], spec: Path) -> dict[str, Any]:
    expected = expected_resource_ids(app)
    actual = _load(outputs)
    if set(actual) != OUTPUT_NAMES or any(_id(actual[name].get("value")) != value for name, value in expected.items()):
        raise ValueError("Applied monitoring outputs do not identify the five approved resources")
    inventory = []
    alert_ids = {}
    for role, name in ALERT_NAMES.items():
        resource_id = _id(app["id"]).split("/providers/", 1)[0] + "/providers/microsoft.insights/scheduledqueryrules/" + name
        alert_ids[role] = resource_id
        inventory.append(az_json([
            "rest", "--method", "get", "--url", f"https://management.azure.com{resource_id}?api-version=2023-12-01",
        ], label=f"Applied {role} alert read"))
    attest_alerts(
        inventory, expected_alert_ids=alert_ids,
        expected_scope_ids={"application_insights": app["id"]},
        expected_action_group_ids={"critical": expected["critical_action_group_id"]},
        specification_path=spec,
    )
    group = az_json([
        "rest", "--method", "get",
        "--url", f"https://management.azure.com{expected['critical_action_group_id']}?api-version=2023-01-01",
    ], label="Applied notification group read")
    validate_action_group(group, expected["critical_action_group_id"], os.environ["TF_VAR_alert_email"])
    return {"canonical_alerts_verified": 4, "approved_email_groups_verified": 1, "receiver_source": "ALERT_EMAIL"}


def notification_result(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("state") != "Completed":
        raise ValueError("Azure has not completed the approved notification test")
    detail = _one(payload.get("actionDetails"), "email notification result")
    if (
        detail.get("MechanismType") != "Email" or detail.get("Name") != "admin"
        or detail.get("Status") != "Completed" or not detail.get("SendTime")
    ):
        raise ValueError("Azure did not confirm completion of the approved email test")
    return {
        "azure_test_state": "Completed", "email_test_status": "Completed",
        "send_time": detail["SendTime"], "recipient_source": "ALERT_EMAIL",
        "recipient_inbox_receipt_confirmed": False,
    }


def test_email(app: dict[str, Any]) -> dict[str, Any]:
    group_id = expected_resource_ids(app)["critical_action_group_id"]
    group = az_json([
        "rest", "--method", "get",
        "--url", f"https://management.azure.com{group_id}?api-version=2023-01-01",
    ], label="Notification test receiver verification")
    validate_action_group(group, group_id, os.environ["TF_VAR_alert_email"])
    result = az_json([
        "monitor", "action-group", "test-notifications", "create",
        "--resource-group", os.environ["AZURE_RESOURCE_GROUP"], "--action-group", ACTION_GROUP_NAME,
        "--alert-type", "logalertv2", "--add-action", "email", "admin",
        os.environ["TF_VAR_alert_email"], "usecommonalertschema",
    ], label="Approved email test notification")
    return notification_result(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("approval")
    bundle = commands.add_parser("bundle")
    bundle.add_argument("--encrypted", type=Path, required=True)
    bundle.add_argument("--run", type=Path, required=True)
    unpack = commands.add_parser("unpack")
    unpack.add_argument("--archive", type=Path, required=True)
    unpack.add_argument("--destination", type=Path, required=True)
    query = commands.add_parser("queries")
    query.add_argument("--app", type=Path, required=True)
    query.add_argument("--workspace", type=Path, required=True)
    query.add_argument("--spec", type=Path, required=True)
    query.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--evidence", type=Path, required=True)
    verify.add_argument("--current", type=Path, required=True)
    verify.add_argument("--root", type=Path, default=Path("."))
    verify.add_argument("--output", type=Path, required=True)
    attest = commands.add_parser("attest")
    attest.add_argument("--outputs", type=Path, required=True)
    attest.add_argument("--app", type=Path, required=True)
    attest.add_argument("--spec", type=Path, required=True)
    attest.add_argument("--output", type=Path, required=True)
    notification = commands.add_parser("test-email")
    notification.add_argument("--app", type=Path, required=True)
    notification.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "approval":
        approval()
        print("Exact-source monitoring-only approval confirmed.")
    elif args.command == "bundle":
        verify_bundle(args.encrypted, _load(args.run))
        print("Exact successful plan run and approved ciphertext verified.")
    elif args.command == "unpack":
        unpack_plan(args.archive, args.destination)
        print("Bounded reviewed-plan files extracted safely.")
    else:
        if args.command == "queries":
            report = validate_queries(_load(args.app), _load(args.workspace), args.spec)
        elif args.command == "verify":
            report = verify_saved_plan(args.evidence, args.current, args.root)
        elif args.command == "attest":
            report = attest_live(args.outputs, _load(args.app), args.spec)
        else:
            approval()
            report = test_email(_load(args.app))
        args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
