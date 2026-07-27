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

# SQLite-specific: enable WAL mode for concurrent reads + write-ahead logging
_IS_SQLITE = DATABASE_URL.startswith("sqlite")
_IS_POSTGRES = DATABASE_URL.startswith(("postgresql://", "postgresql+psycopg://", "postgresql+asyncpg://"))
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
ASYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://").replace("sqlite:///", "sqlite+aiosqlite:///")
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
            "Production database schema verified at Alembic head %s",
            readiness["expected_revision"],
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

                required_tables = {
                    "analysis_mutation_receipts",
                    "workspaces",
                    "analyses",
                    "analysis_versions",
                    "diagram_lifecycle",
                    "project_members",
                    "purge_operations",
                    "restore_grants",
                    "tenant_rehome_audit",
                }
                present_tables = set(inspector.get_table_names())
                missing_schema_objects.extend(
                    f"table:{table_name}"
                    for table_name in sorted(required_tables - present_tables)
                )
                if "workspaces" in present_tables:
                    workspace_columns = {
                        column["name"] for column in inspector.get_columns("workspaces")
                    }
                    if "is_default" not in workspace_columns:
                        missing_schema_objects.append("column:workspaces.is_default")
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
        "required_schema_present": required_schema_present,
        "missing_schema_objects": missing_schema_objects,
        "ready_for_production": (
            _IS_POSTGRES
            and connection_ok
            and (
                not _PRODUCTION_LIKE
                or (schema_at_head and required_schema_present)
            )
        ),
    }
