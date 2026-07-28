#!/usr/bin/env python3
"""Fail-closed validation for the isolated migration-bootstrap state and plan."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


_ALLOWED_MANAGED = {
    "azurerm_user_assigned_identity.database_migration": "azurerm_user_assigned_identity",
    "azurerm_role_assignment.acr_pull": "azurerm_role_assignment",
    "azurerm_role_assignment.database_secret_reader[0]": "azurerm_role_assignment",
    "azurerm_key_vault_access_policy.database_secret_reader[0]": "azurerm_key_vault_access_policy",
    "time_sleep.rbac_propagation": "time_sleep",
    "azurerm_container_app_job.database_migration": "azurerm_container_app_job",
}
_ALLOWED_DATA_TYPES = {
    "azurerm_container_app_environment",
    "azurerm_container_registry",
    "azurerm_key_vault",
}
_FORBIDDEN_TYPES = {
    "azurerm_container_app",
    "azurerm_container_app_environment",
    "azurerm_cdn_frontdoor_endpoint",
    "azurerm_private_endpoint",
    "azurerm_resource_group",
    "azurerm_static_web_app",
    "azurerm_subnet",
    "azurerm_virtual_network",
}


def validate_backend_separation(*, primary: tuple[str, str, str], bootstrap: tuple[str, str, str]) -> None:
    """Require two complete, unambiguous remote-state identities."""
    fields = ("storage account", "container", "key")
    for prefix, backend in (("primary", primary), ("bootstrap", bootstrap)):
        for field, value in zip(fields, backend, strict=True):
            if not value or value.strip() != value:
                raise ValueError(f"Terraform {prefix} backend {field} is missing or ambiguous")
    if bootstrap == primary:
        raise ValueError("migration bootstrap backend tuple equals the primary backend")
    if bootstrap[2] == primary[2]:
        raise ValueError("migration bootstrap state key must differ from the primary state key")
    if bootstrap[0] == primary[0] and bootstrap[1] == primary[1]:
        raise ValueError(
            "migration bootstrap must use a separate storage account or container, not only a key"
        )


def _actions(change: dict[str, Any]) -> list[str]:
    return list(change.get("change", {}).get("actions", []))


def validate_plan(plan: dict[str, Any]) -> dict[str, int]:
    """Allow only the reviewed bootstrap graph and non-destructive actions."""
    if not isinstance(plan.get("resource_changes", []), list):
        raise ValueError("Terraform plan is missing resource_changes")
    counts = {"create": 0, "update": 0, "read": 0, "no-op": 0}
    kv_modes: set[str] = set()
    for change in plan.get("resource_changes", []):
        address = str(change.get("address") or "")
        resource_type = str(change.get("type") or "")
        mode = str(change.get("mode") or "managed")
        actions = _actions(change)
        if "delete" in actions or {"create", "delete"}.issubset(actions):
            raise ValueError(f"bootstrap plan contains delete/replace action at {address}")
        if mode == "data":
            if resource_type not in _ALLOWED_DATA_TYPES or any(
                action not in {"read", "no-op"} for action in actions
            ):
                raise ValueError(f"bootstrap plan contains unknown data read at {address}")
        else:
            if resource_type in _FORBIDDEN_TYPES:
                raise ValueError(f"bootstrap plan contains forbidden application resource at {address}")
            expected_type = _ALLOWED_MANAGED.get(address)
            if expected_type is None or expected_type != resource_type:
                raise ValueError(f"bootstrap plan contains unknown managed resource at {address}")
            if any(action not in {"create", "update", "read", "no-op"} for action in actions):
                raise ValueError(f"bootstrap plan contains unsupported action at {address}: {actions}")
            if address.startswith("azurerm_role_assignment.database_secret_reader"):
                kv_modes.add("rbac")
            if address.startswith("azurerm_key_vault_access_policy.database_secret_reader"):
                kv_modes.add("access-policy")
        for action in actions:
            if action in counts:
                counts[action] += 1
    if len(kv_modes) > 1:
        raise ValueError("bootstrap plan enables both Key Vault authorization alternatives")
    return counts


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _state_identity(path: Path) -> dict[str, Any]:
    state = json.loads(path.read_text(encoding="utf-8"))
    lineage = state.get("lineage")
    serial = state.get("serial")
    if not isinstance(lineage, str) or not lineage or not isinstance(serial, int):
        raise ValueError(f"Terraform state {path} has no valid lineage/serial")
    return {"lineage": lineage, "serial": serial, "sha256": _sha256(path)}


def write_metadata(
    *,
    plan: Path,
    lock: Path,
    primary_state: Path,
    bootstrap_state: Path,
    output: Path,
) -> dict[str, Any]:
    metadata = {
        "schema_version": 1,
        "plan_sha256": _sha256(plan),
        "provider_lock_sha256": _sha256(lock),
        "primary_state": _state_identity(primary_state),
        "bootstrap_state": _state_identity(bootstrap_state),
    }
    output.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return metadata


def verify_metadata(
    *,
    metadata_path: Path,
    plan: Path,
    lock: Path,
    primary_state: Path,
    bootstrap_state: Path,
) -> None:
    expected = json.loads(metadata_path.read_text(encoding="utf-8"))
    actual = {
        "schema_version": 1,
        "plan_sha256": _sha256(plan),
        "provider_lock_sha256": _sha256(lock),
        "primary_state": _state_identity(primary_state),
        "bootstrap_state": _state_identity(bootstrap_state),
    }
    if actual != expected:
        raise ValueError("migration bootstrap plan/state integrity changed before apply")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    backend = subparsers.add_parser("backend")
    for name in (
        "primary-account",
        "primary-container",
        "primary-key",
        "bootstrap-account",
        "bootstrap-container",
        "bootstrap-key",
    ):
        backend.add_argument(f"--{name}", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--input", required=True, type=Path)
    for command in ("write-metadata", "verify-metadata"):
        metadata = subparsers.add_parser(command)
        metadata.add_argument("--plan", required=True, type=Path)
        metadata.add_argument("--lock", required=True, type=Path)
        metadata.add_argument("--primary-state", required=True, type=Path)
        metadata.add_argument("--bootstrap-state", required=True, type=Path)
        metadata.add_argument("--metadata", required=True, type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "backend":
        validate_backend_separation(
            primary=(args.primary_account, args.primary_container, args.primary_key),
            bootstrap=(args.bootstrap_account, args.bootstrap_container, args.bootstrap_key),
        )
        print("Migration bootstrap backend is isolated from the primary state.")
    elif args.command == "plan":
        plan = json.loads(args.input.read_text(encoding="utf-8"))
        print(json.dumps(validate_plan(plan), sort_keys=True))
    elif args.command == "write-metadata":
        write_metadata(
            plan=args.plan,
            lock=args.lock,
            primary_state=args.primary_state,
            bootstrap_state=args.bootstrap_state,
            output=args.metadata,
        )
    else:
        verify_metadata(
            metadata_path=args.metadata,
            plan=args.plan,
            lock=args.lock,
            primary_state=args.primary_state,
            bootstrap_state=args.bootstrap_state,
        )
        print("Migration bootstrap plan and both state identities remain unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
