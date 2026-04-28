"""
Tests for the database layer (Issue #168).

Covers:
  - Engine creation with SQLite defaults
  - Model table creation via init_db()
  - Session lifecycle (create, query, rollback)
  - BaseRepository CRUD operations
"""

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─────────────────────────────────────────────────────────────
# Engine & session factory
# ─────────────────────────────────────────────────────────────

class TestDatabaseModule:
    """Tests for database.py engine setup."""

    def test_engine_is_created(self):
        from database import engine
        assert engine is not None

    def test_session_local_factory(self):
        from database import SessionLocal
        session = SessionLocal()
        assert session is not None
        session.close()

    def test_base_metadata_has_tables(self):
        from database import Base
        # After importing models, Base.metadata should have table definitions
        import models  # noqa: F401
        assert len(Base.metadata.tables) >= 10, (
            f"Expected >=10 tables, got {len(Base.metadata.tables)}: "
            f"{list(Base.metadata.tables.keys())}"
        )

    def test_init_db_creates_tables(self):
        """init_db() should create all tables without error."""
        from database import init_db
        # Should not raise
        init_db()

    def test_get_db_dependency(self):
        """get_db() yields a session and closes it."""
        from database import get_db
        gen = get_db()
        session = next(gen)
        assert session is not None
        try:
            gen.send(None)
        except StopIteration:
            pass

    def test_database_readiness_shape(self):
        from database import database_readiness
        readiness = database_readiness()
        assert readiness["backend"] in {"sqlite", "postgresql", "other"}
        assert "ready_for_production" in readiness


# ─────────────────────────────────────────────────────────────
# Model imports & table names
# ─────────────────────────────────────────────────────────────

class TestModels:
    """Verify all model classes are importable and have correct table names."""

    def test_feedback_record(self):
        from models.feedback import FeedbackRecord
        assert FeedbackRecord.__tablename__ == "feedback"

    def test_bug_report_record(self):
        from models.feedback import BugReportRecord
        assert BugReportRecord.__tablename__ == "bug_reports"

    def test_analytics_event_record(self):
        from models.analytics import AnalyticsEventRecord
        assert AnalyticsEventRecord.__tablename__ == "analytics_events"

    def test_analytics_session_record(self):
        from models.analytics import AnalyticsSessionRecord
        assert AnalyticsSessionRecord.__tablename__ == "analytics_sessions"

    def test_version_record(self):
        from models.versioning import VersionRecord
        assert VersionRecord.__tablename__ == "architecture_versions"

    def test_version_change_record(self):
        from models.versioning import VersionChangeRecord
        assert VersionChangeRecord.__tablename__ == "version_changes"

    def test_audit_log_record(self):
        from models.audit import AuditLogRecord
        assert AuditLogRecord.__tablename__ == "audit_log"

    def test_audit_alert_record(self):
        from models.audit import AuditAlertRecord
        assert AuditAlertRecord.__tablename__ == "audit_alerts"

    def test_usage_counter_record(self):
        from models.usage import UsageCounterRecord
        assert UsageCounterRecord.__tablename__ == "usage_counters"

    def test_funnel_step_record(self):
        from models.usage import FunnelStepRecord
        assert FunnelStepRecord.__tablename__ == "funnel_steps"

    def test_job_record(self):
        from models.job import JobRecord
        assert JobRecord.__tablename__ == "jobs"


# ─────────────────────────────────────────────────────────────
# BaseRepository CRUD
# ─────────────────────────────────────────────────────────────

class TestBaseRepository:
    """Test BaseRepository generic CRUD with FeedbackRecord."""

    def _make_repo(self):
        from database import SessionLocal, init_db
        from models.feedback import FeedbackRecord
        from repositories.base import BaseRepository

        class FeedbackRepo(BaseRepository):
            model = FeedbackRecord

        init_db()
        session = SessionLocal()
        return FeedbackRepo(session), session

    def test_create_and_get_by_id(self):
        repo, session = self._make_repo()
        try:
            record = repo.create(
                feedback_type="rating",
                score=5,
                category="general",
                comment="Great tool!",
            )
            assert record.id is not None
            fetched = repo.get_by_id(record.id)
            assert fetched is not None
            assert fetched.comment == "Great tool!"
        finally:
            session.rollback()
            session.close()

    def test_list_all(self):
        repo, session = self._make_repo()
        try:
            repo.create(feedback_type="rating", score=4, category="test1")
            repo.create(feedback_type="rating", score=3, category="test2")
            items = repo.list_all(limit=10)
            assert len(items) >= 2
        finally:
            session.rollback()
            session.close()

    def test_count(self):
        repo, session = self._make_repo()
        try:
            before = repo.count()
            repo.create(feedback_type="bug", score=1, category="count_test")
            after = repo.count()
            assert after == before + 1
        finally:
            session.rollback()
            session.close()

    def test_delete_by_id(self):
        repo, session = self._make_repo()
        try:
            record = repo.create(feedback_type="rating", score=2, category="del_test")
            rid = record.id
            deleted = repo.delete_by_id(rid)
            assert deleted is True
            assert repo.get_by_id(rid) is None
        finally:
            session.rollback()
            session.close()

    def test_get_by_filter(self):
        repo, session = self._make_repo()
        try:
            repo.create(feedback_type="nps", score=9, category="filter_test")
            result = repo.get_by(feedback_type="nps")
            assert result is not None
            assert result.feedback_type == "nps"
        finally:
            session.rollback()
            session.close()
