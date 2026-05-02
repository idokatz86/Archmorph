"""Freshness registry for scheduled jobs (issue #640).

Generalises the lesson from issue #571 (silent service-catalog refresh failure
for 46 days): every scheduled / periodic job in the codebase must publish a
freshness signal so silent breakage is automatically detected.

Usage:

    from freshness_registry import register, mark_success

    # On module import:
    register("service_catalog_refresh", budget_hours=36)

    # Inside the job, on successful completion:
    mark_success("service_catalog_refresh")

The registry exposes `get_all()` which the /api/health endpoint surfaces and
which the GitHub Actions watchdog workflow polls every 4 hours. Any job whose
last success exceeded its budget marks the system ``degraded`` and triggers
an automated alert issue.

Design notes:
  - State is held in-process; this is intentionally not durable. The watchdog
    polls /api/health which reads in-memory state, so a container restart
    "loses" history but `mark_success` runs on the next invocation. For jobs
    that need durable state (e.g. service_catalog_refresh) the underlying
    persistence layer (e.g. service_updates.json) is the source of truth.
  - Thread-safe via a module-level Lock.
  - Zero external dependencies (datetime + threading only).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class _Registration:
    """A single scheduled-job registration."""
    name: str
    budget_hours: float
    last_success: Optional[datetime] = None
    description: str = ""


_lock = threading.Lock()
_registry: dict[str, _Registration] = {}


def register(name: str, *, budget_hours: float, description: str = "") -> None:
    """Register a scheduled job with a freshness budget.

    Idempotent: registering the same name twice keeps the existing
    ``last_success`` (so a hot-reload doesn't reset history).

    Args:
        name: Stable identifier (e.g. ``"service_catalog_refresh"``).
        budget_hours: Maximum acceptable time between successful runs. A job
            stale beyond this marks the system ``degraded`` on /api/health.
        description: Optional human-readable description of what the job does.
    """
    with _lock:
        if name not in _registry:
            _registry[name] = _Registration(
                name=name,
                budget_hours=float(budget_hours),
                description=description,
            )
        else:
            # Allow updating the budget / description, keep last_success.
            existing = _registry[name]
            _registry[name] = _Registration(
                name=name,
                budget_hours=float(budget_hours),
                last_success=existing.last_success,
                description=description or existing.description,
            )


def mark_success(name: str, *, when: Optional[datetime] = None) -> None:
    """Record a successful run of a registered job.

    Calling ``mark_success`` for an unregistered job is a no-op (intentional
    so test isolation that bypasses the register() call doesn't crash). The
    call is logged at debug level.

    Args:
        name: The registered job name.
        when: Optional explicit timestamp; defaults to ``datetime.now(timezone.utc)``.
    """
    ts = when or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    with _lock:
        if name in _registry:
            _registry[name].last_success = ts


def get_all() -> list[dict]:
    """Return a serialisable snapshot of every registered job.

    Each entry contains:
        - ``name``: registration name
        - ``budget_hours``: configured budget
        - ``last_success``: ISO-8601 timestamp or ``None``
        - ``age_hours``: time since last success or ``None``
        - ``stale``: ``True`` when older than the budget OR never ran
        - ``description``: optional description
    """
    now = datetime.now(timezone.utc)
    out: list[dict] = []
    with _lock:
        for reg in _registry.values():
            age_hours: Optional[float]
            stale: bool
            if reg.last_success is None:
                age_hours = None
                stale = True
            else:
                age_hours = round(
                    (now - reg.last_success).total_seconds() / 3600, 2
                )
                stale = age_hours > reg.budget_hours
            out.append({
                "name": reg.name,
                "budget_hours": reg.budget_hours,
                "last_success": reg.last_success.isoformat() if reg.last_success else None,
                "age_hours": age_hours,
                "stale": stale,
                "description": reg.description,
            })
    # Stable sort by name for deterministic /api/health output.
    out.sort(key=lambda e: e["name"])
    return out


def is_any_stale() -> bool:
    """True when at least one registered job is stale or never ran."""
    return any(entry["stale"] for entry in get_all())


def reset_for_tests() -> None:
    """Clear the registry. Test-only helper."""
    with _lock:
        _registry.clear()
