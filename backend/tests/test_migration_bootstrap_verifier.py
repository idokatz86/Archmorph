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
