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
from typing import Generator

from sqlalchemy import create_engine, event
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
_ENFORCE_POSTGRES = os.getenv("ENFORCE_POSTGRES", "").lower() in ("1", "true", "yes")

# Issue #287 — Warn loudly / fail if SQLite is used in production.
# SQLite DB files are ephemeral in containerized deployments.
if _IS_SQLITE and _ENVIRONMENT in ("production", "prod", "staging"):
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
    """Create all tables defined by SQLAlchemy models.

    Safe to call multiple times — uses CREATE IF NOT EXISTS.
    In production, prefer Alembic migrations over this.
    """
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
        from sqlalchemy import text
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
    """Return operator-facing database readiness metadata for release gates."""
    return {
        "backend": database_backend(),
        "postgres_configured": _IS_POSTGRES,
        "sqlite_configured": _IS_SQLITE,
        "production_like": _ENVIRONMENT in ("production", "prod", "staging"),
        "enforce_postgres": _ENFORCE_POSTGRES,
        "ready_for_production": _IS_POSTGRES,
    }
