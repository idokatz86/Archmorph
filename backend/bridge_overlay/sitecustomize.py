"""Bounded 013/014 readiness adapter for the immutable no-DDL bridge source."""

from __future__ import annotations

import os


if os.getenv("ARCHMORPH_RELEASE_ROLE", "").strip().lower() == "bridge":
    os.environ.setdefault("ENFORCE_POSTGRES", "true")
    os.environ.setdefault("SCHEDULER_DISABLED", "1")
    import database
    from sqlalchemy import inspect, text

    _BRIDGE_REVISIONS = frozenset({"013", "014"})
    _CORE_TABLES = frozenset(
        {
            "workspaces",
            "source_assets",
            "analyses",
            "analysis_versions",
            "artifacts",
            "decisions",
        }
    )

    def _bridge_database_readiness() -> dict[str, object]:
        current_revision = None
        missing_schema_objects: list[str] = []
        connection_ok = False
        connection_error = None
        try:
            with database.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                revisions = tuple(
                    connection.execute(
                        text("SELECT version_num FROM alembic_version ORDER BY version_num")
                    ).scalars()
                )
                current_revision = ",".join(revisions) or None
                present_tables = set(inspect(connection).get_table_names())
                missing_schema_objects = [
                    f"table:{name}" for name in sorted(_CORE_TABLES - present_tables)
                ]
            connection_ok = True
        except Exception as exc:  # noqa: BLE001 - sanitized readiness classification
            connection_error = type(exc).__name__
        compatible = bool(
            connection_ok
            and current_revision in _BRIDGE_REVISIONS
            and not missing_schema_objects
        )
        return {
            "backend": "postgresql",
            "postgres_configured": True,
            "sqlite_configured": False,
            "production_like": True,
            "enforce_postgres": True,
            "connection_ok": connection_ok,
            "connection_error": connection_error,
            "current_revision": current_revision,
            "expected_revision": "014",
            "schema_at_head": current_revision == "014",
            "required_schema_present": not missing_schema_objects,
            "missing_schema_objects": missing_schema_objects,
            "ready_for_production": compatible,
        }

    database.database_readiness = _bridge_database_readiness