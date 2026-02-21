"""
Tests for Archmorph Audit Logging Module
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from audit_logging import (
    log_audit_event, get_audit_logs, get_audit_summary, clear_audit_logs,
    AuditEventType, AuditSeverity,
)


@pytest.fixture(autouse=True)
def clean_audit_logs():
    """Clear audit logs before and after each test."""
    clear_audit_logs()
    yield
    clear_audit_logs()


class TestAuditEventTypes:
    """Tests for audit event type enumeration."""
    
    def test_auth_events_exist(self):
        """Authentication event types exist."""
        assert AuditEventType.AUTH_LOGIN
        assert AuditEventType.AUTH_LOGOUT
        assert AuditEventType.AUTH_FAILED
    
    def test_api_events_exist(self):
        """API event types exist."""
        assert AuditEventType.API_REQUEST
        assert AuditEventType.API_ERROR
        assert AuditEventType.API_RATE_LIMITED
    
    def test_security_events_exist(self):
        """Security event types exist."""
        assert AuditEventType.SECURITY_SUSPICIOUS
        assert AuditEventType.SECURITY_BLOCKED
        assert AuditEventType.SECURITY_ALERT


class TestAuditSeverity:
    """Tests for audit severity levels."""
    
    def test_severity_levels(self):
        """All severity levels exist."""
        assert AuditSeverity.INFO.value == "info"
        assert AuditSeverity.WARNING.value == "warning"
        assert AuditSeverity.ERROR.value == "error"
        assert AuditSeverity.CRITICAL.value == "critical"


class TestLogAuditEvent:
    """Tests for logging audit events."""
    
    def test_basic_event_logging(self):
        """Log a basic audit event."""
        entry = log_audit_event(
            event_type=AuditEventType.API_REQUEST,
            endpoint="/api/health",
            method="GET",
            status_code=200,
        )
        
        assert entry["event_type"] == "api.request"
        assert entry["endpoint"] == "/api/health"
        assert entry["method"] == "GET"
        assert entry["status_code"] == 200
    
    def test_event_with_user_info(self):
        """Log event with user information."""
        entry = log_audit_event(
            event_type=AuditEventType.AUTH_LOGIN,
            user_id="user_123",
            session_id="sess_abc",
            ip_address="192.168.1.1",
        )
        
        assert entry["user_id"] == "user_123"
        assert entry["session_id"] == "sess_abc"
        assert entry["ip_address"] == "192.168.1.1"
    
    def test_event_with_details(self):
        """Log event with additional details."""
        entry = log_audit_event(
            event_type=AuditEventType.DATA_UPLOAD,
            details={"file_size": 1024, "file_type": "image/png"},
        )
        
        assert entry["details"]["file_size"] == 1024
        assert entry["details"]["file_type"] == "image/png"
    
    def test_event_severity(self):
        """Log event with different severity levels."""
        entry = log_audit_event(
            event_type=AuditEventType.SECURITY_ALERT,
            severity=AuditSeverity.CRITICAL,
        )
        
        assert entry["severity"] == "critical"
    
    def test_event_has_timestamp(self):
        """Logged events have timestamps."""
        entry = log_audit_event(
            event_type=AuditEventType.API_REQUEST,
        )
        
        assert "timestamp" in entry
        assert "T" in entry["timestamp"]  # ISO format


class TestGetAuditLogs:
    """Tests for retrieving audit logs."""
    
    def test_get_empty_logs(self):
        """Get logs when none exist."""
        logs = get_audit_logs()
        assert logs == []
    
    def test_get_logged_events(self):
        """Get previously logged events."""
        log_audit_event(AuditEventType.API_REQUEST)
        log_audit_event(AuditEventType.AUTH_LOGIN)
        
        logs = get_audit_logs()
        assert len(logs) == 2
    
    def test_filter_by_event_type(self):
        """Filter logs by event type."""
        log_audit_event(AuditEventType.API_REQUEST)
        log_audit_event(AuditEventType.AUTH_LOGIN)
        log_audit_event(AuditEventType.API_REQUEST)
        
        logs = get_audit_logs(event_type="api.request")
        assert len(logs) == 2
    
    def test_filter_by_user_id(self):
        """Filter logs by user ID."""
        log_audit_event(AuditEventType.API_REQUEST, user_id="user_1")
        log_audit_event(AuditEventType.API_REQUEST, user_id="user_2")
        
        logs = get_audit_logs(user_id="user_1")
        assert len(logs) == 1
        assert logs[0]["user_id"] == "user_1"
    
    def test_filter_by_severity(self):
        """Filter logs by severity."""
        log_audit_event(AuditEventType.API_REQUEST, severity=AuditSeverity.INFO)
        log_audit_event(AuditEventType.SECURITY_ALERT, severity=AuditSeverity.CRITICAL)
        
        logs = get_audit_logs(severity="critical")
        assert len(logs) == 1
    
    def test_limit_results(self):
        """Limit number of returned logs."""
        for i in range(10):
            log_audit_event(AuditEventType.API_REQUEST)
        
        logs = get_audit_logs(limit=5)
        assert len(logs) == 5
    
    def test_most_recent_first(self):
        """Logs are returned most recent first."""
        log_audit_event(AuditEventType.API_REQUEST, endpoint="/first")
        log_audit_event(AuditEventType.API_REQUEST, endpoint="/second")
        
        logs = get_audit_logs()
        assert logs[0]["endpoint"] == "/second"
        assert logs[1]["endpoint"] == "/first"


class TestGetAuditSummary:
    """Tests for audit summary statistics."""
    
    def test_empty_summary(self):
        """Summary for empty logs."""
        summary = get_audit_summary()
        
        assert summary["total_events"] == 0
        assert summary["by_type"] == {}
        assert summary["by_severity"] == {}
    
    def test_summary_counts_events(self):
        """Summary counts total events."""
        log_audit_event(AuditEventType.API_REQUEST)
        log_audit_event(AuditEventType.AUTH_LOGIN)
        log_audit_event(AuditEventType.API_REQUEST)
        
        summary = get_audit_summary()
        
        assert summary["total_events"] == 3
        assert summary["by_type"]["api.request"] == 2
        assert summary["by_type"]["auth.login"] == 1
    
    def test_summary_counts_by_severity(self):
        """Summary counts events by severity."""
        log_audit_event(AuditEventType.API_REQUEST, severity=AuditSeverity.INFO)
        log_audit_event(AuditEventType.SECURITY_ALERT, severity=AuditSeverity.CRITICAL)
        
        summary = get_audit_summary()
        
        assert summary["by_severity"]["info"] == 1
        assert summary["by_severity"]["critical"] == 1
    
    def test_summary_security_events_count(self):
        """Summary tracks security events."""
        log_audit_event(AuditEventType.SECURITY_ALERT)
        log_audit_event(AuditEventType.SECURITY_BLOCKED)
        log_audit_event(AuditEventType.API_REQUEST)
        
        summary = get_audit_summary()
        
        assert summary["security_events"] == 2
    
    def test_summary_auth_failures_count(self):
        """Summary tracks authentication failures."""
        log_audit_event(AuditEventType.AUTH_FAILED)
        log_audit_event(AuditEventType.AUTH_FAILED)
        log_audit_event(AuditEventType.AUTH_LOGIN)
        
        summary = get_audit_summary()
        
        assert summary["auth_failures"] == 2


class TestClearAuditLogs:
    """Tests for clearing audit logs."""
    
    def test_clear_logs(self):
        """Clear all audit logs."""
        log_audit_event(AuditEventType.API_REQUEST)
        log_audit_event(AuditEventType.AUTH_LOGIN)
        
        cleared = clear_audit_logs()
        
        assert cleared == 2
        assert get_audit_logs() == []
    
    def test_clear_empty_logs(self):
        """Clear when no logs exist."""
        cleared = clear_audit_logs()
        
        assert cleared == 0
