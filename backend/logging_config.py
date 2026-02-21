"""Structured JSON logging configuration for Archmorph."""

import logging
import sys
from contextvars import ContextVar

try:
    from pythonjsonlogger.json import JsonFormatter as _JsonFormatter
except ImportError:  # python-json-logger < 3.0
    from pythonjsonlogger.jsonlogger import JsonFormatter as _JsonFormatter

# Context var for correlation ID — accessible across async request lifecycle
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


class ArchmorphJsonFormatter(_JsonFormatter):
    """JSON formatter that injects correlation_id and normalised fields."""

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["timestamp"] = self.formatTime(record, self.datefmt)
        log_record["level"] = record.levelname.lower()
        log_record["logger"] = record.name
        cid = correlation_id_var.get("")
        if cid:
            log_record["correlation_id"] = cid


def configure_logging(level: str = "INFO") -> None:
    """Configure all loggers to emit JSON to stdout.

    Call once at startup, before any other logging takes place.
    """
    handler = logging.StreamHandler(sys.stdout)
    formatter = ArchmorphJsonFormatter(
        fmt="%(timestamp)s %(level)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )  # type: ignore[call-arg]  # positional varies across versions
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Suppress noisy third-party loggers
    for noisy in ("httpx", "httpcore", "urllib3", "azure", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
