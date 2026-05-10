from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).parents[2]
PERF_BUDGET_SCRIPT = REPO_ROOT / "scripts" / "perf_budget.py"
BUNDLE_BUDGET = REPO_ROOT / "frontend" / "perf" / "bundle-budget.json"
LIGHTHOUSE_BUDGET = REPO_ROOT / "frontend" / "lighthouse-budget.json"
LIGHTHOUSE_CONFIG = REPO_ROOT / "frontend" / "lighthouserc.json"
ANALYZE_BUDGET = Path(__file__).parent / "performance" / "analyze_latency_budget.json"


def _load_perf_budget_module():
    spec = importlib.util.spec_from_file_location("perf_budget", PERF_BUDGET_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


perf_budget = _load_perf_budget_module()


def test_bundle_budget_rejects_100kb_regression():
    budget = perf_budget.load_budget(BUNDLE_BUDGET)
    summary = perf_budget.BundleSummary(
        total_bytes=budget["max_total_bytes"] - 90_000,
        javascript_bytes=budget["max_javascript_bytes"] - 50_000,
        stylesheet_bytes=budget["max_stylesheet_bytes"] - 10_000,
        largest_asset_bytes=budget["max_asset_bytes"] - 10_000,
        largest_asset_path="assets/app.js",
        asset_count=12,
    )
    assert perf_budget.evaluate_bundle_budget(summary, budget).passed

    regressed = perf_budget.BundleSummary(
        total_bytes=summary.total_bytes + 100_000,
        javascript_bytes=summary.javascript_bytes + 100_000,
        stylesheet_bytes=summary.stylesheet_bytes,
        largest_asset_bytes=summary.largest_asset_bytes + 100_000,
        largest_asset_path=summary.largest_asset_path,
        asset_count=summary.asset_count,
    )
    result = perf_budget.evaluate_bundle_budget(regressed, budget)
    assert not result.passed
    assert any("bundle" in violation or "asset" in violation for violation in result.violations)


def test_latency_budget_rejects_30_percent_regression():
    budget = perf_budget.load_budget(ANALYZE_BUDGET)

    assert perf_budget.evaluate_latency_budget(3.89, budget).passed

    result = perf_budget.evaluate_latency_budget(3.91, budget)
    assert not result.passed
    assert "/analyze p95" in result.violations[0]


def test_frontend_perf_budget_files_are_checked_in():
    for path in (BUNDLE_BUDGET, LIGHTHOUSE_BUDGET, LIGHTHOUSE_CONFIG):
        assert path.exists(), f"missing {path}"
