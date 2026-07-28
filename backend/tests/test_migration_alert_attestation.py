"""Applied migration-alert attestation contracts."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_migration_alerts.py"
SPEC = importlib.util.spec_from_file_location("verify_migration_alerts", SCRIPT)
assert SPEC and SPEC.loader
alerts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(alerts)

ACTION_GROUP = "/subscriptions/example/resourceGroups/example/providers/Microsoft.Insights/actionGroups/platform"
IDS = {
    role: f"/subscriptions/example/resourceGroups/example/providers/Microsoft.Insights/scheduledQueryRules/{role}"
    for role in ("failure", "timeout", "missing_evidence")
}


def _alert(role: str, query: str, *, group: str = ACTION_GROUP) -> dict:
    return {
        "id": IDS[role],
        "properties": {
            "enabled": True,
            "criteria": {"allOf": [{"query": query}]},
            "actions": {"actionGroups": [group]},
        },
    }


def _inventory() -> list[dict]:
    return [
        _alert("failure", "AppEvents | where Name == 'migration_failed'"),
        _alert("timeout", "AppEvents | where Name == 'migration_timed_out'"),
        _alert(
            "missing_evidence",
            "AppEvents | where Name in ('migration_started', 'migration_succeeded')",
        ),
    ]


def test_applied_alert_attestation_passes_for_exact_ids_queries_and_action_group():
    evidence = alerts.attest_alerts(
        _inventory(),
        expected_alert_ids=IDS,
        expected_action_group_id=ACTION_GROUP,
    )
    assert evidence == IDS


def test_applied_alert_attestation_rejects_missing_alert():
    with pytest.raises(ValueError, match="timeout.*absent"):
        alerts.attest_alerts(
            _inventory()[:1] + _inventory()[2:],
            expected_alert_ids=IDS,
            expected_action_group_id=ACTION_GROUP,
        )


def test_applied_alert_attestation_rejects_miswired_action_group():
    inventory = _inventory()
    inventory[0] = _alert("failure", "migration_failed", group="/wrong/group")
    with pytest.raises(ValueError, match="wrong action group"):
        alerts.attest_alerts(
            inventory,
            expected_alert_ids=IDS,
            expected_action_group_id=ACTION_GROUP,
        )


def test_applied_alert_attestation_rejects_disabled_or_wrong_query():
    inventory = _inventory()
    inventory[2]["properties"]["enabled"] = False
    with pytest.raises(ValueError, match="disabled"):
        alerts.attest_alerts(
            inventory,
            expected_alert_ids=IDS,
            expected_action_group_id=ACTION_GROUP,
        )