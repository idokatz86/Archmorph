"""Controlled single-writer migration runner contracts."""

from types import SimpleNamespace
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
    connection.execute.side_effect = [
        MagicMock(),
        MagicMock(scalars=MagicMock(return_value=("013",))),
        MagicMock(),
    ]
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

    assert upgrade.call_args.args[1] == "014"
    assert upgrade.call_args.args[0].attributes["connection"] is connection
    assert connection.execute.call_count == 3
    lock_statement = str(connection.execute.call_args_list[0].args[0])
    revision_statement = str(connection.execute.call_args_list[1].args[0])
    unlock_statement = str(connection.execute.call_args_list[2].args[0])
    assert "pg_advisory_lock" in lock_statement
    assert "SELECT version_num" in revision_statement
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
    connection.execute.side_effect = [
        MagicMock(),
        MagicMock(scalars=MagicMock(return_value=("013",))),
        MagicMock(),
    ]

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

    assert connection.execute.call_count == 3
    assert "pg_advisory_unlock" in str(connection.execute.call_args_list[2].args[0])
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
    _connection.execute.side_effect = [
        MagicMock(),
        MagicMock(scalars=MagicMock(return_value=("014",))),
        MagicMock(),
    ]
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
        pytest.raises(RuntimeError, match="target does not exist"),
    ):
        run_migrations.run(expected_head="015")


def test_migration_runner_noops_and_validates_when_database_is_already_at_head(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/archmorph")
    engine, connection = _engine_and_connection()
    connection.execute.side_effect = [
        MagicMock(),
        MagicMock(scalars=MagicMock(return_value=("014",))),
        MagicMock(),
    ]
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

    upgrade.assert_not_called()
    assert evidence["status"] == "already_at_head"
    assert "pg_advisory_unlock" in str(connection.execute.call_args_list[2].args[0])


def test_migration_runner_uses_reviewed_target_when_newer_unreviewed_head_exists(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/archmorph")
    engine, connection = _engine_and_connection()
    connection.execute.side_effect = [
        MagicMock(),
        MagicMock(scalars=MagicMock(return_value=("013",))),
        MagicMock(),
    ]
    script = MagicMock()
    script.get_heads.return_value = ["015"]
    script.get_revision.return_value = SimpleNamespace(revision="014")
    script.iterate_revisions.return_value = [
        SimpleNamespace(revision="014"),
        SimpleNamespace(revision="013"),
    ]
    readiness = {
        "postgres_configured": True,
        "connection_ok": True,
        "schema_at_head": False,
        "required_schema_present": True,
        "current_revision": "014",
        "expected_revision": "015",
    }
    with (
        patch.object(run_migrations, "create_engine", return_value=engine),
        patch.object(
            run_migrations.ScriptDirectory,
            "from_config",
            return_value=script,
        ),
        patch.object(run_migrations.command, "upgrade") as upgrade,
        patch("database.database_readiness", return_value=readiness),
    ):
        run_migrations.run(expected_head="014")

    upgrade.assert_called_once()
    assert upgrade.call_args.args[1] == "014"
    assert upgrade.call_args.args[1] != "head"


def test_migration_runner_rejects_unreachable_reviewed_target_before_upgrade(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/archmorph")
    engine, connection = _engine_and_connection()
    connection.execute.side_effect = [
        MagicMock(),
        MagicMock(scalars=MagicMock(return_value=("014",))),
        MagicMock(),
    ]
    script = MagicMock()
    script.get_revision.return_value = SimpleNamespace(revision="013")
    script.iterate_revisions.side_effect = RuntimeError("not an ancestor")
    with (
        patch.object(run_migrations, "create_engine", return_value=engine),
        patch.object(
            run_migrations.ScriptDirectory,
            "from_config",
            return_value=script,
        ),
        patch.object(run_migrations.command, "upgrade") as upgrade,
        pytest.raises(RuntimeError, match="cannot reach the reviewed target"),
    ):
        run_migrations.run(expected_head="013")
    upgrade.assert_not_called()


def test_empty_database_bootstrap_is_explicit_and_targets_expected_head(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/archmorph")
    readiness = {
        "postgres_configured": True,
        "connection_ok": True,
        "schema_at_head": True,
        "required_schema_present": True,
        "current_revision": "014",
        "expected_revision": "014",
    }

    blocked_engine, blocked_connection = _engine_and_connection()
    blocked_connection.execute.side_effect = [
        MagicMock(),
        MagicMock(all=MagicMock(return_value=[])),
        MagicMock(),
    ]
    empty_inspector = MagicMock()
    empty_inspector.has_table.return_value = False
    empty_inspector.get_table_names.return_value = []
    with (
        patch.object(run_migrations, "create_engine", return_value=blocked_engine),
        patch.object(run_migrations, "inspect", return_value=empty_inspector),
        patch.object(run_migrations.command, "upgrade") as upgrade,
        pytest.raises(RuntimeError, match="explicit bootstrap is required"),
    ):
        run_migrations.run(expected_head="014")
    upgrade.assert_not_called()

    engine, connection = _engine_and_connection()
    connection.execute.side_effect = [
        MagicMock(),
        MagicMock(all=MagicMock(return_value=[])),
        MagicMock(),
    ]
    with (
        patch.object(run_migrations, "create_engine", return_value=engine),
        patch.object(run_migrations, "inspect", return_value=empty_inspector),
        patch.object(run_migrations.command, "upgrade") as upgrade,
        patch("database.database_readiness", return_value=readiness),
    ):
        evidence = run_migrations.run(expected_head="014", bootstrap=True)
    assert upgrade.call_args.args[1] == "014"
    assert evidence["status"] == "bootstrapped"


def test_bootstrap_rejects_existing_non_alembic_tables(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/archmorph")
    engine, connection = _engine_and_connection()
    connection.execute.side_effect = [
        MagicMock(),
        MagicMock(
            all=MagicMock(return_value=[("customer_schema", "customer_data")])
        ),
        MagicMock(),
    ]
    inspector = MagicMock()
    inspector.has_table.return_value = False
    inspector.get_table_names.return_value = []
    with (
        patch.object(run_migrations, "create_engine", return_value=engine),
        patch.object(run_migrations, "inspect", return_value=inspector),
        patch.object(run_migrations.command, "upgrade") as upgrade,
        pytest.raises(RuntimeError, match="application tables but no alembic_version"),
    ):
        run_migrations.run(expected_head="014", bootstrap=True)
    upgrade.assert_not_called()


def test_bootstrap_flag_rejects_an_already_versioned_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/archmorph")
    engine, connection = _engine_and_connection()
    connection.execute.side_effect = [MagicMock(), MagicMock()]
    inspector = MagicMock()
    inspector.has_table.return_value = True
    with (
        patch.object(run_migrations, "create_engine", return_value=engine),
        patch.object(run_migrations, "inspect", return_value=inspector),
        patch.object(run_migrations.command, "upgrade") as upgrade,
        pytest.raises(RuntimeError, match="disable bootstrap for upgrades"),
    ):
        run_migrations.run(expected_head="014", bootstrap=True)
    upgrade.assert_not_called()


def test_bootstrap_does_not_misclassify_connection_or_sql_failure(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/archmorph")
    engine, _connection = _engine_and_connection()
    engine.connect.side_effect = RuntimeError("credential failure")
    with (
        patch.object(run_migrations, "create_engine", return_value=engine),
        patch.object(run_migrations.command, "upgrade") as upgrade,
        pytest.raises(RuntimeError, match="credential failure"),
    ):
        run_migrations.run(expected_head="014", bootstrap=True)
    upgrade.assert_not_called()


def test_preflight_allows_only_explicit_verified_empty_bootstrap(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/archmorph")
    engine, connection = _engine_and_connection()
    connection.execute.side_effect = [
        MagicMock(scalar_one=MagicMock(return_value=1)),
        MagicMock(all=MagicMock(return_value=[])),
    ]
    inspector = MagicMock()
    inspector.has_table.return_value = False
    inspector.get_table_names.return_value = []
    with (
        patch.object(run_migrations, "create_engine", return_value=engine),
        patch.object(run_migrations, "inspect", return_value=inspector),
    ):
        evidence = run_migrations.preflight(
            accepted_current=("013", "014"),
            bootstrap=True,
        )
    assert evidence["current_revision"] == "empty"
