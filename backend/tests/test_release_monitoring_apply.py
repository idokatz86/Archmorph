"""Exact-plan authorization, live-query, extraction, and notification safeguards."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest
import yaml

from tests.test_release_monitoring_plan import APP, EMAIL, SPEC_PATH, WORKSPACE, _plan
from tests.test_migration_alert_attestation import _alert


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("release_monitoring_apply", ROOT / "scripts/release_monitoring_apply.py")
assert SPEC and SPEC.loader
operations = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(operations)


@pytest.fixture(autouse=True)
def approved_environment(monkeypatch):
    for key, value in {
        "AZURE_SUBSCRIPTION_ID": "example", "AZURE_RESOURCE_GROUP": "example-runtime",
        "MONITORING_APPLICATION_INSIGHTS_NAME": "example-insights", "MONITORING_WORKSPACE_NAME": "example-logs",
        "TFSTATE_STORAGE_ACCOUNT": "example-state", "TFSTATE_CONTAINER": "primary", "TFSTATE_KEY": "application.tfstate",
        "MIGRATION_TFSTATE_STORAGE_ACCOUNT": "example-state", "MIGRATION_TFSTATE_CONTAINER": "migration",
        "MIGRATION_TFSTATE_KEY": "migration.tfstate", "MONITORING_TFSTATE_KEY": "release-monitoring.tfstate",
        "TF_VAR_alert_email": EMAIL, "APPROVED_SOURCE_SHA": "a" * 40, "GITHUB_SHA": "a" * 40,
        "APPROVED_PLAN_SHA256": "b" * 64, "APPROVED_BUNDLE_SHA256": "c" * 64,
        "APPROVED_PLAN_RUN_ID": "123", "APPROVED_PLAN_RUN_ATTEMPT": "1",
        "GITHUB_REF": "refs/heads/main", "CONFIRM_MONITORING_APPLY": "true",
        "GITHUB_ACTOR": "example-owner", "GITHUB_RUN_ID": "456",
    }.items():
        monkeypatch.setenv(key, value)


def _run():
    return {
        "id": 123, "run_attempt": 1, "head_sha": "a" * 40, "head_branch": "main",
        "path": operations.PLAN_WORKFLOW, "event": "workflow_dispatch",
        "status": "completed", "conclusion": "success",
    }


def test_approval_requires_explicit_exact_source_and_hashes(monkeypatch):
    assert operations.approval()["source_sha"] == "a" * 40
    for key, bad in (
        ("CONFIRM_MONITORING_APPLY", "false"), ("GITHUB_REF", "refs/heads/feature"),
        ("GITHUB_SHA", "d" * 40), ("APPROVED_PLAN_RUN_ID", "../123"),
        ("APPROVED_PLAN_SHA256", "b" * 63),
    ):
        with monkeypatch.context() as scoped:
            scoped.setenv(key, bad)
            with pytest.raises(ValueError):
                operations.approval()


def test_ciphertext_is_bound_to_exact_successful_plan_run(tmp_path, monkeypatch):
    path = tmp_path / "plan.enc"
    path.write_bytes(b"encrypted fixture")
    monkeypatch.setenv("APPROVED_BUNDLE_SHA256", operations._digest(path))
    operations.verify_bundle(path, _run())
    path.write_bytes(b"changed ciphertext")
    with pytest.raises(ValueError, match="hash"):
        operations.verify_bundle(path, _run())


@pytest.mark.parametrize(
    ("field", "bad"),
    [("id", 124), ("run_attempt", 2), ("head_sha", "d" * 40), ("head_branch", "feature"),
     ("path", ".github/workflows/untrusted.yml"), ("event", "pull_request"),
     ("status", "in_progress"), ("conclusion", "failure")],
)
def test_run_identity_cannot_be_substituted(tmp_path, monkeypatch, field, bad):
    path = tmp_path / "plan.enc"
    path.write_bytes(b"encrypted fixture")
    monkeypatch.setenv("APPROVED_BUNDLE_SHA256", operations._digest(path))
    with pytest.raises(ValueError, match="exact successful"):
        operations.verify_bundle(path, {**_run(), field: bad})


def _archive(path, entries):
    with tarfile.open(path, "w:gz") as archive:
        for name, content, kind in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))


def test_review_archive_extracts_only_regular_bounded_files(tmp_path):
    archive = tmp_path / "plan.tgz"
    required = (
        "release-monitoring.tfplan", "plan-metadata.json", "provider.lock.hcl",
        "migration-alert-specs.json", "query-evidence.json",
    )
    _archive(archive, [(f"./{name}", b"fixture", tarfile.REGTYPE) for name in required])
    destination = tmp_path / "reviewed"
    operations.unpack_plan(archive, destination)
    assert sorted(item.name for item in destination.iterdir()) == sorted(required)
    with pytest.raises(FileExistsError):
        operations.unpack_plan(archive, destination)


@pytest.mark.parametrize(
    ("name", "kind"),
    [("../plan.json", tarfile.REGTYPE), ("/plan.json", tarfile.REGTYPE),
     ("folder/plan.json", tarfile.REGTYPE), ("plan.json", tarfile.SYMTYPE),
     ("plan.json", tarfile.LNKTYPE), ("unexpected.sh", tarfile.REGTYPE)],
)
def test_review_archive_rejects_unsafe_entries_before_writing(tmp_path, name, kind):
    archive = tmp_path / "plan.tgz"
    _archive(archive, [(name, b"", kind)])
    destination = tmp_path / "reviewed"
    with pytest.raises(ValueError, match="unsafe"):
        operations.unpack_plan(archive, destination)
    assert not destination.exists()


def test_review_archive_rejects_duplicate_or_missing_evidence(tmp_path):
    archive = tmp_path / "plan.tgz"
    _archive(archive, [("plan.json", b"{}", tarfile.REGTYPE)] * 2)
    with pytest.raises(ValueError, match="unsafe"):
        operations.unpack_plan(archive, tmp_path / "duplicate")
    _archive(archive, [("plan.json", b"{}", tarfile.REGTYPE)])
    with pytest.raises(ValueError, match="missing required"):
        operations.unpack_plan(archive, tmp_path / "missing")


def test_review_archive_size_limit_is_enforced_before_extraction(tmp_path):
    archive = tmp_path / "oversized.tgz"
    with tarfile.open(archive, "w:gz") as writer:
        member = tarfile.TarInfo("plan.json")
        member.size = 101 * 1024 * 1024
        writer.addfile(member)
    with pytest.raises(ValueError, match="size bound"):
        operations.unpack_plan(archive, tmp_path / "reviewed")


def _query_result(column, value):
    return {"tables": [{
        "name": "PrimaryResult", "columns": [{"name": column, "type": "long"}], "rows": [[value]],
    }]}


@pytest.mark.parametrize("value", [None, True, 0.1, -1, "1"])
def test_live_query_requires_exact_scalar_count(value):
    with pytest.raises(ValueError):
        operations.query_count(_query_result("FailureEvents", value), "FailureEvents")


def test_live_query_partial_errors_and_shape_mismatches_fail_closed():
    valid = _query_result("FailureEvents", 0)
    assert operations.query_count(valid, "FailureEvents") == 0
    with pytest.raises(ValueError):
        operations.query_count({**valid, "error": {"code": "PartialError"}}, "FailureEvents")
    with pytest.raises(ValueError):
        operations.query_count(valid, "WrongMetric")


def test_each_exact_query_and_synthetic_predicates_are_checked(monkeypatch):
    specs = operations._load(SPEC_PATH)["alerts"]
    requests = []

    def query(arguments, *, label):
        body = json.loads(arguments[arguments.index("--body") + 1])
        role = label.split()[0]
        synthetic = "let customEvents" in body["query"]
        assert body["query"].endswith(specs[role]["query"])
        assert body["timespan"] == specs[role]["window_duration"]
        assert arguments[arguments.index("--url") + 1] == f"https://api.loganalytics.azure.com/v1{APP['id']}/query"
        requests.append((role, synthetic))
        return _query_result(specs[role]["criteria"]["metric_measure_column"], 1 if synthetic else 0)

    monkeypatch.setattr(operations, "az_json", query)
    result = operations.validate_queries(APP, WORKSPACE, SPEC_PATH)
    assert len(requests) == 8
    assert all(value == {"live": 0, "synthetic": 1} for value in result["queries"].values())
    assert "unrelated" in operations._synthetic_events()


def test_query_semantics_failure_is_not_success(monkeypatch):
    specs = operations._load(SPEC_PATH)["alerts"]
    monkeypatch.setattr(operations, "az_json", lambda _args, label: _query_result(
        specs[label.split()[0]]["criteria"]["metric_measure_column"], 0,
    ))
    with pytest.raises(ValueError, match="synthetic"):
        operations.validate_queries(APP, WORKSPACE, SPEC_PATH)


def test_azure_cli_timeout_does_not_disclose_private_command(monkeypatch):
    failure = subprocess.TimeoutExpired(["az", "--receiver", "private@example.com"], 180)
    monkeypatch.setattr(operations.subprocess, "run", Mock(side_effect=failure))
    with pytest.raises(RuntimeError, match="did not complete") as caught:
        operations.az_json([], label="approved test")
    assert "private@example.com" not in str(caught.value)


def test_azure_cli_failure_retains_private_detail_without_disclosing_it(tmp_path, monkeypatch):
    monkeypatch.setenv("MONITORING_EVIDENCE_DIR", str(tmp_path))
    result = subprocess.CompletedProcess(["az"], 1, "", "private@example.com: failure")
    monkeypatch.setattr(operations.subprocess, "run", Mock(return_value=result))
    with pytest.raises(RuntimeError, match="private diagnostics") as caught:
        operations.az_json([], label="approved operation")
    assert EMAIL not in str(caught.value)
    assert "private@example.com" not in str(caught.value)
    assert "private@example.com" in (tmp_path / "azure-errors.log").read_text()


def test_azure_json_success_is_bounded_and_explicit(monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess(["az"], 0, '{"result":1}', ""))
    monkeypatch.setattr(operations.subprocess, "run", run)
    assert operations.az_json(["resource", "show"], label="read metadata") == {"result": 1}
    assert run.call_args.kwargs["timeout"] == 180
    assert run.call_args.kwargs["capture_output"] is True
    assert run.call_args.args[0] == ["az", "resource", "show", "--only-show-errors", "--output", "json"]


@pytest.fixture
def saved_plan(tmp_path, monkeypatch):
    evidence, current, root = (tmp_path / name for name in ("evidence", "current", "root"))
    for path in (evidence, current, root / "infra/release-monitoring", root / "infra/monitoring"):
        path.mkdir(parents=True)
    binary = evidence / "release-monitoring.tfplan"
    binary.write_bytes(b"approved binary fixture")
    monkeypatch.setenv("APPROVED_PLAN_SHA256", operations._digest(binary))
    lock = root / "infra/release-monitoring/.terraform.lock.hcl"
    lock.write_text("verified lock")
    (evidence / "provider.lock.hcl").write_bytes(lock.read_bytes())
    spec = root / "infra/monitoring/migration-alert-specs.json"
    spec.write_bytes(SPEC_PATH.read_bytes())
    (evidence / "migration-alert-specs.json").write_bytes(spec.read_bytes())
    (current / "telemetry.json").write_text(json.dumps(APP))
    (current / "workspace.json").write_text(json.dumps(WORKSPACE))
    (current / "live-resource-inventory.json").write_text("[]")
    (current / "terraform-version.json").write_text('{"terraform_version":"1.9.8"}')
    plan = _plan()
    plan["terraform_version"] = "1.9.8"
    (current / "plan.json").write_text(json.dumps(plan))
    (current / "query-evidence.json").write_text(json.dumps({
        "spec_sha256": operations._digest(spec),
        "queries": {role: {"live": 0, "synthetic": 1} for role in operations.ALERT_NAMES},
    }))
    metadata = {
        "schema_version": 2, "purpose": "review-only-not-approved-for-apply",
        "source_sha": "a" * 40, "plan_sha256": operations._digest(binary),
        "provider_lock_sha256": operations._digest(lock), "spec_sha256": operations._digest(spec),
        "run_id": "123", "run_attempt": "1", "planned_at": datetime.now(timezone.utc).isoformat(),
        "changes": operations.validate_plan(
            plan, app=APP, workspace=WORKSPACE, expected_email=EMAIL, specification_path=spec,
        ),
        "monitoring_backend_sha256": operations.hashlib.sha256(json.dumps([
            os.environ["MIGRATION_TFSTATE_STORAGE_ACCOUNT"], os.environ["MIGRATION_TFSTATE_CONTAINER"],
            os.environ["MONITORING_TFSTATE_KEY"],
        ]).encode()).hexdigest(),
    }
    for name in ("primary", "migration", "monitoring"):
        state = current / f"{name}-state.json"
        state.write_text(json.dumps({
            "version": 4, "lineage": name, "serial": 1, "resources": [], "outputs": {},
        }))
        metadata[f"{name}_state"] = operations._state_identity(state)
    (evidence / "plan-metadata.json").write_text(json.dumps(metadata))
    return evidence, current, root


def test_exact_saved_plan_and_current_state_must_match(saved_plan):
    report = operations.verify_saved_plan(*saved_plan)
    assert report["changes"]["create"] == 5
    assert EMAIL not in json.dumps(report)


@pytest.mark.parametrize(
    "target",
    ["binary", "lock", "spec", "primary", "migration", "monitoring", "backend",
     "metadata", "expired", "future", "queries", "terraform", "receiver", "live_resource"],
)
def test_any_approved_binding_drift_prevents_apply(saved_plan, monkeypatch, target):
    evidence, current, root = saved_plan
    if target == "binary":
        (evidence / "release-monitoring.tfplan").write_bytes(b"changed")
    elif target == "lock":
        (root / "infra/release-monitoring/.terraform.lock.hcl").write_text("changed")
    elif target == "spec":
        (root / "infra/monitoring/migration-alert-specs.json").write_text("{}")
    elif target in {"primary", "migration", "monitoring"}:
        path = current / f"{target}-state.json"
        state = json.loads(path.read_text())
        state["serial"] += 1
        path.write_text(json.dumps(state))
    elif target == "backend":
        monkeypatch.setenv("MONITORING_TFSTATE_KEY", "changed.tfstate")
    elif target in {"metadata", "expired", "future"}:
        path = evidence / "plan-metadata.json"
        data = json.loads(path.read_text())
        if target == "metadata":
            data["run_attempt"] = "2"
        else:
            delta = timedelta(days=-8 if target == "expired" else 1)
            data["planned_at"] = (datetime.now(timezone.utc) + delta).isoformat()
        path.write_text(json.dumps(data))
    elif target == "queries":
        (current / "query-evidence.json").write_text("{}")
    elif target == "terraform":
        (current / "terraform-version.json").write_text('{"terraform_version":"1.10.0"}')
    elif target == "receiver":
        monkeypatch.setenv("TF_VAR_alert_email", "unapproved@example.com")
    else:
        (current / "live-resource-inventory.json").write_text(json.dumps([{
            "name": operations.ACTION_GROUP_NAME, "type": "Microsoft.Insights/actionGroups",
        }]))
    with pytest.raises(ValueError):
        operations.verify_saved_plan(evidence, current, root)


def _group():
    group_id = operations.expected_resource_ids(APP)["critical_action_group_id"]
    return {
        "id": group_id,
        "properties": {"enabled": True, "groupShortName": "archcrit", "emailReceivers": [{
            "name": "admin", "emailAddress": EMAIL, "useCommonAlertSchema": True, "status": "Enabled",
        }]},
    }


def test_applied_group_is_exactly_the_approved_email_only_route():
    group = _group()
    operations.validate_action_group(group, group["id"], EMAIL)
    group["properties"]["webhookReceivers"] = [{"name": "unexpected"}]
    with pytest.raises(ValueError, match="additional"):
        operations.validate_action_group(group, group["id"], EMAIL)


@pytest.mark.parametrize("change", ["identity", "disabled", "recipient", "schema", "receiver_status"])
def test_applied_group_drift_blocks_email_test(change):
    group = _group()
    expected_id = group["id"]
    if change == "identity":
        group["id"] += "-other"
    elif change == "disabled":
        group["properties"]["enabled"] = False
    else:
        receiver = group["properties"]["emailReceivers"][0]
        field, value = {
            "recipient": ("emailAddress", "unapproved@example.com"),
            "schema": ("useCommonAlertSchema", False),
            "receiver_status": ("status", "Disabled"),
        }[change]
        receiver[field] = value
    with pytest.raises(ValueError):
        operations.validate_action_group(group, expected_id, EMAIL)


def test_attest_live_checks_every_exact_output_alert_and_receiver(tmp_path, monkeypatch):
    expected = operations.expected_resource_ids(APP)
    outputs = tmp_path / "outputs.json"
    outputs.write_text(json.dumps({key: {"value": value} for key, value in expected.items()}))
    seen = []

    def query(arguments, *, label):
        seen.append(label)
        if label == "Applied notification group read":
            return _group()
        role = label.split()[1]
        resource_id = arguments[arguments.index("--url") + 1].split("https://management.azure.com", 1)[1].split("?")[0]
        payload = _alert(role)
        payload["id"] = resource_id
        payload["properties"]["scopes"] = [APP["id"]]
        payload["properties"]["actions"]["actionGroups"] = [expected["critical_action_group_id"]]
        return payload

    monkeypatch.setattr(operations, "az_json", query)
    assert operations.attest_live(outputs, APP, SPEC_PATH) == {
        "canonical_alerts_verified": 4, "approved_email_groups_verified": 1, "receiver_source": "ALERT_EMAIL",
    }
    assert len(seen) == 5
    data = json.loads(outputs.read_text())
    data["critical_action_group_id"]["value"] += "-other"
    outputs.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="outputs"):
        operations.attest_live(outputs, APP, SPEC_PATH)
    assert len(seen) == 5


def _notification():
    return {"state": "Completed", "actionDetails": [{
        "MechanismType": "Email", "Name": "admin", "Status": "Completed",
        "SendTime": "2026-10-08T10:00:00Z", "Detail": None,
    }]}


def test_notification_evidence_never_claims_inbox_receipt():
    evidence = operations.notification_result(_notification())
    assert evidence["email_test_status"] == "Completed"
    assert evidence["recipient_inbox_receipt_confirmed"] is False


def test_pending_notification_is_not_reported_as_delivered():
    payload = _notification()
    payload["state"] = "InProgress"
    with pytest.raises(ValueError, match="not completed"):
        operations.notification_result(payload)


def test_email_test_uses_only_preverified_existing_recipient(monkeypatch):
    query = Mock(return_value=_group())
    sender = Mock(return_value=operations.notification_result(_notification()))
    monkeypatch.setattr(operations, "az_json", query)
    monkeypatch.setattr(operations, "send_email_test", sender)
    report = operations.test_email(APP)
    assert report["recipient_inbox_receipt_confirmed"] is False
    sender.assert_called_once_with(
        _group()["properties"]["emailReceivers"][0], _group()["id"],
    )


def test_email_rest_payload_contains_the_verified_receiver(monkeypatch):
    monkeypatch.setattr(operations, "az_json", Mock(return_value={"accessToken": "short-lived-test-token"}))
    request = Mock(return_value=(200, _notification(), None))
    monkeypatch.setattr(operations, "notification_request", request)
    result = operations.send_email_test(_group()["properties"]["emailReceivers"][0], _group()["id"])
    assert result["email_test_status"] == "Completed"
    assert request.call_args.args[2] == {
        "alertType": "logalertv2",
        "emailReceivers": [{"name": "admin", "emailAddress": EMAIL, "useCommonAlertSchema": True}],
    }
    assert request.call_args.args[0].endswith("/createNotifications?api-version=2021-09-01")


def test_accepted_test_polls_without_resending_and_retains_request_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("MONITORING_EVIDENCE_DIR", str(tmp_path))
    monkeypatch.setattr(operations, "az_json", Mock(return_value={"accessToken": "short-lived-test-token"}))
    monkeypatch.setattr(operations.time, "sleep", Mock())
    location = _group()["id"] + "/notificationStatus/example-id?api-version=2022-06-01"
    request = Mock(side_effect=[
        (202, {}, location), (200, {"state": "InProgress"}, None), (200, _notification(), None),
    ])
    monkeypatch.setattr(operations, "notification_request", request)
    operations.send_email_test(_group()["properties"]["emailReceivers"][0], _group()["id"])
    assert len(request.call_args_list[0].args) == 3
    assert all(len(call.args) == 2 for call in request.call_args_list[1:])
    saved = json.loads((tmp_path / "notification-request.json").read_text())
    assert saved["send_attempts"] == 1 and saved["accepted"] is True
    assert EMAIL not in json.dumps(saved)


def test_accepted_notification_timeout_never_resends(monkeypatch):
    monkeypatch.setattr(operations, "az_json", Mock(return_value={"accessToken": "short-lived-test-token"}))
    monkeypatch.setattr(operations.time, "monotonic", Mock(side_effect=[0, 301]))
    request = Mock(return_value=(202, {}, (
        _group()["id"] + "/notificationStatus/id?api-version=2021-09-01"
    )))
    monkeypatch.setattr(operations, "notification_request", request)
    with pytest.raises(TimeoutError, match="do not resend"):
        operations.send_email_test(_group()["properties"]["emailReceivers"][0], _group()["id"])
    assert request.call_count == 1


def test_notification_http_error_does_not_disclose_tokens_or_receiver(monkeypatch):
    opener = Mock()
    opener.open.side_effect = HTTPError(
        "https://management.azure.com", 400, "private@example.com short-lived-test-token", {}, None,
    )
    monkeypatch.setattr(operations, "build_opener", Mock(return_value=opener))
    with pytest.raises(RuntimeError, match="HTTP 400") as caught:
        operations.notification_request("https://management.azure.com", "short-lived-test-token", {})
    assert "private@example.com" not in str(caught.value)
    assert "short-lived-test-token" not in str(caught.value)
    assert opener.open.call_args.kwargs["timeout"] == 30
    assert isinstance(operations.build_opener.call_args.args[0], operations._NoRedirect)


@pytest.mark.parametrize("location", [
    "https://example.com/token",
    "http://management.azure.com/subscriptions/example/providers/Microsoft.Insights/notificationStatus/id?api-version=2021-09-01",
    "/subscriptions/example-other/providers/Microsoft.Insights/notificationStatus/id?api-version=2021-09-01",
    "/subscriptions/example/providers/Microsoft.Insights/notificationStatus/../id?api-version=2021-09-01",
    _group()["id"] + "-other/notificationStatus/id?api-version=2021-09-01",
    _group()["id"] + "/notificationStatus/../id?api-version=2021-09-01",
    _group()["id"] + "/notificationStatus/id?api-version=2021-09-01&extra=unapproved",
])
def test_notification_polling_cannot_send_token_outside_approved_endpoint(location):
    with pytest.raises(ValueError):
        operations._notification_poll_url(location, _group()["id"])


def test_documented_action_group_scoped_location_is_accepted():
    location = "https://management.azure.com" + _group()["id"] + "/notificationStatus/11111111111111?api-version=2022-06-01"
    assert operations._notification_poll_url(location, _group()["id"]) == location
    assert operations._notification_poll_url(location.upper().replace(
        "HTTPS://MANAGEMENT.AZURE.COM", "https://management.azure.com"
    ).replace("API-VERSION", "api-version"), _group()["id"])


@pytest.mark.parametrize(
    ("field", "value"),
    [("MechanismType", "Webhook"), ("Name", "other"), ("Status", "Failed"), ("SendTime", None)],
)
def test_notification_failure_or_wrong_receiver_never_looks_successful(field, value):
    payload = _notification()
    payload["actionDetails"][0][field] = value
    with pytest.raises(ValueError):
        operations.notification_result(payload)


def test_apply_workflow_is_manual_exact_artifact_and_monitoring_only():
    text = (ROOT / ".github/workflows/release-monitoring-apply.yml").read_text()
    workflow = yaml.safe_load(text)
    trigger = workflow.get("on", workflow.get(True))
    assert set(trigger) == {"workflow_dispatch"}
    assert trigger["workflow_dispatch"]["inputs"]["confirm_monitoring_apply"]["default"] is False
    job = workflow["jobs"]["monitoring-apply"]
    assert job["environment"] == "production"
    assert job["runs-on"] == "${{ fromJSON(vars.PRODUCTION_RUNNER_LABELS) }}"
    names = [step.get("name") for step in job["steps"]]
    assert names.index("Verify ciphertext and safely extract the reviewed plan") < names.index("Azure Login (OIDC)")
    assert names.index("Acquire renewable production mutation ownership") < names.index(
        "Revalidate and apply only the explicitly approved saved monitoring plan"
    )
    apply = next(step["run"] for step in job["steps"] if step.get("id") == "apply")
    assert apply.index("release_monitoring_apply.py verify") < apply.index("supervise-command")
    assert 'terraform -chdir=infra/release-monitoring apply' in apply
    assert '"$E/reviewed/release-monitoring.tfplan"' in apply
    assert "terraform plan" not in text
    assert "az containerapp" not in text
    assert "az keyvault secret" not in text
    assert "-target" not in text
    assert "id-token: write" in text
    assert "Release renewable mutation ownership" in names
    for step in job["steps"]:
        if "uses" in step:
            assert re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", step["uses"])
    uploads = [step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact@")]
    assert len(uploads) == 1
    assert uploads[0]["with"]["path"].endswith(".tar.gz.enc")


def test_planning_workflow_requires_live_queries_but_still_cannot_apply():
    text = (ROOT / ".github/workflows/release-monitoring-plan.yml").read_text()
    workflow = yaml.safe_load(text)
    steps = workflow["jobs"]["monitoring-plan"]["steps"]
    names = [step.get("name") for step in steps]
    assert names.index("Validate live and synthetic canonical queries without ingestion") < names.index(
        "Create and verify the five-resource saved plan without apply"
    )
    assert re.search(r"\bterraform(?:\s+-\S+)*\s+apply\b", text) is None
    assert all(step.get("with", {}).get("terraform_version", "1.9.8") == "1.9.8" for step in steps)


def test_notification_recovery_is_separate_from_apply_and_production_rollout():
    text = (ROOT / ".github/workflows/release-monitoring-notification.yml").read_text()
    workflow = yaml.safe_load(text)
    trigger = workflow.get("on", workflow.get(True))
    assert set(trigger) == {"workflow_dispatch"}
    assert trigger["workflow_dispatch"]["inputs"]["confirm_notification_test"]["default"] is False
    job = workflow["jobs"]["notification-test"]
    assert job["environment"] == "production"
    assert "secrets.ALERT_EMAIL" in job["env"]["TF_VAR_alert_email"]
    assert re.search(r"\bterraform(?:\s+-\S+)*\s+(apply|plan|destroy)\b", text) is None
    assert "az containerapp" not in text
    names = [step.get("name") for step in job["steps"]]
    assert names.index("Attest the existing monitored resources without changing state") < names.index(
        "Send one verified existing-recipient test"
    )
    assert "--retry-only" in text
    for step in job["steps"]:
        if "uses" in step:
            assert re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", step["uses"])


@pytest.mark.parametrize(
    ("confirmation", "ref", "sha", "allowed"),
    [
        ("true", "refs/heads/main", "a" * 40, True),
        ("false", "refs/heads/main", "a" * 40, False),
        ("", "refs/heads/main", "a" * 40, False),
        ("true", "refs/heads/feature", "a" * 40, False),
        ("true", "refs/heads/main", "d" * 40, False),
    ],
)
def test_notification_only_cli_checks_authorization_before_any_send(
    tmp_path, monkeypatch, confirmation, ref, sha, allowed,
):
    app = tmp_path / "app.json"
    app.write_text(json.dumps(APP))
    output = tmp_path / "result.json"
    sender = Mock(return_value={"test": "completed"})
    monkeypatch.setattr(operations, "test_email", sender)
    monkeypatch.setenv("CONFIRM_NOTIFICATION_TEST", confirmation)
    monkeypatch.setenv("GITHUB_REF", ref)
    monkeypatch.setenv("GITHUB_SHA", sha)
    monkeypatch.setattr(sys, "argv", [
        "release_monitoring_apply.py", "test-email", "--retry-only",
        "--app", str(app), "--output", str(output),
    ])
    if allowed:
        operations.main()
        sender.assert_called_once_with(APP)
        assert output.exists()
    else:
        with pytest.raises(ValueError, match="exact-source protected approval"):
            operations.main()
        sender.assert_not_called()
        assert not output.exists()


@pytest.mark.parametrize("command", ["queries", "verify", "attest", "test-email"])
def test_cli_writes_safe_evidence_for_verified_operations(tmp_path, monkeypatch, capsys, command):
    app, workspace, outputs, output = (tmp_path / name for name in ("app.json", "workspace.json", "outputs.json", "result.json"))
    app.write_text(json.dumps(APP))
    workspace.write_text(json.dumps(WORKSPACE))
    outputs.write_text("{}")
    report = {"verified": True}
    if command == "queries":
        monkeypatch.setattr(operations, "validate_queries", Mock(return_value=report))
        args = ["--app", str(app), "--workspace", str(workspace), "--spec", str(SPEC_PATH)]
    elif command == "verify":
        monkeypatch.setattr(operations, "verify_saved_plan", Mock(return_value=report))
        args = ["--evidence", str(tmp_path), "--current", str(tmp_path), "--root", str(ROOT)]
    elif command == "attest":
        monkeypatch.setattr(operations, "attest_live", Mock(return_value=report))
        args = ["--outputs", str(outputs), "--app", str(app), "--spec", str(SPEC_PATH)]
    else:
        monkeypatch.setattr(operations, "test_email", Mock(return_value=report))
        args = ["--app", str(app)]
    monkeypatch.setattr(sys, "argv", ["release_monitoring_apply.py", command, *args, "--output", str(output)])
    operations.main()
    assert json.loads(output.read_text()) == report
    assert json.loads(capsys.readouterr().out) == report


@pytest.mark.parametrize("command", ["approval", "bundle", "unpack"])
def test_cli_routes_preflight_commands_without_application_mutation(tmp_path, monkeypatch, capsys, command):
    run = tmp_path / "run.json"
    run.write_text(json.dumps(_run()))
    if command == "approval":
        args = []
    elif command == "bundle":
        monkeypatch.setattr(operations, "verify_bundle", Mock())
        args = ["--encrypted", str(tmp_path / "bundle.enc"), "--run", str(run)]
    else:
        monkeypatch.setattr(operations, "unpack_plan", Mock())
        args = ["--archive", str(tmp_path / "archive.tgz"), "--destination", str(tmp_path / "reviewed")]
    monkeypatch.setattr(sys, "argv", ["release_monitoring_apply.py", command, *args])
    operations.main()
    assert "verified" in capsys.readouterr().out.lower() or command in {"approval", "unpack"}
