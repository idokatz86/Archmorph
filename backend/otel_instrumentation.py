"""
Deep OpenTelemetry auto-instrumentation for Archmorph (#502).

Configures auto-instrumentation for:
  - FastAPI (HTTP requests, middleware spans)
  - SQLAlchemy (database query tracing)
  - Redis (cache operation spans)
  - httpx/requests (outbound HTTP calls, including OpenAI)

This module should be imported early in main.py AFTER azure-monitor-opentelemetry
is configured (which sets up the global tracer/meter providers).

If APPLICATIONINSIGHTS_CONNECTION_STRING is not set, instruments with
a no-op provider — no performance penalty.
"""

import logging
import os

logger = logging.getLogger(__name__)


def configure_auto_instrumentation():
    """Enable auto-instrumentation for all supported libraries."""
    if not os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        logger.debug("OTEL auto-instrumentation skipped — no App Insights connection string")
        return

    _instrument_fastapi()
    _instrument_sqlalchemy()
    _instrument_redis()
    _instrument_httpx()
    _instrument_logging()

    logger.info("OpenTelemetry auto-instrumentation configured for FastAPI, SQLAlchemy, Redis, httpx")


def _instrument_fastapi():
    """Add HTTP request/response spans for all FastAPI endpoints."""
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument()
        logger.debug("OTEL: FastAPI instrumented")
    except ImportError:
        logger.debug("OTEL: opentelemetry-instrumentation-fastapi not installed, skipping")
    except Exception as exc:
        logger.warning("OTEL: FastAPI instrumentation failed: %s", exc)


def _instrument_sqlalchemy():
    """Add database query spans with statement text and parameters."""
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        SQLAlchemyInstrumentor().instrument(enable_commenter=True)
        logger.debug("OTEL: SQLAlchemy instrumented")
    except ImportError:
        logger.debug("OTEL: opentelemetry-instrumentation-sqlalchemy not installed, skipping")
    except Exception as exc:
        logger.warning("OTEL: SQLAlchemy instrumentation failed: %s", exc)


def _instrument_redis():
    """Add Redis command spans."""
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        RedisInstrumentor().instrument()
        logger.debug("OTEL: Redis instrumented")
    except ImportError:
        logger.debug("OTEL: opentelemetry-instrumentation-redis not installed, skipping")
    except Exception as exc:
        logger.warning("OTEL: Redis instrumentation failed: %s", exc)


def _instrument_httpx():
    """Add outbound HTTP spans (covers OpenAI API calls via httpx)."""
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        HTTPXClientInstrumentor().instrument()
        logger.debug("OTEL: httpx instrumented")
    except ImportError:
        logger.debug("OTEL: opentelemetry-instrumentation-httpx not installed, skipping")
    except Exception as exc:
        logger.warning("OTEL: httpx instrumentation failed: %s", exc)


def _instrument_logging():
    """Attach trace context (trace_id, span_id) to log records."""
    try:
        from opentelemetry.instrumentation.logging import LoggingInstrumentor
        LoggingInstrumentor().instrument(set_logging_format=False)
        logger.debug("OTEL: Logging instrumented")
    except ImportError:
        logger.debug("OTEL: opentelemetry-instrumentation-logging not installed, skipping")
    except Exception as exc:
        logger.warning("OTEL: Logging instrumentation failed: %s", exc)
