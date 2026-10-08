"""Contracts for isolated, non-applying release-monitoring planning."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import re
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "verify_release_monitoring", ROOT / "scripts" / "verify_release_monitoring.py",
)
assert SPEC and SPEC.loader
monitoring = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitoring)
SPEC_PATH = ROOT / "infra/monitoring/migration-alert-specs.json"
PREFIX = "/subscriptions/example/resourceGroups/example-runtime"
APP = {
    "id": PREFIX + "/providers/Microsoft.Insights/components/example-insights",
    "location": "westeurope",
    "workspaceId": PREFIX + "/providers/Microsoft.OperationalInsights/workspaces/example-logs",
}
WORKSPACE = {"id": APP["workspaceId"], "location": "westeurope"}
EMAIL = "oncall@example.com"
ACTION_GROUP_ID = PREFIX + "/providers/Microsoft.Insights/actionGroups/archmorph-critical-alerts"


@pytest.fixture(autouse=True)
def approved_scope(monkeypatch):
    for name, value in {
        "AZURE_SUBSCRIPTION_ID": "example",
        "AZURE_RESOURCE_GROUP": "example-runtime",
        "MONITORING_APPLICATION_INSIGHTS_NAME": "example-insights",
        "MONITORING_WORKSPACE_NAME": "example-logs",
        "TFSTATE_STORAGE_ACCOUNT": "example-state",
        "TFSTATE_CONTAINER": "primary",
        "TFSTATE_KEY": "application.tfstate",
        "MIGRATION_TFSTATE_STORAGE_ACCOUNT": "example-state",
        "MIGRATION_TFSTATE_CONTAINER": "migration",
        "MIGRATION_TFSTATE_KEY": "migration.tfstate",
        "MONITORING_TFSTATE_KEY": "release-monitoring.tfstate",
    }.items():
        monkeypatch.setenv(name, value)


def _plan():
    specs = json.loads(SPEC_PATH.read_text())["alerts"]
    group = {
        "address": monitoring.ACTION_GROUP_ADDRESS,
        "type": "azurerm_monitor_action_group",
        "mode": "managed",
        "change": {
            "actions": ["create"], "after_unknown": {"id": True},
            "after": {
                "name": monitoring.ACTION_GROUP_NAME,
                "resource_group_name": "example-runtime",
                "location": "global",
                "short_name": "archcrit",
                "enabled": True,
                "email_receiver": [{"name": "admin", "email_address": EMAIL, "use_common_alert_schema": True}],
            },
        },
    }
    resources = [group]
    for role, spec in specs.items():
        criteria = {**spec["criteria"], "query": spec["query"]}
        criteria["failing_periods"] = [criteria["failing_periods"]]
        resources.append({
            "address": monitoring.ALERT_ADDRESSES[role],
            "type": "azurerm_monitor_scheduled_query_rules_alert_v2",
            "mode": "managed",
            "change": {
                "actions": ["create"], "after_unknown": {"id": True},
                "after": {
                    "name": monitoring.ALERT_NAMES[role],
                    "resource_group_name": "example-runtime", "location": "westeurope",
                    "auto_mitigation_enabled": True, "skip_query_validation": False,
                    "workspace_alerts_storage_enabled": False,
                    "enabled": spec["enabled"], "severity": spec["severity"],
                    "scopes": [APP["id"]], "evaluation_frequency": spec["evaluation_frequency"],
                    "window_duration": spec["window_duration"],
                    "criteria": [criteria], "action": [{"action_groups": [ACTION_GROUP_ID]}],
                },
            },
        })
    return {
        "resource_changes": resources,
        "configuration": {
            "root_module": {
                "resources": [{
                    "address": "azurerm_monitor_scheduled_query_rules_alert_v2.release",
                    "expressions": {"action": [{"action_groups": {
                        "references": ["local.critical_action_id"],
                    }}]},
                }],
            },
        },
        "output_changes": {name: {} for name in monitoring.OUTPUT_NAMES},
        "checks": [{"status": "pass"}],
    }


def _verify(plan):
    return monitoring.validate_plan(
        plan, app=APP, workspace=WORKSPACE, expected_email=EMAIL, specification_path=SPEC_PATH,
    )


def test_exact_canonical_five_create_plan_passes_without_disclosing_recipient():
    result = _verify(_plan())
    assert result == {
        "create": 5, "update": 0, "delete": 0,
        "roles": sorted(monitoring.ALERT_NAMES), "receiver_source": "ALERT_EMAIL",
    }
    assert EMAIL not in json.dumps(result)


@pytest.mark.parametrize("actions", [["delete"], ["update"], ["delete", "create"], ["no-op"], ["forget"]])
def test_initial_plan_rejects_every_non_create_operation(actions):
    plan = _plan()
    plan["resource_changes"][0]["change"]["actions"] = actions
    with pytest.raises(ValueError, match="five creates only"):
        _verify(plan)


@pytest.mark.parametrize("mode", ["extra", "missing", "duplicate"])
def test_plan_cannot_expand_or_reduce_approved_resource_set(mode):
    plan = _plan()
    if mode == "extra":
        extra = copy.deepcopy(plan["resource_changes"][0])
        extra["address"] = "azurerm_role_assignment.unapproved"
        extra["type"] = "azurerm_role_assignment"
        plan["resource_changes"].append(extra)
    elif mode == "missing":
        plan["resource_changes"].pop()
    else:
        plan["resource_changes"].append(copy.deepcopy(plan["resource_changes"][0]))
    with pytest.raises(ValueError):
        _verify(plan)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("severity", 3), ("enabled", False), ("skip_query_validation", True),
        ("auto_mitigation_enabled", False), ("workspace_alerts_storage_enabled", True),
        ("scopes", [WORKSPACE["id"]]), ("evaluation_frequency", "PT15M"),
        ("resource_group_name", "example-other"), ("location", "eastus"),
        ("identity", [{"type": "SystemAssigned"}]),
    ],
)
def test_plan_rejects_alert_scope_or_behavior_drift(field, value):
    plan = _plan()
    plan["resource_changes"][1]["change"]["after"][field] = value
    with pytest.raises(ValueError):
        _verify(plan)


@pytest.mark.parametrize("field", ["query", "threshold", "dimension", "metric_measure_column"])
def test_plan_reuses_canonical_kql_and_aggregation_contract(field):
    plan = _plan()
    criterion = plan["resource_changes"][1]["change"]["after"]["criteria"][0]
    criterion[field] = {
        "query": "AppEvents | where false | count",
        "threshold": 5,
        "dimension": [{"name": "customer", "operator": "Include", "values": ["*"]}],
        "metric_measure_column": "Different",
    }[field]
    with pytest.raises(ValueError):
        _verify(plan)


def test_plan_rejects_unknown_security_relevant_values():
    plan = _plan()
    plan["resource_changes"][1]["change"]["after_unknown"]["severity"] = True
    with pytest.raises(ValueError, match="must be known"):
        _verify(plan)


def test_provider_computed_readonly_metadata_is_allowed():
    plan = _plan()
    for entry in plan["resource_changes"][1:]:
        entry["change"]["after_unknown"].update({
            "created_with_api_version": True,
            "is_a_legacy_log_analytics_rule": True,
            "is_workspace_alerts_storage_configured": True,
        })
    assert _verify(plan)["create"] == 5


def test_unknown_action_properties_do_not_hide_behind_new_group_id():
    plan = _plan()
    plan["resource_changes"][1]["change"]["after_unknown"]["action"] = [{"custom_properties": True}]
    with pytest.raises(ValueError, match="must be known"):
        _verify(plan)


@pytest.mark.parametrize("mode", ["different_email", "additional_receiver", "disabled_group", "external_group"])
def test_notification_contract_cannot_change_or_expand(mode):
    plan = _plan()
    group = plan["resource_changes"][0]["change"]["after"]
    if mode == "different_email":
        group["email_receiver"][0]["email_address"] = "unapproved@example.com"
    elif mode == "additional_receiver":
        group["webhook_receiver"] = [{"name": "unapproved", "service_uri": "https://example.com/hook"}]
    elif mode == "disabled_group":
        group["enabled"] = False
    else:
        plan["resource_changes"][1]["change"]["after"]["action"][0]["action_groups"] = [
            PREFIX + "/providers/Microsoft.Insights/actionGroups/unapproved",
        ]
    with pytest.raises(ValueError):
        _verify(plan)


def test_unexpected_provisioners_and_modules_fail_closed():
    for change in ("provisioner", "module"):
        plan = _plan()
        configuration = plan["configuration"]["root_module"]
        if change == "provisioner":
            configuration["resources"][0]["provisioners"] = [{"type": "local-exec"}]
        else:
            configuration["module_calls"] = {"unreviewed": {}}
        with pytest.raises(ValueError):
            _verify(plan)


def test_output_contract_cannot_silently_shrink():
    plan = _plan()
    plan["output_changes"].pop("critical_action_group_id")
    with pytest.raises(ValueError, match="six resource identities"):
        _verify(plan)


@pytest.mark.parametrize("groups", [None, [None], [], [ACTION_GROUP_ID, ACTION_GROUP_ID]])
def test_action_group_binding_must_be_concrete_and_single(groups):
    plan = _plan()
    plan["resource_changes"][1]["change"]["after"]["action"][0]["action_groups"] = groups
    with pytest.raises(ValueError):
        _verify(plan)


def test_unknown_action_group_id_is_not_accepted_as_a_plan_approval():
    plan = _plan()
    plan["resource_changes"][1]["change"]["after_unknown"]["action"] = [{"action_groups": True}]
    with pytest.raises(ValueError, match="must be known"):
        _verify(plan)


@pytest.fixture
def plan_files(tmp_path, monkeypatch):
    files = {
        name: tmp_path / name for name in (
            "input", "app", "workspace", "primary-state", "migration-state",
            "primary-current", "migration-current", "monitoring-existence",
            "plan-binary", "lock", "output",
        )
    }
    files["input"].write_text(json.dumps(_plan()))
    files["app"].write_text(json.dumps(APP))
    files["workspace"].write_text(json.dumps(WORKSPACE))
    for name in ("primary-state", "migration-state", "primary-current", "migration-current"):
        lineage = "primary" if name.startswith("primary") else "migration"
        files[name].write_text(json.dumps({"lineage": lineage, "serial": 7, "resources": []}))
    files["monitoring-existence"].write_text('{"exists":false}')
    files["plan-binary"].write_bytes(b"example reviewed binary")
    files["lock"].write_bytes(b"example pinned provider lock")
    for key, value in {
        "TF_VAR_alert_email": EMAIL, "GITHUB_SHA": "a" * 40,
        "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
    }.items():
        monkeypatch.setenv(key, value)
    arguments = ["verify_release_monitoring.py", "plan", "--spec", str(SPEC_PATH)]
    for name, path in files.items():
        arguments.extend([f"--{name}", str(path)])
    monkeypatch.setattr(sys, "argv", arguments)
    return files


def test_plan_cli_emits_review_only_identity_not_private_values(plan_files, capsys):
    monitoring.main()
    public_summary = json.loads(capsys.readouterr().out)
    evidence = json.loads(plan_files["output"].read_text())
    assert evidence["purpose"] == "review-only-not-approved-for-apply"
    assert evidence["monitoring_state_initially_absent"] is True
    assert evidence["primary_state"]["serial"] == 7
    assert evidence["migration_state"]["serial"] == 7
    assert len(evidence["plan_sha256"]) == 64
    assert public_summary["plan_sha256"] == evidence["plan_sha256"]
    assert EMAIL not in json.dumps(public_summary)
    assert APP["id"] not in json.dumps(public_summary)


@pytest.mark.parametrize("which", ["primary-current", "migration-current"])
def test_plan_cli_rejects_state_changed_during_plan(plan_files, which):
    path = plan_files[which]
    state = json.loads(path.read_text())
    state["serial"] += 1
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError, match="state changed"):
        monitoring.main()
    assert not plan_files["output"].exists()


def test_plan_cli_requires_explicit_unused_monitoring_key_evidence(plan_files):
    plan_files["monitoring-existence"].write_text('{"exists":true}')
    with pytest.raises(ValueError, match="unused state key"):
        monitoring.main()


def test_initial_plan_requires_confirmed_primary_ownership_absence():
    monitoring.validate_primary_ownership({"resources": []})
    for address in monitoring.LEGACY_ADDRESSES:
        resource_type, name = address.split(".", 1)
        with pytest.raises(ValueError, match="already owns"):
            monitoring.validate_primary_ownership({
                "resources": [{"type": resource_type, "name": name, "mode": "managed", "instances": []}],
            })


def test_resource_alias_cannot_hide_existing_primary_ownership():
    with pytest.raises(ValueError, match="already owns"):
        monitoring.validate_primary_ownership({"resources": [{
            "type": "azurerm_monitor_action_group", "name": "different_address",
            "instances": [{"attributes": {"name": monitoring.ACTION_GROUP_NAME}}],
        }]})


def test_preexisting_untracked_monitors_require_explicit_adoption():
    monitoring.validate_live_absence([])
    monitoring.validate_live_absence([{
        "name": "Application Insights Smart Detection", "type": "Microsoft.Insights/actionGroups",
    }])
    with pytest.raises(ValueError, match="adoption"):
        monitoring.validate_live_absence([{
            "name": monitoring.ACTION_GROUP_NAME.upper(), "type": "microsoft.insights/actiongroups",
        }])


def test_distinct_backend_key_reuses_existing_private_container():
    monitoring.validate_backend()


@pytest.mark.parametrize("key", ["migration.tfstate", "application.tfstate", "../bad.tfstate", ""])
def test_colliding_or_invalid_backend_identity_is_rejected(monkeypatch, key):
    monkeypatch.setenv("MONITORING_TFSTATE_KEY", key)
    with pytest.raises(ValueError):
        monitoring.validate_backend()


def test_existing_workspace_link_must_match_approved_telemetry():
    app = {**APP, "workspaceId": WORKSPACE["id"] + "-different"}
    with pytest.raises(ValueError, match="not linked"):
        monitoring.validate_telemetry(app, WORKSPACE)


def test_plan_workflow_is_manual_protected_exact_sha_and_cannot_apply():
    source = (ROOT / ".github/workflows/release-monitoring-plan.yml").read_text()
    workflow = yaml.safe_load(source)
    trigger = workflow.get("on", workflow.get(True))
    assert set(trigger) == {"workflow_dispatch"}
    assert set(trigger["workflow_dispatch"]["inputs"]) == {"source_sha"}
    job = workflow["jobs"]["monitoring-plan"]
    assert job["environment"] == "production"
    assert job["runs-on"] == "${{ fromJSON(vars.PRODUCTION_RUNNER_LABELS) }}"
    assert workflow["permissions"] == {"contents": "read", "id-token": "write"}
    guard = job["steps"][0]["run"]
    assert '"$GITHUB_REF" != "refs/heads/main"' in guard
    assert '"$GITHUB_SHA" != "$APPROVED_SOURCE_SHA"' in guard
    assert "terraform -chdir=infra/release-monitoring validate" in source
    assert "terraform -chdir=infra/release-monitoring plan" in source
    assert re.search(r"\bterraform(?:\s+-\S+)*\s+apply\b", source) is None
    assert "az containerapp" not in source
    assert "az keyvault secret" not in source
    assert "--target" not in source and "-target=" not in source
    upload = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact@"))
    assert upload["with"]["path"].endswith(".tar.gz.enc")
    assert upload["with"]["name"].endswith("${{ github.run_id }}-${{ github.run_attempt }}")
    assert "Remove plaintext plan and state evidence" in source
    for step in job["steps"]:
        if "uses" in step:
            assert re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", step["uses"]), (
                "Every action in the production OIDC planning job must be immutable"
            )


def test_monitoring_has_one_owner_and_primary_never_destroys_it():
    primary = (ROOT / "infra/main.tf").read_text()
    removals = (ROOT / "infra/release-monitoring-ownership.tf").read_text()
    assert 'data "azurerm_monitor_action_group" "critical"' in primary
    assert 'resource "azurerm_monitor_action_group" "critical"' not in primary
    for address in monitoring.LEGACY_ADDRESSES:
        assert f"from = {address}" in removals
        resource_type, name = address.split(".", 1)
        assert f'resource "{resource_type}" "{name}"' not in primary
    assert removals.count("destroy = false") == 5
