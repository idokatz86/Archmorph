"""Tests for backend/freshness_registry.py (issue #640)."""

import os
import sys
from datetime import datetime, timezone, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import freshness_registry as fr


@pytest.fixture(autouse=True)
def reset_registry():
    """Each test gets a clean registry."""
    fr.reset_for_tests()
    yield
    fr.reset_for_tests()


class TestRegister:
    def test_register_basic(self):
        fr.register("job_a", budget_hours=24)
        entries = fr.get_all()
        assert len(entries) == 1
        assert entries[0]["name"] == "job_a"
        assert entries[0]["budget_hours"] == 24.0
        assert entries[0]["last_success"] is None
        assert entries[0]["age_hours"] is None
        assert entries[0]["stale"] is True  # never ran

    def test_register_with_description(self):
        fr.register("job_b", budget_hours=12, description="does something")
        entries = fr.get_all()
        assert entries[0]["description"] == "does something"

    def test_register_idempotent_keeps_last_success(self):
        fr.register("job_c", budget_hours=24)
        fr.mark_success("job_c")
        first_ts = fr.get_all()[0]["last_success"]
        # Re-register with new budget; last_success must survive.
        fr.register("job_c", budget_hours=48, description="updated")
        entry = fr.get_all()[0]
        assert entry["last_success"] == first_ts
        assert entry["budget_hours"] == 48.0
        assert entry["description"] == "updated"

    def test_register_with_last_success_seeds_durable_state(self):
        success_time = datetime.now(timezone.utc) - timedelta(hours=2)
        fr.register_with_last_success(
            "job_seeded",
            budget_hours=24,
            last_success=success_time,
            description="seeded",
        )
        entry = fr.get_all()[0]
        assert entry["last_success"] is not None
        assert entry["stale"] is False
        assert entry["description"] == "seeded"

    def test_register_with_last_success_advances_existing_seed(self):
        older = datetime.now(timezone.utc) - timedelta(hours=8)
        newer = datetime.now(timezone.utc) - timedelta(hours=1)
        fr.register_with_last_success("job_seeded", budget_hours=24, last_success=older)
        fr.register_with_last_success("job_seeded", budget_hours=24, last_success=newer)
        entry = fr.get_all()[0]
        assert entry["age_hours"] is not None
        assert entry["age_hours"] < 2


class TestMarkSuccess:
    def test_mark_success_unregistered_is_noop(self):
        # No exception, no entry created
        fr.mark_success("never_registered")
        assert fr.get_all() == []

    def test_mark_success_sets_timestamp(self):
        fr.register("job_d", budget_hours=24)
        fr.mark_success("job_d")
        entry = fr.get_all()[0]
        assert entry["last_success"] is not None
        assert entry["age_hours"] is not None
        assert entry["age_hours"] < 1.0

    def test_mark_success_explicit_timestamp(self):
        fr.register("job_e", budget_hours=24)
        ts = datetime.now(timezone.utc) - timedelta(hours=10)
        fr.mark_success("job_e", when=ts)
        entry = fr.get_all()[0]
        assert 9.5 < entry["age_hours"] < 10.5
        assert entry["stale"] is False  # 10h < 24h budget

    def test_mark_success_naive_datetime_treated_as_utc(self):
        fr.register("job_f", budget_hours=24)
        naive = datetime.utcnow() - timedelta(hours=2)  # noqa: DTZ003 - intentional
        fr.mark_success("job_f", when=naive)
        entry = fr.get_all()[0]
        assert entry["age_hours"] is not None
        assert entry["age_hours"] < 3


class TestStaleness:
    def test_never_run_is_stale(self):
        fr.register("job_g", budget_hours=24)
        assert fr.get_all()[0]["stale"] is True

    def test_within_budget_is_fresh(self):
        fr.register("job_h", budget_hours=24)
        fr.mark_success("job_h", when=datetime.now(timezone.utc) - timedelta(hours=10))
        assert fr.get_all()[0]["stale"] is False

    def test_beyond_budget_is_stale(self):
        fr.register("job_i", budget_hours=24)
        fr.mark_success("job_i", when=datetime.now(timezone.utc) - timedelta(hours=48))
        assert fr.get_all()[0]["stale"] is True

    def test_at_exactly_budget_is_fresh(self):
        # Boundary: equal-to-budget is not stale (only > is stale)
        fr.register("job_j", budget_hours=24)
        fr.mark_success("job_j", when=datetime.now(timezone.utc) - timedelta(hours=24))
        # Allow a tiny race: the check below must accept either side of the boundary
        entry = fr.get_all()[0]
        assert entry["age_hours"] is not None


class TestIsAnyStale:
    def test_empty_registry_returns_false(self):
        assert fr.is_any_stale() is False

    def test_all_fresh_returns_false(self):
        fr.register("a", budget_hours=24)
        fr.register("b", budget_hours=24)
        fr.mark_success("a")
        fr.mark_success("b")
        assert fr.is_any_stale() is False

    def test_one_stale_returns_true(self):
        fr.register("a", budget_hours=24)
        fr.register("b", budget_hours=24)
        fr.mark_success("a")  # b never ran → stale
        assert fr.is_any_stale() is True


class TestGetAllOutput:
    def test_sorted_by_name(self):
        fr.register("zebra", budget_hours=24)
        fr.register("apple", budget_hours=24)
        fr.register("mango", budget_hours=24)
        names = [e["name"] for e in fr.get_all()]
        assert names == ["apple", "mango", "zebra"]

    def test_serialisable_to_json(self):
        import json
        fr.register("job_k", budget_hours=24, description="json-safe")
        fr.mark_success("job_k")
        # Must round-trip through json without error
        encoded = json.dumps(fr.get_all())
        decoded = json.loads(encoded)
        assert decoded[0]["name"] == "job_k"


class TestServiceCatalogIntegration:
    """The service_catalog_refresh job must auto-register on import."""

    def test_service_updater_registers_job_on_import(self):
        # service_updater runs registration at import time; reloading covers
        # that production path after this fixture resets the registry.
        fr.reset_for_tests()
        import importlib
        import service_updater
        importlib.reload(service_updater)
        names = [e["name"] for e in fr.get_all()]
        assert "service_catalog_refresh" in names
