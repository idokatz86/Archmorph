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
        url = base_url.set(database=name).render_as_string(hide_password=False)
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
                "REDIS_URL": os.getenv(
                    "ARCHMORPH_TEST_REDIS_URL",
                    "redis://127.0.0.1:6379/15",
                ),
                "JWT_SECRET": "bridge-test-placeholder-secret-32-bytes",
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



@pytest.mark.parametrize("revision", ["013", "014"])
def test_bridge_core_reads_are_real_postgres_read_only_and_tenant_scoped(revision):
    base_url = make_url(BASE_URL)
    name = f"{base_url.database}_bridge_reads_{revision}_{uuid.uuid4().hex[:8]}"
    admin_engine = create_engine(
        base_url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
    )
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        url = base_url.set(database=name).render_as_string(hide_password=False)
        engine = create_engine(url)
        config = Config(str(BACKEND / "alembic.ini"))
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, revision)
        config.attributes.pop("connection", None)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO workspaces "
                    "(id, owner_user_id, tenant_id, name, source_cloud, target_cloud, "
                    "status, is_public) VALUES "
                    "('workspace-a', 'owner-a', 'tenant-a', 'Workspace A', 'aws', "
                    "'azure', 'active', false), "
                    "('workspace-b', 'owner-b', 'tenant-b', 'Workspace B', 'aws', "
                    "'azure', 'active', false)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO analyses "
                    "(id, workspace_id, owner_user_id, tenant_id, title, source_cloud, "
                    "target_cloud, status, services_detected, current_version) VALUES "
                    "('analysis-a', 'workspace-a', 'owner-a', 'tenant-a', 'Analysis A', "
                    "'aws', 'azure', 'completed', 1, 1), "
                    "('analysis-b', 'workspace-b', 'owner-b', 'tenant-b', 'Analysis B', "
                    "'aws', 'azure', 'completed', 1, 0)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO analysis_versions "
                    "(id, analysis_id, version_number, snapshot, content_hash) VALUES "
                    "('version-a', 'analysis-a', 1, "
                    "'{\"title\":\"safe\",\"_owner_user_id\":\"hidden\"}', 'abc123')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO artifacts "
                    "(id, analysis_id, owner_user_id, tenant_id, artifact_type, format, "
                    "content_hash, size_bytes) VALUES "
                    "('artifact-a', 'analysis-a', 'owner-a', 'tenant-a', "
                    "'terraform', 'hcl', 'def456', 10)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO decisions "
                    "(id, analysis_id, owner_user_id, tenant_id, decision_type, title, status) "
                    "VALUES ('decision-a', 'analysis-a', 'owner-a', 'tenant-a', "
                    "'decision', 'Keep private', 'open')"
                )
            )
        with engine.connect() as connection:
            before = {
                table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                for table in (
                    "workspaces",
                    "analyses",
                    "analysis_versions",
                    "artifacts",
                    "decisions",
                )
            }
        engine.dispose()
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; sys.path.insert(0, 'bridge_overlay'); "
                    "import bridge_readonly as b; "
                    "own=b.execute_safe_read(operation='workspace_list', identifiers={}, "
                    "parameters={}, owner='owner-a', tenant='tenant-a'); "
                    "assert [x['id'] for x in own['workspaces']] == ['workspace-a']; "
                    "versions=b.execute_safe_read(operation='version_get', "
                    "identifiers={'analysis':'analysis-a','version':'1'}, parameters={}, "
                    "owner='owner-a', tenant='tenant-a'); "
                    "assert versions['snapshot'] == {'title':'safe'}; "
                    "artifacts=b.execute_safe_read(operation='artifact_list', "
                    "identifiers={'analysis':'analysis-a'}, parameters={}, "
                    "owner='owner-a', tenant='tenant-a'); "
                    "assert artifacts['artifacts'][0]['id'] == 'artifact-a'; "
                    "decisions=b.execute_safe_read(operation='decision_list', "
                    "identifiers={'analysis':'analysis-a'}, parameters={}, "
                    "owner='owner-a', tenant='tenant-a'); "
                    "assert decisions['decisions'][0]['id'] == 'decision-a'; "
                    "foreign=b.execute_safe_read(operation='workspace_list', identifiers={}, "
                    "parameters={}, owner='owner-a', tenant='tenant-b'); "
                    "assert foreign['workspaces'] == []"
                ),
            ],
            cwd=BACKEND,
            env={
                **os.environ,
                "ARCHMORPH_RELEASE_ROLE": "bridge",
                "DATABASE_URL": url,
                "REDIS_URL": os.getenv(
                    "ARCHMORPH_TEST_REDIS_URL",
                    "redis://127.0.0.1:6379/15",
                ),
                "JWT_SECRET": "bridge-test-placeholder-secret-32-bytes",
                "ENFORCE_POSTGRES": "true",
                "ENVIRONMENT": "production",
            },
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        verification_engine = create_engine(url)
        with verification_engine.connect() as connection:
            after = {
                table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                for table in before
            }
        verification_engine.dispose()
        assert after == before
    finally:
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin_engine.dispose()
