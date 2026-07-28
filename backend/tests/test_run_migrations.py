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


def test_migration_preflight_resolves_connection_selects_one_and_checks_schema(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/archmorph")
    engine, connection = _engine_and_connection()
    connection.execute.side_effect = [
        MagicMock(scalar_one=MagicMock(return_value=1)),
        MagicMock(scalars=MagicMock(return_value=("013",))),
    ]

    with patch.object(run_migrations, "create_engine", return_value=engine):
        evidence = run_migrations.preflight(expected_current="013")

    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert statements == ["SELECT 1", "SELECT version_num FROM alembic_version ORDER BY version_num"]
    assert evidence["status"] == "preflight_succeeded"
    assert evidence["current_revision"] == "013"
    assert evidence["accepted_revisions"] == ["013"]
    engine.dispose.assert_called_once_with()


def test_migration_preflight_fails_closed_on_data_plane_or_schema_mismatch(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/archmorph")
    engine, connection = _engine_and_connection()
    connection.execute.side_effect = [
        MagicMock(scalar_one=MagicMock(return_value=1)),
        MagicMock(scalars=MagicMock(return_value=("014",))),
    ]

    with (
        patch.object(run_migrations, "create_engine", return_value=engine),
        pytest.raises(RuntimeError, match="SELECT 1 or exact schema contract"),
    ):
        run_migrations.preflight(expected_current="013")


def test_migration_preflight_discovers_one_of_reviewed_transition_revisions(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/archmorph")
    engine, connection = _engine_and_connection()
    connection.execute.side_effect = [
        MagicMock(scalar_one=MagicMock(return_value=1)),
        MagicMock(scalars=MagicMock(return_value=("014",))),
    ]

    with patch.object(run_migrations, "create_engine", return_value=engine):
        evidence = run_migrations.preflight(accepted_current=("013", "014"))

    assert evidence["current_revision"] == "014"
    assert evidence["accepted_revisions"] == ["013", "014"]


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
