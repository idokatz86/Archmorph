#!/usr/bin/env python3
"""Attest applied migration alerts against reviewed canonical specifications."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


_REQUIRED_ROLES = ("failure", "timeout", "missing_evidence", "customer_degraded")
_REF_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _normalized_id(value: object) -> str:
    return str(value or "").strip().rstrip("/").lower()


def _canonical_query(value: object) -> str:
    """Normalize KQL layout while preserving operators, literals, and predicates."""
    lines = []
    for raw_line in str(value or "").replace("\r\n", "\n").split("\n"):
        line = " ".join(raw_line.strip().split())
        if line:
            lines.append(line)
    return "\n".join(lines)


def _required(properties: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in properties:
            return properties[name]
    raise ValueError(f"migration alert state is missing required field {names[0]}")


def _first(value: object) -> dict[str, Any]:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ValueError("migration alert must contain exactly one criteria condition")
    return value[0]


def _integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"migration alert {field} must be an integer")
    return value


def _action_group_ids(properties: dict[str, Any]) -> list[str]:
    actions = properties.get("actions") or properties.get("action")
    if not isinstance(actions, dict):
        raise ValueError("migration alert state is missing actions")
    groups = _required(actions, "actionGroups", "action_groups")
    if not isinstance(groups, list):
        raise ValueError("migration alert action groups must be a list")
    result: list[str] = []
    for item in groups:
        if isinstance(item, str):
            value = item
        elif isinstance(item, dict):
            value = (
                item.get("actionGroupId")
                or item.get("action_group_id")
                or item.get("id")
            )
        else:
            value = ""
        normalized = _normalized_id(value)
        if not normalized:
            raise ValueError("migration alert contains an empty action group ID")
        result.append(normalized)
    return sorted(result)


def _criterion(properties: dict[str, Any]) -> dict[str, Any]:
    criteria = _required(properties, "criteria")
    if not isinstance(criteria, dict):
        raise ValueError("migration alert criteria must be an object")
    return _first(_required(criteria, "allOf", "all_of"))


def _canonical_applied_alert(alert: dict[str, Any]) -> dict[str, Any]:
    properties = alert.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("migration alert state is missing properties")
    condition = _criterion(properties)
    failing_periods = _required(condition, "failingPeriods", "failing_periods")
    if not isinstance(failing_periods, dict):
        raise ValueError("migration alert failing periods must be an object")
    scopes = _required(properties, "scopes")
    if not isinstance(scopes, list) or not scopes:
        raise ValueError("migration alert scopes must be a nonempty list")
    normalized_scopes = sorted(_normalized_id(scope) for scope in scopes)
    if any(not scope for scope in normalized_scopes):
        raise ValueError("migration alert contains an empty scope ID")
    enabled = _required(properties, "enabled")
    if not isinstance(enabled, bool):
        raise ValueError("migration alert enabled must be a boolean")
    return {
        "scopes": normalized_scopes,
        "severity": _integer(_required(properties, "severity"), field="severity"),
        "enabled": enabled,
        "evaluation_frequency": str(
            _required(properties, "evaluationFrequency", "evaluation_frequency")
        ).upper(),
        "window_duration": str(
            _required(properties, "windowSize", "windowDuration", "window_duration")
        ).upper(),
        "query": _canonical_query(_required(condition, "query")),
        "criteria": {
            "time_aggregation_method": str(
                _required(
                    condition,
                    "timeAggregation",
                    "timeAggregationMethod",
                    "time_aggregation_method",
                )
            ).lower(),
            "operator": str(_required(condition, "operator")).lower(),
            "threshold": _required(condition, "threshold"),
            "metric_measure_column": str(
                _required(condition, "metricMeasureColumn", "metric_measure_column")
            ),
            "failing_periods": {
                "minimum_failing_periods_to_trigger_alert": _integer(
                    _required(
                        failing_periods,
                        "minFailingPeriodsToAlert",
                        "minimumFailingPeriodsToTriggerAlert",
                        "minimum_failing_periods_to_trigger_alert",
                    ),
                    field="minimum failing periods",
                ),
                "number_of_evaluation_periods": _integer(
                    _required(
                        failing_periods,
                        "numberOfEvaluationPeriods",
                        "number_of_evaluation_periods",
                    ),
                    field="number of evaluation periods",
                ),
            },
        },
        "action_group_ids": _action_group_ids(properties),
    }


def _load_reviewed_specs(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("alerts"), dict):
        raise ValueError("reviewed migration alert specification has an invalid schema")
    specifications = payload["alerts"]
    if set(specifications) != set(_REQUIRED_ROLES):
        raise ValueError(
            "reviewed migration alert specification must define exactly the required roles"
        )
    return specifications


def _resolve_refs(refs: object, values: dict[str, str], *, field: str) -> list[str]:
    if not isinstance(refs, list) or not refs:
        raise ValueError(f"reviewed migration alert {field} refs must be a nonempty list")
    resolved = []
    for ref in refs:
        if not isinstance(ref, str) or not _REF_RE.fullmatch(ref) or ref not in values:
            raise ValueError(f"reviewed migration alert contains an unresolved {field} ref")
        normalized = _normalized_id(values[ref])
        if not normalized:
            raise ValueError(f"reviewed migration alert {field} resource ID is required")
        resolved.append(normalized)
    return sorted(resolved)


def _canonical_expected_alert(
    specification: dict[str, Any],
    *,
    scope_ids: dict[str, str],
    action_group_ids: dict[str, str],
) -> dict[str, Any]:
    criteria = specification.get("criteria")
    if not isinstance(criteria, dict):
        raise ValueError("reviewed migration alert criteria must be an object")
    failing_periods = criteria.get("failing_periods")
    if not isinstance(failing_periods, dict):
        raise ValueError("reviewed migration alert failing periods must be an object")
    return {
        "scopes": _resolve_refs(specification.get("scope_refs"), scope_ids, field="scope"),
        "severity": int(specification["severity"]),
        "enabled": specification.get("enabled"),
        "evaluation_frequency": str(specification["evaluation_frequency"]).upper(),
        "window_duration": str(specification["window_duration"]).upper(),
        "query": _canonical_query(specification.get("query")),
        "criteria": {
            "time_aggregation_method": str(criteria["time_aggregation_method"]).lower(),
            "operator": str(criteria["operator"]).lower(),
            "threshold": criteria["threshold"],
            "metric_measure_column": str(criteria["metric_measure_column"]),
            "failing_periods": {
                "minimum_failing_periods_to_trigger_alert": int(
                    failing_periods["minimum_failing_periods_to_trigger_alert"]
                ),
                "number_of_evaluation_periods": int(
                    failing_periods["number_of_evaluation_periods"]
                ),
            },
        },
        "action_group_ids": _resolve_refs(
            specification.get("action_group_refs"),
            action_group_ids,
            field="action group",
        ),
    }


def attest_alerts(
    alerts: list[dict[str, Any]],
    *,
    expected_alert_ids: dict[str, str],
    expected_scope_ids: dict[str, str],
    expected_action_group_ids: dict[str, str],
    specification_path: Path,
) -> dict[str, dict[str, Any]]:
    """Require exact canonical applied state for every reviewed migration alert."""
    specifications = _load_reviewed_specs(specification_path)
    by_id = {_normalized_id(alert.get("id")): alert for alert in alerts}
    evidence: dict[str, dict[str, Any]] = {}
    for role in _REQUIRED_ROLES:
        expected_id = _normalized_id(expected_alert_ids.get(role))
        if not expected_id:
            raise ValueError(f"expected {role} migration alert resource ID is required")
        alert = by_id.get(expected_id)
        if alert is None:
            raise ValueError(f"required {role} migration alert is absent from applied Azure state")
        expected = _canonical_expected_alert(
            specifications[role],
            scope_ids=expected_scope_ids,
            action_group_ids=expected_action_group_ids,
        )
        actual = _canonical_applied_alert(alert)
        if actual != expected:
            drift = [field for field in expected if actual.get(field) != expected[field]]
            raise ValueError(
                f"required {role} migration alert differs from reviewed canonical state: "
                + ", ".join(drift)
            )
        evidence[role] = {
            "resource_id": str(alert["id"]),
            "canonical_state": actual,
        }
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alerts", required=True, type=Path)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--failure-alert-id", required=True)
    parser.add_argument("--timeout-alert-id", required=True)
    parser.add_argument("--missing-evidence-alert-id", required=True)
    parser.add_argument("--customer-degraded-alert-id", required=True)
    parser.add_argument("--application-insights-id", required=True)
    parser.add_argument("--action-group-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    inventory = json.loads(args.alerts.read_text(encoding="utf-8"))
    if not isinstance(inventory, list):
        raise ValueError("Azure alert inventory must be a JSON list")
    evidence = attest_alerts(
        inventory,
        expected_alert_ids={
            "failure": args.failure_alert_id,
            "timeout": args.timeout_alert_id,
            "missing_evidence": args.missing_evidence_alert_id,
            "customer_degraded": args.customer_degraded_alert_id,
        },
        expected_scope_ids={"application_insights": args.application_insights_id},
        expected_action_group_ids={"critical": args.action_group_id},
        specification_path=args.spec,
    )
    args.output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("Applied migration alerts match reviewed canonical specifications.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
