"""Run Alembic under a PostgreSQL advisory lock for controlled rollouts."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


logger = logging.getLogger(__name__)
MIGRATION_LOCK_ID = 7_823_719_237_014


def _validate_expected_head(expected_head: str) -> None:
    if not expected_head or any(
        character in expected_head for character in (",", " ", "\t", "\n")
    ):
        raise RuntimeError("An exact single EXPECTED_ALEMBIC_HEAD is required")


def preflight(
    *,
    expected_current: str = "",
    accepted_current: tuple[str, ...] = (),
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
            revisions = tuple(
                connection.execute(
                    text("SELECT version_num FROM alembic_version ORDER BY version_num")
                ).scalars()
            )
    finally:
        engine.dispose()

    current_revision = ",".join(revisions)
    if probe != 1 or current_revision not in accepted:
        raise RuntimeError(
            "Database preflight failed the SELECT 1 or exact schema contract"
        )
    evidence = {
        "status": "preflight_succeeded",
        "current_revision": current_revision,
        "accepted_revisions": list(accepted),
        "image_reference": os.environ.get("MIGRATION_IMAGE_REFERENCE", "unknown"),
    }
    logger.info(
        "Database secret, SELECT 1, and schema contract verified at revision %s",
        current_revision,
    )
    print("ARCHMORPH_MIGRATION_PREFLIGHT_EVIDENCE=" + json.dumps(evidence, sort_keys=True))
    return evidence


def run(*, expected_head: str) -> dict[str, str]:
    _validate_expected_head(expected_head)
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("Controlled migrations require a PostgreSQL DATABASE_URL")

    backend_dir = Path(__file__).resolve().parent
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    engine = create_engine(database_url, pool_pre_ping=True)
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
                    command.upgrade(config, "head")
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
        and readiness["schema_at_head"]
        and readiness["required_schema_present"]
        and readiness["current_revision"] == expected_head
        and readiness["expected_revision"] == expected_head
    ):
        raise RuntimeError(
            "Migration completed without satisfying the exact expected schema contract"
        )
    evidence = {
        "status": "migrated",
        "current_revision": expected_head,
        "expected_revision": expected_head,
        "image_reference": os.environ.get("MIGRATION_IMAGE_REFERENCE", "unknown"),
    }
    logger.info("Database migrated and verified at exact Alembic head %s", expected_head)
    print("ARCHMORPH_MIGRATION_EVIDENCE=" + json.dumps(evidence, sort_keys=True))
    return evidence


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expect-head",
        default=os.environ.get("EXPECTED_ALEMBIC_HEAD", ""),
        help="Exact Alembic head declared by the reviewed application image",
    )
    parser.add_argument(
        "--accept-current",
        action="append",
        default=[],
        help="Allowed exact current revision; repeat only for reviewed transition states",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Resolve DATABASE_URL and prove SELECT 1/current schema without DDL",
    )
    parser.add_argument(
        "--expect-current",
        default=os.environ.get("EXPECTED_CURRENT_ALEMBIC_REVISION", ""),
        help="Exact current Alembic revision required by --preflight-only",
    )
    return parser.parse_args()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        arguments = _parse_args()
        if arguments.preflight_only:
            preflight(
                expected_current=arguments.expect_current,
                accepted_current=tuple(arguments.accept_current),
            )
        else:
            run(expected_head=arguments.expect_head)
    except Exception:
        logger.exception("Controlled database migration failed")
        sys.exit(1)
