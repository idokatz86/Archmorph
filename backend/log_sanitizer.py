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

import re

_CRLF_RE = re.compile(r"[\r\n]+")


def safe(value: object) -> str:
    """Return a log-safe string with CR/LF characters removed.

    This function acts as a **taint barrier** for static analysis
    tools (CodeQL, Semgrep, Bandit).  Every untrusted value passed
    to a ``logger.*`` call should be wrapped with ``safe()``.
    """
    return _CRLF_RE.sub("", str(value))
