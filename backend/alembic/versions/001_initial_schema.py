"""Initial schema — all tables

Revision ID: 001
Revises: None
Create Date: 2026-02-22
"""

from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Feedback ──
    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("feedback_type", sa.String(20), nullable=False, index=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(20), nullable=True),
        sa.Column("feature", sa.String(100), nullable=True),
        sa.Column("helpful", sa.Boolean(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("session_id", sa.String(100), nullable=True, index=True),
        sa.Column("feature_context", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
    )

    op.create_table(
        "bug_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("session_id", sa.String(100), nullable=True, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
    )

    # ── Analytics ──
    op.create_table(
        "analytics_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(50), unique=True, nullable=False, index=True),
        sa.Column("event_name", sa.String(100), nullable=False, index=True),
        sa.Column("category", sa.String(30), nullable=False, index=True),
        sa.Column("user_id", sa.String(100), nullable=True, index=True),
        sa.Column("session_id", sa.String(100), nullable=True, index=True),
        sa.Column("properties", sa.Text(), nullable=True),
        sa.Column("metrics", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
    )
    op.create_index("ix_analytics_events_cat_time", "analytics_events", ["category", "created_at"])

    op.create_table(
        "analytics_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(100), unique=True, nullable=False, index=True),
        sa.Column("user_id", sa.String(100), nullable=True, index=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_activity", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("events_count", sa.Integer(), server_default="0"),
        sa.Column("page_views", sa.Text(), nullable=True),
        sa.Column("conversion_achieved", sa.Integer(), server_default="0"),
        sa.Column("duration_seconds", sa.Float(), server_default="0.0"),
    )

    # ── Versioning ──
    op.create_table(
        "architecture_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("version_id", sa.String(50), unique=True, nullable=False, index=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("diagram_id", sa.String(50), nullable=False, index=True),
        sa.Column("snapshot", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
    )
    op.create_index("ix_versions_diagram_num", "architecture_versions", ["diagram_id", "version_number"])

    op.create_table(
        "version_changes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("version_id", sa.String(50), sa.ForeignKey("architecture_versions.version_id"), nullable=False, index=True),
        sa.Column("change_type", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── Audit ──
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(50), nullable=False, index=True),
        sa.Column("severity", sa.String(20), nullable=False, server_default="info"),
        sa.Column("risk_level", sa.String(20), nullable=False, server_default="low"),
        sa.Column("user_id", sa.String(100), nullable=True, index=True),
        sa.Column("session_id", sa.String(100), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("endpoint", sa.String(255), nullable=True, index=True),
        sa.Column("method", sa.String(10), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
    )
    op.create_index("ix_audit_log_type_time", "audit_log", ["event_type", "created_at"])
    op.create_index("ix_audit_log_user_time", "audit_log", ["user_id", "created_at"])

    op.create_table(
        "audit_alerts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("alert_type", sa.String(50), nullable=False, index=True),
        sa.Column("severity", sa.String(20), nullable=False, server_default="warning"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("acknowledged", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
    )

    # ── Usage Metrics ──
    op.create_table(
        "usage_counters",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("counter_name", sa.String(100), nullable=False, index=True),
        sa.Column("date", sa.String(10), nullable=False, index=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_usage_counters_name_date", "usage_counters", ["counter_name", "date"], unique=True)

    op.create_table(
        "funnel_steps",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("diagram_id", sa.String(50), nullable=False, index=True),
        sa.Column("step", sa.String(30), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_funnel_diagram_step", "funnel_steps", ["diagram_id", "step"], unique=True)

    # ── Jobs ──
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(50), unique=True, nullable=False, index=True),
        sa.Column("job_type", sa.String(50), nullable=False, index=True),
        sa.Column("diagram_id", sa.String(50), nullable=True, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued", index=True),
        sa.Column("progress", sa.Integer(), server_default="0"),
        sa.Column("progress_message", sa.String(255), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
    )
    op.create_index("ix_jobs_diagram_type", "jobs", ["diagram_id", "job_type"])
    op.create_index("ix_jobs_status_created", "jobs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_table("funnel_steps")
    op.drop_table("usage_counters")
    op.drop_table("audit_alerts")
    op.drop_table("audit_log")
    op.drop_table("version_changes")
    op.drop_table("architecture_versions")
    op.drop_table("analytics_sessions")
    op.drop_table("analytics_events")
    op.drop_table("bug_reports")
    op.drop_table("feedback")
