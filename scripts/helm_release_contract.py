#!/usr/bin/env python3
"""Schema-bound Helm release planning and runtime verification."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


_SCHEMA_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_CONTRACT_FIELDS = (
    "contract_version",
    "migration_target_revision",
    "minimum_revision",
    "maximum_revision",
    "accepted_revisions",
    "alias_read_through_until",
)


def _json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_contract(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or set(payload) != set(_CONTRACT_FIELDS):
        raise ValueError("schema contract fields are incomplete or unexpected")
    if payload.get("contract_version") != 1:
        raise ValueError("schema contract version is unsupported")
    raw_accepted = payload.get("accepted_revisions")
    if not isinstance(raw_accepted, list) or not raw_accepted:
        raise ValueError("schema contract requires accepted revisions")
    accepted = [str(item) for item in raw_accepted]
    if accepted != sorted(set(accepted)) or any(
        not _SCHEMA_RE.fullmatch(item) for item in accepted
    ):
        raise ValueError("schema contract accepted revisions are invalid")
    contract: dict[str, object] = {
        "contract_version": 1,
        "migration_target_revision": str(
            payload.get("migration_target_revision") or ""
        ),
        "minimum_revision": str(payload.get("minimum_revision") or ""),
        "maximum_revision": str(payload.get("maximum_revision") or ""),
        "accepted_revisions": accepted,
        "alias_read_through_until": str(payload.get("alias_read_through_until") or ""),
    }
    for field in (
        "migration_target_revision",
        "minimum_revision",
        "maximum_revision",
        "alias_read_through_until",
    ):
        revision = str(contract[field])
        if not _SCHEMA_RE.fullmatch(revision) or revision not in accepted:
            raise ValueError(f"schema contract {field} is not accepted")
    return contract


def contract_digest(payload: object) -> str:
    contract = normalize_contract(payload)
    canonical = json.dumps(contract, separators=(",", ":"), sort_keys=True).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def runtime_contract(
    payload: object, *, expected_role: str | None = None
) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("status") != "compatible":
        raise ValueError("runtime did not report a compatible schema")
    role = str(payload.get("release_role") or "")
    if role not in {"bridge", "final"}:
        raise ValueError("runtime release role is invalid")
    if expected_role is not None and role != expected_role:
        raise ValueError("runtime release role does not match the expected role")
    current = str(payload.get("current_revision") or "")
    contract = normalize_contract(
        {
            "contract_version": 1,
            "migration_target_revision": payload.get("migration_target_revision"),
            "minimum_revision": payload.get("minimum_revision"),
            "maximum_revision": payload.get("maximum_revision"),
            "accepted_revisions": payload.get("accepted_revisions"),
            "alias_read_through_until": payload.get("alias_read_through_until"),
        }
    )
    if current not in contract["accepted_revisions"]:
        raise ValueError("runtime current schema is outside its image contract")
    return {
        "role": role,
        "current_revision": current,
        "contract": contract,
        "contract_digest": contract_digest(contract),
    }


def _validate_migration_contract(payload: object, *, current: str, target: str) -> None:
    if not isinstance(payload, dict):
        raise ValueError("migration contract is missing")
    expected_head = str(payload.get("expected_head") or "")
    accepted = payload.get("accepted_current")
    if expected_head != target or not isinstance(accepted, list):
        raise ValueError("migration contract does not target the application schema")
    revisions = [str(item) for item in accepted]
    if (
        revisions != sorted(set(revisions))
        or current not in revisions
        or target not in revisions
    ):
        raise ValueError(
            "migration contract does not accept current and target schemas"
        )


def plan_release(
    *,
    previous_runtime: object,
    target_contract_payload: object,
    migration_contract: object,
    bridge_runtime: object | None = None,
    bridge_contract_payload: object | None = None,
) -> dict[str, object]:
    """Choose a schema-safe phase plan before any migration is allowed."""
    previous = runtime_contract(previous_runtime)
    target_contract = normalize_contract(target_contract_payload)
    target = str(target_contract["migration_target_revision"])
    if target not in target_contract["accepted_revisions"]:
        raise ValueError("target image does not accept its migration target")
    current = str(previous["current_revision"])
    _validate_migration_contract(migration_contract, current=current, target=target)

    previous_accepts_target = target in previous["contract"]["accepted_revisions"]
    if previous["role"] == "bridge":
        if bridge_contract_payload is None:
            raise ValueError("active bridge requires a reviewed bridge contract")
        reviewed_bridge = normalize_contract(bridge_contract_payload)
        if previous["contract"] != reviewed_bridge:
            raise ValueError("active bridge differs from the reviewed bridge contract")
        if not previous_accepts_target:
            raise ValueError("active recovery bridge does not accept the target schema")
        protection_mode = "existing_bridge"
        bridge = previous
    elif previous_accepts_target:
        protection_mode = "compatible_previous"
        bridge = None
    else:
        if bridge_runtime is None:
            raise ValueError(
                "previous workload excludes the target schema and no verified bridge is available"
            )
        if bridge_contract_payload is None:
            raise ValueError("staged bridge requires a reviewed bridge contract")
        bridge = runtime_contract(bridge_runtime, expected_role="bridge")
        reviewed_bridge = normalize_contract(bridge_contract_payload)
        if bridge["contract"] != reviewed_bridge:
            raise ValueError("staged bridge differs from the reviewed bridge contract")
        if bridge["current_revision"] != current:
            raise ValueError(
                "bridge observation does not match the current database schema"
            )
        bridge_accepted = bridge["contract"]["accepted_revisions"]
        if current not in bridge_accepted or target not in bridge_accepted:
            raise ValueError("bridge does not span the current and target schemas")
        protection_mode = "staged_bridge"

    return {
        "schema_version": 1,
        "current_schema": current,
        "target_schema": target,
        "migration_required": current != target,
        "protection_mode": protection_mode,
        "previous_role": previous["role"],
        "previous_contract_digest": previous["contract_digest"],
        "target_contract_digest": contract_digest(target_contract),
        "bridge_contract_digest": bridge["contract_digest"] if bridge else None,
        "automatic_rollback_allowed": False,
        "post_migration_failure_action": (
            "retain_bridge_and_fix_forward"
            if protection_mode in {"existing_bridge", "staged_bridge"}
            else "retain_compatible_previous_and_fix_forward"
        ),
    }


def verify_target_runtime(
    runtime_payload: object,
    target_contract_payload: object,
    *,
    expected_schema: str,
) -> dict[str, object]:
    runtime = runtime_contract(runtime_payload, expected_role="final")
    expected = normalize_contract(target_contract_payload)
    if runtime["current_revision"] != expected_schema:
        raise ValueError("target runtime did not observe the committed schema")
    if runtime["contract"] != expected:
        raise ValueError(
            "target runtime contract differs from the reviewed image contract"
        )
    return runtime


def _write_json_atomic(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    digest = subparsers.add_parser("contract-digest")
    digest.add_argument("--contract", required=True, type=Path)

    plan = subparsers.add_parser("plan")
    plan.add_argument("--previous-runtime", required=True, type=Path)
    plan.add_argument("--target-contract", required=True, type=Path)
    plan.add_argument("--migration-contract", required=True, type=Path)
    plan.add_argument("--bridge-runtime", type=Path)
    plan.add_argument("--bridge-contract", type=Path)
    plan.add_argument("--output", required=True, type=Path)

    verify = subparsers.add_parser("verify-target")
    verify.add_argument("--runtime", required=True, type=Path)
    verify.add_argument("--target-contract", required=True, type=Path)
    verify.add_argument("--expected-schema", required=True)

    args = parser.parse_args()
    if args.command == "contract-digest":
        print(contract_digest(_json(args.contract)))
    elif args.command == "plan":
        result = plan_release(
            previous_runtime=_json(args.previous_runtime),
            target_contract_payload=_json(args.target_contract),
            migration_contract=_json(args.migration_contract),
            bridge_runtime=_json(args.bridge_runtime) if args.bridge_runtime else None,
            bridge_contract_payload=(
                _json(args.bridge_contract) if args.bridge_contract else None
            ),
        )
        _write_json_atomic(args.output, result)
        print(json.dumps(result, sort_keys=True))
    else:
        print(
            json.dumps(
                verify_target_runtime(
                    _json(args.runtime),
                    _json(args.target_contract),
                    expected_schema=args.expected_schema,
                ),
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
