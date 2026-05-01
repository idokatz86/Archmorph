"""
#587 — Icon registry lazy-load regression tests.

The CTO E2E review on 2026-05-01 measured a 100% icon-miss rate on the
`landing-zone-svg` pipeline because `_load_from_disk()` and
`load_builtin_packs()` ran only from the FastAPI startup hook. Any
cold-import context (CLI scripts, tests, isolated workers, the SVG
generator imported before the app spins up) saw `_ICON_STORE = {}` and
`resolve_icon()` returned `None` for every service.

The fix in `icons.registry` adds `_ensure_loaded()` — an idempotent,
thread-safe lazy-bootstrap gate that fires on first lookup and is reset
by `clear_all()`. These tests guard that contract so a future refactor
can't silently regress D1.

Tests in this file run with `ICON_REGISTRY_AUTOLOAD=1` (the production
default) — the unit-test suite in `test_icon_registry.py` runs with
autoload disabled to keep fixture-driven tests deterministic.
"""

from __future__ import annotations

import importlib
import os
import sys
import threading
from pathlib import Path

import pytest

# Ensure backend is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# NOTE: do NOT mutate `os.environ` at module level — xdist runs test files in
# the same worker process, and a top-level `os.environ[...] = "1"` would
# permanently overwrite the `=0` that `test_icon_registry.py` sets to keep
# its fixture-driven tests deterministic. Each test below uses
# `monkeypatch.setenv` so its env mutations are scoped to the test.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")


@pytest.fixture
def fresh_registry(monkeypatch, tmp_path):
    """Reload `icons.registry` so each test sees a pristine module-level state.

    Equivalent to a cold process import without the cost of spawning a
    subprocess. We:
      - force production-default autoload behaviour
      - point `ICON_REGISTRY_DATA_DIR` at a tmpdir so a stale disk snapshot
        from a prior test run can't hide a regression by satisfying the
        lazy-load with 1 unrelated icon
      - drop the cached registry module so the env-vars take effect
    """
    monkeypatch.setenv("ICON_REGISTRY_AUTOLOAD", "1")
    monkeypatch.setenv("ICON_REGISTRY_DATA_DIR", str(tmp_path))
    # Drop any cached registry module + the LZ generator (which holds its own
    # `_ICON_CACHE` populated from a registry import).
    for mod in ("icons.registry", "icons", "azure_landing_zone"):
        sys.modules.pop(mod, None)
    from icons import registry as fresh
    yield fresh
    # Cleanup: clear so we don't leak ingested packs into subsequent tests.
    fresh.clear_all()


def test_cold_import_resolve_icon_lazy_loads(fresh_registry):
    """First `resolve_icon` call after cold import populates the store (#587)."""
    registry = fresh_registry
    assert registry._LOAD_ATTEMPTED is False
    assert len(registry._ICON_STORE) == 0

    icon = registry.resolve_icon("AKS", provider="azure")

    assert registry._LOAD_ATTEMPTED is True, "lazy-load gate must flip"
    assert len(registry._ICON_STORE) > 0, "store must populate from disk or builtin packs"
    assert icon is not None, "AKS lookup must hit a real icon, not return None"
    assert icon.svg, "resolved icon must carry SVG content"


def test_cold_import_get_icon_lazy_loads(fresh_registry):
    """`get_icon` is also a lookup path and must trigger lazy-load."""
    registry = fresh_registry
    # Use a canonical id from the disk snapshot if it exists; otherwise
    # this test simply verifies the gate flips on the call.
    assert registry._LOAD_ATTEMPTED is False
    registry.get_icon("does-not-exist")
    assert registry._LOAD_ATTEMPTED is True


def test_cold_import_search_icons_lazy_loads(fresh_registry):
    """`search_icons` must trigger lazy-load and return non-empty for azure."""
    registry = fresh_registry
    results = registry.search_icons(provider="azure")
    assert registry._LOAD_ATTEMPTED is True
    assert len(results) > 0, "search must surface bootstrapped icons"


def test_cold_import_list_packs_lazy_loads(fresh_registry):
    """`list_packs` must trigger lazy-load."""
    registry = fresh_registry
    packs = registry.list_packs()
    assert registry._LOAD_ATTEMPTED is True
    assert isinstance(packs, list)


def test_lazy_load_is_idempotent(fresh_registry):
    """Multiple lookups must not reload — the gate flips exactly once."""
    registry = fresh_registry

    call_counts = {"disk": 0, "builtin": 0}
    real_disk = registry._load_from_disk
    real_builtin = registry.load_builtin_packs

    def counting_disk() -> bool:
        call_counts["disk"] += 1
        return real_disk()

    def counting_builtin() -> int:
        call_counts["builtin"] += 1
        return real_builtin()

    registry._load_from_disk = counting_disk  # type: ignore[assignment]
    registry.load_builtin_packs = counting_builtin  # type: ignore[assignment]
    try:
        for service in ("AKS", "Key Vault", "App Service", "Azure SQL"):
            registry.resolve_icon(service, provider="azure")
        # Bootstrap path runs at most once total: either disk-load succeeded
        # (1×disk, 0×builtin) or it returned False and we fell through to
        # builtin (1×disk, 1×builtin). Subsequent lookups must not retry.
        total = call_counts["disk"] + call_counts["builtin"]
        assert call_counts["disk"] == 1, (
            f"_load_from_disk fired {call_counts['disk']} times, expected 1"
        )
        assert total <= 2, f"bootstrap fired {total} subroutines, expected ≤2"
    finally:
        registry._load_from_disk = real_disk  # type: ignore[assignment]
        registry.load_builtin_packs = real_builtin  # type: ignore[assignment]


def test_clear_all_resets_lazy_load_gate(fresh_registry):
    """`clear_all()` must reset the gate so the next lookup re-bootstraps."""
    registry = fresh_registry
    registry.resolve_icon("AKS", provider="azure")
    assert registry._LOAD_ATTEMPTED is True
    assert len(registry._ICON_STORE) > 0

    registry.clear_all()
    assert registry._LOAD_ATTEMPTED is False
    assert len(registry._ICON_STORE) == 0

    # Next lookup re-bootstraps.
    registry.resolve_icon("AKS", provider="azure")
    assert registry._LOAD_ATTEMPTED is True
    assert len(registry._ICON_STORE) > 0


def test_concurrent_lookups_load_only_once(fresh_registry):
    """Race: many threads calling `resolve_icon` simultaneously trigger one load."""
    registry = fresh_registry

    call_counts = {"disk": 0, "builtin": 0}
    real_disk = registry._load_from_disk
    real_builtin = registry.load_builtin_packs
    lock = threading.Lock()

    def counting_disk() -> bool:
        with lock:
            call_counts["disk"] += 1
        return real_disk()

    def counting_builtin() -> int:
        with lock:
            call_counts["builtin"] += 1
        return real_builtin()

    registry._load_from_disk = counting_disk  # type: ignore[assignment]
    registry.load_builtin_packs = counting_builtin  # type: ignore[assignment]

    barrier = threading.Barrier(20)
    results = []
    results_lock = threading.Lock()

    def worker():
        barrier.wait()
        r = registry.resolve_icon("AKS", provider="azure")
        with results_lock:
            results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
    finally:
        registry._load_from_disk = real_disk  # type: ignore[assignment]
        registry.load_builtin_packs = real_builtin  # type: ignore[assignment]

    assert all(r is not None for r in results), "every concurrent lookup must succeed"
    assert call_counts["disk"] == 1, (
        f"_load_from_disk fired {call_counts['disk']} times under contention; must be 1"
    )
    assert call_counts["builtin"] <= 1, (
        f"load_builtin_packs fired {call_counts['builtin']} times under contention; must be ≤1"
    )


def test_ensure_registry_loaded_public_api(fresh_registry):
    """`ensure_registry_loaded()` is the supported entry point for non-FastAPI callers."""
    registry = fresh_registry
    assert registry._LOAD_ATTEMPTED is False
    count = registry.ensure_registry_loaded()
    assert count > 0
    assert registry._LOAD_ATTEMPTED is True

    # Idempotent.
    count2 = registry.ensure_registry_loaded()
    assert count2 == count

    # `force=True` re-runs even if already loaded (caller asserts a refresh).
    count3 = registry.ensure_registry_loaded(force=True)
    assert count3 > 0


def test_autoload_env_disabled(monkeypatch, tmp_path):
    """`ICON_REGISTRY_AUTOLOAD=0` keeps the gate inert until explicitly forced.

    This is the contract that the unit-test suite in `test_icon_registry.py`
    relies on to keep fixture-driven tests deterministic.
    """
    monkeypatch.setenv("ICON_REGISTRY_AUTOLOAD", "0")
    monkeypatch.setenv("ICON_REGISTRY_DATA_DIR", str(tmp_path))
    for mod in ("icons.registry", "icons", "azure_landing_zone"):
        sys.modules.pop(mod, None)
    from icons import registry as r

    assert r._autoload_disabled() is True
    assert r._LOAD_ATTEMPTED is False

    # Lookup must not bootstrap.
    icon = r.resolve_icon("AKS", provider="azure")
    assert icon is None
    assert len(r._ICON_STORE) == 0

    # Explicit `force=True` still works for callers that need a guaranteed load.
    count = r.ensure_registry_loaded(force=True)
    assert count > 0


def test_landing_zone_svg_embeds_real_icons_on_cold_import(fresh_registry):
    """End-to-end #587 acceptance: cold-import LZ generator must embed real icons.

    This is the single load-bearing assertion behind the production-ready GA
    gate (#604) — the icon-resolution-hit-rate metric in #595 reads off the
    same code path.
    """
    # `fresh_registry` already cleared `azure_landing_zone` from sys.modules,
    # so this re-imports it and rebuilds its `_ICON_CACHE`.
    from azure_landing_zone import generate_landing_zone_svg

    analysis = {
        "source_provider": "aws",
        "mappings": [
            {"source_service": "EC2", "azure_service": "Virtual Machines", "category": "compute"},
            {"source_service": "S3", "azure_service": "Blob Storage", "category": "storage"},
            {"source_service": "Lambda", "azure_service": "Azure Functions", "category": "compute"},
            {"source_service": "EKS", "azure_service": "AKS", "category": "container"},
            {"source_service": "RDS", "azure_service": "Azure SQL", "category": "database"},
        ],
    }
    result = generate_landing_zone_svg(analysis, dr_variant="primary")
    svg = result["content"]

    # Every embedded icon is a base64 data URI (no external URLs — security
    # invariant from #571). Pre-fix this count was 0; post-fix the canonical
    # 5-service fixture above resolves at least 5 of 5 mappings + the static
    # network/identity tier icons.
    real_icon_count = svg.count("data:image/svg+xml;base64,")
    assert real_icon_count >= 5, (
        f"cold-import LZ generator must embed ≥5 real icons; got {real_icon_count}. "
        f"D1 lazy-load regression — see #587."
    )
