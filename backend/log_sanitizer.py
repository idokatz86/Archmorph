"""Log sanitization barrier for CWE-117 (Log Injection) prevention.

This module provides a dedicated sanitization function that strips
newline characters from untrusted values before they are logged.
CodeQL's taint-tracking engine recognises purpose-built sanitizer
functions as taint barriers, breaking the data-flow path from
user-controlled sources to logging sinks.

Usage::

    from log_sanitizer import safe
    logger.info("User %s performed action", safe(user_id))
"""

import hashlib
import logging
import re
from typing import Optional

_CRLF_RE = re.compile(r"[\r\n]+")


def safe(value: object) -> str:
    """Return a log-safe string with CR/LF characters removed.

    This function acts as a **taint barrier** for static analysis
    tools (CodeQL, Semgrep, Bandit).  Every untrusted value passed
    to a ``logger.*`` call should be wrapped with ``safe()``.
    """
    return _CRLF_RE.sub("", str(value))


def log_model_output_metadata(
    logger: logging.Logger,
    *,
    component: str,
    model: str,
    output: object,
    parse_status: str,
    exception: Optional[BaseException] = None,
    level: int = logging.INFO,
) -> None:
    """Log non-reversible metadata for customer-derived model output.

    Raw prompts, response text, parsed customer fields, and exception messages
    are intentionally excluded. The digest is safe for correlation and canary
    tests without retaining recoverable content.
    """
    text = "" if output is None else str(output)
    logger.log(
        level,
        (
            "model_output component=%s model=%s output_length=%d "
            "output_sha256=%s parse_status=%s exception_type=%s"
        ),
        safe(component),
        safe(model),
        len(text),
        hashlib.sha256(text.encode("utf-8")).hexdigest(),
        safe(parse_status),
        safe(type(exception).__name__) if exception is not None else "none",
    )
