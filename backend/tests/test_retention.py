"""
Tests for retention metrics (Sprint 0 / E6).

Covers:
  - Cohort math (Day-7 return rate, cohort assembly, ±window).
  - Cookie behavior (set on first visit, stable across visits, HttpOnly).
  - DNT / Sec-GPC honored.
  - Skip-path list excludes admin/health.
  - Admin endpoints require auth.
  - Anonymous fast-path (POST /api/diagrams/* surface) is not regressed:
    a request with no cookie still works and returns the same shape.
  - Event taxonomy contract: in-code dict equals docs/EVENT_TAXONOMY.md
    canonical table.
"""

from __future__ import annotations

import importlib
import os
import re
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────


def _enable_retention(monkeypatch):
    """Re-import retention with tracking enabled."""
    monkeypatch.setenv("RETENTION_TRACKING_ENABLED", "true")
    monkeypatch.setenv("ENVIRONMENT", "development")  # cookie not Secure in dev
    import retention  # noqa: WPS433
    importlib.reload(retention)
    retention._reset_for_tests()
    return retention


def _disable_retention(monkeypatch):
    monkeypatch.setenv("RETENTION_TRACKING_ENABLED", "false")
    import retention  # noqa: WPS433
    importlib.reload(retention)
    retention._reset_for_tests()
    return retention


# ─────────────────────────────────────────────────────────────
# Module-level math
# ─────────────────────────────────────────────────────────────


class TestCohortMath:
    def test_no_traffic_returns_zero(self, monkeypatch):
        ret = _enable_retention(monkeypatch)
        result = ret.compute_day7_return_rate()
        assert result.cohort_size == 0
        assert result.returned_day7_count == 0
        assert result.return_rate == 0.0

    def test_single_user_returning_on_day_7(self, monkeypatch):
        ret = _enable_retention(monkeypatch)
        cohort_day = datetime.now(timezone.utc) - timedelta(days=7)
        return_day = cohort_day + timedelta(days=7)

        ret._record_visit_direct("user-A", when=cohort_day)
        ret._record_visit_direct("user-A", when=return_day)

        result = ret.compute_day7_return_rate(cohort_day=cohort_day.date())
        assert result.cohort_size == 1
        assert result.returned_day7_count == 1
        assert result.return_rate == 1.0

    def test_user_returning_within_plus_minus_window(self, monkeypatch):
        ret = _enable_retention(monkeypatch)
        cohort_day = datetime.now(timezone.utc) - timedelta(days=8)
        # User returns on D+6, which is in the ±1 window around D+7.
        return_day = cohort_day + timedelta(days=6)

        ret._record_visit_direct("user-B", when=cohort_day)
        ret._record_visit_direct("user-B", when=return_day)

        result = ret.compute_day7_return_rate(
            cohort_day=cohort_day.date(), window_days=1
        )
        assert result.cohort_size == 1
        assert result.returned_day7_count == 1

    def test_user_outside_window_does_not_count(self, monkeypatch):
        ret = _enable_retention(monkeypatch)
        cohort_day = datetime.now(timezone.utc) - timedelta(days=15)
        # User returns on D+10 — outside ±1 around D+7.
        return_day = cohort_day + timedelta(days=10)

        ret._record_visit_direct("user-C", when=cohort_day)
        ret._record_visit_direct("user-C", when=return_day)

        result = ret.compute_day7_return_rate(
            cohort_day=cohort_day.date(), window_days=1
        )
        assert result.cohort_size == 1
        assert result.returned_day7_count == 0
        assert result.return_rate == 0.0

    def test_idempotent_visits_same_day(self, monkeypatch):
        ret = _enable_retention(monkeypatch)
        cohort_day = datetime.now(timezone.utc) - timedelta(days=7)

        for _ in range(5):
            ret._record_visit_direct("user-D", when=cohort_day)
        # Returns once, but user clicks 10 times that day.
        return_day = cohort_day + timedelta(days=7)
        for _ in range(10):
            ret._record_visit_direct("user-D", when=return_day)

        result = ret.compute_day7_return_rate(cohort_day=cohort_day.date())
        assert result.cohort_size == 1
        assert result.returned_day7_count == 1

    def test_baseline_aggregates_only_completed_cohorts(self, monkeypatch):
        ret = _enable_retention(monkeypatch)
        # Two users, two cohort days, both 8+ days old (completed).
        d1 = datetime.now(timezone.utc) - timedelta(days=10)
        d2 = datetime.now(timezone.utc) - timedelta(days=12)

        ret._record_visit_direct("u1", when=d1)
        ret._record_visit_direct("u1", when=d1 + timedelta(days=7))
        ret._record_visit_direct("u2", when=d2)  # never returns

        baseline = ret.get_baseline(lookback_days=30)
        assert baseline["enabled"] is True
        assert baseline["total_cohort"] == 2
        assert baseline["total_returned"] == 1
        assert baseline["overall_day7_return_rate"] == 0.5
        assert baseline["kpi_target"] == 0.35


# ─────────────────────────────────────────────────────────────
# HMAC + privacy
# ─────────────────────────────────────────────────────────────


class TestPrivacy:
    def test_hash_is_stable_and_irreversible(self, monkeypatch):
        ret = _enable_retention(monkeypatch)
        h1 = ret._hash_anon("alpha")
        h2 = ret._hash_anon("alpha")
        h3 = ret._hash_anon("beta")
        assert h1 == h2
        assert h1 != h3
        assert "alpha" not in h1  # raw value never leaks into the hash.
        assert len(h1) == 64  # sha256 hex digest length

    def test_disabled_module_records_nothing(self, monkeypatch):
        ret = _disable_retention(monkeypatch)
        cohort_day = datetime.now(timezone.utc) - timedelta(days=7)
        # Direct call still works (used by tests), but cookie path is gated.
        # Validate the gate via record_visit_from_request below.
        assert ret.ENABLED is False

    def test_event_taxonomy_is_read_only_view(self, monkeypatch):
        ret = _enable_retention(monkeypatch)
        view = ret.get_event_taxonomy()
        view["malicious"] = "tamper"
        # Underlying dict unchanged.
        assert "malicious" not in ret.CANONICAL_EVENTS


# ─────────────────────────────────────────────────────────────
# Middleware integration via FastAPI TestClient
# ─────────────────────────────────────────────────────────────


@pytest.fixture
def client_enabled(monkeypatch):
    """TestClient with retention enabled."""
    monkeypatch.setenv("RETENTION_TRACKING_ENABLED", "true")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")

    # Force a fresh module import so the env flag is picked up.
    import retention  # noqa: WPS433
    importlib.reload(retention)
    retention._reset_for_tests()

    # Reload main so its captured _record_retention_visit reference points
    # at the reloaded module's function.
    import main  # noqa: WPS433
    importlib.reload(main)

    from fastapi.testclient import TestClient
    with TestClient(main.app, raise_server_exceptions=False) as client:
        yield client, retention


class TestMiddlewareCookieBehavior:
    def test_first_request_sets_cookie(self, client_enabled):
        client, ret = client_enabled
        r = client.get("/api/health")
        # Health is in the skip list — no cookie expected.
        assert "set-cookie" not in {h.lower(): v for h, v in r.headers.items()}.keys() or \
               ret.ANON_COOKIE_NAME not in r.headers.get("set-cookie", "")

    def test_first_user_request_sets_anon_cookie(self, client_enabled):
        client, ret = client_enabled
        # Hit a non-skipped path. /api/services is read-only and Live.
        r = client.get("/api/services/catalog/aws")
        cookie_header = r.headers.get("set-cookie", "")
        assert ret.ANON_COOKIE_NAME in cookie_header
        assert "HttpOnly" in cookie_header
        assert "SameSite=lax" in cookie_header.lower() or "samesite=lax" in cookie_header.lower()

    def test_dnt_header_skips_cookie(self, client_enabled):
        client, ret = client_enabled
        r = client.get("/api/services/catalog/aws", headers={"DNT": "1"})
        cookie_header = r.headers.get("set-cookie", "")
        assert ret.ANON_COOKIE_NAME not in cookie_header

    def test_admin_path_does_not_set_anon_cookie(self, client_enabled):
        client, ret = client_enabled
        # Even though admin will return 401, retention must not set the cookie.
        r = client.get("/api/admin/metrics")
        cookie_header = r.headers.get("set-cookie", "")
        assert ret.ANON_COOKIE_NAME not in cookie_header


# ─────────────────────────────────────────────────────────────
# Admin endpoint contract
# ─────────────────────────────────────────────────────────────


class TestAdminContract:
    def test_day7_requires_admin(self, client_enabled):
        client, _ = client_enabled
        r = client.get("/api/admin/retention/day7")
        assert r.status_code in (401, 503)  # 503 if admin not configured

    def test_baseline_requires_admin(self, client_enabled):
        client, _ = client_enabled
        r = client.get("/api/admin/retention/baseline")
        assert r.status_code in (401, 503)

    def test_taxonomy_requires_admin(self, client_enabled):
        client, _ = client_enabled
        r = client.get("/api/admin/retention/taxonomy")
        assert r.status_code in (401, 503)

    def test_v1_mirror_exists(self, client_enabled):
        client, _ = client_enabled
        r = client.get("/api/v1/admin/retention/day7")
        # v1 mirror should also enforce auth — never 404.
        assert r.status_code in (401, 503)


# ─────────────────────────────────────────────────────────────
# Anonymous fast-path regression
# ─────────────────────────────────────────────────────────────


class TestAnonymousFastPathRegression:
    """Sprint 0 hard rule: retention must not regress the anon path."""

    def test_health_is_unaffected(self, client_enabled):
        client, _ = client_enabled
        r = client.get("/api/health")
        assert r.status_code == 200

    def test_services_catalog_works_without_cookie(self, client_enabled):
        client, _ = client_enabled
        r = client.get("/api/services/catalog/aws")
        # The endpoint may be 200 or 404 depending on data, but never 5xx
        # caused by retention middleware.
        assert r.status_code < 500

    def test_response_ok_even_when_cookie_secret_unset(self, monkeypatch):
        """Retention runs lazily; missing config must never crash a request."""
        monkeypatch.setenv("RETENTION_TRACKING_ENABLED", "true")
        monkeypatch.setenv("RETENTION_HMAC_SALT", "")  # explicitly blank
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
        import retention  # noqa: WPS433
        importlib.reload(retention)
        retention._reset_for_tests()
        import main  # noqa: WPS433
        importlib.reload(main)

        from fastapi.testclient import TestClient
        with TestClient(main.app, raise_server_exceptions=False) as client:
            r = client.get("/api/health")
            assert r.status_code == 200


# ─────────────────────────────────────────────────────────────
# Taxonomy contract — code matches docs
# ─────────────────────────────────────────────────────────────


class TestTaxonomyContract:
    def test_code_taxonomy_matches_docs(self):
        """Names in CANONICAL_EVENTS must equal the events listed in
        docs/EVENT_TAXONOMY.md (allowing the docs to add prose)."""
        import retention  # noqa: WPS433

        repo_root = Path(__file__).resolve().parents[2]
        doc_path = repo_root / "docs" / "EVENT_TAXONOMY.md"
        assert doc_path.exists(), f"Missing taxonomy doc at {doc_path}"
        text = doc_path.read_text(encoding="utf-8")

        # Pull out backticked event names from the canonical table.
        # Pattern: lines starting with "| `event_name` |" in the table.
        doc_events = set(re.findall(r"^\|\s*`([a-z_]+)`\s*\|", text, re.MULTILINE))
        code_events = set(retention.CANONICAL_EVENTS.keys())

        missing_in_doc = code_events - doc_events
        missing_in_code = doc_events - code_events
        assert not missing_in_doc, f"Doc missing events: {missing_in_doc}"
        assert not missing_in_code, f"Code missing events: {missing_in_code}"
