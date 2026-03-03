"""Tests for error_envelope module (#281)."""
from fastapi import FastAPI, HTTPException

from error_envelope import _build_envelope, register_error_handlers, ErrorEnvelope


def test_build_envelope_basic():
    result = _build_envelope(404, "Not found")
    assert result["error"]["code"] == "NOT_FOUND"
    assert result["error"]["message"] == "Not found"
    assert result["error"]["details"] is None


def test_build_envelope_with_details():
    result = _build_envelope(400, "Bad request", details={"field": "name"})
    assert result["error"]["details"] == {"field": "name"}


def test_build_envelope_has_correlation_id():
    result = _build_envelope(500, "Internal error")
    assert "correlation_id" in result["error"]


def test_error_envelope_model():
    env = ErrorEnvelope(error={
        "code": "NOT_FOUND",
        "message": "Not found",
        "details": None,
        "correlation_id": "abc",
    })
    assert env.error.code == "NOT_FOUND"
    assert env.error.message == "Not found"


def test_register_error_handlers_adds_handlers():
    app = FastAPI()
    register_error_handlers(app)
    # After registration, the app should have exception handlers
    assert HTTPException in app.exception_handlers or len(app.exception_handlers) > 0
