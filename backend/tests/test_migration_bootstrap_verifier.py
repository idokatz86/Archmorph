"""Deterministic migration-bootstrap backend, plan, and integrity contracts."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_migration_bootstrap.py"
SPEC = importlib.util.spec_from_file_location("verify_migration_bootstrap", SCRIPT)
assert SPEC and SPEC.loader
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


def _change(address: str, resource_type: str, actions: list[str], *, mode: str = "managed") -> dict:
    return {
        "address": address,
        "mode": mode,
        "type": resource_type,
        "change": {"actions": actions},
    }


ENVIRONMENT_ID = (
    "/subscriptions/example/resourceGroups/runtime/providers/"
    "Microsoft.App/managedEnvironments/private-runtime"
)
ENVIRONMENT = {
    "id": ENVIRONMENT_ID,
    "location": "North Europe",
    "subnetId": "/subscriptions/example/resourceGroups/runtime/providers/Microsoft.Network/virtualNetworks/runtime/subnets/apps",
    "provisioningState": "Succeeded",
}


def test_environment_accepts_exact_runtime_identity_case_insensitively():
    verifier.validate_environment(
        {"environmentId": ENVIRONMENT_ID.upper()},
        ENVIRONMENT,
    )


@pytest.mark.parametrize(
    ("app", "environment", "reason"),
    [
        (None, ENVIRONMENT, "metadata must be objects"),
        ({}, ENVIRONMENT, "identity is missing"),
        ({"environmentId": None}, ENVIRONMENT, "identity is missing"),
        ({"environmentId": ENVIRONMENT_ID + "-legacy"}, ENVIRONMENT, "does not match"),
        (
            {"environmentId": ENVIRONMENT_ID.replace("/example/", "/example-different/")},
            ENVIRONMENT, "does not match",
        ),
        ({"environmentId": ENVIRONMENT_ID}, {**ENVIRONMENT, "subnetId": None}, "no private-network"),
        ({"environmentId": ENVIRONMENT_ID}, {**ENVIRONMENT, "subnetId": ""}, "no private-network"),
        ({"environmentId": ENVIRONMENT_ID}, {**ENVIRONMENT, "provisioningState": "Failed"}, "not ready"),
    ],
)
def test_environment_rejects_stale_missing_or_non_private_target(app, environment, reason):
    with pytest.raises(ValueError, match=reason):
        verifier.validate_environment(app, environment)


def test_existing_identity_keeps_its_region_when_job_environment_changes():
    assert verifier.select_identity_location(
        [{"name": "migration-identity", "location": "westeurope"}],
        "migration-identity", ENVIRONMENT,
    ) == "westeurope"


def test_new_identity_uses_runtime_region():
    assert verifier.select_identity_location([], "migration-identity", ENVIRONMENT) == "northeurope"


@pytest.mark.parametrize(
    "identities",
    [
        [{"name": "migration-identity", "location": None}],
        [{"name": "migration-identity", "location": ""}],
        [{"name": "migration-identity", "location": "west/europe"}],
        [
            {"name": "migration-identity", "location": "westeurope"},
            {"name": "MIGRATION-IDENTITY", "location": "northeurope"},
        ],
        [None],
    ],
)
def test_identity_location_cannot_silently_fallback_for_existing_identity(identities):
    with pytest.raises(ValueError, match="identity"):
        verifier.select_identity_location(identities, "migration-identity", ENVIRONMENT)


def test_backend_rejects_equal_keys_even_when_other_tuple_fields_differ():
    with pytest.raises(ValueError, match="state key must differ"):
        verifier.validate_backend_separation(
            primary=("primary", "tfstate", "prod.tfstate"),
            bootstrap=("bootstrap", "migration", "prod.tfstate"),
        )


def test_backend_rejects_equal_full_tuple_and_ambiguous_values():
    with pytest.raises(ValueError, match="tuple equals|state key"):
        verifier.validate_backend_separation(
            primary=("state", "tfstate", "prod.tfstate"),
            bootstrap=("state", "tfstate", "prod.tfstate"),
        )
    with pytest.raises(ValueError, match="missing or ambiguous"):
        verifier.validate_backend_separation(
            primary=("state", "tfstate", "prod.tfstate"),
            bootstrap=("state", " migration ", "migration.tfstate"),
        )


def test_backend_requires_separate_account_or_container_not_only_key():
    with pytest.raises(ValueError, match="separate storage account or container"):
        verifier.validate_backend_separation(
            primary=("state", "tfstate", "prod.tfstate"),
            bootstrap=("state", "tfstate", "migration.tfstate"),
        )
    verifier.validate_backend_separation(
        primary=("state", "tfstate", "prod.tfstate"),
        bootstrap=("state", "migration", "migration.tfstate"),
    )


@pytest.mark.parametrize("actions", [["delete"], ["delete", "create"], ["create", "delete"]])
def test_plan_rejects_delete_and_replace(actions):
    plan = {
        "resource_changes": [
            _change(
                "azurerm_container_app_job.database_migration",
                "azurerm_container_app_job",
                actions,
            )
        ]
    }
    with pytest.raises(ValueError, match="delete/replace"):
        verifier.validate_plan(plan)


def test_plan_rejects_unknown_or_primary_resource_change():
    for address, resource_type in (
        ("azurerm_storage_account.unreviewed", "azurerm_storage_account"),
        ("azurerm_container_app.backend", "azurerm_container_app"),
    ):
        with pytest.raises(ValueError, match="unknown managed|forbidden"):
            verifier.validate_plan(
                {"resource_changes": [_change(address, resource_type, ["create"])]}
            )


@pytest.mark.parametrize(
    "kv_change",
    [
        _change(
            "azurerm_role_assignment.database_secret_reader[0]",
            "azurerm_role_assignment",
            ["create"],
        ),
        _change(
            "azurerm_key_vault_access_policy.database_secret_reader[0]",
            "azurerm_key_vault_access_policy",
            ["create"],
        ),
        None,
    ],
)
def test_plan_allows_reviewed_rbac_access_policy_and_noop_branches(kv_change):
    changes = [
        _change(
            "data.azurerm_container_app_environment.runtime",
            "azurerm_container_app_environment",
            ["read"],
            mode="data",
        ),
        _change(
            "data.azurerm_container_registry.runtime",
            "azurerm_container_registry",
            ["read"],
            mode="data",
        ),
        _change(
            "data.azurerm_key_vault.runtime",
            "azurerm_key_vault",
            ["read"],
            mode="data",
        ),
        _change(
            "azurerm_user_assigned_identity.database_migration",
            "azurerm_user_assigned_identity",
            ["create"],
        ),
        _change("azurerm_role_assignment.acr_pull", "azurerm_role_assignment", ["create"]),
        _change("time_sleep.rbac_propagation", "time_sleep", ["create"]),
        _change(
            "azurerm_container_app_job.database_migration",
            "azurerm_container_app_job",
            ["update"] if kv_change else ["no-op"],
        ),
    ]
    if kv_change:
        changes.append(kv_change)
    counts = verifier.validate_plan({"resource_changes": changes})
    assert counts["read"] == 3
    assert sum(counts.values()) == len(changes)


def test_plan_rejects_both_key_vault_authorization_modes():
    with pytest.raises(ValueError, match="both Key Vault"):
        verifier.validate_plan(
            {
                "resource_changes": [
                    _change(
                        "azurerm_role_assignment.database_secret_reader[0]",
                        "azurerm_role_assignment",
                        ["create"],
                    ),
                    _change(
                        "azurerm_key_vault_access_policy.database_secret_reader[0]",
                        "azurerm_key_vault_access_policy",
                        ["create"],
                    ),
                ]
            }
        )


def test_plan_metadata_detects_plan_lock_lineage_serial_or_state_hash_change(tmp_path):
    plan = tmp_path / "plan"
    lock = tmp_path / "lock"
    primary = tmp_path / "primary.json"
    bootstrap = tmp_path / "bootstrap.json"
    metadata = tmp_path / "metadata.json"
    plan.write_bytes(b"plan")
    lock.write_bytes(b"lock")
    primary.write_text(json.dumps({"lineage": "primary", "serial": 4}))
    bootstrap.write_text(json.dumps({"lineage": "bootstrap", "serial": 7}))
    verifier.write_metadata(
        plan=plan,
        lock=lock,
        primary_state=primary,
        bootstrap_state=bootstrap,
        output=metadata,
    )
    verifier.verify_metadata(
        metadata_path=metadata,
        plan=plan,
        lock=lock,
        primary_state=primary,
        bootstrap_state=bootstrap,
    )

    bootstrap.write_text(json.dumps({"lineage": "bootstrap", "serial": 8}))
    with pytest.raises(ValueError, match="integrity changed"):
        verifier.verify_metadata(
            metadata_path=metadata,
            plan=plan,
            lock=lock,
            primary_state=primary,
            bootstrap_state=bootstrap,
        )


@pytest.fixture
def integrity_files(tmp_path):
    files = {
        name: tmp_path / name
        for name in ("plan", "lock", "primary_state", "bootstrap_state", "metadata_path")
    }
    files["plan"].write_bytes(b"reviewed binary plan")
    files["lock"].write_bytes(b"reviewed provider lock")
    for name in ("primary_state", "bootstrap_state"):
        files[name].write_text(json.dumps({
            "lineage": name,
            "serial": 7,
            "resources": [
                {"name": "example-a", "values": {"setting": "before"}},
                {"name": "example-b", "values": {"setting": "unchanged"}},
            ],
            "check_results": [
                {"object_kind": "var", "config_addr": "var.region", "status": "pass", "objects": []},
                {"object_kind": "var", "config_addr": "var.image", "status": "pass", "objects": []},
            ],
        }))
    verifier.write_metadata(
        plan=files["plan"], lock=files["lock"],
        primary_state=files["primary_state"], bootstrap_state=files["bootstrap_state"],
        output=files["metadata_path"],
    )
    return files


def test_metadata_accepts_only_serialization_and_check_result_order_changes(integrity_files):
    for name in ("primary_state", "bootstrap_state"):
        path = integrity_files[name]
        state = json.loads(path.read_text())
        state["check_results"].reverse()
        path.write_text(json.dumps(state, indent=4, sort_keys=True) + "\n")
    verifier.verify_metadata(**integrity_files)


@pytest.mark.parametrize("name", ["primary_state", "bootstrap_state"])
@pytest.mark.parametrize(
    "field",
    ["lineage", "serial", "resource_value", "resource_order", "check_status", "check_removed", "check_added"],
)
def test_canonical_state_digest_still_rejects_real_changes(integrity_files, name, field):
    path = integrity_files[name]
    state = json.loads(path.read_text())
    if field == "lineage":
        state["lineage"] = "different"
    elif field == "serial":
        state["serial"] += 1
    elif field == "resource_value":
        state["resources"][0]["values"]["setting"] = "after"
    elif field == "resource_order":
        state["resources"].reverse()
    elif field == "check_status":
        state["check_results"][0]["status"] = "fail"
    elif field == "check_removed":
        state["check_results"].pop()
    else:
        state["check_results"].append(dict(state["check_results"][0]))
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError, match="integrity changed"):
        verifier.verify_metadata(**integrity_files)


@pytest.mark.parametrize("name", ["plan", "lock"])
def test_plan_and_provider_lock_still_use_exact_byte_hashes(integrity_files, name):
    path = integrity_files[name]
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="integrity changed"):
        verifier.verify_metadata(**integrity_files)


def test_canonical_state_metadata_has_distinct_schema_and_rejects_legacy(integrity_files):
    path = integrity_files["metadata_path"]
    metadata = json.loads(path.read_text())
    assert metadata["schema_version"] == 2
    metadata["schema_version"] = 1
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="integrity changed"):
        verifier.verify_metadata(**integrity_files)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("0.5", "0.50000000000000001"),
        ("9007199254740992.0", "9007199254740993.0"),
        ("1e-30", "1.0000000000000001e-30"),
        ("0.5", '"0.5"'),
        ("7", '"7"'),
    ],
)
def test_raw_json_number_changes_cannot_be_lost_or_collide_with_strings(
    integrity_files, before, after,
):
    path = integrity_files["primary_state"]
    original = path.read_text()
    path.write_text(original.replace('"before"', before, 1))
    verifier.write_metadata(
        plan=integrity_files["plan"], lock=integrity_files["lock"],
        primary_state=path, bootstrap_state=integrity_files["bootstrap_state"],
        output=integrity_files["metadata_path"],
    )
    path.write_text(original.replace('"before"', after, 1))
    with pytest.raises(ValueError, match="integrity changed"):
        verifier.verify_metadata(**integrity_files)


def test_duplicate_state_object_keys_fail_closed(tmp_path):
    path = tmp_path / "state"
    path.write_text('{"lineage":"example","serial":7,"value":1,"value":2}')
    with pytest.raises(ValueError, match="duplicate"):
        verifier._state_identity(path)
