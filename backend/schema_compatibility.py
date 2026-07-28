"""Application/database schema compatibility contract for safe activation."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


_CONTRACT_PATH = Path(__file__).with_name("schema-contract.json")


@dataclass(frozen=True)
class SchemaContract:
    """Schema revisions that one application image can safely serve."""

    migration_target_revision: str
    minimum_revision: str
    maximum_revision: str
    accepted_revisions: tuple[str, ...]
    alias_read_through_until: str


def _normalized_revision(value: object) -> str:
    revision = str(value or "").strip()
    if not revision or any(character in revision for character in (",", " ", "\t", "\n")):
        raise ValueError("Schema revisions must be non-empty single Alembic revisions")
    return revision


def _load_contract(path: Path = _CONTRACT_PATH) -> SchemaContract:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("contract_version") != 1:
        raise ValueError("Unsupported schema compatibility contract version")
    accepted = tuple(_normalized_revision(item) for item in payload.get("accepted_revisions", ()))
    if not accepted or len(set(accepted)) != len(accepted):
        raise ValueError("Schema compatibility contract requires unique accepted revisions")
    minimum = _normalized_revision(payload.get("minimum_revision"))
    maximum = _normalized_revision(payload.get("maximum_revision"))
    migration_target = _normalized_revision(payload.get("migration_target_revision"))
    alias_until = _normalized_revision(payload.get("alias_read_through_until"))
    for required in (minimum, maximum, migration_target, alias_until):
        if required not in accepted:
            raise ValueError("Schema contract bounds and migration target must be accepted revisions")
    return SchemaContract(
        migration_target_revision=migration_target,
        minimum_revision=minimum,
        maximum_revision=maximum,
        accepted_revisions=accepted,
        alias_read_through_until=alias_until,
    )


SCHEMA_CONTRACT = _load_contract()


def supported_schema_metadata() -> dict[str, object]:
    """Return non-secret application metadata used by rollout preflights."""
    return {
        "minimum_revision": SCHEMA_CONTRACT.minimum_revision,
        "maximum_revision": SCHEMA_CONTRACT.maximum_revision,
        "accepted_revisions": list(SCHEMA_CONTRACT.accepted_revisions),
        "migration_target_revision": SCHEMA_CONTRACT.migration_target_revision,
        "alias_read_through_until": SCHEMA_CONTRACT.alias_read_through_until,
    }


def schema_is_supported(
    current_revisions: str | Iterable[str] | None,
    *,
    accepted_revisions: Iterable[str] | None = None,
) -> bool:
    """Return whether every current Alembic head is declared compatible."""
    if current_revisions is None:
        return False
    if isinstance(current_revisions, str):
        revisions = tuple(item.strip() for item in current_revisions.split(",") if item.strip())
    else:
        revisions = tuple(_normalized_revision(item) for item in current_revisions)
    accepted = frozenset(accepted_revisions or SCHEMA_CONTRACT.accepted_revisions)
    return bool(revisions) and len(revisions) == len(set(revisions)) and all(
        revision in accepted for revision in revisions
    )


def alias_read_through_enabled() -> bool:
    """Keep legacy identity aliases readable through the declared contract window."""
    override = os.getenv("ARCHMORPH_ALIAS_READ_THROUGH", "true").strip().lower()
    return override in {"1", "true", "yes"}
