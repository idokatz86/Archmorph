import json
import hashlib
import hmac
import importlib.util
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "containerapp_rollout.py"
SPEC = importlib.util.spec_from_file_location("containerapp_rollout", SCRIPT)
assert SPEC and SPEC.loader
rollout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rollout)

apply_traffic = rollout.apply_traffic
authoritative_latest_revision = rollout.authoritative_latest_revision
canonical_traffic = rollout.canonical_traffic
create_release_state = rollout.create_release_state
explicit_traffic = rollout.explicit_traffic
mark_release_stage = rollout.mark_release_stage
recovery_decision = rollout.recovery_decision
recover_release = rollout.recover_release
set_release_bridge = rollout.set_release_bridge
traffic_command = rollout.traffic_command
verify_manifest = rollout.verify_manifest
write_manifest = rollout.write_manifest


def test_latest_traffic_becomes_explicit_without_changing_multi_revision_weights():
    source = [
        {"latestRevision": True, "weight": 70},
        {"revisionName": "api-canary", "weight": 20},
        {"revisionName": "api-stable", "weight": 10, "label": "stable"},
    ]

    result = explicit_traffic(source, latest_revision="api-blue")

    assert result == canonical_traffic(
        [
            {"revisionName": "api-blue", "weight": 70},
            {"revisionName": "api-canary", "weight": 20},
            {"revisionName": "api-stable", "weight": 10, "label": "stable"},
        ]
    )
    assert "latest=" not in traffic_command(result)
    assert "api-blue=70" in traffic_command(result)
    assert "api-canary=20" in traffic_command(result)
    assert "stable=10" in traffic_command(result)


def test_explicit_only_traffic_does_not_require_an_unused_latest_revision():
    source = [{"revisionName": "api-stable", "weight": 100, "label": "stable"}]

    assert explicit_traffic(source, latest_revision="") == canonical_traffic(source)


def test_authoritative_latest_not_highest_weight_preserves_stable90_latest10():
    source = [
        {"revisionName": "api-stable", "weight": 90, "label": "stable"},
        {"latestRevision": True, "weight": 10},
    ]
    app = {
        "properties": {
            "latestRevisionName": "api-created-but-not-ready",
            "latestReadyRevisionName": "api-authoritative-latest",
        }
    }

    result = explicit_traffic(
        source,
        latest_revision=authoritative_latest_revision(
            app,
            [
                {
                    "name": "api-authoritative-latest",
                    "properties": {
                        "active": True,
                        "provisioningState": "Succeeded",
                        "runningState": "Running",
                        "healthState": "Healthy",
                    },
                }
            ],
        ),
    )

    assert result == canonical_traffic(
        [
            {"revisionName": "api-stable", "weight": 90, "label": "stable"},
            {"revisionName": "api-authoritative-latest", "weight": 10},
        ]
    )


def test_authoritative_latest_preserves_labels_and_multiple_revisions_exactly():
    source = [
        {"revisionName": "api-a", "weight": 40},
        {"revisionName": "api-b", "weight": 20, "label": "canary"},
        {"latestRevision": True, "weight": 30},
        {"revisionName": "api-c", "weight": 10, "label": "stable"},
    ]
    result = explicit_traffic(
        source,
        latest_revision=authoritative_latest_revision(
            {"properties": {"latestReadyRevisionName": "api-d"}},
            [{"name": "api-d", "properties": {"active": True}}],
        ),
    )
    assert result == canonical_traffic(
        [
            {"revisionName": "api-a", "weight": 40},
            {"revisionName": "api-b", "weight": 20, "label": "canary"},
            {"revisionName": "api-d", "weight": 30},
            {"revisionName": "api-c", "weight": 10, "label": "stable"},
        ]
    )


def test_authoritative_latest_requires_latest_ready_not_merely_latest_revision():
    with pytest.raises(ValueError, match="no authoritative latest-ready"):
        authoritative_latest_revision(
            {"properties": {"latestRevisionName": "api-created-not-ready"}},
            [
                {
                    "name": "api-created-not-ready",
                    "properties": {
                        "active": True,
                        "provisioningState": "Succeeded",
                        "runningState": "Running",
                        "healthState": "Healthy",
                    },
                }
            ],
        )


@pytest.mark.parametrize(
    ("properties", "message"),
    [
        ({"active": False, "healthState": "Healthy"}, "not active"),
        ({"active": True, "healthState": "Unhealthy"}, "unready healthState"),
        ({"active": True, "runningState": "Stopped"}, "unready runningState"),
        ({"active": True, "provisioningState": "Failed"}, "unready provisioningState"),
    ],
)
def test_authoritative_latest_rejects_inactive_or_unready_revision(properties, message):
    with pytest.raises(ValueError, match=message):
        authoritative_latest_revision(
            {"properties": {"latestReadyRevisionName": "api-blue"}},
            [{"name": "api-blue", "properties": properties}],
        )


def test_authoritative_latest_rejects_latest_ready_absent_from_revision_state():
    with pytest.raises(ValueError, match="absent or duplicated"):
        authoritative_latest_revision(
            {"properties": {"latestReadyRevisionName": "api-blue"}},
            [{"name": "api-other", "properties": {"active": True}}],
        )


def test_authoritative_latest_merges_existing_unlabeled_route_without_weight_loss():
    source = [
        {"revisionName": "api-latest", "weight": 15},
        {"latestRevision": True, "weight": 10},
        {"revisionName": "api-stable", "weight": 75, "label": "stable"},
    ]
    assert explicit_traffic(source, latest_revision="api-latest") == canonical_traffic(
        [
            {"revisionName": "api-latest", "weight": 25},
            {"revisionName": "api-stable", "weight": 75, "label": "stable"},
        ]
    )


def _release_state(*, schema="013", original=None):
    original = original or [
        {"revisionName": "api-blue", "weight": 70},
        {"revisionName": "api-canary", "weight": 20, "label": "canary"},
        {"revisionName": "api-stable", "weight": 10, "label": "stable"},
    ]
    return create_release_state(
        current_schema=schema,
        migration_from="013",
        target_schema="014",
        baseline_traffic=original,
        bridge_revision="api-bridge" if schema == "013" else "",
    )


def test_release_state_migration_branch_requires_bridge_but_routine_preserves_weights():
    migration = _release_state(schema="013")
    routine = _release_state(schema="014")
    repeated = create_release_state(
        current_schema="014",
        migration_from="013",
        target_schema="014",
        baseline_traffic=routine["pre_green_traffic"],
    )

    assert migration["branch"] == "migration"
    assert migration["pre_green_traffic"] == canonical_traffic(
        [{"revisionName": "api-bridge", "weight": 100}]
    )
    assert routine["branch"] == "routine"
    assert routine["pre_green_traffic"] == routine["baseline_traffic"]
    assert repeated["pre_green_traffic"] == routine["pre_green_traffic"]
    captured = create_release_state(
        current_schema="013",
        migration_from="013",
        target_schema="014",
        baseline_traffic=routine["baseline_traffic"],
    )
    assert captured["pre_green_traffic"] == []
    assert set_release_bridge(captured, "api-bridge")["pre_green_traffic"] == migration[
        "pre_green_traffic"
    ]
    with pytest.raises(ValueError, match="must not resolve or route"):
        create_release_state(
            current_schema="014",
            migration_from="013",
            target_schema="014",
            baseline_traffic=routine["baseline_traffic"],
            bridge_revision="api-bridge",
        )


@pytest.mark.parametrize(
    ("stage", "schema", "expected_action"),
    [
        ("baseline_attempted", "013", "restore_original"),
        ("bridge_route_attempted", "013", "restore_original"),
        ("migration_attempted", "013", "restore_original"),
        ("migration_attempted", "014", "retain_bridge"),
        ("green_shift_attempted", "014", "retain_bridge"),
    ],
)
def test_migration_failure_recovery_is_schema_aware_and_exact(stage, schema, expected_action):
    state = mark_release_stage(_release_state(schema="013"), stage)
    action, target = recovery_decision(state, observed_schema=schema)
    assert action == expected_action
    expected = (
        state["baseline_traffic"]
        if expected_action == "restore_original"
        else state["pre_green_traffic"]
    )
    assert target == expected


def test_recover_release_records_incident_when_schema_advanced_and_verifies_bridge(tmp_path):
    state = mark_release_stage(_release_state(schema="013"), "migration_attempted")
    evidence = tmp_path / "incident.json"
    with patch.object(rollout, "apply_traffic") as apply:
        result = recover_release(
            state,
            observed_schema="014",
            name="api",
            resource_group="example-rg",
            evidence_output=evidence,
        )
    apply.assert_called_once_with(
        state["pre_green_traffic"],
        name="api",
        resource_group="example-rg",
    )
    assert result["status"] == "bridge_retained"
    assert json.loads(evidence.read_text())["action"] == "retain_bridge"


def test_recover_release_preserves_primary_error_when_cleanup_fails(tmp_path):
    state = mark_release_stage(_release_state(schema="013"), "bridge_route_attempted")
    evidence = tmp_path / "incident.json"
    with (
        patch.object(rollout, "apply_traffic", side_effect=RuntimeError("partial command failure")),
        pytest.raises(RuntimeError, match="partial command failure"),
    ):
        recover_release(
            state,
            observed_schema="013",
            name="api",
            resource_group="example-rg",
            evidence_output=evidence,
        )


def test_routine_failure_restores_exact_original_when_health_schema_probe_is_unavailable():
    state = mark_release_stage(_release_state(schema="014"), "green_shift_attempted")
    action, target = recovery_decision(state, observed_schema="")
    assert action == "restore_original"
    assert target == state["baseline_traffic"]


@pytest.mark.parametrize(
    ("schema", "stage", "observed_schema"),
    [
        ("014", "green_shift_attempted", ""),
        ("013", "bridge_route_attempted", "013"),
        ("013", "migration_attempted", "013"),
    ],
)
@pytest.mark.parametrize(
    ("raw", "expected_revisions"),
    [
        (
            [
                {"latestRevision": True, "weight": 10},
                {"revisionName": "api-stable", "weight": 90, "label": "stable"},
            ],
            {"api-blue-ready", "api-stable"},
        ),
        ([{"latestRevision": True, "weight": 100}], {"api-blue-ready"}),
    ],
)
def test_recovery_uses_captured_explicit_baseline_never_raw_latest(
    schema, stage, observed_schema, raw, expected_revisions
):
    baseline = explicit_traffic(raw, latest_revision="api-blue-ready")
    state = create_release_state(
        current_schema=schema,
        migration_from="013",
        target_schema="014",
        baseline_traffic=baseline,
        bridge_revision="api-bridge" if schema == "013" else "",
    )
    state = mark_release_stage(state, stage)
    failed_revision = "api-new-failed"

    action, target = recovery_decision(state, observed_schema=observed_schema)

    assert action == "restore_original"
    assert target == baseline
    assert all("latestRevision" not in item for item in target)
    assert all(item.get("revisionName") != failed_revision for item in target)
    assert {item.get("revisionName") for item in target} == expected_revisions


def test_release_state_and_execution_reject_dynamic_recovery_manifests():
    raw_latest = [{"latestRevision": True, "weight": 100}]
    with pytest.raises(ValueError, match="must not contain dynamic latest"):
        create_release_state(
            current_schema="014",
            migration_from="013",
            target_schema="014",
            baseline_traffic=raw_latest,
        )
    with pytest.raises(ValueError, match="must not contain dynamic latest"):
        with patch.object(rollout.subprocess, "run") as run:
            apply_traffic(raw_latest, name="api", resource_group="example-rg")
        run.assert_not_called()


def test_traffic_validation_rejects_implicit_or_invalid_manifest():
    with pytest.raises(ValueError, match="valid revision"):
        canonical_traffic([{"revisionName": "", "weight": 100}])
    with pytest.raises(ValueError, match="between 0 and 100"):
        canonical_traffic([{"revisionName": "api-blue", "weight": 101}])
    with pytest.raises(ValueError, match="sum to 0 or 100"):
        canonical_traffic([{"revisionName": "api-blue", "weight": 99}])


def test_same_revision_can_have_labeled_and_unlabeled_routes():
    manifest = [
        {"revisionName": "api-blue", "weight": 80},
        {"revisionName": "api-blue", "weight": 20, "label": "stable"},
    ]

    assert sum(item["weight"] for item in canonical_traffic(manifest)) == 100


def test_apply_traffic_sets_then_reads_and_requires_exact_restoration(tmp_path):
    manifest = [
        {"revisionName": "api-blue", "weight": 70},
        {"revisionName": "api-canary", "weight": 30},
    ]
    output = tmp_path / "actual.json"
    with patch.object(
        rollout.subprocess,
        "run",
        side_effect=[
            CompletedProcess([], 0, stdout=json.dumps(manifest)),
            CompletedProcess([], 0),
            CompletedProcess([], 0, stdout=json.dumps(manifest)),
        ],
    ) as run:
        apply_traffic(
            manifest,
            name="api",
            resource_group="example-rg",
            actual_output=output,
        )

    assert run.call_args_list[1].args[0][-3:] == [
        "--revision-weight",
        "api-blue=70",
        "api-canary=30",
    ]
    assert run.call_args_list[2].args[0][1:3] == ["containerapp", "show"]
    assert json.loads(output.read_text()) == manifest


def test_apply_traffic_fails_when_platform_returns_partial_shift():
    expected = [{"revisionName": "api-blue", "weight": 100}]
    actual = [
        {"revisionName": "api-blue", "weight": 50},
        {"revisionName": "api-green", "weight": 50},
    ]
    with (
        patch.object(
            rollout.subprocess,
            "run",
            side_effect=[
                CompletedProcess([], 0, stdout=json.dumps(actual)),
                CompletedProcess([], 0),
                CompletedProcess([], 0, stdout=json.dumps(actual)),
            ],
        ),
        pytest.raises(RuntimeError, match="mismatch after apply"),
    ):
        apply_traffic(expected, name="api", resource_group="example-rg")


def test_apply_traffic_explicitly_clears_extra_current_targets_and_preserves_zero_entries():
    current = [
        {"revisionName": "api-blue", "weight": 50},
        {"revisionName": "api-old", "weight": 50, "label": "old"},
    ]
    expected = [
        {"revisionName": "api-blue", "weight": 100},
        {"revisionName": "api-old", "weight": 0, "label": "old"},
    ]
    with patch.object(
        rollout.subprocess,
        "run",
        side_effect=[
            CompletedProcess([], 0, stdout=json.dumps(current)),
            CompletedProcess([], 0),
            CompletedProcess([], 0, stdout=json.dumps(expected)),
        ],
    ) as run:
        apply_traffic(expected, name="api", resource_group="example-rg")

    command = run.call_args_list[1].args[0]
    assert "api-blue=100" in command
    assert "old=0" in command


def test_signed_bridge_manifest_is_immutable_and_role_bound(tmp_path, monkeypatch):
    monkeypatch.setenv("RELEASE_MANIFEST_HMAC_KEY", "x" * 32)
    path = tmp_path / "bridge.json"
    image = "registry.example/archmorph-api@sha256:" + "a" * 64
    write_manifest(
        path,
        role="bridge",
        revision="api-bridge",
        image=image,
        source_sha="b" * 40,
        accepted_revisions=["014", "013"],
    )

    assert verify_manifest(path, required_role="bridge")["accepted_revisions"] == ["013", "014"]
    with pytest.raises(ValueError, match="role"):
        verify_manifest(path, required_role="final")

    payload = json.loads(path.read_text())
    payload["revision"] = "api-arbitrary"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="signature"):
        verify_manifest(path, required_role="bridge")


def test_signed_manifest_rejects_invalid_source_or_schema_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("RELEASE_MANIFEST_HMAC_KEY", "x" * 32)
    path = tmp_path / "bridge.json"
    image = "registry.example/archmorph-api@sha256:" + "a" * 64
    write_manifest(
        path,
        role="bridge",
        revision="api-bridge",
        image=image,
        source_sha="b" * 40,
        accepted_revisions=["013", "014"],
    )
    payload = json.loads(path.read_text())
    payload["source_sha"] = "short"
    unsigned = {key: value for key, value in payload.items() if key != "signature"}
    canonical = json.dumps(unsigned, separators=(",", ":"), sort_keys=True).encode()
    payload["signature"] = "sha256=" + hmac.new(b"x" * 32, canonical, hashlib.sha256).hexdigest()
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="source SHA"):
        verify_manifest(path, required_role="bridge")