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
_ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()

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
    if os.getenv("ENFORCE_POSTGRES", "").lower() in ("1", "true", "yes"):
        raise RuntimeError(
            "ENFORCE_POSTGRES is set but DATABASE_URL points to SQLite. "
            "Set DATABASE_URL to a PostgreSQL connection string."
        )

# Connection pool settings (PostgreSQL)
_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
_POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))


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
# Public API
# ─────────────────────────────────────────────────────────────

def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a DB session, auto-closes on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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

    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized: %s (%d tables)", DATABASE_URL, len(Base.metadata.tables))


def drop_all() -> None:
    """Drop all tables — ONLY for testing."""
    Base.metadata.drop_all(bind=engine)


def get_engine():
    """Return the SQLAlchemy engine (for Alembic / advanced usage)."""
    return engine
