"""Run Alembic under a PostgreSQL advisory lock for controlled rollouts."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from migration_runtime_contract import (
    RuntimeEnvelopeError,
    parse_runtime_envelope,
    validate_revision,
)
from sqlalchemy import create_engine, inspect, text


logger = logging.getLogger(__name__)
MIGRATION_LOCK_ID = 7_823_719_237_014


def _validate_expected_head(expected_head: str) -> None:
    try:
        validate_revision(expected_head, field="expected_head")
    except RuntimeEnvelopeError as error:
        raise RuntimeError(
            "An exact single EXPECTED_ALEMBIC_HEAD is required"
        ) from error


def _migration_config(database_url: str) -> Config:
    backend_dir = Path(__file__).resolve().parent
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _validate_reviewed_target(
    config: Config,
    *,
    expected_head: str,
    current_revisions: tuple[str, ...],
    bootstrap: bool,
) -> None:
    """Prove the reviewed target exists and every current branch can reach it."""
    script = ScriptDirectory.from_config(config)
    try:
        target = script.get_revision(expected_head)
    except Exception as error:
        raise RuntimeError("Expected Alembic target does not exist") from error
    if target is None or target.revision != expected_head:
        raise RuntimeError("Expected Alembic target must be a full exact revision")
    if not current_revisions and not bootstrap:
        raise RuntimeError("Database has no Alembic revision; explicit bootstrap is required")
    for current in current_revisions:
        try:
            revisions = tuple(
                revision.revision
                for revision in script.iterate_revisions(
                    expected_head,
                    current,
                    inclusive=True,
                )
            )
        except Exception as error:
            raise RuntimeError(
                "Current Alembic revision cannot reach the reviewed target"
            ) from error
        if current not in revisions or expected_head not in revisions:
            raise RuntimeError("Current Alembic revision cannot reach the reviewed target")


def _read_current_revisions(connection, *, bootstrap: bool) -> tuple[str, ...]:
    """Distinguish an absent version table from SQL/credential failures."""
    inspector = inspect(connection)
    if inspector.has_table("alembic_version"):
        if bootstrap:
            raise RuntimeError(
                "Bootstrap requires an absent alembic_version table; disable bootstrap for upgrades"
            )
        revisions = tuple(
            connection.execute(
                text("SELECT version_num FROM alembic_version ORDER BY version_num")
            ).scalars()
        )
        if not revisions:
            raise RuntimeError("Database alembic_version table is empty; refusing migration")
        return revisions
    default_schema_tables = set(inspector.get_table_names())
    catalog_objects = {
        f"{object_kind}:{object_name}"
        for object_kind, object_name in connection.execute(
            text(
                "SELECT 'schema', n.nspname "
                "FROM pg_catalog.pg_namespace AS n "
                "WHERE n.nspname <> 'public' "
                "AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND n.nspname NOT LIKE 'pg_toast%' "
                "AND n.nspname NOT LIKE 'pg_temp_%' "
                "UNION ALL "
                "SELECT 'relation', n.nspname || '.' || c.relname "
                "FROM pg_catalog.pg_class AS c "
                "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
                "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND n.nspname NOT LIKE 'pg_toast%' "
                "AND n.nspname NOT LIKE 'pg_temp_%' "
                "UNION ALL "
                "SELECT 'routine', n.nspname || '.' || p.proname "
                "FROM pg_catalog.pg_proc AS p "
                "JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace "
                "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND n.nspname NOT LIKE 'pg_toast%' "
                "AND n.nspname NOT LIKE 'pg_temp_%' "
                "UNION ALL "
                "SELECT 'type', n.nspname || '.' || t.typname "
                "FROM pg_catalog.pg_type AS t "
                "JOIN pg_catalog.pg_namespace AS n ON n.oid = t.typnamespace "
                "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND n.nspname NOT LIKE 'pg_toast%' "
                "AND n.nspname NOT LIKE 'pg_temp_%' "
                "UNION ALL "
                "SELECT 'collation', n.nspname || '.' || c.collname "
                "FROM pg_catalog.pg_collation AS c "
                "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.collnamespace "
                "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND n.nspname NOT LIKE 'pg_toast%' "
                "AND n.nspname NOT LIKE 'pg_temp_%' "
                "UNION ALL "
                "SELECT 'conversion', n.nspname || '.' || c.conname "
                "FROM pg_catalog.pg_conversion AS c "
                "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.connamespace "
                "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND n.nspname NOT LIKE 'pg_toast%' "
                "AND n.nspname NOT LIKE 'pg_temp_%' "
                "UNION ALL "
                "SELECT 'text_search_config', n.nspname || '.' || c.cfgname "
                "FROM pg_catalog.pg_ts_config AS c "
                "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.cfgnamespace "
                "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND n.nspname NOT LIKE 'pg_toast%' "
                "AND n.nspname NOT LIKE 'pg_temp_%' "
                "UNION ALL "
                "SELECT 'text_search_dict', n.nspname || '.' || d.dictname "
                "FROM pg_catalog.pg_ts_dict AS d "
                "JOIN pg_catalog.pg_namespace AS n ON n.oid = d.dictnamespace "
                "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND n.nspname NOT LIKE 'pg_toast%' "
                "AND n.nspname NOT LIKE 'pg_temp_%' "
                "UNION ALL "
                "SELECT 'extension', e.extname "
                "FROM pg_catalog.pg_extension AS e "
                "WHERE e.extname <> 'plpgsql' "
                "UNION ALL "
                "SELECT 'foreign_data_wrapper', f.fdwname "
                "FROM pg_catalog.pg_foreign_data_wrapper AS f "
                "UNION ALL "
                "SELECT 'foreign_server', s.srvname "
                "FROM pg_catalog.pg_foreign_server AS s "
                "UNION ALL "
                "SELECT 'event_trigger', e.evtname "
                "FROM pg_catalog.pg_event_trigger AS e "
                "UNION ALL "
                "SELECT 'publication', p.pubname "
                "FROM pg_catalog.pg_publication AS p"
            )
        ).all()
    }
    user_objects = sorted(default_schema_tables | catalog_objects)
    if user_objects:
        raise RuntimeError(
            "Database has application objects but no alembic_version; refusing bootstrap"
        )
    if not bootstrap:
        raise RuntimeError("Database has no alembic_version; explicit bootstrap is required")
    return ()


def preflight(
    *,
    expected_current: str = "",
    accepted_current: tuple[str, ...] = (),
    bootstrap: bool = False,
) -> dict[str, object]:
    """Prove the Job identity can resolve the secret and query the live schema."""
    accepted = accepted_current or ((expected_current,) if expected_current else ())
    if not accepted:
        raise RuntimeError("At least one exact accepted current revision is required")
    for revision in accepted:
        _validate_expected_head(revision)
    if len(set(accepted)) != len(accepted):
        raise RuntimeError("Accepted current revisions must be unique")
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("Controlled migrations require a PostgreSQL DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            probe = connection.execute(text("SELECT 1")).scalar_one()
            revisions = _read_current_revisions(
                connection,
                bootstrap=bootstrap,
            )
    finally:
        engine.dispose()

    current_revision = ",".join(revisions)
    if probe != 1 or (current_revision not in accepted and not (bootstrap and not revisions)):
        raise RuntimeError(
            "Database preflight failed the SELECT 1 or exact schema contract"
        )
    evidence = {
        "status": "preflight_succeeded",
        "current_revision": current_revision or "empty",
        "accepted_revisions": list(accepted),
        "image_reference": os.environ.get("MIGRATION_IMAGE_REFERENCE", "unknown"),
    }
    logger.info(
        "Database secret, SELECT 1, and schema contract verified at revision %s",
        current_revision or "empty",
    )
    print("ARCHMORPH_MIGRATION_PREFLIGHT_EVIDENCE=" + json.dumps(evidence, sort_keys=True))
    return evidence


def run(*, expected_head: str, bootstrap: bool = False) -> dict[str, str]:
    _validate_expected_head(expected_head)
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("Controlled migrations require a PostgreSQL DATABASE_URL")

    config = _migration_config(database_url)
    engine = create_engine(database_url, pool_pre_ping=True)
    already_at_head = False
    try:
        with engine.connect() as connection:
            connection.execute(
                text("SELECT pg_advisory_lock(:lock_id)"),
                {"lock_id": MIGRATION_LOCK_ID},
            )
            try:
                connection.commit()
                with connection.begin():
                    config.attributes["connection"] = connection
                    current_revisions = _read_current_revisions(
                        connection,
                        bootstrap=bootstrap,
                    )
                    _validate_reviewed_target(
                        config,
                        expected_head=expected_head,
                        current_revisions=current_revisions,
                        bootstrap=bootstrap,
                    )
                    if current_revisions == (expected_head,):
                        already_at_head = True
                        logger.info(
                            "Database already at exact Alembic head %s; DDL skipped",
                            expected_head,
                        )
                    else:
                        command.upgrade(config, expected_head)
            finally:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": MIGRATION_LOCK_ID},
                )
                connection.commit()
    finally:
        engine.dispose()

    from database import database_readiness

    readiness = database_readiness()
    if not (
        readiness["postgres_configured"]
        and readiness["connection_ok"]
        and readiness["required_schema_present"]
        and readiness["current_revision"] == expected_head
    ):
        raise RuntimeError(
            "Migration completed without satisfying the exact expected schema contract"
        )
    evidence = {
        "status": (
            "already_at_head"
            if already_at_head
            else "bootstrapped"
            if bootstrap
            else "migrated"
        ),
        "current_revision": expected_head,
        "expected_revision": expected_head,
        "image_reference": os.environ.get("MIGRATION_IMAGE_REFERENCE", "unknown"),
    }
    logger.info("Database migrated and verified at exact Alembic head %s", expected_head)
    print("ARCHMORPH_MIGRATION_EVIDENCE=" + json.dumps(evidence, sort_keys=True))
    return evidence


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "runtime_envelope",
        nargs="?",
        help="Canonical JSON runtime envelope; must be the sole container argument",
    )
    parser.add_argument(
        "--expect-head",
        default=None,
        help="Exact Alembic head declared by the reviewed application image",
    )
    parser.add_argument(
        "--accept-current",
        action="append",
        default=None,
        help="Allowed exact current revision; repeat only for reviewed transition states",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Resolve DATABASE_URL and prove SELECT 1/current schema without DDL",
    )
    parser.add_argument(
        "--expect-current",
        default=None,
        help="Exact current Alembic revision required by --preflight-only",
    )
    parser.add_argument(
        "--bootstrap-empty-database",
        action="store_true",
        help="Opt in to migrating a verified empty database with no version table",
    )
    parser.add_argument(
        "--execution-marker",
        default=None,
        help="Non-secret rollout marker used to recover an interrupted Job start",
    )
    return parser.parse_args(argv)


def _legacy_input_present(arguments: argparse.Namespace) -> bool:
    return any(
        (
            arguments.expect_head is not None,
            arguments.accept_current is not None,
            arguments.preflight_only,
            arguments.expect_current is not None,
            arguments.bootstrap_empty_database,
            arguments.execution_marker is not None,
        )
    )


def _validate_envelope_environment(envelope: dict[str, object]) -> None:
    expected_head = os.environ.get("EXPECTED_ALEMBIC_HEAD", "")
    if expected_head:
        _validate_expected_head(expected_head)
        if envelope["mode"] == "migrate":
            if envelope["expected_head"] != expected_head:
                raise RuntimeError(
                    "Migration runtime envelope conflicts with expected-head evidence"
                )
        elif expected_head not in envelope["accept_current"]:
            raise RuntimeError(
                "Migration runtime envelope excludes expected-head evidence"
            )

    image_reference = os.environ.get("MIGRATION_IMAGE_REFERENCE", "")
    if image_reference:
        repository, separator, digest = image_reference.rpartition("@")
        if not repository or separator != "@" or digest != envelope["image_digest"]:
            raise RuntimeError(
                "Migration runtime envelope conflicts with immutable image evidence"
            )


def _runtime_request(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.runtime_envelope is not None:
        if _legacy_input_present(arguments):
            raise RuntimeError(
                "Migration runtime envelope cannot be combined with legacy CLI flags"
            )
        envelope = parse_runtime_envelope(arguments.runtime_envelope)
        _validate_envelope_environment(envelope)
        return envelope

    execution_marker = arguments.execution_marker or ""
    if execution_marker and not re.fullmatch(
        r"[a-z0-9][a-z0-9-]{0,127}", execution_marker
    ):
        raise RuntimeError("Migration execution marker is invalid")
    if arguments.preflight_only:
        if arguments.expect_head is not None:
            raise RuntimeError("Preflight legacy flags must not include --expect-head")
        return {
            "mode": "preflight",
            "accept_current": list(arguments.accept_current or ()),
            "expected_current": arguments.expect_current
            if arguments.expect_current is not None
            else os.environ.get("EXPECTED_CURRENT_ALEMBIC_REVISION", ""),
            "bootstrap": arguments.bootstrap_empty_database,
        }
    if arguments.accept_current is not None or arguments.expect_current is not None:
        raise RuntimeError(
            "Migration legacy flags must not include preflight revision options"
        )
    return {
        "mode": "migrate",
        "expected_head": arguments.expect_head
        if arguments.expect_head is not None
        else os.environ.get("EXPECTED_ALEMBIC_HEAD", ""),
        "bootstrap": arguments.bootstrap_empty_database,
    }


def _execute(arguments: argparse.Namespace) -> dict[str, object]:
    request = _runtime_request(arguments)
    if request["mode"] == "preflight":
        return preflight(
            expected_current=str(request.get("expected_current") or ""),
            accepted_current=tuple(request["accept_current"]),
            bootstrap=bool(request["bootstrap"]),
        )
    return run(
        expected_head=str(request["expected_head"]),
        bootstrap=bool(request["bootstrap"]),
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        _execute(_parse_args())
    except Exception:
        logger.exception("Controlled database migration failed")
        sys.exit(1)
