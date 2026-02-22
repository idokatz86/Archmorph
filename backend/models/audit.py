"""Audit logging database models (Issue #168)."""

from sqlalchemy import Column, String, Integer, Float, Text, DateTime, Index
from sqlalchemy.sql import func
from database import Base


class AuditLogRecord(Base):
    """Persisted audit log entry — replaces in-memory _audit_log deque."""

    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(50), nullable=False, index=True)
    severity = Column(String(20), nullable=False, default="info")
    risk_level = Column(String(20), nullable=False, default="low")
    user_id = Column(String(100), nullable=True, index=True)
    session_id = Column(String(100), nullable=True)
    ip_address = Column(String(45), nullable=True)  # supports IPv6
    endpoint = Column(String(255), nullable=True, index=True)
    method = Column(String(10), nullable=True)
    status_code = Column(Integer, nullable=True)
    latency_ms = Column(Float, nullable=True)
    correlation_id = Column(String(64), nullable=True)
    details = Column(Text, nullable=True)           # JSON-serialized
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_audit_log_type_time", "event_type", "created_at"),
        Index("ix_audit_log_user_time", "user_id", "created_at"),
    )

    def to_dict(self):
        import json as _json
        return {
            "id": self.id,
            "event_type": self.event_type,
            "severity": self.severity,
            "risk_level": self.risk_level,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "ip_address": self.ip_address,
            "endpoint": self.endpoint,
            "method": self.method,
            "status_code": self.status_code,
            "latency_ms": self.latency_ms,
            "correlation_id": self.correlation_id,
            "details": _json.loads(self.details) if self.details else {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AuditAlertRecord(Base):
    """Persisted audit alert — replaces in-memory _alerts deque."""

    __tablename__ = "audit_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_type = Column(String(50), nullable=False, index=True)
    severity = Column(String(20), nullable=False, default="warning")
    message = Column(Text, nullable=False)
    details = Column(Text, nullable=True)           # JSON-serialized
    acknowledged = Column(Integer, default=0)       # 0=no, 1=yes (SQLite compat)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def to_dict(self):
        import json as _json
        return {
            "id": self.id,
            "alert_type": self.alert_type,
            "severity": self.severity,
            "message": self.message,
            "details": _json.loads(self.details) if self.details else {},
            "acknowledged": bool(self.acknowledged),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
