"""Applied migration-alert attestation contracts."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify_migration_alerts.py"
SPEC_PATH = ROOT / "infra" / "monitoring" / "migration-alert-specs.json"
SPEC = importlib.util.spec_from_file_location("verify_migration_alerts", SCRIPT)
assert SPEC and SPEC.loader
alerts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(alerts)

ACTION_GROUP = "/subscriptions/example/resourceGroups/example/providers/Microsoft.Insights/actionGroups/platform"
APP_INSIGHTS = "/subscriptions/example/resourceGroups/example/providers/Microsoft.Insights/components/archmorph"
IDS = {
    role: f"/subscriptions/example/resourceGroups/example/providers/Microsoft.Insights/scheduledQueryRules/{role}"
    for role in ("failure", "timeout", "missing_evidence")
}


def _specs() -> dict:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))["alerts"]


def _alert(role: str) -> dict:
    specification = _specs()[role]
    criteria = specification["criteria"]
    periods = criteria["failing_periods"]
    return {
        "id": IDS[role],
        "properties": {
            "enabled": specification["enabled"],
            "severity": specification["severity"],
            "scopes": [APP_INSIGHTS],
            "evaluationFrequency": specification["evaluation_frequency"],
            "windowSize": specification["window_duration"],
            "criteria": {
                "allOf": [
                    {
                        "query": specification["query"],
                        "timeAggregation": criteria["time_aggregation_method"],
                        "operator": criteria["operator"],
                        "threshold": criteria["threshold"],
                        "metricMeasureColumn": criteria["metric_measure_column"],
                        "failingPeriods": {
                            "minFailingPeriodsToAlert": periods[
                                "minimum_failing_periods_to_trigger_alert"
                            ],
                            "numberOfEvaluationPeriods": periods[
                                "number_of_evaluation_periods"
                            ],
                        },
                    }
                ]
            },
            "actions": {"actionGroups": [ACTION_GROUP]},
        },
    }


def _inventory() -> list[dict]:
    return [_alert(role) for role in IDS]


def _attest(inventory: list[dict]) -> dict[str, dict]:
    return alerts.attest_alerts(
        inventory,
        expected_alert_ids=IDS,
        expected_scope_ids={"application_insights": APP_INSIGHTS},
        expected_action_group_ids={"critical": ACTION_GROUP},
        specification_path=SPEC_PATH,
    )


def test_applied_alert_attestation_passes_exact_state_and_whitespace_only_kql_changes():
    inventory = _inventory()
    inventory[0]["properties"]["criteria"]["allOf"][0]["query"] = """
        AppEvents
          | where   Name == 'migration_failed'
        | where tostring(Properties['application']) == 'archmorph'
        | where tostring(Properties['owner']) == 'platform-engineering'
        | summarize FailureEvents = count()
    """

    evidence = _attest(inventory)
    assert {
        role: role_evidence["resource_id"] for role, role_evidence in evidence.items()
    } == IDS
    assert evidence["failure"]["canonical_state"]["query"].endswith(
        "| summarize FailureEvents = count()"
    )


def test_applied_alert_attestation_rejects_missing_alert():
    with pytest.raises(ValueError, match="timeout.*absent"):
        _attest(_inventory()[:1] + _inventory()[2:])


@pytest.mark.parametrize(
    ("field", "value", "drift"),
    [
        ("enabled", False, "enabled"),
        ("severity", 2, "severity"),
        (
            "scopes",
            ["/subscriptions/example/resourceGroups/wrong/providers/Microsoft.Insights/components/wrong"],
            "scopes",
        ),
        ("evaluationFrequency", "PT10M", "evaluation_frequency"),
        ("windowSize", "PT1H", "window_duration"),
    ],
)
def test_applied_alert_attestation_rejects_top_level_drift(field, value, drift):
    inventory = _inventory()
    inventory[0]["properties"][field] = value
    with pytest.raises(ValueError, match=drift):
        _attest(inventory)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("timeAggregation", "Average"),
        ("operator", "LessThan"),
        ("threshold", 1),
        ("metricMeasureColumn", "WrongColumn"),
        (
            "failingPeriods",
            {"minFailingPeriodsToAlert": 2, "numberOfEvaluationPeriods": 2},
        ),
    ],
)
def test_applied_alert_attestation_rejects_criteria_drift(field, value):
    inventory = _inventory()
    inventory[1]["properties"]["criteria"]["allOf"][0][field] = value
    with pytest.raises(ValueError, match="criteria"):
        _attest(inventory)


@pytest.mark.parametrize(
    "query_mutation",
    [
        lambda query: query + "\n| where false",
        lambda query: query.replace("migration_failed", "migration_succeeded"),
        lambda query: query.replace("platform-engineering", "other-owner"),
    ],
)
def test_applied_alert_attestation_rejects_semantically_inert_or_changed_kql(
    query_mutation,
):
    inventory = _inventory()
    condition = inventory[0]["properties"]["criteria"]["allOf"][0]
    condition["query"] = query_mutation(condition["query"])
    with pytest.raises(ValueError, match="query"):
        _attest(inventory)


def test_applied_alert_attestation_rejects_action_group_drift():
    inventory = _inventory()
    inventory[0]["properties"]["actions"]["actionGroups"] = ["/wrong/group"]
    with pytest.raises(ValueError, match="action_group_ids"):
        _attest(inventory)


def test_applied_alert_attestation_rejects_extra_scope_action_or_condition():
    for mutate, drift in (
        (
            lambda alert: alert["properties"]["scopes"].append("/extra/scope"),
            "scopes",
        ),
        (
            lambda alert: alert["properties"]["actions"]["actionGroups"].append(
                "/extra/group"
            ),
            "action_group_ids",
        ),
    ):
        inventory = copy.deepcopy(_inventory())
        mutate(inventory[0])
        with pytest.raises(ValueError, match=drift):
            _attest(inventory)

    inventory = _inventory()
    inventory[0]["properties"]["criteria"]["allOf"].append(
        copy.deepcopy(inventory[0]["properties"]["criteria"]["allOf"][0])
    )
    with pytest.raises(ValueError, match="exactly one criteria condition"):
        _attest(inventory)