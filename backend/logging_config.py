"""Structured JSON logging configuration for Archmorph."""

import logging
import re
import sys
from contextvars import ContextVar

try:
    from pythonjsonlogger.json import JsonFormatter as _JsonFormatter
except ImportError:  # python-json-logger < 3.0
    from pythonjsonlogger.jsonlogger import JsonFormatter as _JsonFormatter

# Context var for correlation ID — accessible across async request lifecycle
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")

_SECRET_PATTERNS = (
    re.compile(r"(?i)authorization\s*[:=]\s*(?:bearer\s+)?[^\s,;]+"),
    re.compile(r"(?i)(api[_-]?key|authorization|token|password|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+\-/]+=*"),
    re.compile(r"\barch_[A-Za-z0-9]{12,}\b"),
)


def redact_log_text(value: object) -> str:
    """Remove credential-like material and line breaks from retained logs."""
    redacted = str(value).replace("\r", " ").replace("\n", " ")
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted[:4096]


class SensitiveLogFilter(logging.Filter):
    """Redact records before any configured or externally attached handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_log_text(record.getMessage())
        record.args = ()
        if isinstance(record.exc_info, tuple) and record.exc_info[0] is not None:
            record.msg = f"{record.msg} error_type={record.exc_info[0].__name__}"
            record.exc_info = None
            record.exc_text = None
        elif record.exc_info:
            record.exc_info = None
            record.exc_text = None
        record.stack_info = None
        return True


class ArchmorphJsonFormatter(_JsonFormatter):
    """JSON formatter that injects correlation_id and normalised fields."""

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["message"] = redact_log_text(
            log_record.get("message") or record.getMessage()
        )
        for key, value in tuple(log_record.items()):
            if isinstance(value, str):
                log_record[key] = redact_log_text(value)
        log_record.pop("exc_info", None)
        log_record.pop("stack_info", None)
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
    handler.addFilter(SensitiveLogFilter())
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
