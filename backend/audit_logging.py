"""
Archmorph Audit Logging Module

Provides comprehensive audit logging for compliance and security monitoring.
Includes:
- AuditEvent dataclass with full security context
- AuditLogger class with specialized methods and async buffer flush
- Alerting rules for brute-force, off-hours admin, and bulk exports
- Decorators for route-level audit tagging
"""

import os
import logging
import json
import functools
import time as _time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Callable
from enum import Enum
from collections import deque
import threading

from logging_config import correlation_id_var

logger = logging.getLogger(__name__)

# Configuration
AUDIT_LOG_ENABLED = os.getenv("AUDIT_LOG_ENABLED", "true").lower() == "true"
AUDIT_LOG_MAX_ENTRIES = int(os.getenv("AUDIT_LOG_MAX_ENTRIES", "10000"))
AUDIT_LOG_FILE = os.getenv("AUDIT_LOG_FILE", "")  # optional file sink

# Alerting thresholds
FAILED_LOGIN_THRESHOLD = int(os.getenv("AUDIT_FAILED_LOGIN_THRESHOLD", "5"))
FAILED_LOGIN_WINDOW_SECONDS = int(os.getenv("AUDIT_FAILED_LOGIN_WINDOW", "300"))
BUSINESS_HOURS_START = int(os.getenv("AUDIT_BUSINESS_HOURS_START", "8"))
BUSINESS_HOURS_END = int(os.getenv("AUDIT_BUSINESS_HOURS_END", "18"))
BULK_EXPORT_THRESHOLD = int(os.getenv("AUDIT_BULK_EXPORT_THRESHOLD", "10"))
BULK_EXPORT_WINDOW_SECONDS = int(os.getenv("AUDIT_BULK_EXPORT_WINDOW", "300"))


# ─────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────

class AuditEventType(str, Enum):
    """Types of audit events."""
    # Authentication
    AUTH_LOGIN = "auth.login"
    AUTH_LOGOUT = "auth.logout"
    AUTH_FAILED = "auth.failed"
    AUTH_TOKEN_REFRESH = "auth.token_refresh"  # nosec B105 - event type label, not a credential

    # API Access
    API_REQUEST = "api.request"
    API_ERROR = "api.error"
    API_RATE_LIMITED = "api.rate_limited"

    # Data Operations
    DATA_UPLOAD = "data.upload"
    DATA_EXPORT = "data.export"
    DATA_DELETE = "data.delete"
    DATA_ANALYZE = "data.analyze"

    # Admin Actions
    ADMIN_CONFIG_CHANGE = "admin.config_change"
    ADMIN_USER_MANAGEMENT = "admin.user_management"
    ADMIN_QUOTA_CHANGE = "admin.quota_change"

    # Security Events
    SECURITY_SUSPICIOUS = "security.suspicious"
    SECURITY_BLOCKED = "security.blocked"
    SECURITY_ALERT = "security.alert"

    # Feature Usage
    FEATURE_CHAT = "feature.chat"
    FEATURE_ROADMAP = "feature.roadmap"
    FEATURE_ISSUE_CREATE = "feature.issue_create"


class AuditSeverity(str, Enum):
    """Severity levels for audit events."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class RiskLevel(str, Enum):
    """Risk classification for audit events."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ─────────────────────────────────────────────────────────────
# AuditEvent dataclass
# ─────────────────────────────────────────────────────────────

@dataclass
class AuditEvent:
    """Structured audit event with full security context."""
    timestamp: str
    event_type: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    ip_address: Optional[str] = None
    endpoint: Optional[str] = None
    method: Optional[str] = None
    status_code: Optional[int] = None
    latency_ms: Optional[float] = None
    correlation_id: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    risk_level: str = RiskLevel.LOW.value
    severity: str = AuditSeverity.INFO.value

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─────────────────────────────────────────────────────────────
# In-memory store (shared between legacy functions and AuditLogger)
# ─────────────────────────────────────────────────────────────

_audit_lock = threading.Lock()
_audit_log: deque = deque(maxlen=AUDIT_LOG_MAX_ENTRIES)
_alerts: deque = deque(maxlen=1000)


# ─────────────────────────────────────────────────────────────
# AuditLogger class
# ─────────────────────────────────────────────────────────────

class AuditLogger:
    """
    Centralized audit logger with:
    - Structured JSON file output (optional)
    - In-memory buffer with async flush
    - Convenience methods for auth / API / export / admin / security events
    - Compliance query helpers
    - Alerting rules for brute-force, off-hours admin, bulk exports
    """

    def __init__(
        self,
        log_file: Optional[str] = None,
        buffer_size: int = 100,
        failed_login_threshold: int = FAILED_LOGIN_THRESHOLD,
        failed_login_window: int = FAILED_LOGIN_WINDOW_SECONDS,
        business_hours: tuple = (BUSINESS_HOURS_START, BUSINESS_HOURS_END),
        bulk_export_threshold: int = BULK_EXPORT_THRESHOLD,
        bulk_export_window: int = BULK_EXPORT_WINDOW_SECONDS,
    ):
        self._log_file = log_file or AUDIT_LOG_FILE
        self._buffer: List[Dict[str, Any]] = []
        self._buffer_lock = threading.Lock()
        self._buffer_size = buffer_size

        # Alerting config
        self._failed_login_threshold = failed_login_threshold
        self._failed_login_window = failed_login_window
        self._business_hours = business_hours
        self._bulk_export_threshold = bulk_export_threshold
        self._bulk_export_window = bulk_export_window

        # Tracking structures for alerting
        self._failed_logins: Dict[str, List[float]] = {}  # ip -> [timestamps]
        self._failed_logins_lock = threading.Lock()

        # Set up file handler if configured
        self._file_logger: Optional[logging.Logger] = None
        if self._log_file:
            self._file_logger = logging.getLogger("archmorph.audit.file")
            self._file_logger.setLevel(logging.INFO)
            self._file_logger.propagate = False
            fh = logging.FileHandler(self._log_file)
            fh.setFormatter(logging.Formatter("%(message)s"))
            if not self._file_logger.handlers:
                self._file_logger.addHandler(fh)

    # ── Core logging ──

    def _record(self, event: AuditEvent) -> Dict[str, Any]:
        """Persist an AuditEvent to all sinks and return the dict."""
        entry = event.to_dict()

        # Global in-memory store
        with _audit_lock:
            _audit_log.append(entry)

        # Buffer for batch flush
        with self._buffer_lock:
            self._buffer.append(entry)
            if len(self._buffer) >= self._buffer_size:
                self._flush_buffer_unlocked()

        # Structured log to stdout via standard logger
        log_message = json.dumps({"audit": True, **entry})
        sev = event.severity
        if sev == AuditSeverity.CRITICAL.value:
            logger.critical(log_message)
        elif sev == AuditSeverity.ERROR.value:
            logger.error(log_message)
        elif sev == AuditSeverity.WARNING.value:
            logger.warning(log_message)
        else:
            logger.info(log_message)

        # Optional file sink
        if self._file_logger:
            self._file_logger.info(log_message)

        # Run alerting rules
        self._check_alerts(event)

        return entry

    def _flush_buffer_unlocked(self) -> List[Dict[str, Any]]:
        """Flush the buffer — caller must hold _buffer_lock."""
        flushed = list(self._buffer)
        self._buffer.clear()
        return flushed

    def flush(self) -> List[Dict[str, Any]]:
        """Flush the in-memory buffer and return flushed entries."""
        with self._buffer_lock:
            return self._flush_buffer_unlocked()

    def get_buffer_size(self) -> int:
        """Return number of entries currently in the buffer."""
        with self._buffer_lock:
            return len(self._buffer)

    # ── Convenience methods ──

    def log_auth_event(
        self,
        event_type: AuditEventType,
        *,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        session_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        success: bool = True,
    ) -> Dict[str, Any]:
        """Log an authentication event (login, logout, failure)."""
        if event_type == AuditEventType.AUTH_FAILED:
            risk = RiskLevel.HIGH
            sev = AuditSeverity.WARNING
        elif not success:
            risk = RiskLevel.MEDIUM
            sev = AuditSeverity.WARNING
        else:
            risk = RiskLevel.LOW
            sev = AuditSeverity.INFO

        event = AuditEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=event_type.value,
            user_id=user_id,
            session_id=session_id,
            ip_address=ip_address,
            correlation_id=correlation_id_var.get(""),
            details=details or {},
            risk_level=risk.value,
            severity=sev.value,
        )
        return self._record(event)

    def log_api_access(
        self,
        *,
        endpoint: str,
        method: str,
        status_code: int,
        latency_ms: float,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        session_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Log an API access event with latency tracking."""
        if status_code >= 500:
            risk = RiskLevel.MEDIUM
            sev = AuditSeverity.ERROR
            etype = AuditEventType.API_ERROR
        elif status_code == 429:
            risk = RiskLevel.MEDIUM
            sev = AuditSeverity.WARNING
            etype = AuditEventType.API_RATE_LIMITED
        elif status_code >= 400:
            risk = RiskLevel.LOW
            sev = AuditSeverity.WARNING
            etype = AuditEventType.API_ERROR
        else:
            risk = RiskLevel.LOW
            sev = AuditSeverity.INFO
            etype = AuditEventType.API_REQUEST

        event = AuditEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=etype.value,
            user_id=user_id,
            session_id=session_id,
            ip_address=ip_address,
            endpoint=endpoint,
            method=method,
            status_code=status_code,
            latency_ms=round(latency_ms, 2),
            correlation_id=correlation_id_var.get(""),
            details=details or {},
            risk_level=risk.value,
            severity=sev.value,
        )
        return self._record(event)

    def log_data_export(
        self,
        *,
        endpoint: Optional[str] = None,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        export_type: str = "unknown",
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Log a data export event."""
        d = dict(details or {})
        d["export_type"] = export_type
        event = AuditEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=AuditEventType.DATA_EXPORT.value,
            user_id=user_id,
            ip_address=ip_address,
            endpoint=endpoint,
            correlation_id=correlation_id_var.get(""),
            details=d,
            risk_level=RiskLevel.MEDIUM.value,
            severity=AuditSeverity.INFO.value,
        )
        return self._record(event)

    def log_admin_action(
        self,
        event_type: AuditEventType = AuditEventType.ADMIN_CONFIG_CHANGE,
        *,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        endpoint: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Log an admin action event."""
        event = AuditEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=event_type.value,
            user_id=user_id,
            ip_address=ip_address,
            endpoint=endpoint,
            correlation_id=correlation_id_var.get(""),
            details=details or {},
            risk_level=RiskLevel.HIGH.value,
            severity=AuditSeverity.WARNING.value,
        )
        return self._record(event)

    def log_security_event(
        self,
        event_type: AuditEventType = AuditEventType.SECURITY_ALERT,
        *,
        risk_level: RiskLevel = RiskLevel.HIGH,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Log a security event (suspicious activity, blocked request, etc.)."""
        sev = AuditSeverity.CRITICAL if risk_level == RiskLevel.CRITICAL else AuditSeverity.ERROR
        event = AuditEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=event_type.value,
            user_id=user_id,
            ip_address=ip_address,
            correlation_id=correlation_id_var.get(""),
            details=details or {},
            risk_level=risk_level.value,
            severity=sev.value,
        )
        return self._record(event)

    # ── Alerting rules ──

    def _check_alerts(self, event: AuditEvent) -> None:
        """Evaluate alerting rules against the incoming event."""
        # Rule 1: Failed login brute-force detection
        if event.event_type == AuditEventType.AUTH_FAILED.value and event.ip_address:
            self._track_failed_login(event.ip_address)

        # Rule 2: Admin action outside business hours
        if event.event_type.startswith("admin."):
            self._check_off_hours_admin(event)

        # Rule 3: Bulk data export detection
        if event.event_type == AuditEventType.DATA_EXPORT.value:
            self._check_bulk_export(event)

    def _track_failed_login(self, ip: str) -> None:
        """Track failed logins per IP and raise alert if threshold exceeded."""
        now = _time.time()
        cutoff = now - self._failed_login_window

        with self._failed_logins_lock:
            attempts = self._failed_logins.setdefault(ip, [])
            attempts.append(now)
            # Prune old entries
            self._failed_logins[ip] = [t for t in attempts if t > cutoff]
            count = len(self._failed_logins[ip])

        if count >= self._failed_login_threshold:
            alert = {
                "alert_type": "brute_force_detected",
                "ip_address": ip,
                "attempts": count,
                "window_seconds": self._failed_login_window,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            with _audit_lock:
                _alerts.append(alert)
            logger.critical(
                json.dumps({"audit_alert": True, **alert})
            )

    def _check_off_hours_admin(self, event: AuditEvent) -> None:
        """Alert if admin actions occur outside business hours (UTC)."""
        try:
            ts = datetime.fromisoformat(event.timestamp)
        except (ValueError, TypeError):
            return
        hour = ts.hour
        start_h, end_h = self._business_hours
        if hour < start_h or hour >= end_h:
            alert = {
                "alert_type": "off_hours_admin_action",
                "event_type": event.event_type,
                "user_id": event.user_id,
                "hour_utc": hour,
                "timestamp": event.timestamp,
            }
            with _audit_lock:
                _alerts.append(alert)
            logger.warning(
                json.dumps({"audit_alert": True, **alert})
            )

    def _check_bulk_export(self, event: AuditEvent) -> None:
        """Alert if exports exceed threshold within time window."""
        now = _time.time()
        cutoff = now - self._bulk_export_window
        with _audit_lock:
            recent_exports = [
                e for e in _audit_log
                if e.get("event_type") == AuditEventType.DATA_EXPORT.value
            ]
        # Count exports whose timestamp falls within window
        count = 0
        for ex in recent_exports:
            try:
                ts = datetime.fromisoformat(ex["timestamp"])
                if ts.timestamp() > cutoff:
                    count += 1
            except (ValueError, KeyError, TypeError):
                continue
        if count >= self._bulk_export_threshold:
            alert = {
                "alert_type": "bulk_export_detected",
                "export_count": count,
                "window_seconds": self._bulk_export_window,
                "user_id": event.user_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            with _audit_lock:
                _alerts.append(alert)
            logger.warning(
                json.dumps({"audit_alert": True, **alert})
            )

    # ── Compliance query helpers ──

    def get_failed_logins(
        self, limit: int = 100, ip_address: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Return recent failed login events."""
        with _audit_lock:
            logs = list(_audit_log)
        results = []
        for entry in reversed(logs):
            if entry.get("event_type") != AuditEventType.AUTH_FAILED.value:
                continue
            if ip_address and entry.get("ip_address") != ip_address:
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return results

    def get_admin_actions(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return recent admin action events."""
        with _audit_lock:
            logs = list(_audit_log)
        results = []
        for entry in reversed(logs):
            if not entry.get("event_type", "").startswith("admin."):
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return results

    def get_exports(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return recent data export events."""
        with _audit_lock:
            logs = list(_audit_log)
        results = []
        for entry in reversed(logs):
            if entry.get("event_type") != AuditEventType.DATA_EXPORT.value:
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return results

    def get_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return triggered alerts."""
        with _audit_lock:
            return list(_alerts)[-limit:]

    def clear_alerts(self) -> int:
        """Clear all alerts."""
        with _audit_lock:
            count = len(_alerts)
            _alerts.clear()
        return count


# ── Module-level singleton ──
audit_logger = AuditLogger()


# ─────────────────────────────────────────────────────────────
# Audit Decorators
# ─────────────────────────────────────────────────────────────

def audit_admin_action(action_name: str = "admin_action"):
    """Decorator that logs admin actions on route handlers."""
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            request = kwargs.get("request") or next(
                (a for a in args if hasattr(a, "client")), None
            )
            ip = request.client.host if request and request.client else None
            start = _time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                latency = (_time.perf_counter() - start) * 1000
                audit_logger.log_admin_action(
                    endpoint=request.url.path if request else action_name,
                    ip_address=ip,
                    details={"action": action_name, "latency_ms": round(latency, 2)},
                )
                return result
            except Exception as exc:
                latency = (_time.perf_counter() - start) * 1000
                audit_logger.log_security_event(
                    event_type=AuditEventType.SECURITY_ALERT,
                    risk_level=RiskLevel.HIGH,
                    ip_address=ip,
                    details={
                        "action": action_name,
                        "error": str(exc),
                        "latency_ms": round(latency, 2),
                    },
                )
                raise
        return wrapper
    return decorator


def audit_export(export_type: str = "generic"):
    """Decorator that logs data export actions on route handlers."""
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            request = kwargs.get("request") or next(
                (a for a in args if hasattr(a, "client")), None
            )
            ip = request.client.host if request and request.client else None
            result = await func(*args, **kwargs)
            audit_logger.log_data_export(
                endpoint=request.url.path if request else None,
                ip_address=ip,
                export_type=export_type,
            )
            return result
        return wrapper
    return decorator


def audit_auth(event_type: AuditEventType = AuditEventType.AUTH_LOGIN):
    """Decorator that logs auth events on route handlers."""
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            request = kwargs.get("request") or next(
                (a for a in args if hasattr(a, "client")), None
            )
            ip = request.client.host if request and request.client else None
            try:
                result = await func(*args, **kwargs)
                audit_logger.log_auth_event(
                    event_type=event_type,
                    ip_address=ip,
                    success=True,
                )
                return result
            except Exception:
                audit_logger.log_auth_event(
                    event_type=AuditEventType.AUTH_FAILED,
                    ip_address=ip,
                    success=False,
                )
                raise
        return wrapper
    return decorator


# ─────────────────────────────────────────────────────────────
# Legacy API (backward-compatible)
# ─────────────────────────────────────────────────────────────

def log_audit_event(
    event_type: AuditEventType,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    endpoint: Optional[str] = None,
    method: Optional[str] = None,
    status_code: Optional[int] = None,
    latency_ms: Optional[float] = None,
    details: Optional[Dict[str, Any]] = None,
    severity: AuditSeverity = AuditSeverity.INFO,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Log an audit event (legacy interface — delegates to AuditLogger).

    Returns:
        The created audit log entry.
    """
    if not AUDIT_LOG_ENABLED:
        return {}

    # Map severity to risk level
    risk_map = {
        AuditSeverity.INFO: RiskLevel.LOW,
        AuditSeverity.WARNING: RiskLevel.MEDIUM,
        AuditSeverity.ERROR: RiskLevel.HIGH,
        AuditSeverity.CRITICAL: RiskLevel.CRITICAL,
    }
    risk = risk_map.get(severity, RiskLevel.LOW)

    event = AuditEvent(
        timestamp=datetime.now(timezone.utc).isoformat(),
        event_type=event_type.value,
        severity=severity.value,
        user_id=user_id,
        session_id=session_id,
        ip_address=ip_address,
        endpoint=endpoint,
        method=method,
        status_code=status_code,
        latency_ms=latency_ms,
        correlation_id=correlation_id or correlation_id_var.get(""),
        details=details or {},
        risk_level=risk.value,
    )

    # Use the shared store directly (matches old behavior)
    entry = event.to_dict()
    with _audit_lock:
        _audit_log.append(entry)

    log_message = json.dumps({"audit": True, **entry})
    if severity == AuditSeverity.CRITICAL:
        logger.critical(log_message)
    elif severity == AuditSeverity.ERROR:
        logger.error(log_message)
    elif severity == AuditSeverity.WARNING:
        logger.warning(log_message)
    else:
        logger.info(log_message)

    return entry


def get_audit_logs(
    event_type: Optional[str] = None,
    user_id: Optional[str] = None,
    severity: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    Query audit logs with optional filters.

    Returns:
        List of matching audit log entries (most recent first).
    """
    with _audit_lock:
        logs = list(_audit_log)

    filtered = []
    for entry in reversed(logs):
        if event_type and entry.get("event_type") != event_type:
            continue
        if user_id and entry.get("user_id") != user_id:
            continue
        if severity and entry.get("severity") != severity:
            continue
        if start_time:
            if entry.get("timestamp", "") < start_time:
                continue
        if end_time:
            if entry.get("timestamp", "") > end_time:
                continue

        filtered.append(entry)
        if len(filtered) >= limit:
            break

    return filtered


def get_audit_summary() -> Dict[str, Any]:
    """
    Get summary statistics of audit logs.

    Returns:
        Dictionary with audit statistics.
    """
    with _audit_lock:
        logs = list(_audit_log)

    if not logs:
        return {
            "total_events": 0,
            "by_type": {},
            "by_severity": {},
            "time_range": None,
        }

    by_type: Dict[str, int] = {}
    by_severity: Dict[str, int] = {}

    for entry in logs:
        event_type = entry.get("event_type", "unknown")
        severity = entry.get("severity", "info")

        by_type[event_type] = by_type.get(event_type, 0) + 1
        by_severity[severity] = by_severity.get(severity, 0) + 1

    return {
        "total_events": len(logs),
        "by_type": by_type,
        "by_severity": by_severity,
        "time_range": {
            "oldest": logs[0].get("timestamp"),
            "newest": logs[-1].get("timestamp"),
        },
        "security_events": sum(
            1 for e in logs if e.get("event_type", "").startswith("security.")
        ),
        "auth_failures": sum(
            1 for e in logs if e.get("event_type") == AuditEventType.AUTH_FAILED.value
        ),
    }


def clear_audit_logs() -> int:
    """
    Clear all audit logs (admin operation).

    Returns:
        Number of entries cleared.
    """
    with _audit_lock:
        count = len(_audit_log)
        _audit_log.clear()
    return count
