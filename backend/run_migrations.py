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


def run(*, expected_head: str) -> dict[str, str]:
    if not expected_head or any(character in expected_head for character in (",", " ", "\t", "\n")):
        raise RuntimeError("An exact single EXPECTED_ALEMBIC_HEAD is required")
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
    return parser.parse_args()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        run(expected_head=_parse_args().expect_head)
    except Exception:
        logger.exception("Controlled database migration failed")
        sys.exit(1)
