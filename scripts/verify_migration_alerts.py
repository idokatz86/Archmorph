#!/usr/bin/env python3
"""Attest required migration alerts and their action-group wiring from Azure state JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


_REQUIRED_ALERTS = {
    "failure": ("migration_failed",),
    "timeout": ("migration_timed_out",),
    "missing_evidence": ("migration_started", "migration_succeeded"),
}


def _normalized_id(value: object) -> str:
    return str(value or "").rstrip("/").lower()


def _action_group_ids(alert: dict[str, Any]) -> set[str]:
    properties = alert.get("properties", {})
    actions = properties.get("actions") or properties.get("action") or {}
    groups = actions.get("actionGroups") or actions.get("action_groups") or []
    result: set[str] = set()
    for item in groups:
        if isinstance(item, str):
            result.add(_normalized_id(item))
        elif isinstance(item, dict):
            result.add(
                _normalized_id(
                    item.get("actionGroupId")
                    or item.get("action_group_id")
                    or item.get("id")
                )
            )
    return {item for item in result if item}


def _query(alert: dict[str, Any]) -> str:
    properties = alert.get("properties", {})
    criteria = properties.get("criteria", {})
    if isinstance(criteria, dict):
        conditions = criteria.get("allOf") or criteria.get("all_of") or []
        if conditions and isinstance(conditions[0], dict):
            return str(conditions[0].get("query") or "")
    return str(properties.get("query") or "")


def attest_alerts(
    alerts: list[dict[str, Any]],
    *,
    expected_alert_ids: dict[str, str],
    expected_action_group_id: str,
) -> dict[str, str]:
    """Require each exact applied alert ID, enabled state, query, and action group."""
    expected_group = _normalized_id(expected_action_group_id)
    if not expected_group:
        raise ValueError("expected migration action group resource ID is required")
    by_id = {_normalized_id(alert.get("id")): alert for alert in alerts}
    evidence: dict[str, str] = {}
    for role, query_markers in _REQUIRED_ALERTS.items():
        expected_id = _normalized_id(expected_alert_ids.get(role))
        if not expected_id:
            raise ValueError(f"expected {role} migration alert resource ID is required")
        alert = by_id.get(expected_id)
        if alert is None:
            raise ValueError(f"required {role} migration alert is absent from applied Azure state")
        properties = alert.get("properties", {})
        if properties.get("enabled") is not True:
            raise ValueError(f"required {role} migration alert is disabled")
        query = _query(alert)
        if not all(marker in query for marker in query_markers):
            raise ValueError(f"required {role} migration alert query is misconfigured")
        if expected_group not in _action_group_ids(alert):
            raise ValueError(f"required {role} migration alert targets the wrong action group")
        evidence[role] = str(alert["id"])
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alerts", required=True, type=Path)
    parser.add_argument("--failure-alert-id", required=True)
    parser.add_argument("--timeout-alert-id", required=True)
    parser.add_argument("--missing-evidence-alert-id", required=True)
    parser.add_argument("--action-group-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    alerts = json.loads(args.alerts.read_text(encoding="utf-8"))
    if not isinstance(alerts, list):
        raise ValueError("Azure alert inventory must be a JSON list")
    evidence = attest_alerts(
        alerts,
        expected_alert_ids={
            "failure": args.failure_alert_id,
            "timeout": args.timeout_alert_id,
            "missing_evidence": args.missing_evidence_alert_id,
        },
        expected_action_group_id=args.action_group_id,
    )
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("Applied migration alert state and action-group wiring verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
