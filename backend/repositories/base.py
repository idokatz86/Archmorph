"""
Base repository with common CRUD operations (Issue #168).

All concrete repositories inherit from this and get standard
create / get / list / delete operations for free.
"""

import logging
from typing import Any, List, Optional, Type, TypeVar

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

T = TypeVar("T")


class BaseRepository:
    """Generic repository with CRUD operations.

    Subclass and set ``model`` to a SQLAlchemy model class::

        class FeedbackRepo(BaseRepository):
            model = FeedbackRecord
    """

    model: Type[Any] = None  # set in subclass

    def __init__(self, db: Session):
        self.db = db

    def create(self, **kwargs) -> Any:
        """Create a new record and flush (assigns ID without committing)."""
        obj = self.model(**kwargs)
        self.db.add(obj)
        self.db.flush()
        return obj

    def get_by_id(self, record_id: int) -> Optional[Any]:
        """Get a record by primary key."""
        return self.db.query(self.model).get(record_id)

    def get_by(self, **filters) -> Optional[Any]:
        """Get a single record matching all filters."""
        return self.db.query(self.model).filter_by(**filters).first()

    def list_all(self, limit: int = 100, offset: int = 0, **filters) -> List[Any]:
        """List records with optional filters, pagination."""
        q = self.db.query(self.model)
        if filters:
            q = q.filter_by(**filters)
        return q.order_by(self.model.id.desc()).offset(offset).limit(limit).all()

    def count(self, **filters) -> int:
        """Count records matching filters."""
        q = self.db.query(self.model)
        if filters:
            q = q.filter_by(**filters)
        return q.count()

    def delete_by_id(self, record_id: int) -> bool:
        """Delete a record by primary key. Returns True if found."""
        obj = self.get_by_id(record_id)
        if obj:
            self.db.delete(obj)
            self.db.flush()
            return True
        return False

    def commit(self) -> None:
        """Commit the current transaction."""
        self.db.commit()

    def rollback(self) -> None:
        """Roll back the current transaction."""
        self.db.rollback()
