#!/usr/bin/env python3
"""Fail-closed validation and redacted evidence for a five-resource monitoring plan."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from verify_migration_alerts import attest_alerts
from verify_migration_bootstrap import _state_identity, validate_backend_separation


ALERT_NAMES = {
    "failure": "archmorph-migration-job-failure",
    "timeout": "archmorph-migration-job-timeout",
    "missing_evidence": "archmorph-migration-missing-evidence",
    "customer_degraded": "archmorph-bridge-customer-degraded",
}
ACTION_GROUP_NAME = "archmorph-critical-alerts"
ACTION_GROUP_ADDRESS = "azurerm_monitor_action_group.critical"
ALERT_ADDRESSES = {
    role: f'azurerm_monitor_scheduled_query_rules_alert_v2.release["{role}"]'
    for role in ALERT_NAMES
}
LEGACY_ADDRESSES = {
    ACTION_GROUP_ADDRESS,
    "azurerm_monitor_scheduled_query_rules_alert_v2.migration_job_failure",
    "azurerm_monitor_scheduled_query_rules_alert_v2.migration_job_timeout",
    "azurerm_monitor_scheduled_query_rules_alert_v2.migration_missing_evidence",
    "azurerm_monitor_scheduled_query_rules_alert_v2.bridge_customer_degraded",
}
OUTPUT_NAMES = {
    "application_insights_resource_id",
    "critical_action_group_id",
    "migration_failure_alert_id",
    "migration_timeout_alert_id",
    "migration_missing_evidence_alert_id",
    "bridge_customer_degraded_alert_id",
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _id(value: object) -> str:
    if not isinstance(value, str) or not value.startswith("/subscriptions/"):
        raise ValueError("An explicit Azure resource identity is required")
    return value.rstrip("/").casefold()


def validate_backend() -> None:
    primary = tuple(os.environ[name] for name in (
        "TFSTATE_STORAGE_ACCOUNT", "TFSTATE_CONTAINER", "TFSTATE_KEY",
    ))
    migration = tuple(os.environ[name] for name in (
        "MIGRATION_TFSTATE_STORAGE_ACCOUNT", "MIGRATION_TFSTATE_CONTAINER", "MIGRATION_TFSTATE_KEY",
    ))
    monitoring = tuple(os.environ[name] for name in (
        "MIGRATION_TFSTATE_STORAGE_ACCOUNT", "MIGRATION_TFSTATE_CONTAINER", "MONITORING_TFSTATE_KEY",
    ))
    validate_backend_separation(primary=primary, bootstrap=monitoring)
    if monitoring == migration or monitoring[2] == migration[2]:
        raise ValueError("Monitoring state must not reuse the migration state key")
    if not re.fullmatch(r"[a-z0-9][a-z0-9/_.-]*\.tfstate", monitoring[2]):
        raise ValueError("Monitoring state key is invalid")
    if ".." in monitoring[2].split("/"):
        raise ValueError("Monitoring state key must not contain parent traversal")


def validate_telemetry(app: dict[str, Any], workspace: dict[str, Any]) -> None:
    if not isinstance(app, dict) or not isinstance(workspace, dict):
        raise ValueError("Telemetry metadata must be objects")
    component_id = _id(app.get("id"))
    workspace_id = _id(workspace.get("id"))
    prefix = "/subscriptions/" + os.environ["AZURE_SUBSCRIPTION_ID"].casefold()
    group = prefix + "/resourcegroups/" + os.environ["AZURE_RESOURCE_GROUP"].casefold()
    expected_app = group + "/providers/microsoft.insights/components/" + os.environ["MONITORING_APPLICATION_INSIGHTS_NAME"].casefold()
    expected_workspace = group + "/providers/microsoft.operationalinsights/workspaces/" + os.environ["MONITORING_WORKSPACE_NAME"].casefold()
    if component_id != expected_app or workspace_id != expected_workspace:
        raise ValueError("Telemetry inventory does not match the explicit approved scope")
    if _id(app.get("workspaceId")) != workspace_id:
        raise ValueError("Application Insights is not linked to the approved existing workspace")
    if not isinstance(app.get("location"), str) or not app["location"]:
        raise ValueError("Telemetry region is missing")


def validate_primary_ownership(state: dict[str, Any]) -> None:
    """An isolated initial plan cannot adopt or forget already-owned resources."""
    if not isinstance(state, dict) or not isinstance(state.get("resources"), list):
        raise ValueError("Primary state inventory is invalid")
    for resource in state["resources"]:
        if resource.get("mode", "managed") != "managed":
            continue
        address = f'{resource.get("type")}.{resource.get("name")}'
        names = [
            instance.get("attributes", {}).get("name")
            for instance in resource.get("instances", [])
        ]
        if address in LEGACY_ADDRESSES or any(
            name in {ACTION_GROUP_NAME, *ALERT_NAMES.values()} for name in names
        ):
            raise ValueError("Primary state already owns release monitoring; reviewed state transfer required")


def validate_live_absence(inventory: list[dict[str, Any]]) -> None:
    if not isinstance(inventory, list) or any(not isinstance(item, dict) for item in inventory):
        raise ValueError("Live monitoring inventory is invalid")
    names = {name.casefold() for name in (ACTION_GROUP_NAME, *ALERT_NAMES.values())}
    types = {"microsoft.insights/actiongroups", "microsoft.insights/scheduledqueryrules"}
    if any(
        str(item.get("type", "")).casefold() in types
        and str(item.get("name", "")).casefold() in names
        for item in inventory
    ):
        raise ValueError("Release monitoring already exists; reviewed adoption is required")


def empty_monitoring_identity(path: Path) -> dict[str, Any]:
    """Allow only Terraform's initialized, never-applied monitoring state."""
    identity = _state_identity(path)
    state = _load(path)
    if (
        type(state.get("version")) is not int or state["version"] != 4 or identity["serial"] != 0
        or state.get("resources") != [] or state.get("outputs") != {}
        or state.get("check_results") not in (None, [])
    ):
        raise ValueError("Monitoring state is not pristine; reviewed adoption is required")
    return identity


def _one(values: object, label: str) -> dict[str, Any]:
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise ValueError(f"Exactly one {label} is required")
    return values[0]


def _known_unknowns(value: dict[str, Any], allowed: set[str]) -> None:
    for key, unknown in value.items():
        if key in allowed:
            continue
        if _has_unknown(unknown):
            raise ValueError("Security-relevant monitoring plan values must be known before approval")


def _has_unknown(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_has_unknown(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_unknown(item) for item in value)
    return value is True


def validate_plan(
    plan: dict[str, Any],
    *,
    app: dict[str, Any],
    workspace: dict[str, Any],
    expected_email: str,
    specification_path: Path,
) -> dict[str, Any]:
    validate_telemetry(app, workspace)
    if not isinstance(expected_email, str) or not expected_email or expected_email.strip() != expected_email:
        raise ValueError("Approved ALERT_EMAIL is required")
    if not isinstance(plan.get("resource_changes"), list):
        raise ValueError("Monitoring plan has no resource change inventory")
    if plan.get("errored") or plan.get("complete") is False:
        raise ValueError("Monitoring plan is incomplete")
    _configuration_resources(plan)
    expected = {ACTION_GROUP_ADDRESS, *ALERT_ADDRESSES.values()}
    managed: dict[str, dict[str, Any]] = {}
    for entry in plan["resource_changes"]:
        address = entry.get("address")
        change = entry.get("change", {})
        if entry.get("mode") == "data":
            if (
                address not in {"data.azurerm_resources.application_insights", "data.azurerm_resources.workspace"}
                or entry.get("type") != "azurerm_resources"
                or change.get("actions") not in (["read"], ["no-op"])
            ):
                raise ValueError("Unexpected monitoring data source or mutation")
            continue
        if address not in expected or address in managed:
            raise ValueError("Monitoring plan contains an unexpected or duplicate managed resource")
        if change.get("actions") != ["create"] or entry.get("previous_address"):
            raise ValueError("Initial monitoring plan must contain five creates only, without replacement or adoption")
        if not isinstance(change.get("after"), dict):
            raise ValueError("Monitoring plan resource values are missing")
        managed[address] = entry
    if set(managed) != expected:
        raise ValueError("Initial monitoring plan must contain exactly four alerts and one action group")
    if any(check.get("status") != "pass" for check in plan.get("checks", [])):
        raise ValueError("Monitoring Terraform checks must all pass")

    group_entry = managed[ACTION_GROUP_ADDRESS]
    group = group_entry["change"]["after"]
    _known_unknowns(group_entry["change"].get("after_unknown", {}), {"id"})
    if (
        group_entry.get("type") != "azurerm_monitor_action_group"
        or group.get("name") != ACTION_GROUP_NAME
        or group.get("resource_group_name") != os.environ["AZURE_RESOURCE_GROUP"]
        or group.get("location", "").lower() != "global"
        or group.get("short_name") != "archcrit"
        or group.get("enabled") is not True
    ):
        raise ValueError("Action group differs from approved identity or enabled state")
    receiver = _one(group.get("email_receiver"), "email receiver")
    if receiver != {"name": "admin", "email_address": expected_email, "use_common_alert_schema": True}:
        raise ValueError("Notification recipient differs from the approved ALERT_EMAIL contract")
    if any(value for key, value in group.items() if key.endswith("_receiver") and key != "email_receiver"):
        raise ValueError("Additional notification receivers are not approved")

    prefix = _id(app["id"]).split("/providers/", 1)[0]
    action_id = prefix + "/providers/microsoft.insights/actiongroups/" + ACTION_GROUP_NAME
    expected_ids = {
        role: prefix + "/providers/microsoft.insights/scheduledqueryrules/" + name
        for role, name in ALERT_NAMES.items()
    }
    inventory = []
    for role, address in ALERT_ADDRESSES.items():
        entry = managed[address]
        values = entry["change"]["after"]
        unknowns = entry["change"].get("after_unknown", {})
        _known_unknowns(unknowns, {
            "id", "created_with_api_version",
            "is_a_legacy_log_analytics_rule", "is_workspace_alerts_storage_configured",
        })
        if (
            entry.get("type") != "azurerm_monitor_scheduled_query_rules_alert_v2"
            or values.get("name") != ALERT_NAMES[role]
            or values.get("resource_group_name") != os.environ["AZURE_RESOURCE_GROUP"]
            or values.get("location", "").replace(" ", "").lower() != app["location"].replace(" ", "").lower()
            or values.get("auto_mitigation_enabled") is not True
            or values.get("skip_query_validation") is not False
            or values.get("workspace_alerts_storage_enabled") is not False
            or values.get("identity")
        ):
            raise ValueError("Alert scope, behavior, or query validation differs from the approved plan")
        criterion = _one(values.get("criteria"), "alert criterion")
        if isinstance(criterion.get("threshold"), bool):
            raise ValueError("Alert threshold must be numeric, not a boolean")
        periods = _one(criterion.get("failing_periods"), "alert failing-period contract")
        if criterion.get("dimension") or criterion.get("resource_id_column"):
            raise ValueError("Unreviewed alert dimensionality is not allowed")
        action = _one(values.get("action"), "alert action")
        if action.get("custom_properties") or action.get("email_subject"):
            raise ValueError("Unreviewed alert actions are not allowed")
        groups = action.get("action_groups")
        if not isinstance(groups, list) or len(groups) != 1:
            raise ValueError("Exactly one reviewed alert action group is required")
        if _id(groups[0]) != action_id:
            raise ValueError("Alert targets an unexpected notification group")
        inventory.append({
            "id": expected_ids[role],
            "properties": {
                "enabled": values.get("enabled"),
                "severity": values.get("severity"),
                "scopes": values.get("scopes"),
                "evaluationFrequency": values.get("evaluation_frequency"),
                "windowSize": values.get("window_duration"),
                "criteria": {"allOf": [{
                    "query": criterion.get("query"),
                    "timeAggregation": criterion.get("time_aggregation_method"),
                    "operator": criterion.get("operator"),
                    "threshold": criterion.get("threshold"),
                    "metricMeasureColumn": criterion.get("metric_measure_column"),
                    "failingPeriods": {
                        "minFailingPeriodsToAlert": periods.get("minimum_failing_periods_to_trigger_alert"),
                        "numberOfEvaluationPeriods": periods.get("number_of_evaluation_periods"),
                    },
                }]},
                "actions": {"actionGroups": [action_id]},
            },
        })
    attest_alerts(
        inventory, expected_alert_ids=expected_ids,
        expected_scope_ids={"application_insights": app["id"]},
        expected_action_group_ids={"critical": action_id},
        specification_path=specification_path,
    )
    if set(plan.get("output_changes", {})) != OUTPUT_NAMES:
        raise ValueError("Monitoring output contract must contain exactly six resource identities")
    return {"create": 5, "update": 0, "delete": 0, "roles": sorted(ALERT_NAMES), "receiver_source": "ALERT_EMAIL"}


def _configuration_resources(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    configuration = plan.get("configuration", {}).get("root_module", {})
    if configuration.get("module_calls"):
        raise ValueError("Unexpected modules in the isolated monitoring root")
    resources = configuration.get("resources", [])
    if any(resource.get("provisioners") for resource in resources):
        raise ValueError("Monitoring plan must not execute provisioners")
    return {resource["address"]: resource for resource in resources}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("backend")
    empty = subparsers.add_parser("empty-state")
    empty.add_argument("--input", type=Path, required=True)
    inputs = subparsers.add_parser("inputs")
    inputs.add_argument("--app", type=Path, required=True)
    inputs.add_argument("--workspace", type=Path, required=True)
    inputs.add_argument("--primary-state", type=Path, required=True)
    inputs.add_argument("--inventory", type=Path, required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--input", type=Path, required=True)
    plan.add_argument("--app", type=Path, required=True)
    plan.add_argument("--workspace", type=Path, required=True)
    plan.add_argument("--primary-state", type=Path, required=True)
    plan.add_argument("--migration-state", type=Path, required=True)
    plan.add_argument("--primary-current", type=Path, required=True)
    plan.add_argument("--migration-current", type=Path, required=True)
    plan.add_argument("--monitoring-existence", type=Path, required=True)
    plan.add_argument("--monitoring-state", type=Path, required=True)
    plan.add_argument("--monitoring-current", type=Path, required=True)
    plan.add_argument("--monitoring-before-init", type=Path, required=True)
    plan.add_argument("--plan-binary", type=Path, required=True)
    plan.add_argument("--lock", type=Path, required=True)
    plan.add_argument("--spec", type=Path, required=True)
    plan.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "backend":
        validate_backend()
        print("Monitoring state identity is distinct from primary and migration state.")
    elif args.command == "empty-state":
        empty_monitoring_identity(args.input)
        print("Monitoring state is initialized but contains no resources, outputs, or apply history.")
    elif args.command == "inputs":
        validate_telemetry(_load(args.app), _load(args.workspace))
        validate_primary_ownership(_load(args.primary_state))
        validate_live_absence(_load(args.inventory))
        print("Existing telemetry linkage and unowned monitoring scope verified.")
    else:
        validate_backend()
        validate_primary_ownership(_load(args.primary_state))
        if (
            _state_identity(args.primary_state) != _state_identity(args.primary_current)
            or _state_identity(args.migration_state) != _state_identity(args.migration_current)
        ):
            raise ValueError("Primary or migration state changed during monitoring planning")
        existence = _load(args.monitoring_existence)
        if (
            not isinstance(existence, dict) or set(existence) != {"exists"}
            or not isinstance(existence["exists"], bool)
        ):
            raise ValueError("Initial monitoring planning requires explicit state-existence evidence")
        monitoring_identity = empty_monitoring_identity(args.monitoring_state)
        if existence["exists"] and monitoring_identity != empty_monitoring_identity(args.monitoring_before_init):
            raise ValueError("Monitoring state changed during initialization")
        if monitoring_identity != empty_monitoring_identity(args.monitoring_current):
            raise ValueError("Monitoring state changed during planning")
        result = validate_plan(
            _load(args.input), app=_load(args.app), workspace=_load(args.workspace),
            expected_email=os.environ["TF_VAR_alert_email"], specification_path=args.spec,
        )
        source = os.environ["GITHUB_SHA"]
        if not re.fullmatch(r"[0-9a-f]{40}", source):
            raise ValueError("Plan source must be an exact commit")
        metadata = {
            "schema_version": 2, "purpose": "review-only-not-approved-for-apply",
            "planned_at": datetime.now(timezone.utc).isoformat(),
            "source_sha": source, "plan_sha256": _digest(args.plan_binary),
            "provider_lock_sha256": _digest(args.lock), "spec_sha256": _digest(args.spec),
            "primary_state": _state_identity(args.primary_state),
            "migration_state": _state_identity(args.migration_state),
            "monitoring_state": monitoring_identity,
            "monitoring_state_exists_before_init": existence["exists"],
            "monitoring_backend_sha256": hashlib.sha256(json.dumps([
                os.environ["MIGRATION_TFSTATE_STORAGE_ACCOUNT"],
                os.environ["MIGRATION_TFSTATE_CONTAINER"],
                os.environ["MONITORING_TFSTATE_KEY"],
            ]).encode("utf-8")).hexdigest(),
            "run_id": os.environ["GITHUB_RUN_ID"], "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
            "changes": result,
        }
        args.output.write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"source_sha": source, "plan_sha256": metadata["plan_sha256"], "changes": result}))


if __name__ == "__main__":
    main()
