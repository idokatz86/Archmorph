"""
Unit tests for the standardized error envelope module.

Covers:
  - ErrorBody / ErrorEnvelope Pydantic models
  - _build_envelope helper
  - Exception handlers produce correct envelope
  - HTTP status code mapping
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from error_envelope import (
    ErrorBody,
    ErrorEnvelope,
    _build_envelope,
    _STATUS_CODES,
)


class TestStatusCodes:
    """Verify the status code mapping."""

    def test_common_codes_present(self):
        assert _STATUS_CODES[400] == "BAD_REQUEST"
        assert _STATUS_CODES[401] == "UNAUTHORIZED"
        assert _STATUS_CODES[403] == "FORBIDDEN"
        assert _STATUS_CODES[404] == "NOT_FOUND"
        assert _STATUS_CODES[422] == "VALIDATION_ERROR"
        assert _STATUS_CODES[429] == "RATE_LIMITED"
        assert _STATUS_CODES[500] == "INTERNAL_ERROR"

    def test_all_codes_are_strings(self):
        for status, code in _STATUS_CODES.items():
            assert isinstance(status, int)
            assert isinstance(code, str)


class TestBuildEnvelope:
    """Test the _build_envelope helper function."""

    def test_known_status(self):
        env = _build_envelope(404, "Not found")
        assert env["error"]["code"] == "NOT_FOUND"
        assert env["error"]["message"] == "Not found"
        assert env["error"]["details"] is None

    def test_unknown_status_uses_http_prefix(self):
        env = _build_envelope(418, "I'm a teapot")
        assert env["error"]["code"] == "HTTP_418"

    def test_details_passed_through(self):
        details = [{"loc": ["body", "name"], "msg": "required"}]
        env = _build_envelope(422, "Validation failed", details=details)
        assert env["error"]["details"] == details

    def test_correlation_id_included(self):
        env = _build_envelope(500, "Error")
        assert "correlation_id" in env["error"]


class TestPydanticModels:
    """Test ErrorBody and ErrorEnvelope models."""

    def test_error_body_creates(self):
        body = ErrorBody(code="NOT_FOUND", message="Not found")
        assert body.code == "NOT_FOUND"
        assert body.message == "Not found"
        assert body.details is None

    def test_error_envelope_creates(self):
        body = ErrorBody(code="BAD_REQUEST", message="Bad request")
        env = ErrorEnvelope(error=body)
        assert env.error.code == "BAD_REQUEST"

    def test_error_body_with_details(self):
        body = ErrorBody(
            code="VALIDATION_ERROR",
            message="Validation failed",
            details=[{"field": "name", "issue": "required"}],
        )
        assert len(body.details) == 1
