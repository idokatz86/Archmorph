"""
Archmorph Repositories — data access layer (Issue #168).

Repository pattern provides a clean abstraction over SQLAlchemy
sessions, making it easy to swap between DB-backed and in-memory
storage for testing.
"""

from repositories.base import BaseRepository  # noqa: F401
