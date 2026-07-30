"""Adversarial schema-bound Helm release choreography contracts."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "helm_release_contract.py"
SPEC = importlib.util.spec_from_file_location("helm_release_contract", SCRIPT)
assert SPEC and SPEC.loader
contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contract)


def _schema(*accepted: str) -> dict:
    return {
        "contract_version": 1,
        "migration_target_revision": accepted[-1],
        "minimum_revision": accepted[0],
        "maximum_revision": accepted[-1],
        "accepted_revisions": list(accepted),
        "alias_read_through_until": accepted[-1],
    }


def _runtime(current: str, *accepted: str, role: str = "final") -> dict:
    schema = _schema(*accepted)
    return {
        "status": "compatible",
        "current_revision": current,
        "minimum_revision": schema["minimum_revision"],
        "maximum_revision": schema["maximum_revision"],
        "accepted_revisions": schema["accepted_revisions"],
        "migration_target_revision": schema["migration_target_revision"],
        "alias_read_through_until": schema["alias_read_through_until"],
        "release_role": role,
    }


def _migration_contract() -> dict:
    return {"expected_head": "014", "accepted_current": ["013", "014"]}


def test_first_013_to_014_failure_after_migration_retains_verified_bridge():
    plan = contract.plan_release(
        previous_runtime=_runtime("013", "013"),
        target_contract_payload=_schema("014"),
        migration_contract=_migration_contract(),
        bridge_runtime=_runtime("013", "013", "014", role="bridge"),
        bridge_contract_payload=_schema("013", "014"),
    )

    assert plan["migration_required"] is True
    assert plan["protection_mode"] == "staged_bridge"
    assert plan["automatic_rollback_allowed"] is False
    assert plan["post_migration_failure_action"] == "retain_bridge_and_fix_forward"


def test_routine_014_to_014_failure_retains_compatible_previous_image():
    plan = contract.plan_release(
        previous_runtime=_runtime("014", "014"),
        target_contract_payload=_schema("014"),
        migration_contract=_migration_contract(),
    )

    assert plan["migration_required"] is False
    assert plan["protection_mode"] == "compatible_previous"
    assert plan["post_migration_failure_action"] == (
        "retain_compatible_previous_and_fix_forward"
    )
    assert plan["automatic_rollback_allowed"] is False


def test_compatible_prior_image_can_protect_013_to_014_without_bridge():
    plan = contract.plan_release(
        previous_runtime=_runtime("013", "013", "014"),
        target_contract_payload=_schema("014"),
        migration_contract=_migration_contract(),
    )

    assert plan["migration_required"] is True
    assert plan["protection_mode"] == "compatible_previous"
    assert plan["bridge_contract_digest"] is None


def test_incompatible_prior_image_is_rejected_before_migration_without_bridge():
    with pytest.raises(ValueError, match="no verified bridge"):
        contract.plan_release(
            previous_runtime=_runtime("013", "013"),
            target_contract_payload=_schema("014"),
            migration_contract=_migration_contract(),
        )


def test_target_readiness_contract_failure_is_fix_forward_not_old_image_rollback():
    with pytest.raises(ValueError, match="target runtime contract differs"):
        contract.verify_target_runtime(
            _runtime("014", "013", "014"),
            _schema("014"),
            expected_schema="014",
        )

    with pytest.raises(ValueError, match="did not report a compatible schema"):
        runtime = _runtime("014", "014")
        runtime["status"] = "incompatible"
        contract.verify_target_runtime(runtime, _schema("014"), expected_schema="014")


def test_rerun_after_committed_migration_reuses_only_live_verified_bridge():
    plan = contract.plan_release(
        previous_runtime=_runtime("014", "013", "014", role="bridge"),
        target_contract_payload=_schema("014"),
        migration_contract=_migration_contract(),
        bridge_contract_payload=_schema("013", "014"),
    )

    assert plan["migration_required"] is False
    assert plan["protection_mode"] == "existing_bridge"
    assert plan["post_migration_failure_action"] == "retain_bridge_and_fix_forward"


def test_bridge_observation_or_contract_cannot_be_substituted():
    with pytest.raises(ValueError, match="does not match the current"):
        contract.plan_release(
            previous_runtime=_runtime("013", "013"),
            target_contract_payload=_schema("014"),
            migration_contract=_migration_contract(),
            bridge_runtime=_runtime("014", "013", "014", role="bridge"),
            bridge_contract_payload=_schema("013", "014"),
        )

    with pytest.raises(ValueError, match="differs from the reviewed bridge"):
        contract.plan_release(
            previous_runtime=_runtime("013", "013"),
            target_contract_payload=_schema("014"),
            migration_contract=_migration_contract(),
            bridge_runtime=_runtime("013", "013", role="bridge"),
            bridge_contract_payload=_schema("013", "014"),
        )

    with pytest.raises(ValueError, match="differs from the reviewed bridge"):
        contract.plan_release(
            previous_runtime=_runtime("013", "013"),
            target_contract_payload=_schema("014"),
            migration_contract=_migration_contract(),
            bridge_runtime=_runtime("013", "013", "014", role="bridge"),
            bridge_contract_payload={
                **_schema("013", "014"),
                "alias_read_through_until": "013",
            },
        )
