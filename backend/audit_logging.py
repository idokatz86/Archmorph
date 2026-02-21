"""
Archmorph Audit Logging Module

Provides comprehensive audit logging for compliance and security monitoring.
"""

import os
import logging
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from enum import Enum
from collections import deque
import threading

logger = logging.getLogger(__name__)

# Configuration
AUDIT_LOG_ENABLED = os.getenv("AUDIT_LOG_ENABLED", "true").lower() == "true"
AUDIT_LOG_MAX_ENTRIES = int(os.getenv("AUDIT_LOG_MAX_ENTRIES", "10000"))


class AuditEventType(str, Enum):
    """Types of audit events."""
    # Authentication
    AUTH_LOGIN = "auth.login"
    AUTH_LOGOUT = "auth.logout"
    AUTH_FAILED = "auth.failed"
    AUTH_TOKEN_REFRESH = "auth.token_refresh"
    
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


# Thread-safe in-memory audit log store
_audit_lock = threading.Lock()
_audit_log: deque = deque(maxlen=AUDIT_LOG_MAX_ENTRIES)


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
    Log an audit event.
    
    Args:
        event_type: Type of audit event
        user_id: User identifier (if authenticated)
        session_id: Session identifier
        ip_address: Client IP address
        endpoint: API endpoint accessed
        method: HTTP method
        status_code: HTTP response status code
        latency_ms: Request latency in milliseconds
        details: Additional event-specific details
        severity: Event severity level
        correlation_id: Request correlation ID for tracing
        
    Returns:
        The created audit log entry.
    """
    if not AUDIT_LOG_ENABLED:
        return {}
    
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type.value,
        "severity": severity.value,
        "user_id": user_id,
        "session_id": session_id,
        "ip_address": ip_address,
        "endpoint": endpoint,
        "method": method,
        "status_code": status_code,
        "latency_ms": latency_ms,
        "correlation_id": correlation_id,
        "details": details or {},
    }
    
    with _audit_lock:
        _audit_log.append(entry)
    
    # Also log to standard logger for external aggregation
    log_message = json.dumps({
        "audit": True,
        **entry
    })
    
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
    
    Args:
        event_type: Filter by event type
        user_id: Filter by user ID
        severity: Filter by severity level
        start_time: Filter events after this time (ISO format)
        end_time: Filter events before this time (ISO format)
        limit: Maximum number of entries to return
        
    Returns:
        List of matching audit log entries.
    """
    with _audit_lock:
        logs = list(_audit_log)
    
    # Apply filters
    filtered = []
    for entry in reversed(logs):  # Most recent first
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
