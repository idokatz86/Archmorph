"""Real PostgreSQL bridge compatibility proof for schemas 013 and 014."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
import uuid

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


BACKEND = Path(__file__).resolve().parents[1]
BASE_URL = os.getenv("ARCHMORPH_TEST_POSTGRES_URL", "")
pytestmark = pytest.mark.skipif(not BASE_URL, reason="ARCHMORPH_TEST_POSTGRES_URL not configured")
@pytest.mark.parametrize("revision", ["013", "014"])
def test_bridge_readiness_accepts_reviewed_schema_without_ddl(revision):
    base_url = make_url(BASE_URL)
    name = f"{base_url.database}_bridge_{revision}_{uuid.uuid4().hex[:8]}"
    admin_engine = create_engine(
        base_url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
    )
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        url = str(base_url.set(database=name))
        engine = create_engine(url)
        config = Config(str(BACKEND / "alembic.ini"))
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, revision)
        config.attributes.pop("connection", None)
        engine.dispose()
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import runpy; "
                    "runpy.run_path('bridge_overlay/sitecustomize.py'); "
                    "import database; result=database.database_readiness(); "
                    "assert result['current_revision'] == '" + revision + "'; "
                    "assert result['ready_for_production'] is True"
                ),
            ],
            cwd=BACKEND,
            env={
                **os.environ,
                "ARCHMORPH_RELEASE_ROLE": "bridge",
                "DATABASE_URL": url,
                "ENFORCE_POSTGRES": "true",
                "ENVIRONMENT": "production",
            },
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
    finally:
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin_engine.dispose()