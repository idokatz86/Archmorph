"""
Tests for Archmorph Audit Logging Module

Covers:
- Legacy API (log_audit_event, get_audit_logs, get_audit_summary, clear_audit_logs)
- New enums: RiskLevel
- AuditEvent dataclass
- AuditLogger class (convenience methods, buffer, compliance queries)
- Alerting rules (brute-force, off-hours admin, bulk export)
- Audit decorators (audit_admin_action, audit_export, audit_auth)
"""

import pytest
import sys
import os
import asyncio
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from audit_logging import (
    log_audit_event, get_audit_logs, get_audit_summary, clear_audit_logs,
    AuditEventType, AuditSeverity,
    RiskLevel, AuditEvent, AuditLogger,
    audit_logger,
    audit_admin_action, audit_export, audit_auth,
    _audit_lock, _alerts,
)


@pytest.fixture(autouse=True)
def clean_audit_logs():
    """Clear audit logs before and after each test."""
    clear_audit_logs()
    with _audit_lock:
        _alerts.clear()
    # Also reset the singleton failed-login tracker
    with audit_logger._failed_logins_lock:
        audit_logger._failed_logins.clear()
    audit_logger.flush()
    yield
    clear_audit_logs()
    with _audit_lock:
        _alerts.clear()
    with audit_logger._failed_logins_lock:
        audit_logger._failed_logins.clear()
    audit_logger.flush()


# ─────────────────────────────────────────────────────────────
# Enum tests
# ─────────────────────────────────────────────────────────────

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

    def test_data_events_exist(self):
        """Data operation event types exist."""
        assert AuditEventType.DATA_UPLOAD
        assert AuditEventType.DATA_EXPORT
        assert AuditEventType.DATA_DELETE

    def test_admin_events_exist(self):
        """Admin event types exist."""
        assert AuditEventType.ADMIN_CONFIG_CHANGE
        assert AuditEventType.ADMIN_USER_MANAGEMENT
        assert AuditEventType.ADMIN_QUOTA_CHANGE


class TestAuditSeverity:
    """Tests for audit severity levels."""

    def test_severity_levels(self):
        """All severity levels exist."""
        assert AuditSeverity.INFO.value == "info"
        assert AuditSeverity.WARNING.value == "warning"
        assert AuditSeverity.ERROR.value == "error"
        assert AuditSeverity.CRITICAL.value == "critical"


class TestRiskLevel:
    """Tests for risk level enumeration."""

    def test_risk_levels(self):
        """All risk levels exist with correct values."""
        assert RiskLevel.LOW.value == "low"
        assert RiskLevel.MEDIUM.value == "medium"
        assert RiskLevel.HIGH.value == "high"
        assert RiskLevel.CRITICAL.value == "critical"


# ─────────────────────────────────────────────────────────────
# AuditEvent dataclass tests
# ─────────────────────────────────────────────────────────────

class TestAuditEvent:
    """Tests for AuditEvent dataclass."""

    def test_create_minimal_event(self):
        event = AuditEvent(
            timestamp="2026-01-01T00:00:00+00:00",
            event_type="api.request",
        )
        assert event.timestamp == "2026-01-01T00:00:00+00:00"
        assert event.event_type == "api.request"
        assert event.risk_level == "low"
        assert event.severity == "info"

    def test_create_full_event(self):
        event = AuditEvent(
            timestamp="2026-01-01T00:00:00+00:00",
            event_type="auth.failed",
            user_id="u1",
            session_id="s1",
            ip_address="10.0.0.1",
            endpoint="/api/login",
            method="POST",
            status_code=401,
            latency_ms=42.5,
            correlation_id="cid-123",
            details={"reason": "bad password"},
            risk_level="high",
            severity="warning",
        )
        assert event.user_id == "u1"
        assert event.latency_ms == 42.5
        assert event.details["reason"] == "bad password"

    def test_to_dict(self):
        event = AuditEvent(
            timestamp="2026-01-01T00:00:00+00:00",
            event_type="api.request",
        )
        d = event.to_dict()
        assert isinstance(d, dict)
        assert d["event_type"] == "api.request"
        assert d["risk_level"] == "low"

    def test_default_details_is_empty_dict(self):
        e1 = AuditEvent(timestamp="t", event_type="api.request")
        e2 = AuditEvent(timestamp="t", event_type="api.request")
        # Ensure independent dicts (no shared mutable default)
        e1.details["x"] = 1
        assert "x" not in e2.details


# ─────────────────────────────────────────────────────────────
# Legacy API tests (backward compatibility)
# ─────────────────────────────────────────────────────────────

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

    def test_event_has_risk_level(self):
        """Legacy events include risk_level field."""
        entry = log_audit_event(
            event_type=AuditEventType.API_REQUEST,
            severity=AuditSeverity.CRITICAL,
        )
        assert entry["risk_level"] == "critical"

    def test_severity_to_risk_mapping(self):
        """Severity maps to matching risk level in legacy API."""
        info_entry = log_audit_event(AuditEventType.API_REQUEST, severity=AuditSeverity.INFO)
        warn_entry = log_audit_event(AuditEventType.API_REQUEST, severity=AuditSeverity.WARNING)
        err_entry = log_audit_event(AuditEventType.API_REQUEST, severity=AuditSeverity.ERROR)
        crit_entry = log_audit_event(AuditEventType.API_REQUEST, severity=AuditSeverity.CRITICAL)
        assert info_entry["risk_level"] == "low"
        assert warn_entry["risk_level"] == "medium"
        assert err_entry["risk_level"] == "high"
        assert crit_entry["risk_level"] == "critical"


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


# ─────────────────────────────────────────────────────────────
# AuditLogger class tests
# ─────────────────────────────────────────────────────────────

class TestAuditLoggerAuthEvent:
    """Tests for AuditLogger.log_auth_event()."""

    def test_successful_login(self):
        entry = audit_logger.log_auth_event(
            AuditEventType.AUTH_LOGIN,
            user_id="u1",
            ip_address="10.0.0.1",
        )
        assert entry["event_type"] == "auth.login"
        assert entry["risk_level"] == "low"
        assert entry["severity"] == "info"

    def test_failed_login(self):
        entry = audit_logger.log_auth_event(
            AuditEventType.AUTH_FAILED,
            ip_address="10.0.0.2",
        )
        assert entry["event_type"] == "auth.failed"
        assert entry["risk_level"] == "high"
        assert entry["severity"] == "warning"

    def test_auth_event_with_session(self):
        entry = audit_logger.log_auth_event(
            AuditEventType.AUTH_LOGOUT,
            user_id="u1",
            session_id="sess_abc",
        )
        assert entry["session_id"] == "sess_abc"


class TestAuditLoggerApiAccess:
    """Tests for AuditLogger.log_api_access()."""

    def test_successful_request(self):
        entry = audit_logger.log_api_access(
            endpoint="/api/services",
            method="GET",
            status_code=200,
            latency_ms=12.3,
        )
        assert entry["event_type"] == "api.request"
        assert entry["risk_level"] == "low"
        assert entry["latency_ms"] == 12.3

    def test_server_error(self):
        entry = audit_logger.log_api_access(
            endpoint="/api/analyze",
            method="POST",
            status_code=500,
            latency_ms=100.0,
        )
        assert entry["event_type"] == "api.error"
        assert entry["risk_level"] == "medium"
        assert entry["severity"] == "error"

    def test_rate_limited(self):
        entry = audit_logger.log_api_access(
            endpoint="/api/analyze",
            method="POST",
            status_code=429,
            latency_ms=5.0,
        )
        assert entry["event_type"] == "api.rate_limited"
        assert entry["severity"] == "warning"

    def test_client_error(self):
        entry = audit_logger.log_api_access(
            endpoint="/api/bad",
            method="GET",
            status_code=404,
            latency_ms=2.0,
        )
        assert entry["event_type"] == "api.error"
        assert entry["severity"] == "warning"


class TestAuditLoggerDataExport:
    """Tests for AuditLogger.log_data_export()."""

    def test_export_event(self):
        entry = audit_logger.log_data_export(
            endpoint="/api/export/terraform",
            user_id="u1",
            export_type="terraform",
        )
        assert entry["event_type"] == "data.export"
        assert entry["details"]["export_type"] == "terraform"
        assert entry["risk_level"] == "medium"

    def test_export_with_details(self):
        entry = audit_logger.log_data_export(
            export_type="hld_pdf",
            details={"page_count": 5},
        )
        assert entry["details"]["page_count"] == 5
        assert entry["details"]["export_type"] == "hld_pdf"


class TestAuditLoggerAdminAction:
    """Tests for AuditLogger.log_admin_action()."""

    def test_admin_config_change(self):
        entry = audit_logger.log_admin_action(
            event_type=AuditEventType.ADMIN_CONFIG_CHANGE,
            user_id="admin1",
            details={"setting": "rate_limit", "value": 100},
        )
        assert entry["event_type"] == "admin.config_change"
        assert entry["risk_level"] == "high"
        assert entry["severity"] == "warning"

    def test_admin_user_management(self):
        entry = audit_logger.log_admin_action(
            event_type=AuditEventType.ADMIN_USER_MANAGEMENT,
            details={"action": "ban_user", "target": "u2"},
        )
        assert entry["event_type"] == "admin.user_management"


class TestAuditLoggerSecurityEvent:
    """Tests for AuditLogger.log_security_event()."""

    def test_security_alert(self):
        entry = audit_logger.log_security_event(
            event_type=AuditEventType.SECURITY_ALERT,
            risk_level=RiskLevel.CRITICAL,
            details={"reason": "SQL injection attempt"},
        )
        assert entry["event_type"] == "security.alert"
        assert entry["risk_level"] == "critical"
        assert entry["severity"] == "critical"

    def test_security_blocked(self):
        entry = audit_logger.log_security_event(
            event_type=AuditEventType.SECURITY_BLOCKED,
            risk_level=RiskLevel.HIGH,
            ip_address="10.0.0.99",
        )
        assert entry["event_type"] == "security.blocked"
        assert entry["severity"] == "error"


# ─────────────────────────────────────────────────────────────
# Buffer / flush tests
# ─────────────────────────────────────────────────────────────

class TestAuditLoggerBuffer:
    """Tests for in-memory buffer and flush."""

    def test_buffer_accumulates(self):
        audit_logger.log_api_access(
            endpoint="/a", method="GET", status_code=200, latency_ms=1.0,
        )
        assert audit_logger.get_buffer_size() >= 1

    def test_flush_returns_entries(self):
        audit_logger.log_api_access(
            endpoint="/b", method="GET", status_code=200, latency_ms=1.0,
        )
        flushed = audit_logger.flush()
        assert len(flushed) >= 1
        assert audit_logger.get_buffer_size() == 0

    def test_auto_flush_on_threshold(self):
        """Buffer auto-flushes when buffer_size is exceeded."""
        small_logger = AuditLogger(buffer_size=3)
        for i in range(5):
            small_logger.log_api_access(
                endpoint=f"/x{i}", method="GET", status_code=200, latency_ms=1.0,
            )
        # After 5 entries with buffer_size=3, buffer should have been flushed
        assert small_logger.get_buffer_size() < 5


# ─────────────────────────────────────────────────────────────
# Compliance query tests
# ─────────────────────────────────────────────────────────────

class TestComplianceQueries:
    """Tests for get_failed_logins, get_admin_actions, get_exports."""

    def test_get_failed_logins(self):
        audit_logger.log_auth_event(AuditEventType.AUTH_FAILED, ip_address="10.0.0.1")
        audit_logger.log_auth_event(AuditEventType.AUTH_LOGIN, ip_address="10.0.0.2")
        audit_logger.log_auth_event(AuditEventType.AUTH_FAILED, ip_address="10.0.0.3")

        failures = audit_logger.get_failed_logins()
        assert len(failures) == 2
        assert all(f["event_type"] == "auth.failed" for f in failures)

    def test_get_failed_logins_by_ip(self):
        audit_logger.log_auth_event(AuditEventType.AUTH_FAILED, ip_address="10.0.0.1")
        audit_logger.log_auth_event(AuditEventType.AUTH_FAILED, ip_address="10.0.0.2")

        failures = audit_logger.get_failed_logins(ip_address="10.0.0.1")
        assert len(failures) == 1
        assert failures[0]["ip_address"] == "10.0.0.1"

    def test_get_admin_actions(self):
        audit_logger.log_admin_action(details={"action": "clear_logs"})
        audit_logger.log_api_access(
            endpoint="/api/x", method="GET", status_code=200, latency_ms=1.0,
        )
        audit_logger.log_admin_action(
            event_type=AuditEventType.ADMIN_USER_MANAGEMENT,
            details={"action": "ban"},
        )

        actions = audit_logger.get_admin_actions()
        assert len(actions) == 2
        assert all(a["event_type"].startswith("admin.") for a in actions)

    def test_get_exports(self):
        audit_logger.log_data_export(export_type="terraform")
        audit_logger.log_api_access(
            endpoint="/api/services", method="GET", status_code=200, latency_ms=1.0,
        )
        audit_logger.log_data_export(export_type="hld_pdf")

        exports = audit_logger.get_exports()
        assert len(exports) == 2
        assert all(e["event_type"] == "data.export" for e in exports)

    def test_get_exports_with_limit(self):
        for i in range(10):
            audit_logger.log_data_export(export_type=f"type_{i}")
        exports = audit_logger.get_exports(limit=3)
        assert len(exports) == 3


# ─────────────────────────────────────────────────────────────
# Alerting rules tests
# ─────────────────────────────────────────────────────────────

class TestAlertingRules:
    """Tests for brute-force, off-hours admin, and bulk export alerts."""

    def test_brute_force_detection(self):
        """Alert fires after 5 failed logins from same IP within window."""
        al = AuditLogger(failed_login_threshold=3, failed_login_window=600)
        for _ in range(3):
            al.log_auth_event(AuditEventType.AUTH_FAILED, ip_address="10.0.0.5")

        alerts = al.get_alerts()
        assert any(a["alert_type"] == "brute_force_detected" for a in alerts)
        bf = next(a for a in alerts if a["alert_type"] == "brute_force_detected")
        assert bf["ip_address"] == "10.0.0.5"
        assert bf["attempts"] >= 3

    def test_no_alert_below_threshold(self):
        al = AuditLogger(failed_login_threshold=5, failed_login_window=600)
        for _ in range(3):
            al.log_auth_event(AuditEventType.AUTH_FAILED, ip_address="10.0.0.6")
        alerts = al.get_alerts()
        assert not any(a.get("alert_type") == "brute_force_detected" for a in alerts)

    def test_off_hours_admin_alert(self):
        """Alert fires for admin actions outside business hours."""
        # Business hours 8-18 UTC; hour 3 is outside
        al = AuditLogger(business_hours=(8, 18))
        # Manually craft an event with a specific timestamp at hour 3
        from audit_logging import AuditEvent
        event = AuditEvent(
            timestamp="2026-02-21T03:15:00+00:00",
            event_type=AuditEventType.ADMIN_CONFIG_CHANGE.value,
            risk_level=RiskLevel.HIGH.value,
            severity=AuditSeverity.WARNING.value,
        )
        al._record(event)
        alerts = al.get_alerts()
        assert any(a["alert_type"] == "off_hours_admin_action" for a in alerts)

    def test_no_off_hours_alert_during_business(self):
        """No alert for admin actions during business hours."""
        al = AuditLogger(business_hours=(8, 18))
        event = AuditEvent(
            timestamp="2026-02-21T10:00:00+00:00",
            event_type=AuditEventType.ADMIN_CONFIG_CHANGE.value,
            risk_level=RiskLevel.HIGH.value,
            severity=AuditSeverity.WARNING.value,
        )
        al._record(event)
        alerts = al.get_alerts()
        assert not any(a.get("alert_type") == "off_hours_admin_action" for a in alerts)

    def test_bulk_export_alert(self):
        """Alert fires when exports exceed threshold within window."""
        al = AuditLogger(bulk_export_threshold=3, bulk_export_window=600)
        for i in range(4):
            al.log_data_export(export_type=f"test_{i}")
        alerts = al.get_alerts()
        assert any(a.get("alert_type") == "bulk_export_detected" for a in alerts)

    def test_clear_alerts(self):
        al = AuditLogger(failed_login_threshold=2, failed_login_window=600)
        al.log_auth_event(AuditEventType.AUTH_FAILED, ip_address="10.0.0.7")
        al.log_auth_event(AuditEventType.AUTH_FAILED, ip_address="10.0.0.7")
        assert len(al.get_alerts()) > 0
        cleared = al.clear_alerts()
        assert cleared > 0
        assert len(al.get_alerts()) == 0


# ─────────────────────────────────────────────────────────────
# Decorator tests
# ─────────────────────────────────────────────────────────────

class TestAuditDecorators:
    """Tests for audit_admin_action, audit_export, audit_auth decorators."""

    def _make_request(self, path="/api/test"):
        request = MagicMock()
        request.url.path = path
        request.client.host = "127.0.0.1"
        return request

    def test_audit_admin_action_decorator(self):
        @audit_admin_action("test_admin_op")
        async def my_route(request):
            return {"ok": True}

        request = self._make_request("/api/admin/config")
        result = asyncio.get_event_loop().run_until_complete(my_route(request=request))
        assert result == {"ok": True}

        actions = audit_logger.get_admin_actions()
        assert len(actions) >= 1
        assert actions[0]["details"]["action"] == "test_admin_op"

    def test_audit_export_decorator(self):
        @audit_export("terraform")
        async def my_export(request):
            return {"data": "tf"}

        request = self._make_request("/api/export/terraform")
        result = asyncio.get_event_loop().run_until_complete(my_export(request=request))
        assert result == {"data": "tf"}

        exports = audit_logger.get_exports()
        assert len(exports) >= 1
        assert exports[0]["details"]["export_type"] == "terraform"

    def test_audit_auth_decorator_success(self):
        @audit_auth(AuditEventType.AUTH_LOGIN)
        async def login(request):
            return {"token": "abc"}

        request = self._make_request("/api/login")
        result = asyncio.get_event_loop().run_until_complete(login(request=request))
        assert result["token"] == "abc"

        logs = get_audit_logs(event_type="auth.login")
        assert len(logs) >= 1

    def test_audit_auth_decorator_failure(self):
        @audit_auth(AuditEventType.AUTH_LOGIN)
        async def login(request):
            raise ValueError("bad creds")

        request = self._make_request("/api/login")
        with pytest.raises(ValueError):
            asyncio.get_event_loop().run_until_complete(login(request=request))

        failures = audit_logger.get_failed_logins()
        assert len(failures) >= 1

    def test_admin_decorator_logs_error_on_exception(self):
        @audit_admin_action("dangerous_op")
        async def dangerous(request):
            raise RuntimeError("boom")

        request = self._make_request("/api/admin/danger")
        with pytest.raises(RuntimeError):
            asyncio.get_event_loop().run_until_complete(dangerous(request=request))

        # Should have logged a security event
        logs = get_audit_logs(event_type="security.alert")
        assert len(logs) >= 1


# ─────────────────────────────────────────────────────────────
# File sink test
# ─────────────────────────────────────────────────────────────

class TestAuditLoggerFileSink:
    """Test that the optional file sink writes structured JSON lines."""

    def test_file_output(self, tmp_path):
        log_file = str(tmp_path / "audit.jsonl")
        al = AuditLogger(log_file=log_file)
        al.log_api_access(
            endpoint="/api/test", method="GET", status_code=200, latency_ms=5.0,
        )
        with open(log_file) as f:
            lines = f.readlines()
        assert len(lines) == 1
        import json
        data = json.loads(lines[0])
        assert data["audit"] is True
        assert data["endpoint"] == "/api/test"
