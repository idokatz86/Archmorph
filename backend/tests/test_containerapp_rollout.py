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
containerapp_revision_name = rollout.containerapp_revision_name
create_release_state = rollout.create_release_state
effective_traffic = rollout.effective_traffic
explicit_traffic = rollout.explicit_traffic
mark_migration_terminal = rollout.mark_migration_terminal
mark_migration_starting = rollout.mark_migration_starting
mark_release_stage = rollout.mark_release_stage
quiesce_migration_execution = rollout.quiesce_migration_execution
recovery_decision = rollout.recovery_decision
recover_release = rollout.recover_release
resolve_exact_revision = rollout.resolve_exact_revision
set_migration_execution = rollout.set_migration_execution
set_release_bridge = rollout.set_release_bridge
supervise_migration_execution = rollout.supervise_migration_execution
traffic_command = rollout.traffic_command
verify_manifest = rollout.verify_manifest
verify_revision_target = rollout.verify_revision_target
verify_runtime_compatibility = rollout.verify_runtime_compatibility
write_manifest = rollout.write_manifest


def _schema_contract(*accepted: str) -> dict:
    return {
        "contract_version": 1,
        "migration_target_revision": "014",
        "minimum_revision": accepted[0],
        "maximum_revision": accepted[-1],
        "accepted_revisions": list(accepted),
        "alias_read_through_until": "014",
    }


def _migration_envelope(*, marker: str, digest: str) -> str:
    return rollout._migration_runtime_module().build_runtime_envelope(
        mode="migrate",
        expected_head="014",
        execution_marker=marker,
        image_digest=digest,
    )


def _write_release_manifest(
    path: Path,
    *,
    role: str = "final",
    build_repository: str = "registry.example/archmorph-api",
    release_repository: str = "registry.example/archmorph-api",
) -> None:
    contract = (
        _schema_contract("014")
        if role == "final"
        else _schema_contract("013", "014")
    )
    build_provenance = path.with_name(f"{role}-build-provenance.json")
    rollout._release_provenance_module().write_build_provenance(
        build_provenance,
        role=role,
        image=f"{build_repository}@sha256:" + "a" * 64,
        source_sha="b" * 40,
        source_repository="example/archmorph",
        source_ref="refs/heads/main",
        workflow="CI/CD",
        workflow_path=".github/workflows/ci.yml",
        run_id="12345",
        run_attempt=2,
        platform="linux/amd64",
        schema_contract=contract,
    )
    write_manifest(
        path,
        role=role,
        revision=f"api-{role}",
        image=f"{release_repository}@sha256:" + "a" * 64,
        source_sha="b" * 40,
        schema_contract=contract,
        observed_schema="014" if role == "final" else "013",
        repository="example/archmorph",
        workflow="CI/CD",
        run_id="12345",
        run_attempt=2,
        build_provenance=build_provenance,
    )


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
            [
                {
                    "name": "api-d",
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
            {"revisionName": "api-a", "weight": 40},
            {"revisionName": "api-b", "weight": 20, "label": "canary"},
            {"revisionName": "api-d", "weight": 30},
            {"revisionName": "api-c", "weight": 10, "label": "stable"},
        ]
    )


def test_effective_traffic_supports_positive_latest_with_inert_revision_entries():
    assert effective_traffic(
        [
            {"latestRevision": True, "weight": 100, "label": ""},
            {"revisionName": "api-old", "weight": 0, "label": "retired"},
        ]
    ) == [{"latestRevision": True, "weight": 100, "label": ""}]


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
        (
            {
                "active": True,
                "provisioningState": "Succeeded",
                "runningState": "Running",
                "healthState": "Unhealthy",
            },
            "unready healthState",
        ),
        (
            {
                "active": True,
                "provisioningState": "Succeeded",
                "runningState": "Stopped",
                "healthState": "Healthy",
            },
            "unready runningState",
        ),
        (
            {
                "active": True,
                "provisioningState": "Failed",
                "runningState": "Running",
                "healthState": "Healthy",
            },
            "unready provisioningState",
        ),
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


@pytest.mark.parametrize("missing", ["provisioningState", "runningState", "healthState"])
def test_authoritative_latest_fails_closed_when_readiness_evidence_is_missing(missing):
    properties = {
        "active": True,
        "provisioningState": "Succeeded",
        "runningState": "Running",
        "healthState": "Healthy",
    }
    properties.pop(missing)
    with pytest.raises(ValueError, match=f"missing required {missing}"):
        authoritative_latest_revision(
            {"properties": {"latestReadyRevisionName": "api-blue"}},
            [{"name": "api-blue", "properties": properties}],
        )


def test_containerapp_revision_name_binds_exact_app_prefix_and_full_length():
    suffix = "sha-12345678-run-1"
    assert containerapp_revision_name("archmorph-api", suffix) == (
        "archmorph-api--sha-12345678-run-1"
    )
    with pytest.raises(ValueError, match="63-character"):
        containerapp_revision_name("a" * 32, "b" * 30)
    with pytest.raises(ValueError, match="suffix"):
        containerapp_revision_name("archmorph-api", "bad--suffix")
    with pytest.raises(ValueError, match="App name"):
        containerapp_revision_name("other_app", suffix)


def test_exact_revision_discovery_rejects_substring_first_match_and_duplicates():
    expected = "archmorph-api--sha-12345678-run-1"
    exact = {"name": expected, "properties": {"active": True}}
    substring = {"name": expected + "-attacker", "properties": {"active": True}}
    assert resolve_exact_revision(expected, [substring, exact]) == exact
    with pytest.raises(ValueError, match="absent or duplicated"):
        resolve_exact_revision(expected, [substring])
    with pytest.raises(ValueError, match="absent or duplicated"):
        resolve_exact_revision(expected, [exact, dict(exact)])


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
    assert result["customer_mode"] == "degraded_read_only"
    assert result["page_owner"] == "platform-engineering"
    assert json.loads(evidence.read_text())["action"] == "retain_bridge"


def test_recovered_baseline_returns_to_normal_customer_mode(tmp_path):
    state = mark_release_stage(_release_state(schema="013"), "bridge_route_attempted")
    with patch.object(rollout, "apply_traffic"):
        result = recover_release(
            state,
            observed_schema="013",
            name="api",
            resource_group="example-rg",
            evidence_output=tmp_path / "recovered.json",
        )
    assert result["status"] == "recovered"
    assert result["customer_mode"] == "normal"
    assert result["page_owner"] is None


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
    with pytest.raises(ValueError, match="sum to 100"):
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


def test_apply_traffic_accepts_aca_omission_of_an_explicit_zero_entry():
    current = [
        {"revisionName": "api-blue", "weight": 50},
        {"revisionName": "api-old", "weight": 50, "label": "old"},
    ]
    expected = [
        {"revisionName": "api-blue", "weight": 100},
        {"revisionName": "api-old", "weight": 0, "label": "old"},
    ]
    actual = [{"revisionName": "api-blue", "weight": 100}]
    with patch.object(
        rollout.subprocess,
        "run",
        side_effect=[
            CompletedProcess([], 0, stdout=json.dumps(current)),
            CompletedProcess([], 0),
            CompletedProcess([], 0, stdout=json.dumps(actual)),
        ],
    ):
        apply_traffic(expected, name="api", resource_group="example-rg")


def test_apply_traffic_ignores_retained_inert_stale_label_binding():
    current = [
        {"revisionName": "api-bridge", "weight": 100},
        {"revisionName": "api-old", "weight": 0, "label": "stable"},
    ]
    expected = [{"revisionName": "api-green", "weight": 100, "label": "stable"}]
    actual = expected + [
        {"revisionName": "api-old", "weight": 0, "label": "retired"}
    ]
    with patch.object(
        rollout.subprocess,
        "run",
        side_effect=[
            CompletedProcess([], 0, stdout=json.dumps(current)),
            CompletedProcess([], 0),
            CompletedProcess([], 0, stdout=json.dumps(actual)),
        ],
    ):
        apply_traffic(expected, name="api", resource_group="example-rg")


@pytest.mark.parametrize("aca_retains_zero", [True, False])
@pytest.mark.parametrize(
    "expected",
    [
        [{"revisionName": "api-green", "weight": 100, "label": ""}],
        [{"revisionName": "api-green", "weight": 100, "label": "stable"}],
        [
            {"revisionName": "api-blue", "weight": 70, "label": ""},
            {"revisionName": "api-canary", "weight": 30, "label": "canary"},
        ],
    ],
)
def test_apply_traffic_accepts_aca_zero_retention_for_production_manifest_shapes(
    expected, aca_retains_zero
):
    current = [
        {"revisionName": "api-bridge", "weight": 100, "label": ""},
        {"latestRevision": True, "weight": 0, "label": ""},
    ]
    actual = list(expected)
    if aca_retains_zero:
        actual.extend(
            [
                {"revisionName": "api-bridge", "weight": 0, "label": ""},
                {"latestRevision": True, "weight": 0, "label": ""},
            ]
        )
    with patch.object(
        rollout.subprocess,
        "run",
        side_effect=[
            CompletedProcess([], 0, stdout=json.dumps(current)),
            CompletedProcess([], 0),
            CompletedProcess([], 0, stdout=json.dumps(actual)),
        ],
    ) as run:
        apply_traffic(expected, name="api", resource_group="example-rg")

    command = run.call_args_list[1].args[0]
    assert "api-bridge=0" in command
    assert "latest=0" not in command


def test_apply_traffic_bridge_to_green_then_green_to_exact_baseline_with_inert_zeros():
    bridge = [{"revisionName": "api-bridge", "weight": 100, "label": ""}]
    green = [{"revisionName": "api-green", "weight": 100, "label": ""}]
    baseline = [
        {"revisionName": "api-blue", "weight": 80, "label": ""},
        {"revisionName": "api-canary", "weight": 20, "label": "canary"},
    ]
    responses = [
        CompletedProcess([], 0, stdout=json.dumps(bridge)),
        CompletedProcess([], 0),
        CompletedProcess(
            [],
            0,
            stdout=json.dumps(
                green + [{"revisionName": "api-bridge", "weight": 0, "label": ""}]
            ),
        ),
        CompletedProcess([], 0, stdout=json.dumps(green)),
        CompletedProcess([], 0),
        CompletedProcess([], 0, stdout=json.dumps(baseline)),
    ]
    with patch.object(rollout.subprocess, "run", side_effect=responses):
        apply_traffic(green, name="api", resource_group="example-rg")
        apply_traffic(baseline, name="api", resource_group="example-rg")


def test_apply_traffic_explicitly_zeros_a_prior_positive_latest_target():
    expected = [{"revisionName": "api-green", "weight": 100}]
    current = [{"latestRevision": True, "weight": 100}]
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
    assert "latest=0" in command
    assert "api-green=100" in command


@pytest.mark.parametrize(
    "actual",
    [
        [
            {"revisionName": "api-green", "weight": 99},
            {"revisionName": "api-unexpected", "weight": 1},
        ],
        [
            {"revisionName": "api-green", "weight": 50},
            {"revisionName": "api-blue", "weight": 50},
        ],
    ],
)
def test_apply_traffic_fails_closed_on_partial_or_unexpected_positive_target(actual):
    expected = [{"revisionName": "api-green", "weight": 100}]
    with (
        patch.object(
            rollout.subprocess,
            "run",
            side_effect=[
                CompletedProcess([], 0, stdout=json.dumps(expected)),
                CompletedProcess([], 0),
                CompletedProcess([], 0, stdout=json.dumps(actual)),
            ],
        ),
        pytest.raises(RuntimeError, match="mismatch after apply"),
    ):
        apply_traffic(expected, name="api", resource_group="example-rg")


def test_apply_traffic_fails_on_wrong_positive_label():
    expected = [{"revisionName": "api-green", "weight": 100, "label": "stable"}]
    actual = [{"revisionName": "api-green", "weight": 100, "label": "other"}]
    with (
        patch.object(
            rollout.subprocess,
            "run",
            side_effect=[
                CompletedProcess([], 0, stdout=json.dumps(expected)),
                CompletedProcess([], 0),
                CompletedProcess([], 0, stdout=json.dumps(actual)),
            ],
        ),
        pytest.raises(RuntimeError, match="mismatch after apply"),
    ):
        apply_traffic(expected, name="api", resource_group="example-rg")


@pytest.mark.parametrize(
    "malformed",
    [
        "not-json",
        json.dumps([{"revisionName": "api-green"}]),
        json.dumps([{"revisionName": "api-green", "weight": "100"}]),
        json.dumps(
            [
                {"revisionName": "api-green", "weight": 100},
                {"revisionName": "api-green", "weight": 0},
            ]
        ),
        json.dumps([{"revisionName": "api-green", "weight": 90}]),
    ],
)
def test_apply_traffic_rejects_malformed_aca_response(malformed):
    expected = [{"revisionName": "api-green", "weight": 100}]
    with (
        patch.object(
            rollout.subprocess,
            "run",
            side_effect=[
                CompletedProcess([], 0, stdout=json.dumps(expected)),
                CompletedProcess([], 0),
                CompletedProcess([], 0, stdout=malformed),
            ],
        ),
        pytest.raises(RuntimeError, match="post-apply traffic response is malformed"),
    ):
        apply_traffic(expected, name="api", resource_group="example-rg")


def test_inert_zeros_cannot_turn_healthy_green_into_recovery_rollback():
    state = mark_release_stage(_release_state(schema="014"), "complete")
    actual = [
        {"revisionName": "api-green", "weight": 100},
        {"revisionName": "api-blue", "weight": 0},
        {"latestRevision": True, "weight": 0},
    ]
    with patch.object(
        rollout.subprocess,
        "run",
        side_effect=[
            CompletedProcess([], 0, stdout=json.dumps(actual)),
            CompletedProcess([], 0),
            CompletedProcess([], 0, stdout=json.dumps(actual)),
        ],
    ):
        apply_traffic(
            [{"revisionName": "api-green", "weight": 100}],
            name="api",
            resource_group="example-rg",
        )
    assert recovery_decision(state, observed_schema="014") == ("none", [])


def test_green_shift_remains_recoverable_until_post_upload_acceptance():
    shifted = mark_release_stage(_release_state(schema="014"), "green_shift_attempted")
    action, target = recovery_decision(shifted, observed_schema="014")

    assert action == "restore_original"
    assert target == shifted["baseline_traffic"]

    accepted = mark_release_stage(shifted, "complete")
    assert recovery_decision(accepted, observed_schema="014") == ("none", [])


def _persisted_execution_state(tmp_path, monkeypatch, *, terminal_status=""):
    monkeypatch.setenv("RELEASE_MANIFEST_HMAC_KEY", "x" * 32)
    state = mark_release_stage(_release_state(schema="013"), "migration_attempted")
    state = set_migration_execution(
        state,
        job_name="migration-job",
        resource_group="example-rg",
        execution_name="migration-job-abc123",
        image_digest="sha256:" + "a" * 64,
    )
    if terminal_status:
        state = mark_migration_terminal(state, terminal_status)
    path = tmp_path / "rollout-state.json"
    rollout._write_release_state(path, state)
    return path


def test_supervision_persists_terminal_status_for_restart_safe_rerun(tmp_path, monkeypatch):
    state_path = _persisted_execution_state(tmp_path, monkeypatch)
    evidence = tmp_path / "execution.json"
    with patch.object(
        rollout,
        "observe_exact_execution",
        side_effect=[
            {"kind": "status", "status": "Running", "source": "show"},
            {"kind": "status", "status": "Succeeded", "source": "show"},
        ],
    ):
        assert supervise_migration_execution(
            state_path,
            evidence_output=evidence,
            max_attempts=2,
            poll_seconds=0,
        ) == "Succeeded"
    assert rollout._read_release_state(state_path)["migration_execution"][
        "terminal_status"
    ] == "Succeeded"
    assert json.loads(evidence.read_text())["status"] == "terminal_observed"


def test_restart_safe_execution_state_rejects_tampering(tmp_path, monkeypatch):
    state_path = _persisted_execution_state(tmp_path, monkeypatch)
    payload = json.loads(state_path.read_text())
    payload["migration_execution"]["execution_name"] = "migration-job-attacker"
    state_path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="signature is invalid"):
        rollout._read_release_state(state_path)


def test_ambiguous_pre_start_boundary_retains_traffic_and_requires_recovery(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("RELEASE_MANIFEST_HMAC_KEY", "x" * 32)
    state = mark_release_stage(_release_state(schema="013"), "migration_attempted")
    state = mark_migration_starting(
        state,
        job_name="migration-job",
        resource_group="example-rg",
        image_digest="sha256:" + "a" * 64,
        execution_marker="migration-123-1",
        known_executions=["migration-job-prior"],
    )
    state_path = tmp_path / "rollout-state.json"
    rollout._write_release_state(state_path, state)
    with pytest.raises(RuntimeError, match="start outcome is ambiguous"):
        recovery_decision(state, observed_schema="013")
    with pytest.raises(RuntimeError, match="quiescence cannot be proven"):
        quiesce_migration_execution(
            state_path,
            evidence_output=tmp_path / "quiescence.json",
            max_attempts=1,
            poll_seconds=0,
        )
    evidence = json.loads((tmp_path / "quiescence.json").read_text())
    assert evidence["status"] == "recovery_required_start_outcome_ambiguous"
    assert evidence["stop_result"] == "not_attempted_without_exact_execution"


def test_interrupted_start_resolves_only_exact_marker_head_and_digest(tmp_path, monkeypatch):
    monkeypatch.setenv("RELEASE_MANIFEST_HMAC_KEY", "x" * 32)
    state = mark_release_stage(_release_state(schema="013"), "migration_attempted")
    state = mark_migration_starting(
        state,
        job_name="migration-job",
        resource_group="example-rg",
        image_digest="sha256:" + "a" * 64,
        execution_marker="migration-123-1",
        known_executions=["migration-job-prior"],
    )
    state_path = tmp_path / "rollout-state.json"
    rollout._write_release_state(state_path, state)
    with patch.object(
        rollout,
        "_control_plane_run",
        side_effect=[
            CompletedProcess(
                [],
                0,
                stdout=json.dumps(["migration-job-prior", "migration-job-exact"]),
            ),
            CompletedProcess(
                [],
                0,
                stdout=json.dumps(
                    {
                        "args": [
                            _migration_envelope(
                                marker="migration-123-1",
                                digest="sha256:" + "a" * 64,
                            )
                        ],
                        "image": "registry.example/api@sha256:" + "a" * 64,
                    }
                ),
            ),
        ],
    ):
        execution = rollout.resolve_migration_start_boundary(
            state_path,
            evidence_output=tmp_path / "start.json",
        )
    assert execution == "migration-job-exact"
    persisted = rollout._read_release_state(state_path)
    assert "migration_starting" not in persisted
    assert persisted["migration_execution"]["execution_name"] == execution


def test_interrupted_start_never_binds_an_unrelated_new_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("RELEASE_MANIFEST_HMAC_KEY", "x" * 32)
    state = mark_release_stage(_release_state(schema="013"), "migration_attempted")
    state = mark_migration_starting(
        state,
        job_name="migration-job",
        resource_group="example-rg",
        image_digest="sha256:" + "a" * 64,
        execution_marker="migration-123-1",
        known_executions=[],
    )
    state_path = tmp_path / "rollout-state.json"
    rollout._write_release_state(state_path, state)
    with (
        patch.object(
            rollout,
            "_control_plane_run",
            side_effect=[
                CompletedProcess([], 0, stdout=json.dumps(["migration-job-unrelated"])),
                CompletedProcess(
                    [],
                    0,
                    stdout=json.dumps(
                        {
                                "args": [
                                    _migration_envelope(
                                        marker="other-run",
                                        digest="sha256:" + "a" * 64,
                                    )
                                ],
                            "image": "registry.example/api@sha256:" + "a" * 64,
                        }
                    ),
                ),
            ],
        ),
        pytest.raises(RuntimeError, match="one exact reviewed execution"),
    ):
        rollout.resolve_migration_start_boundary(
            state_path,
            evidence_output=tmp_path / "start.json",
        )
    persisted = rollout._read_release_state(state_path)
    assert "migration_execution" not in persisted
    assert persisted["migration_starting"]["execution_marker"] == "migration-123-1"


def test_interrupted_start_refuses_legacy_flag_pair_provenance(tmp_path, monkeypatch):
    monkeypatch.setenv("RELEASE_MANIFEST_HMAC_KEY", "x" * 32)
    state = mark_release_stage(_release_state(schema="013"), "migration_attempted")
    state = mark_migration_starting(
        state,
        job_name="migration-job",
        resource_group="example-rg",
        image_digest="sha256:" + "a" * 64,
        execution_marker="migration-123-1",
        known_executions=[],
    )
    state_path = tmp_path / "rollout-state.json"
    evidence_path = tmp_path / "start.json"
    rollout._write_release_state(state_path, state)
    with (
        patch.object(
            rollout,
            "_control_plane_run",
            side_effect=[
                CompletedProcess([], 0, stdout=json.dumps(["migration-job-legacy"])),
                CompletedProcess(
                    [],
                    0,
                    stdout=json.dumps(
                        {
                            "args": [
                                "--expect-head",
                                "014",
                                "--execution-marker",
                                "migration-123-1",
                            ],
                            "image": "registry.example/api@sha256:" + "a" * 64,
                        }
                    ),
                ),
            ],
        ),
        pytest.raises(RuntimeError, match="one exact reviewed execution"),
    ):
        rollout.resolve_migration_start_boundary(
            state_path,
            evidence_output=evidence_path,
        )

    assert json.loads(evidence_path.read_text())["reason_class"] == (
        "execution_details_malformed"
    )


def test_signed_release_state_atomic_write_fsyncs_file_and_directory(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("RELEASE_MANIFEST_HMAC_KEY", "x" * 32)
    state_path = tmp_path / "rollout-state.json"
    original_fsync = rollout.os.fsync
    with patch.object(rollout.os, "fsync", wraps=original_fsync) as fsync:
        rollout._write_release_state(state_path, _release_state(schema="014"))

    assert fsync.call_count >= 2
    assert rollout._read_release_state(state_path)["target_schema"] == "014"
    assert not list(tmp_path.glob(".rollout-state.json.*.tmp"))


def test_exact_execution_query_uses_exact_name_list_fallback_only():
    with patch.object(
        rollout,
        "_control_plane_run",
        side_effect=[
            CompletedProcess([], 2, stderr="show unsupported"),
            CompletedProcess([], 0, stdout="Running\n"),
        ],
    ) as control_plane:
        observation = rollout.observe_exact_execution(
            job_name="migration-job",
            resource_group="example-rg",
            execution_name="migration-job-abc123",
        )
    assert observation == {"kind": "status", "status": "Running", "source": "list"}
    fallback = control_plane.call_args_list[1].args[0]
    assert "[?name=='migration-job-abc123'].properties.status" in fallback
    assert "Running" not in fallback


@pytest.mark.parametrize("terminal", ["Failed", "Succeeded", "Cancelled", "Stopped"])
def test_quiescence_accepts_observed_terminal_without_stopping(tmp_path, monkeypatch, terminal):
    state_path = _persisted_execution_state(tmp_path, monkeypatch)
    evidence = tmp_path / "quiescence.json"
    with (
        patch.object(
            rollout,
            "observe_exact_execution",
            return_value={"kind": "status", "status": terminal, "source": "show"},
        ),
        patch.object(rollout, "_assert_no_unrelated_nonterminal_execution"),
        patch.object(rollout, "_control_plane_run") as control_plane,
    ):
        result = quiesce_migration_execution(
            state_path,
            evidence_output=evidence,
            max_attempts=2,
            poll_seconds=0,
        )
    control_plane.assert_not_called()
    assert result["status"] == "quiesced"
    persisted = rollout._read_release_state(state_path)
    assert persisted["migration_execution"]["quiescence_verified"] is True


@pytest.mark.parametrize("terminal", ["Stopped", "Succeeded"])
def test_quiescence_stops_only_exact_execution_and_handles_success_race(
    tmp_path, monkeypatch, terminal
):
    state_path = _persisted_execution_state(tmp_path, monkeypatch)
    evidence = tmp_path / "quiescence.json"
    with (
        patch.object(
            rollout,
            "observe_exact_execution",
            side_effect=[
                {"kind": "status", "status": "Running", "source": "show"},
                {"kind": "status", "status": terminal, "source": "show"},
            ],
        ),
        patch.object(
            rollout,
            "_control_plane_run",
            return_value=CompletedProcess([], 0, stdout=""),
        ) as control_plane,
        patch.object(rollout, "_assert_no_unrelated_nonterminal_execution"),
    ):
        result = quiesce_migration_execution(
            state_path,
            evidence_output=evidence,
            max_attempts=2,
            poll_seconds=0,
        )
    command = control_plane.call_args.args[0]
    assert command == [
        "az",
        "containerapp",
        "job",
        "stop",
        "--name",
        "migration-job",
        "--resource-group",
        "example-rg",
        "--job-execution-name",
        "migration-job-abc123",
    ]
    assert result["observation"]["status"] == terminal


def test_missing_execution_requires_durable_terminal_evidence(tmp_path, monkeypatch):
    terminal_path = _persisted_execution_state(
        tmp_path,
        monkeypatch,
        terminal_status="Succeeded",
    )
    with patch.object(
        rollout,
        "observe_exact_execution",
        return_value={"kind": "missing"},
    ), patch.object(rollout, "_assert_no_unrelated_nonterminal_execution"):
        result = quiesce_migration_execution(
            terminal_path,
            evidence_output=tmp_path / "terminal.json",
            max_attempts=1,
            poll_seconds=0,
        )
    assert result["status"] == "quiesced_from_durable_terminal_evidence"

    missing_path = _persisted_execution_state(tmp_path, monkeypatch)
    with (
        patch.object(
            rollout,
            "observe_exact_execution",
            return_value={"kind": "missing"},
        ),
        patch.object(
            rollout,
            "_control_plane_run",
            return_value=CompletedProcess([], 1, stderr="not found"),
        ),
        pytest.raises(RuntimeError, match="quiescence could not be proven"),
    ):
        quiesce_migration_execution(
            missing_path,
            evidence_output=tmp_path / "missing.json",
            max_attempts=1,
            poll_seconds=0,
        )


@pytest.mark.parametrize(
    "observation",
    [
        {"kind": "cli_error", "error_class": "AzureCliExecutionQueryError"},
        {"kind": "status", "status": "Processing", "source": "show"},
        {"kind": "status", "status": "Unknown", "source": "show"},
    ],
)
def test_quiescence_cli_error_or_nonterminal_timeout_retains_traffic(
    tmp_path, monkeypatch, observation
):
    state_path = _persisted_execution_state(tmp_path, monkeypatch)
    with (
        patch.object(rollout, "observe_exact_execution", return_value=observation),
        patch.object(
            rollout,
            "_control_plane_run",
            return_value=CompletedProcess([], 1, stderr="control-plane failure"),
        ),
        pytest.raises(RuntimeError, match="recovery required"),
    ):
        quiesce_migration_execution(
            state_path,
            evidence_output=tmp_path / "failure.json",
            max_attempts=1,
            poll_seconds=0,
        )


def test_recovery_refuses_traffic_decision_while_bound_execution_is_not_terminal():
    state = mark_release_stage(_release_state(schema="013"), "migration_attempted")
    state = set_migration_execution(
        state,
        job_name="migration-job",
        resource_group="example-rg",
        execution_name="migration-job-abc123",
        image_digest="sha256:" + "a" * 64,
    )
    with pytest.raises(RuntimeError, match="quiescence is not proven"):
        recovery_decision(state, observed_schema="013")

    terminal = mark_migration_terminal(state, "Succeeded")
    with pytest.raises(RuntimeError, match="concurrent migration quiescence"):
        recovery_decision(terminal, observed_schema="014")


def test_quiescence_blocks_unrelated_nonterminal_execution_without_stopping_it(
    tmp_path, monkeypatch
):
    state_path = _persisted_execution_state(tmp_path, monkeypatch)
    with (
        patch.object(
            rollout,
            "observe_exact_execution",
            return_value={"kind": "status", "status": "Succeeded", "source": "show"},
        ),
        patch.object(
            rollout,
            "_control_plane_run",
            return_value=CompletedProcess(
                [],
                0,
                stdout=json.dumps(
                    [
                        {"name": "migration-job-abc123", "status": "Succeeded"},
                        {"name": "migration-job-unrelated", "status": "Processing"},
                    ]
                ),
            ),
        ) as control_plane,
        pytest.raises(RuntimeError, match="unrelated nonterminal"),
    ):
        quiesce_migration_execution(
            state_path,
            evidence_output=tmp_path / "concurrent.json",
            max_attempts=1,
            poll_seconds=0,
        )
    commands = [call.args[0] for call in control_plane.call_args_list]
    assert all(command[3] != "stop" for command in commands)
    evidence = json.loads((tmp_path / "concurrent.json").read_text())
    assert evidence["status"] == "recovery_required_concurrent_execution_not_quiescent"


def test_signed_bridge_manifest_is_immutable_and_role_bound(tmp_path, monkeypatch):
    monkeypatch.setenv("RELEASE_MANIFEST_HMAC_KEY", "x" * 32)
    path = tmp_path / "bridge.json"
    _write_release_manifest(path, role="bridge")

    payload = verify_manifest(
        path,
        required_role="bridge",
        expected_run_id="12345",
        expected_run_attempt=2,
    )
    assert payload["schema_version"] == 3
    assert payload["schema_contract"]["accepted_revisions"] == ["013", "014"]
    assert payload["image_digest"] == "sha256:" + "a" * 64
    assert payload["observed_schema"] == "013"
    assert payload["platform"] == "linux/amd64"
    assert payload["build_provenance"]["source_sha"] == "b" * 40
    with pytest.raises(ValueError, match="role"):
        verify_manifest(path, required_role="final")

    with pytest.raises(ValueError, match="run attempt"):
        verify_manifest(
            path,
            required_role="bridge",
            expected_run_id="12345",
            expected_run_attempt=1,
        )
    with pytest.raises(ValueError, match="repository"):
        verify_manifest(
            path,
            required_role="bridge",
            expected_repository="other/archmorph",
        )
    with pytest.raises(ValueError, match="workflow"):
        verify_manifest(
            path,
            required_role="bridge",
            expected_workflow="Other Workflow",
        )

    payload = json.loads(path.read_text())
    payload["revision"] = "api-arbitrary"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="signature"):
        verify_manifest(path, required_role="bridge")


def test_release_manifest_accepts_only_same_digest_registry_alias(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("RELEASE_MANIFEST_HMAC_KEY", "x" * 32)
    path = tmp_path / "final.json"
    _write_release_manifest(
        path,
        build_repository="ghcr.io/example/archmorph-api-release-build",
        release_repository="registry.example/archmorph-api",
    )

    manifest = verify_manifest(path, required_role="final")
    assert manifest["image"] == "registry.example/archmorph-api@sha256:" + "a" * 64
    assert manifest["build_provenance"]["image"] == (
        "ghcr.io/example/archmorph-api-release-build@sha256:" + "a" * 64
    )

    with pytest.raises(ValueError, match="digest does not match"):
        write_manifest(
            tmp_path / "substituted.json",
            role="final",
            revision="api-final",
            image="registry.example/archmorph-api@sha256:" + "c" * 64,
            source_sha="b" * 40,
            schema_contract=_schema_contract("014"),
            observed_schema="014",
            repository="example/archmorph",
            workflow="CI/CD",
            run_id="12345",
            run_attempt=2,
            build_provenance=tmp_path / "final-build-provenance.json",
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_sha", "short", "source SHA"),
        ("schema_version", 1, "schema version"),
        ("schema_contract_digest", "sha256:" + "0" * 64, "contract digest"),
    ],
)
def test_signed_manifest_rejects_resigned_invalid_required_field(
    tmp_path, monkeypatch, field, value, message
):
    monkeypatch.setenv("RELEASE_MANIFEST_HMAC_KEY", "x" * 32)
    path = tmp_path / "final.json"
    _write_release_manifest(path)
    payload = json.loads(path.read_text())
    payload[field] = value
    unsigned = {key: value for key, value in payload.items() if key != "signature"}
    canonical = json.dumps(unsigned, separators=(",", ":"), sort_keys=True).encode()
    payload["signature"] = "sha256=" + hmac.new(b"x" * 32, canonical, hashlib.sha256).hexdigest()
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match=message):
        verify_manifest(path, required_role="final")


def test_signed_final_runtime_comparison_is_not_tautological(tmp_path, monkeypatch):
    monkeypatch.setenv("RELEASE_MANIFEST_HMAC_KEY", "x" * 32)
    path = tmp_path / "final.json"
    _write_release_manifest(path)
    manifest = verify_manifest(path, required_role="final")
    runtime = {
        "status": "compatible",
        "current_revision": "014",
        "minimum_revision": "013",
        "maximum_revision": "014",
        "accepted_revisions": ["013", "014"],
        "migration_target_revision": "014",
        "alias_read_through_until": "014",
        "release_role": "final",
    }

    with pytest.raises(ValueError, match="minimum_revision"):
        verify_runtime_compatibility(manifest, runtime)

    runtime.update(minimum_revision="014", accepted_revisions=["014"])
    assert verify_runtime_compatibility(manifest, runtime) == "014"


def test_signed_final_binds_revision_image_source_contract_and_zero_traffic(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("RELEASE_MANIFEST_HMAC_KEY", "x" * 32)
    path = tmp_path / "final.json"
    _write_release_manifest(path)
    manifest = verify_manifest(path, required_role="final")
    revision = {
        "name": "api-final",
        "properties": {
            "active": True,
            "trafficWeight": 0,
            "fqdn": "api-final.example.internal",
            "template": {
                "containers": [
                    {
                        "image": manifest["image"],
                        "env": [
                            {"name": "ARCHMORPH_RELEASE_ROLE", "value": "final"},
                            {"name": "ARCHMORPH_SOURCE_SHA", "value": "b" * 40},
                            {
                                "name": "ARCHMORPH_SCHEMA_CONTRACT_DIGEST",
                                "value": manifest["schema_contract_digest"],
                            },
                            {"name": "APP_SCHEMA_MIN_REVISION", "value": "014"},
                            {"name": "APP_SCHEMA_MAX_REVISION", "value": "014"},
                        ],
                    }
                ]
            },
        },
    }
    assert (
        verify_revision_target(manifest, revision, require_zero_traffic=True)
        == "api-final.example.internal"
    )
    revision["properties"]["template"]["containers"][0]["env"][1]["value"] = (
        "c" * 40
    )
    with pytest.raises(ValueError, match="ARCHMORPH_SOURCE_SHA"):
        verify_revision_target(manifest, revision, require_zero_traffic=True)


def test_release_manifest_rejects_duplicate_json_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("RELEASE_MANIFEST_HMAC_KEY", "x" * 32)
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema_version":3,"schema_version":3,"signature":"invalid"}')
    with pytest.raises(ValueError, match="duplicate key"):
        verify_manifest(path, required_role="final")


def test_release_manifest_rejects_resigned_unexpected_field(tmp_path, monkeypatch):
    monkeypatch.setenv("RELEASE_MANIFEST_HMAC_KEY", "x" * 32)
    path = tmp_path / "final.json"
    _write_release_manifest(path)
    payload = json.loads(path.read_text())
    payload["unreviewed"] = "smuggled"
    unsigned = {key: value for key, value in payload.items() if key != "signature"}
    canonical = json.dumps(unsigned, separators=(",", ":"), sort_keys=True).encode()
    payload["signature"] = (
        "sha256="
        + hmac.new(b"x" * 32, canonical, hashlib.sha256).hexdigest()
    )
    path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="incomplete or unexpected"):
        verify_manifest(path, required_role="final")
