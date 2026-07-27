"""Run Alembic under a PostgreSQL advisory lock for controlled rollouts."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


logger = logging.getLogger(__name__)
MIGRATION_LOCK_ID = 7_823_719_237_014


def run() -> None:
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
    ):
        raise RuntimeError(
            "Migration completed without satisfying the expected schema contract"
        )
    logger.info("Database migrated and verified at Alembic head %s", readiness["expected_revision"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        run()
    except Exception:
        logger.exception("Controlled database migration failed")
        sys.exit(1)
