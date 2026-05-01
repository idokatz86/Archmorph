"""
Archmorph Retention Metrics — Sprint 0 (Retention Initiative E6).

Day-7 first-time-user return rate: did a user who first visited the app
on day D-7 come back within the [D-7, D-7±1] window?

Design constraints (CTO directive + CISO sign-off):
  - Anonymous fast path is preserved.  No login required to be counted.
  - Anon identifier = server-issued random UUID stored in an HttpOnly
    cookie.  Server only ever stores the HMAC-SHA256(salt, value) hash.
  - No PII is recorded.  No IP, no UA, no email, no headers.
  - Disabled by default.  Set ``RETENTION_TRACKING_ENABLED=true`` to opt in
    once the CISO sign-off lands (Sprint 0 day 5).
  - Storage reuses ``session_store.get_store`` so behavior matches the
    rest of the platform (Redis in prod, in-memory in dev).
  - All output is aggregate; no per-user reporting endpoint.

Cohort math:
  cohort(D) = set of anon_id_hashes whose first_seen is on day D.
  returned_d7(D) = subset of cohort(D) that recorded a visit on D+7 ± 1 day.
  day7_return_rate(D) = |returned_d7(D)| / |cohort(D)|.

Public surface:
  - ``record_visit_from_request(request, response)`` — middleware-friendly.
  - ``compute_day7_return_rate(end_date, lookback_days=14)`` — admin-only.
  - ``get_baseline()`` — rolling baseline view for the admin tile.
  - ``get_event_taxonomy()`` — returns the canonical event names for
    contract tests; mirrors ``docs/EVENT_TAXONOMY.md``.

Issue: Sprint 0 / Retention Initiative E6.
"""

from __future__ import annotations

import hmac
import hashlib
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta, date
from typing import Any, Dict, List, Optional

from session_store import get_store

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

# Feature flag: production OFF until CISO sign-off + privacy notice update.
ENABLED = os.getenv("RETENTION_TRACKING_ENABLED", "false").lower() == "true"

# Cookie name — first-party only, no cross-site tracking.
ANON_COOKIE_NAME = os.getenv("RETENTION_COOKIE_NAME", "archmorph_anon")

# Cookie lifetime — 365 days.  Aligned with PostHog default and standard
# first-party analytics retention.
ANON_COOKIE_TTL_SECONDS = int(os.getenv("RETENTION_COOKIE_TTL", str(365 * 24 * 3600)))

# HMAC salt — never serialize, never log.  Rotate by setting RETENTION_HMAC_SALT.
# When rotated, all existing anon_ids effectively become new — acceptable.
_HMAC_SALT = os.getenv("RETENTION_HMAC_SALT") or secrets.token_urlsafe(32)

# Storage TTL — 60 days.  Long enough to compute Day-7 across a 30-day window
# with a buffer.  Short enough to limit data retention.
_STORAGE_TTL_SECONDS = int(os.getenv("RETENTION_STORAGE_TTL", str(60 * 24 * 3600)))

# Path-prefix skip list — health, admin, static, and anything that should not
# count as a "user visit" for the retention metric.
_SKIP_PATHS_PREFIX = (
    "/health",
    "/api/health",
    "/api/admin/",
    "/api/v1/admin/",
    "/api/legal/",
    "/api/v1/legal/",
    "/api/privacy/",
    "/api/v1/privacy/",
    "/openapi.json",
    "/docs",
    "/redoc",
    "/favicon.ico",
)

# Stores — one per concern.  Both Redis-backed when REDIS_URL is set.
_visits_store = get_store("retention_visits", maxsize=200_000, ttl=_STORAGE_TTL_SECONDS)
_first_seen_store = get_store("retention_first_seen", maxsize=200_000, ttl=_STORAGE_TTL_SECONDS)
_cohort_index_store = get_store("retention_cohort_index", maxsize=400, ttl=_STORAGE_TTL_SECONDS)
_visit_index_store = get_store("retention_visit_index", maxsize=400, ttl=_STORAGE_TTL_SECONDS)


# ─────────────────────────────────────────────────────────────
# Event taxonomy (PM artifact, mirrored in docs/EVENT_TAXONOMY.md)
# ─────────────────────────────────────────────────────────────

CANONICAL_EVENTS: Dict[str, str] = {
    "page_view": "User loaded any page in the SPA.",
    "upload_started": "User initiated a diagram upload.",
    "analysis_complete": "Vision analysis finished and mappings rendered.",
    "questions_answered": "User completed the guided migration questions.",
    "iac_generated": "IaC generation finished and artifact is available.",
    "export_completed": "User downloaded an artifact (IaC, HLD, report).",
    "account_claimed": "Anonymous user claimed an account via magic-link.",
    "project_returned": "User returned to a previously-created project.",
}


def get_event_taxonomy() -> Dict[str, str]:
    """Return the canonical event taxonomy (read-only view)."""
    return dict(CANONICAL_EVENTS)


# ─────────────────────────────────────────────────────────────
# Anon identifier helpers
# ─────────────────────────────────────────────────────────────


def _new_anon_value() -> str:
    """Generate a fresh anon cookie value (>=128 bits of entropy)."""
    return secrets.token_urlsafe(24)  # 24 bytes ≈ 192 bits.


def _hash_anon(anon_value: str) -> str:
    """HMAC-SHA256 the cookie value with the server salt.  Never reverse."""
    if not anon_value:
        return ""
    digest = hmac.new(
        _HMAC_SALT.encode("utf-8"),
        anon_value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _iso_day(d: date) -> str:
    return d.isoformat()


# ─────────────────────────────────────────────────────────────
# Recording
# ─────────────────────────────────────────────────────────────


def _should_skip_path(path: str) -> bool:
    return any(path.startswith(p) for p in _SKIP_PATHS_PREFIX)


def _append_to_index(store, key: str, value: str, cap: int = 100_000) -> None:
    """Append a value to a list-backed key in a session store."""
    existing = store.get(key)
    if existing is None:
        store.set(key, [value])
        return
    if not isinstance(existing, list):
        # Defensive: never overwrite non-list state silently.
        logger.warning("retention index %s holds non-list; resetting", key)
        store.set(key, [value])
        return
    if value in existing:
        return  # idempotent — anon already counted this day.
    existing.append(value)
    if len(existing) > cap:
        existing = existing[-cap:]
    store.set(key, existing)


def _record_visit_for_hash(anon_hash: str, when: Optional[datetime] = None) -> Dict[str, Any]:
    """Record a visit for an already-hashed anon identifier.  Internal."""
    if not anon_hash:
        return {"recorded": False, "reason": "empty_hash"}

    moment = when or datetime.now(timezone.utc)
    day = moment.date()
    day_iso = _iso_day(day)

    first_seen_iso = _first_seen_store.get(anon_hash)
    is_new = first_seen_iso is None
    if is_new:
        first_seen_iso = day_iso
        _first_seen_store.set(anon_hash, first_seen_iso)
        _append_to_index(_cohort_index_store, day_iso, anon_hash)

    # Always log the visit-day index — used to compute return.
    _append_to_index(_visit_index_store, day_iso, anon_hash)

    # Per-user visit-day list (for opt-out / debugging only; never exposed).
    visit_days = _visits_store.get(anon_hash) or []
    if day_iso not in visit_days:
        visit_days.append(day_iso)
        if len(visit_days) > 90:
            visit_days = visit_days[-90:]
        _visits_store.set(anon_hash, visit_days)

    return {
        "recorded": True,
        "is_new_user": is_new,
        "first_seen": first_seen_iso,
        "visit_day": day_iso,
    }


def record_visit_from_request(request, response) -> Dict[str, Any]:
    """Middleware hook: read or set the anon cookie, record a visit.

    Safe to call on every request.  Honors ``RETENTION_TRACKING_ENABLED``.
    Never raises.  Never logs the cookie value or its hash.
    """
    if not ENABLED:
        return {"recorded": False, "reason": "disabled"}

    try:
        path = request.url.path
        if _should_skip_path(path):
            return {"recorded": False, "reason": "skipped_path"}

        # Honor Do-Not-Track / Global Privacy Control independently — both must
        # be respected even if the other is unset or set to "0".
        if request.headers.get("DNT") == "1" or request.headers.get("Sec-GPC") == "1":
            return {"recorded": False, "reason": "dnt"}

        anon_value = request.cookies.get(ANON_COOKIE_NAME)
        is_first_request = anon_value is None
        if is_first_request:
            anon_value = _new_anon_value()
            response.set_cookie(
                key=ANON_COOKIE_NAME,
                value=anon_value,
                max_age=ANON_COOKIE_TTL_SECONDS,
                httponly=True,
                secure=os.getenv("ENVIRONMENT", "development").lower()
                in ("production", "prod", "staging"),
                samesite="lax",
                path="/",
            )

        anon_hash = _hash_anon(anon_value)
        result = _record_visit_for_hash(anon_hash)
        result["cookie_set"] = is_first_request
        return result
    except Exception as exc:  # nosec B110 — analytics must never break a request.
        logger.debug("retention recording skipped: %s", exc)
        return {"recorded": False, "reason": "error"}


# ─────────────────────────────────────────────────────────────
# Aggregations
# ─────────────────────────────────────────────────────────────


@dataclass
class CohortResult:
    cohort_day: str
    cohort_size: int
    returned_day7_count: int
    return_rate: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cohort_day": self.cohort_day,
            "cohort_size": self.cohort_size,
            "returned_day7_count": self.returned_day7_count,
            "return_rate": round(self.return_rate, 4),
        }


def _visits_on_day(day_iso: str) -> set:
    raw = _visit_index_store.get(day_iso) or []
    return set(raw)


def _cohort_on_day(day_iso: str) -> List[str]:
    return _cohort_index_store.get(day_iso) or []


def compute_day7_return_rate(
    cohort_day: Optional[date] = None,
    window_days: int = 1,
) -> CohortResult:
    """Return the Day-7 return rate for a single cohort day.

    ``window_days`` = ±N days around D+7 (default 1, i.e. days 6/7/8).
    """
    if cohort_day is None:
        cohort_day = _today_utc() - timedelta(days=7)

    cohort_iso = _iso_day(cohort_day)
    cohort = _cohort_on_day(cohort_iso)
    if not cohort:
        return CohortResult(cohort_iso, 0, 0, 0.0)

    target = cohort_day + timedelta(days=7)
    visit_set: set = set()
    for offset in range(-window_days, window_days + 1):
        visit_set |= _visits_on_day(_iso_day(target + timedelta(days=offset)))

    cohort_set = set(cohort)
    returned = cohort_set & visit_set
    rate = (len(returned) / len(cohort_set)) if cohort_set else 0.0
    return CohortResult(cohort_iso, len(cohort_set), len(returned), rate)


def get_baseline(lookback_days: int = 30) -> Dict[str, Any]:
    """Aggregate Day-7 metrics across the last N completed cohorts.

    A cohort is "completed" if the day is at least 7 days old.
    """
    today = _today_utc()
    last_completed_cohort = today - timedelta(days=8)
    rows: List[Dict[str, Any]] = []

    total_cohort = 0
    total_returned = 0

    for offset in range(lookback_days):
        d = last_completed_cohort - timedelta(days=offset)
        result = compute_day7_return_rate(cohort_day=d)
        rows.append(result.to_dict())
        total_cohort += result.cohort_size
        total_returned += result.returned_day7_count

    overall_rate = (total_returned / total_cohort) if total_cohort > 0 else 0.0
    rows.sort(key=lambda r: r["cohort_day"])

    return {
        "enabled": ENABLED,
        "window_days": lookback_days,
        "total_cohort": total_cohort,
        "total_returned": total_returned,
        "overall_day7_return_rate": round(overall_rate, 4),
        "trend": rows,
        "kpi_target": 0.35,
    }


# ─────────────────────────────────────────────────────────────
# Test/admin helpers (NOT exposed via HTTP)
# ─────────────────────────────────────────────────────────────


def _reset_for_tests() -> None:
    """Clear all retention state — pytest only."""
    _visits_store.clear()
    _first_seen_store.clear()
    _cohort_index_store.clear()
    _visit_index_store.clear()


def _record_visit_direct(anon_value: str, when: Optional[datetime] = None) -> Dict[str, Any]:
    """Test seam: bypass cookie/middleware, record by raw anon value."""
    return _record_visit_for_hash(_hash_anon(anon_value), when=when)
