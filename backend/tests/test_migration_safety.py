import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import URL, make_url


BACKEND_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "migration_n_minus_1.json"
LOCK_BUDGET_SECONDS = 5.0
LOCAL_DATABASE_HOSTS = {"127.0.0.1", "localhost", "::1"}
DATABASE_NAME_PATTERN = re.compile(r"^[a-z0-9_]+$")

STABLE_COLUMNS = {
    "organizations": ("org_id", "name", "slug", "plan", "is_active"),
    "team_members": (
        "org_id",
        "user_id",
        "email",
        "display_name",
        "role",
        "is_active",
    ),
    "agents": ("id", "organization_id", "name", "status", "model_config_data"),
    "executions": (
        "id",
        "agent_id",
        "organization_id",
        "thread_id",
        "status",
        "input_data",
        "output_data",
    ),
    "deployment_state": (
        "project_id",
        "environment",
        "owner_user_id",
        "tenant_id",
        "state_json",
        "previous_state_json",
    ),
}


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _canonical_sha256(snapshot: dict[str, list[dict]]) -> str:
    encoded = json.dumps(
        snapshot,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _snapshot(connection: sa.Connection) -> dict[str, list[dict]]:
    inspector = sa.inspect(connection)
    snapshot = {}
    for table_name, columns in STABLE_COLUMNS.items():
        table = sa.Table(table_name, sa.MetaData(), autoload_with=connection)
        primary_key_columns = inspector.get_pk_constraint(table_name)[
            "constrained_columns"
        ]
        order_by = [table.c[column] for column in primary_key_columns]
        if not order_by:
            order_by = [table.c[column] for column in columns]
        rows = connection.execute(
            sa.select(*(table.c[column] for column in columns)).order_by(*order_by)
        ).mappings()
        snapshot[table_name] = [dict(row) for row in rows]
    return snapshot


def _run_alembic(
    database_url: str,
    *arguments: str,
    timeout_seconds: float = 30.0,
) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    assert result.returncode == 0, (
        f"Alembic {' '.join(arguments)} failed.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def _temporary_database_urls(base_url: str) -> tuple[URL, URL, str]:
    url = make_url(base_url)
    if url.get_backend_name() != "postgresql":
        pytest.fail("MIGRATION_TEST_DATABASE_URL must use PostgreSQL")
    if url.host not in LOCAL_DATABASE_HOSTS:
        pytest.fail(
            "Migration safety tests only create databases on localhost; "
            f"got host {url.host!r}"
        )

    database_name = f"archmorph_migration_safety_{os.getpid()}"
    if not DATABASE_NAME_PATTERN.fullmatch(database_name):
        pytest.fail(f"Unsafe temporary database name: {database_name!r}")
    return url.set(database="postgres"), url.set(database=database_name), database_name


def _create_database(admin_url: URL, database_name: str) -> None:
    engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    finally:
        engine.dispose()


def _drop_database(admin_url: URL, database_name: str) -> None:
    engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(
                sa.text(
                    "SELECT pg_terminate_backend(pid) "
                    "FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
    finally:
        engine.dispose()


def _seed_fixture(connection: sa.Connection, fixture: dict) -> None:
    metadata = sa.MetaData()
    metadata.reflect(bind=connection, only=tuple(fixture["rows"]))
    for table_name, rows in fixture["rows"].items():
        connection.execute(sa.insert(metadata.tables[table_name]), rows)


def _assert_row_counts(snapshot: dict, expected: dict) -> None:
    assert {table: len(rows) for table, rows in snapshot.items()} == expected


def _assert_relationships_and_tenants(connection: sa.Connection) -> None:
    orphan_counts = connection.execute(
        sa.text(
            """
            SELECT
              (SELECT count(*) FROM team_members tm
               LEFT JOIN organizations o ON o.org_id = tm.org_id
               WHERE o.org_id IS NULL) AS team_member_orphans,
              (SELECT count(*) FROM agents a
               LEFT JOIN organizations o ON o.org_id = a.organization_id
               WHERE o.org_id IS NULL) AS agent_orphans,
              (SELECT count(*) FROM executions e
               JOIN agents a ON a.id = e.agent_id
               WHERE e.organization_id <> a.organization_id) AS execution_tenant_mismatches,
              (SELECT count(*) FROM deployment_state ds
               LEFT JOIN team_members tm
                 ON tm.org_id = ds.tenant_id AND tm.user_id = ds.owner_user_id
               WHERE tm.id IS NULL) AS deployment_owner_mismatches
            """
        )
    ).mappings().one()
    assert dict(orphan_counts) == {
        "team_member_orphans": 0,
        "agent_orphans": 0,
        "execution_tenant_mismatches": 0,
        "deployment_owner_mismatches": 0,
    }


def _assert_new_binary_contract(connection: sa.Connection) -> None:
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, owner_user_id, tenant_id, name)
            VALUES
              ('fixture-workspace-01-northwind',
               'fixture-user-northwind-owner',
               'fixture-org-01-northwind',
               'Northwind upgraded workspace'),
              ('fixture-workspace-02-contoso',
               'fixture-user-contoso-owner',
               'fixture-org-02-contoso',
               'Contoso upgraded workspace')
            """
        )
    )
    rows = connection.execute(
        sa.text(
            "SELECT tenant_id, owner_user_id, source_cloud, target_cloud, status, is_public "
            "FROM workspaces ORDER BY tenant_id"
        )
    ).mappings()
    assert [dict(row) for row in rows] == [
        {
            "tenant_id": "fixture-org-01-northwind",
            "owner_user_id": "fixture-user-northwind-owner",
            "source_cloud": "aws",
            "target_cloud": "azure",
            "status": "active",
            "is_public": False,
        },
        {
            "tenant_id": "fixture-org-02-contoso",
            "owner_user_id": "fixture-user-contoso-owner",
            "source_cloud": "aws",
            "target_cloud": "azure",
            "status": "active",
            "is_public": False,
        },
    ]


@pytest.mark.integration
def test_n_minus_1_fixture_survives_migration_within_lock_budget():
    base_url = os.getenv("MIGRATION_TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("MIGRATION_TEST_DATABASE_URL is required for the PostgreSQL migration gate")

    fixture = _load_fixture()
    admin_url, database_url, database_name = _temporary_database_urls(base_url)
    _create_database(admin_url, database_name)
    engine = sa.create_engine(database_url)
    try:
        _run_alembic(database_url.render_as_string(hide_password=False), "upgrade", fixture["revision"])
        with engine.begin() as connection:
            _seed_fixture(connection, fixture)

        with engine.connect() as old_binary_connection:
            old_binary_transaction = old_binary_connection.begin()
            before = _snapshot(old_binary_connection)
            _assert_row_counts(before, fixture["expected_row_counts"])
            _assert_relationships_and_tenants(old_binary_connection)
            before_hash = _canonical_sha256(before)
            assert before_hash == fixture["expected_sha256"]

            started = time.monotonic()
            _run_alembic(
                database_url.render_as_string(hide_password=False),
                "upgrade",
                "head",
                timeout_seconds=LOCK_BUDGET_SECONDS,
            )
            migration_duration = time.monotonic() - started

            assert migration_duration < LOCK_BUDGET_SECONDS
            assert _canonical_sha256(_snapshot(old_binary_connection)) == before_hash
            old_binary_transaction.commit()

        with engine.begin() as connection:
            after = _snapshot(connection)
            _assert_row_counts(after, fixture["expected_row_counts"])
            assert _canonical_sha256(after) == fixture["expected_sha256"]
            _assert_relationships_and_tenants(connection)
            _assert_new_binary_contract(connection)
            waiting_locks = connection.execute(
                sa.text("SELECT count(*) FROM pg_locks WHERE NOT granted")
            ).scalar_one()
            assert waiting_locks == 0

        _run_alembic(database_url.render_as_string(hide_password=False), "downgrade", fixture["revision"])
        with engine.connect() as connection:
            assert _canonical_sha256(_snapshot(connection)) == fixture["expected_sha256"]
            assert not sa.inspect(connection).has_table("workspaces")
    finally:
        engine.dispose()
        _drop_database(admin_url, database_name)
