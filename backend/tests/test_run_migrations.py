"""Controlled single-writer migration runner contracts."""

from unittest.mock import MagicMock, patch

import pytest

import run_migrations


def _engine_and_connection():
    connection = MagicMock()
    connection_context = MagicMock()
    connection_context.__enter__.return_value = connection
    connection_context.__exit__.return_value = False
    engine = MagicMock()
    engine.connect.return_value = connection_context
    return engine, connection


def test_migration_runner_takes_lock_runs_head_and_verifies(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/archmorph")
    engine, connection = _engine_and_connection()
    readiness = {
        "postgres_configured": True,
        "connection_ok": True,
        "schema_at_head": True,
        "required_schema_present": True,
        "current_revision": "014",
        "expected_revision": "014",
    }

    with (
        patch.object(run_migrations, "create_engine", return_value=engine),
        patch.object(run_migrations.command, "upgrade") as upgrade,
        patch("database.database_readiness", return_value=readiness),
    ):
        evidence = run_migrations.run(expected_head="014")

    assert upgrade.call_args.args[1] == "head"
    assert upgrade.call_args.args[0].attributes["connection"] is connection
    assert connection.execute.call_count == 2
    lock_statement = str(connection.execute.call_args_list[0].args[0])
    unlock_statement = str(connection.execute.call_args_list[1].args[0])
    assert "pg_advisory_lock" in lock_statement
    assert "pg_advisory_unlock" in unlock_statement
    assert connection.commit.call_count == 2
    engine.dispose.assert_called_once_with()
    assert evidence["current_revision"] == "014"


def test_migration_runner_releases_lock_and_propagates_alembic_error(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/archmorph")
    engine, connection = _engine_and_connection()

    with (
        patch.object(run_migrations, "create_engine", return_value=engine),
        patch.object(
            run_migrations.command,
            "upgrade",
            side_effect=RuntimeError("migration failed"),
        ),
        pytest.raises(RuntimeError, match="migration failed"),
    ):
        run_migrations.run(expected_head="014")

    assert connection.execute.call_count == 2
    assert "pg_advisory_unlock" in str(connection.execute.call_args_list[1].args[0])
    assert connection.commit.call_count == 2
    engine.dispose.assert_called_once_with()


def test_migration_runner_rejects_missing_or_split_expected_head(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/archmorph")

    with pytest.raises(RuntimeError, match="exact single EXPECTED_ALEMBIC_HEAD"):
        run_migrations.run(expected_head="")
    with pytest.raises(RuntimeError, match="exact single EXPECTED_ALEMBIC_HEAD"):
        run_migrations.run(expected_head="014,015")


def test_migration_runner_rejects_head_mismatch_after_upgrade(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/archmorph")
    engine, _connection = _engine_and_connection()
    readiness = {
        "postgres_configured": True,
        "connection_ok": True,
        "schema_at_head": True,
        "required_schema_present": True,
        "current_revision": "014",
        "expected_revision": "014",
    }

    with (
        patch.object(run_migrations, "create_engine", return_value=engine),
        patch.object(run_migrations.command, "upgrade"),
        patch("database.database_readiness", return_value=readiness),
        pytest.raises(RuntimeError, match="exact expected schema contract"),
    ):
        run_migrations.run(expected_head="015")
