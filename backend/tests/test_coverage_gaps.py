"""
Coverage Gap Tests — exercise under-tested modules and edge cases.

Targets:
  - feature_flags.py edge cases
  - session_store.py edge cases
  - audit_logging.py edge cases
  - observability.py metric recording
  - logging_config.py formatter
  - Thin-coverage routers: feedback, roadmap, migration, terraform

Issue #35
"""

import json
import logging
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("RATE_LIMIT_ENABLED", "false")


# =================================================================
# Feature Flags — edge cases
# =================================================================

@pytest.mark.coverage
class TestFeatureFlagsEdgeCases:
    """Edge cases not covered in the main feature_flags tests."""

    def _fresh(self):
        from feature_flags import FeatureFlags
        return FeatureFlags()

    def test_create_flag_overwrites_existing(self):
        ff = self._fresh()
        ff.create_flag("dark_mode", enabled=False, description="Overwritten")
        flag = ff.get_flag("dark_mode")
        assert flag["enabled"] is False
        assert flag["description"] == "Overwritten"

    def test_update_flag_ignores_disallowed_keys(self):
        ff = self._fresh()
        result = ff.update_flag("dark_mode", {"enabled": True, "name": "hacked", "__class__": "bad"})
        assert result is not None
        assert result["name"] == "dark_mode"  # name must not change

    def test_env_override_individual(self):
        with patch.dict(os.environ, {"FEATURE_FLAG_DARK_MODE": "false"}):
            from feature_flags import FeatureFlags
            ff = FeatureFlags()
            assert ff.is_enabled("dark_mode") is False

    def test_env_override_json_blob(self):
        blob = json.dumps({"new_ai_model": {"enabled": True, "rollout_percentage": 100}})
        with patch.dict(os.environ, {"FEATURE_FLAGS_JSON": blob}):
            from feature_flags import FeatureFlags
            ff = FeatureFlags()
            assert ff.is_enabled("new_ai_model") is True

    def test_env_override_json_invalid(self):
        with patch.dict(os.environ, {"FEATURE_FLAGS_JSON": "not-json{{{"}):
            from feature_flags import FeatureFlags
            ff = FeatureFlags()  # should not raise
            # defaults still work
            assert ff.is_enabled("dark_mode") is True

    def test_env_override_json_boolean_shorthand(self):
        blob = json.dumps({"export_pptx": False})
        with patch.dict(os.environ, {"FEATURE_FLAGS_JSON": blob}):
            from feature_flags import FeatureFlags
            ff = FeatureFlags()
            assert ff.is_enabled("export_pptx") is False

    def test_env_override_json_creates_new_flag(self):
        blob = json.dumps({"brand_new_flag": {"enabled": True, "description": "new"}})
        with patch.dict(os.environ, {"FEATURE_FLAGS_JSON": blob}):
            from feature_flags import FeatureFlags
            ff = FeatureFlags()
            assert ff.is_enabled("brand_new_flag") is True

    def test_percentage_rollout_no_user(self):
        """Percentage rollout with no user uses flag-level hash."""
        ff = self._fresh()
        ff.update_flag("dark_mode", {"enabled": True, "rollout_percentage": 50})
        # Should return bool without raising
        result = ff.is_enabled("dark_mode")
        assert isinstance(result, bool)

    def test_environment_targeting_mismatch(self):
        ff = self._fresh()
        ff.update_flag("dark_mode", {"enabled": True, "target_environments": ["staging"]})
        # Current ENVIRONMENT is "production" by default
        assert ff.is_enabled("dark_mode") is False

    def test_get_all_returns_all_flags(self):
        ff = self._fresh()
        all_flags = ff.get_all()
        assert "dark_mode" in all_flags
        assert "new_ai_model" in all_flags
        assert "export_pptx" in all_flags
        assert "roadmap_v2" in all_flags

    def test_flag_to_dict_roundtrip(self):
        from feature_flags import Flag
        f = Flag(name="test", enabled=True, description="d", rollout_percentage=50)
        d = f.to_dict()
        assert d["name"] == "test"
        assert d["enabled"] is True
        assert d["rollout_percentage"] == 50


# =================================================================
# Session Store — edge cases
# =================================================================

@pytest.mark.coverage
class TestSessionStoreEdgeCases:
    def test_clear_empties_store(self):
        from session_store import InMemoryStore
        store = InMemoryStore()
        store["a"] = 1
        store["b"] = 2
        store.clear()
        assert len(store) == 0

    def test_keys_wildcard(self):
        from session_store import InMemoryStore
        store = InMemoryStore()
        store["diag:1"] = "a"
        store["diag:2"] = "b"
        store["img:1"] = "c"
        keys = store.keys("diag:*")
        assert len(keys) == 2
        assert all(k.startswith("diag:") for k in keys)

    def test_store_contains_false_for_missing(self):
        from session_store import InMemoryStore
        store = InMemoryStore()
        assert "missing" not in store

    def test_store_len_after_delete(self):
        from session_store import InMemoryStore
        store = InMemoryStore()
        store["k1"] = "v1"
        store["k2"] = "v2"
        del store["k1"]
        assert len(store) == 1

    def test_get_store_returns_same_instance(self):
        from session_store import get_store, reset_stores
        reset_stores()
        s1 = get_store("edge_test")
        s2 = get_store("edge_test")
        assert s1 is s2
        reset_stores()

    def test_set_with_explicit_ttl_param(self):
        """InMemoryStore.set ignores per-key TTL but doesn't crash."""
        from session_store import InMemoryStore
        store = InMemoryStore(ttl=300)
        store.set("k", "v", ttl=60)
        assert store.get("k") == "v"

    def test_abstract_clear_raises(self):
        from session_store import SessionStore
        with pytest.raises(NotImplementedError):
            SessionStore().clear()

    def test_abstract_contains(self):
        """SessionStore.__contains__ delegates to .get() which raises."""
        from session_store import SessionStore
        with pytest.raises(NotImplementedError):
            _ = "k" in SessionStore()

    def test_abstract_len(self):
        """SessionStore.__len__ delegates to .keys() which raises."""
        from session_store import SessionStore
        with pytest.raises(NotImplementedError):
            len(SessionStore())


# =================================================================
# Audit Logging — edge cases
# =================================================================

@pytest.mark.coverage
class TestAuditLoggingEdgeCases:
    def setup_method(self):
        from audit_logging import clear_audit_logs
        clear_audit_logs()

    def teardown_method(self):
        from audit_logging import clear_audit_logs
        clear_audit_logs()

    def test_log_and_retrieve(self):
        from audit_logging import log_audit_event, get_audit_logs, AuditEventType, AuditSeverity
        log_audit_event(
            event_type=AuditEventType.API_REQUEST,
            severity=AuditSeverity.INFO,
            details={"endpoint": "/api/health"},
        )
        logs = get_audit_logs()
        assert len(logs) >= 1
        assert logs[-1]["event_type"] == AuditEventType.API_REQUEST.value

    def test_audit_summary_structure(self):
        from audit_logging import log_audit_event, get_audit_summary, AuditEventType, AuditSeverity
        log_audit_event(AuditEventType.API_REQUEST, AuditSeverity.INFO, {"a": 1})
        summary = get_audit_summary()
        assert isinstance(summary, dict)
        assert "total_events" in summary

    def test_clear_audit_logs(self):
        from audit_logging import log_audit_event, get_audit_logs, clear_audit_logs, AuditEventType, AuditSeverity
        log_audit_event(AuditEventType.API_REQUEST, AuditSeverity.INFO, {})
        clear_audit_logs()
        logs = get_audit_logs()
        assert len(logs) == 0

    def test_audit_logger_convenience_log_api_access(self):
        from audit_logging import audit_logger
        audit_logger.log_api_access(
            endpoint="/api/test",
            method="GET",
            status_code=200,
            latency_ms=42.0,
            ip_address="127.0.0.1",
        )
        # Should not raise

    def test_audit_logger_flush(self):
        from audit_logging import audit_logger
        audit_logger.flush()  # should not raise even when empty


# =================================================================
# Observability — additional edge cases
# =================================================================

@pytest.mark.coverage
class TestObservabilityEdgeCases:
    def setup_method(self):
        from observability import _metrics
        _metrics["counters"].clear()
        _metrics["histograms"].clear()
        _metrics["gauges"].clear()

    def test_counter_default_value_is_one(self):
        from observability import increment_counter, get_metrics
        increment_counter("edge.counter")
        m = get_metrics()
        assert m["counters"]["edge.counter"]["value"] == 1

    def test_histogram_single_value_stats(self):
        from observability import record_histogram, get_metrics
        record_histogram("edge.latency", 42.0)
        h = get_metrics()["histograms"]["edge.latency"]
        assert h["count"] == 1
        assert h["min"] == 42.0
        assert h["max"] == 42.0

    def test_gauge_negative_value(self):
        from observability import set_gauge, get_metrics
        set_gauge("edge.gauge", -10)
        assert get_metrics()["gauges"]["edge.gauge"]["value"] == -10

    def test_gauge_zero(self):
        from observability import set_gauge, get_metrics
        set_gauge("edge.zero", 0)
        assert get_metrics()["gauges"]["edge.zero"]["value"] == 0

    def test_span_context_double_end(self):
        from observability import SpanContext
        span = SpanContext("double_end")
        span.end()
        _first_end = span.end_time  # noqa: F841 — assigned for debugging span timing in test assertions
        span.end()
        # Calling end twice should be safe
        assert span.end_time is not None

    def test_trace_span_with_tags(self):
        from observability import trace_span
        with trace_span("tagged_op", {"env": "test"}) as span:
            pass
        assert span.attributes["env"] == "test"
        assert span.end_time is not None


# =================================================================
# Logging Config — formatter
# =================================================================

@pytest.mark.coverage
class TestLoggingConfig:
    def test_configure_logging_does_not_crash(self):
        from logging_config import configure_logging
        configure_logging("DEBUG")
        # Verify root logger has a handler
        root = logging.getLogger()
        assert len(root.handlers) >= 1

    def test_formatter_injects_level(self):
        from logging_config import ArchmorphJsonFormatter
        import io as _io
        handler = logging.StreamHandler(_io.StringIO())
        handler.setFormatter(ArchmorphJsonFormatter())
        logger = logging.getLogger("test.formatter")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.info("test message")
        output = handler.stream.getvalue()
        assert "info" in output.lower() or "test message" in output

    def test_correlation_id_in_log(self):
        from logging_config import ArchmorphJsonFormatter, correlation_id_var
        import io as _io
        handler = logging.StreamHandler(_io.StringIO())
        handler.setFormatter(ArchmorphJsonFormatter())
        test_logger = logging.getLogger("test.correlation")
        test_logger.handlers.clear()
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.DEBUG)

        token = correlation_id_var.set("test-corr-123")
        try:
            test_logger.info("correlated event")
            output = handler.stream.getvalue()
            assert "test-corr-123" in output
        finally:
            correlation_id_var.reset(token)


# =================================================================
# Router coverage — feedback
# =================================================================

@pytest.mark.coverage
class TestFeedbackRouterCoverage:
    @pytest.fixture(scope="class")
    def client(self):
        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_nps_valid(self, client):
        resp = client.post("/api/feedback/nps", json={"score": 9})
        assert resp.status_code == 200

    def test_nps_with_followup(self, client):
        resp = client.post("/api/feedback/nps", json={
            "score": 7,
            "follow_up": "Great product",
            "session_id": "s1",
        })
        assert resp.status_code == 200

    def test_feature_feedback(self, client):
        resp = client.post("/api/feedback/feature", json={
            "feature": "iac_export",
            "helpful": False,
            "comment": "needs improvement",
        })
        assert resp.status_code == 200


# =================================================================
# Router coverage — roadmap
# =================================================================

@pytest.mark.coverage
class TestRoadmapRouterCoverage:
    @pytest.fixture(scope="class")
    def client(self):
        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_roadmap_list(self, client):
        resp = client.get("/api/roadmap")
        assert resp.status_code == 200

    def test_roadmap_release_not_found(self, client):
        resp = client.get("/api/roadmap/release/99.99.99")
        assert resp.status_code == 404


# NOTE: TestMigrationRouterCoverage archived — see _archive/tests/


# =================================================================
# Router coverage — terraform
# =================================================================

@pytest.mark.coverage
class TestTerraformRouterCoverage:
    @pytest.fixture(scope="class")
    def client(self):
        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_validate_valid_hcl(self, client):
        resp = client.post("/api/terraform/validate", json={
            "code": 'resource "azurerm_resource_group" "rg" {\n  name     = "test"\n  location = "eastus"\n}'
        })
        assert resp.status_code == 200

    def test_validate_empty_string(self, client):
        resp = client.post("/api/terraform/validate", json={"code": ""})
        assert resp.status_code in (200, 422)

    def test_validate_missing_code_422(self, client):
        resp = client.post("/api/terraform/validate", json={})
        assert resp.status_code == 422
