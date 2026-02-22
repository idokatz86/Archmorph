"""
Issue #174 — Standardized API Error Envelope

Every error response (4xx/5xx) follows a consistent shape:

    {
        "error": {
            "code": "NOT_FOUND",
            "message": "Human-readable description",
            "details": null | { ... },
            "correlation_id": "uuid"
        }
    }

This module provides:
- ``ErrorBody`` / ``ErrorEnvelope`` Pydantic models for OpenAPI docs
- FastAPI exception handlers that produce the envelope
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from logging_config import correlation_id_var

logger = logging.getLogger(__name__)

# ── HTTP status → short code mapping ────────────────────────
_STATUS_CODES: Dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
}


# ── Pydantic models (for OpenAPI schema) ────────────────────
class ErrorBody(BaseModel):
    code: str = Field(..., examples=["NOT_FOUND"])
    message: str = Field(..., examples=["Resource not found"])
    details: Any = Field(None, description="Optional structured details (validation errors, etc.)")
    correlation_id: Optional[str] = Field(None, description="Request correlation ID for tracing")


class ErrorEnvelope(BaseModel):
    error: ErrorBody


# ── Helper ──────────────────────────────────────────────────
def _build_envelope(status: int, message: str, details: Any = None) -> dict:
    return {
        "error": {
            "code": _STATUS_CODES.get(status, f"HTTP_{status}"),
            "message": message,
            "details": details,
            "correlation_id": correlation_id_var.get(""),
        }
    }


# ── Exception handlers ─────────────────────────────────────
async def _http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=_build_envelope(exc.status_code, detail),
    )


async def _validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=_build_envelope(
            422,
            "Request validation failed",
            details=exc.errors(),
        ),
    )


async def _unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content=_build_envelope(500, "Internal server error"),
    )


def register_error_handlers(app: FastAPI) -> None:
    """Wire up all error-envelope handlers on the given FastAPI app."""
    app.add_exception_handler(HTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
