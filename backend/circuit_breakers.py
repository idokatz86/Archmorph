"""
Circuit breakers for external dependencies (#506).

Wraps PostgreSQL, Redis, Azure Blob Storage, and webhook calls
with pybreaker circuit breakers to prevent cascade failures.

Each breaker trips after `fail_max` consecutive failures and stays
open for `reset_timeout` seconds before trying again (half-open).

The /api/health endpoint can query breaker states for readiness probes.
"""

import logging
import os
from typing import Any, Dict

import pybreaker

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────

FAIL_MAX = int(os.getenv("CIRCUIT_BREAKER_FAIL_MAX", "5"))
RESET_TIMEOUT = int(os.getenv("CIRCUIT_BREAKER_RESET_TIMEOUT", "30"))


class _BreakerListener(pybreaker.CircuitBreakerListener):
    """Log circuit breaker state changes."""

    def state_change(self, cb, old_state, new_state):
        logger.warning(
            "Circuit breaker '%s' state change: %s -> %s",
            cb.name,
            old_state.name,
            new_state.name,
        )

    def failure(self, cb, exc):
        logger.debug("Circuit breaker '%s' recorded failure: %s", cb.name, exc)


_listener = _BreakerListener()

# ── Breakers ──────────────────────────────────────────────────

db_breaker = pybreaker.CircuitBreaker(
    name="postgresql",
    fail_max=FAIL_MAX,
    reset_timeout=RESET_TIMEOUT,
    listeners=[_listener],
)

redis_breaker = pybreaker.CircuitBreaker(
    name="redis",
    fail_max=FAIL_MAX,
    reset_timeout=RESET_TIMEOUT,
    listeners=[_listener],
)

blob_breaker = pybreaker.CircuitBreaker(
    name="azure_blob",
    fail_max=FAIL_MAX,
    reset_timeout=RESET_TIMEOUT,
    listeners=[_listener],
)

webhook_breaker = pybreaker.CircuitBreaker(
    name="webhooks",
    fail_max=FAIL_MAX,
    reset_timeout=RESET_TIMEOUT,
    listeners=[_listener],
)


# ── Health Status ─────────────────────────────────────────────

ALL_BREAKERS = {
    "postgresql": db_breaker,
    "redis": redis_breaker,
    "azure_blob": blob_breaker,
    "webhooks": webhook_breaker,
}


def get_breaker_status() -> Dict[str, Any]:
    """Return the state of all circuit breakers for the health endpoint."""
    status = {}
    for name, breaker in ALL_BREAKERS.items():
        status[name] = {
            "state": breaker.current_state,
            "fail_count": breaker.fail_counter,
            "fail_max": breaker.fail_max,
            "reset_timeout": breaker.reset_timeout,
        }
    return status


def is_healthy() -> bool:
    """Return True if no critical breakers are open."""
    critical = ["postgresql"]  # Only DB being open means unhealthy
    return all(
        ALL_BREAKERS[name].current_state != "open"
        for name in critical
    )
