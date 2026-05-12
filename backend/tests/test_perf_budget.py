from __future__ import annotations

from pathlib import Path

from tests.perf_budget_test_utils import load_perf_budget_module

REPO_ROOT = Path(__file__).parents[2]
BUNDLE_BUDGET = REPO_ROOT / "frontend" / "perf" / "bundle-budget.json"
LIGHTHOUSE_BUDGET = REPO_ROOT / "frontend" / "lighthouse-budget.json"
LIGHTHOUSE_CONFIG = REPO_ROOT / "frontend" / "lighthouserc.json"
ANALYZE_BUDGET = Path(__file__).parent / "performance" / "analyze_latency_budget.json"


perf_budget = load_perf_budget_module()


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


def test_latency_budget_rejects_configured_regression():
    budget = perf_budget.load_budget(ANALYZE_BUDGET)
    threshold = budget["baseline_p95_ms"] * budget["max_regression_ratio"]

    assert perf_budget.evaluate_latency_budget(threshold - 0.01, budget).passed

    result = perf_budget.evaluate_latency_budget(threshold + 0.01, budget)
    assert not result.passed
    assert "/analyze p95" in result.violations[0]


def test_frontend_perf_budget_files_are_checked_in():
    for path in (BUNDLE_BUDGET, LIGHTHOUSE_BUDGET, LIGHTHOUSE_CONFIG):
        assert path.exists(), f"missing {path}"


def test_bundle_summary_requires_built_assets(tmp_path):
    try:
        perf_budget.summarize_bundle(tmp_path)
    except ValueError as exc:
        assert "no .js or .css assets found" in str(exc)
    else:
        raise AssertionError("expected summarize_bundle() to fail when dist assets are missing")
