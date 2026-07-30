"""
Archmorph Database Layer — SQLAlchemy engine + session factory (Issue #168).

Provides a pluggable database backend:
  - SQLite for local dev (zero config, file-based)
  - PostgreSQL for production (set DATABASE_URL env var)

Usage::

    from database import get_db, init_db

    # In FastAPI lifespan:
    init_db()

    # In route handlers:
    db = next(get_db())
    db.add(record)
    db.commit()
"""

import logging
import os
from pathlib import Path
from typing import Generator

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker, Session, declarative_base

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./data/archmorph.db",
)

_POSTGRES_URL_PREFIXES = (
    "postgresql://",
    "postgresql+psycopg://",
    "postgresql+psycopg2://",
    "postgresql+asyncpg://",
)


def _is_postgres_url(database_url: str) -> bool:
    return database_url.startswith(_POSTGRES_URL_PREFIXES)


def _async_database_url(database_url: str) -> str:
    if _is_postgres_url(database_url):
        suffix = database_url.split("://", 1)[1]
        return f"postgresql+asyncpg://{suffix}"
    return database_url.replace("sqlite:///", "sqlite+aiosqlite:///")

# SQLite-specific: enable WAL mode for concurrent reads + write-ahead logging
_IS_SQLITE = DATABASE_URL.startswith("sqlite")
_IS_POSTGRES = _is_postgres_url(DATABASE_URL)
_ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
_PRODUCTION_LIKE = _ENVIRONMENT in ("production", "prod", "staging")
_ENFORCE_POSTGRES = os.getenv(
    "ENFORCE_POSTGRES",
    "true" if _PRODUCTION_LIKE else "false",
).lower() in ("1", "true", "yes")

# Issue #287 — Warn loudly / fail if SQLite is used in production.
# SQLite DB files are ephemeral in containerized deployments.
if _IS_SQLITE and _PRODUCTION_LIKE:
    logger.error(
        "🚨 CRITICAL: SQLite is configured in %s environment! "
        "Database file will be LOST on every container restart/deploy. "
        "Set DATABASE_URL to a PostgreSQL connection string immediately. "
        "Example: DATABASE_URL=postgresql://user:pass@host:5432/archmorph (Issue #287)",
        _ENVIRONMENT,
    )
    # In strict mode, refuse to start with SQLite in production
    if _ENFORCE_POSTGRES:
        raise RuntimeError(
            "ENFORCE_POSTGRES is set but DATABASE_URL points to SQLite. "
            "Set DATABASE_URL to a PostgreSQL connection string."
        )

# Connection pool settings (PostgreSQL)
_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "20"))  # Increased from 10 (#376)
_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))
_POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))
_POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "3600"))  # Recycle stale connections (#376)


# ─────────────────────────────────────────────────────────────
# Engine & Session Factory
# ─────────────────────────────────────────────────────────────

Base = declarative_base()

_engine_kwargs = {"echo": os.getenv("DB_ECHO", "").lower() == "true"}

if _IS_SQLITE:
    # SQLite: single-threaded with check_same_thread=False for FastAPI
    _engine_kwargs.update({
        "connect_args": {"check_same_thread": False},
        "pool_pre_ping": True,
    })
else:
    # PostgreSQL: connection pooling
    _engine_kwargs.update({
        "pool_size": _POOL_SIZE,
        "max_overflow": _MAX_OVERFLOW,
        "pool_timeout": _POOL_TIMEOUT,
        "pool_recycle": _POOL_RECYCLE,
        "pool_pre_ping": True,
    })

engine = create_engine(DATABASE_URL, **_engine_kwargs)

# Enable WAL mode for SQLite (better concurrent performance)
if _IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ─────────────────────────────────────────────────────────────
# Async Engine & Session (Issue #370)
# ─────────────────────────────────────────────────────────────
ASYNC_DATABASE_URL = _async_database_url(DATABASE_URL)
async_engine = create_async_engine(ASYNC_DATABASE_URL, **_engine_kwargs)

if _IS_SQLITE:
    @event.listens_for(async_engine.sync_engine, "connect")
    def _set_async_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

AsyncSessionLocal = async_sessionmaker(class_=AsyncSession, autocommit=False, autoflush=False, bind=async_engine)


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a DB session, auto-closes on exit.

    Wrapped with the PostgreSQL circuit breaker (#506) to prevent cascade
    failures when the database is unreachable.
    """
    from circuit_breakers import db_breaker
    import pybreaker
    try:
        db = db_breaker.call(SessionLocal)
    except pybreaker.CircuitBreakerError:
        raise RuntimeError("Database circuit breaker is open — service temporarily unavailable")
    try:
        yield db
    finally:
        db.close()


async def get_async_db():
    """FastAPI dependency — yields an AsyncSession."""
    async with AsyncSessionLocal() as session:
        yield session


def init_db() -> None:
    """Initialize a development/test schema; production is migration-only.

    Calling ``Base.metadata.create_all`` against a production-like database can
    partially materialize the next ORM schema before Alembic runs.  Production
    startup therefore verifies the exact migration contract without issuing DDL.
    """
    if _PRODUCTION_LIKE:
        if not _IS_POSTGRES:
            raise RuntimeError("Production database must use PostgreSQL")
        readiness = database_readiness()
        if not readiness["ready_for_production"]:
            raise RuntimeError("Production database is not at the expected Alembic head")
        logger.info(
            "Production database schema verified at Alembic revision %s",
            readiness.get("current_revision", readiness.get("expected_revision")),
        )
        return

    # Import all models so Base.metadata knows about them
    import models  # noqa: F401

    # Ensure data directory exists for SQLite
    if _IS_SQLITE:
        db_path = DATABASE_URL.replace("sqlite:///", "")
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
    else:
        # Before creating tables in PostgreSQL, ensure vector extension exists
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.commit()

    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized: %s (%d tables)", DATABASE_URL, len(Base.metadata.tables))


def drop_all() -> None:
    """Drop all tables — ONLY for testing."""
    Base.metadata.drop_all(bind=engine)


def get_engine():
    """Return the SQLAlchemy engine (for Alembic / advanced usage)."""
    return engine


def database_backend() -> str:
    """Return the configured database backend family."""
    if _IS_SQLITE:
        return "sqlite"
    if _IS_POSTGRES:
        return "postgresql"
    return "other"


def database_readiness() -> dict[str, object]:
    """Return connectivity and exact migration/schema readiness metadata."""
    connection_ok = False
    connection_error: str | None = None
    current_revision: str | None = None
    expected_revision: str | None = None
    schema_at_head = False
    schema_compatible = False
    required_schema_present = False
    missing_schema_objects: list[str] = []

    try:
        alembic_config = Config(str(Path(__file__).with_name("alembic.ini")))
        script = ScriptDirectory.from_config(alembic_config)
        heads = tuple(sorted(script.get_heads()))
        expected_revision = ",".join(heads) or None
    except Exception as exc:
        heads = ()
        connection_error = type(exc).__name__

    if _IS_POSTGRES:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                inspector = inspect(connection)
                if inspector.has_table("alembic_version"):
                    revisions = tuple(
                        connection.execute(
                            text("SELECT version_num FROM alembic_version")
                        ).scalars()
                    )
                    current_revision = ",".join(sorted(revisions)) or None

                bridge_on_013 = (
                    os.getenv("ARCHMORPH_RELEASE_ROLE", "final").strip().lower()
                    == "bridge"
                    and current_revision == "013"
                )
                required_tables = {
                    "workspaces",
                    "source_assets",
                    "analyses",
                    "analysis_versions",
                    "artifacts",
                    "decisions",
                    "deployment_state",
                }
                if not bridge_on_013:
                    required_tables.update(
                        {
                            "api_key_credentials",
                            "cost_alerts",
                            "cost_budgets",
                            "analysis_mutation_receipts",
                            "analysis_restore_receipts",
                            "diagram_lifecycle",
                            "migration_replay_events",
                            "migration_replays",
                            "project_members",
                            "purge_operations",
                            "restore_grants",
                            "tenant_rehome_audit",
                            "tenant_rehome_aliases",
                        }
                    )
                present_tables = set(inspector.get_table_names())
                missing_schema_objects.extend(
                    f"table:{table_name}"
                    for table_name in sorted(required_tables - present_tables)
                )
                if "workspaces" in present_tables and not bridge_on_013:
                    workspace_columns = {
                        column["name"] for column in inspector.get_columns("workspaces")
                    }
                    if "is_default" not in workspace_columns:
                        missing_schema_objects.append("column:workspaces.is_default")
                if "purge_operations" in present_tables and not bridge_on_013:
                    purge_columns = {
                        column["name"] for column in inspector.get_columns("purge_operations")
                    }
                    if "manifest" not in purge_columns:
                        missing_schema_objects.append("column:purge_operations.manifest")
                    if "workspace_id" not in purge_columns:
                        missing_schema_objects.append(
                            "column:purge_operations.workspace_id"
                        )
                    purge_indexes = {
                        index.get("name"): tuple(index.get("column_names") or ())
                        for index in inspector.get_indexes("purge_operations")
                    }
                    if purge_indexes.get(
                        "ix_purge_operations_scope_lookup"
                    ) != ("scope_type", "scope_id"):
                        missing_schema_objects.append(
                            "index:purge_operations.scope_lookup"
                        )
                    if purge_indexes.get(
                        "ix_purge_operations_status_id"
                    ) != ("status", "id"):
                        missing_schema_objects.append(
                            "index:purge_operations.status_cursor"
                        )
                if "restore_grants" in present_tables and not bridge_on_013:
                    grant_columns = {
                        column["name"]
                        for column in inspector.get_columns("restore_grants")
                    }
                    if "cleanup_at" not in grant_columns:
                        missing_schema_objects.append(
                            "column:restore_grants.cleanup_at"
                        )
                    grant_indexes = {
                        index.get("name")
                        for index in inspector.get_indexes("restore_grants")
                    }
                    if "ix_restore_grants_cleanup" not in grant_indexes:
                        missing_schema_objects.append("index:restore_grants.cleanup_at")
                if "decisions" in present_tables and not bridge_on_013:
                    decision_checks = {
                        constraint.get("name")
                        for constraint in inspector.get_check_constraints("decisions")
                    }
                    if "ck_decisions_status" not in decision_checks:
                        missing_schema_objects.append("constraint:decisions.status")
                if "cost_records" in present_tables and not bridge_on_013:
                    cost_columns = {
                        column["name"] for column in inspector.get_columns("cost_records")
                    }
                    for column_name in ("owner_user_id", "tenant_id", "actor_kind", "key_id"):
                        if column_name not in cost_columns:
                            missing_schema_objects.append(f"column:cost_records.{column_name}")
                if "deployment_state" in present_tables and not bridge_on_013:
                    state_columns = {
                        column["name"]: column
                        for column in inspector.get_columns("deployment_state")
                    }
                    owner_column = state_columns.get("owner_user_id")
                    if owner_column is None:
                        missing_schema_objects.append(
                            "column:deployment_state.owner_user_id"
                        )
                    elif owner_column.get("nullable", True):
                        missing_schema_objects.append(
                            "nullability:deployment_state.owner_user_id"
                        )
                    unique_constraints = {
                        constraint.get("name"): tuple(
                            constraint.get("column_names") or ()
                        )
                        for constraint in inspector.get_unique_constraints(
                            "deployment_state"
                        )
                    }
                    if unique_constraints.get(
                        "uq_deployment_state_project_environment"
                    ) != ("project_id", "environment"):
                        missing_schema_objects.append(
                            "constraint:deployment_state.project_environment_unique"
                        )
                    foreign_keys = {
                        constraint.get("name"): constraint
                        for constraint in inspector.get_foreign_keys("deployment_state")
                    }
                    project_fk = foreign_keys.get("fk_deployment_state_project")
                    if not (
                        project_fk
                        and tuple(project_fk.get("constrained_columns") or ())
                        == ("project_id",)
                        and project_fk.get("referred_table") == "workspaces"
                        and tuple(project_fk.get("referred_columns") or ()) == ("id",)
                        and str(
                            (project_fk.get("options") or {}).get("ondelete", "")
                        ).upper()
                        == "CASCADE"
                    ):
                        missing_schema_objects.append(
                            "constraint:deployment_state.project_fk"
                        )
                    check_constraints = {
                        constraint.get("name")
                        for constraint in inspector.get_check_constraints(
                            "deployment_state"
                        )
                    }
                    if "ck_deployment_state_environment" not in check_constraints:
                        missing_schema_objects.append(
                            "constraint:deployment_state.environment"
                        )
                required_schema_present = not missing_schema_objects
            connection_ok = True
        except Exception as exc:
            connection_error = type(exc).__name__
    elif _IS_SQLITE and not _PRODUCTION_LIKE:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            connection_ok = True
        except Exception as exc:
            connection_error = type(exc).__name__

    schema_at_head = bool(
        connection_ok
        and len(heads) == 1
        and current_revision == expected_revision
    )
    try:
        from schema_compatibility import schema_is_supported

        schema_compatible = bool(connection_ok and schema_is_supported(current_revision))
    except Exception:
        schema_compatible = False
    return {
        "backend": database_backend(),
        "postgres_configured": _IS_POSTGRES,
        "sqlite_configured": _IS_SQLITE,
        "production_like": _PRODUCTION_LIKE,
        "enforce_postgres": _ENFORCE_POSTGRES,
        "connection_ok": connection_ok,
        "connection_error": connection_error,
        "current_revision": current_revision,
        "expected_revision": expected_revision,
        "schema_at_head": schema_at_head,
        "schema_compatible": schema_compatible,
        "required_schema_present": required_schema_present,
        "missing_schema_objects": missing_schema_objects,
        "ready_for_production": (
            _IS_POSTGRES
            and connection_ok
            and (
                not _PRODUCTION_LIKE
                or (schema_compatible and required_schema_present)
            )
        ),
    }
