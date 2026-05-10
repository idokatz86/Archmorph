from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BundleSummary:
    total_bytes: int
    javascript_bytes: int
    stylesheet_bytes: int
    largest_asset_bytes: int
    largest_asset_path: str
    asset_count: int


@dataclass(frozen=True)
class BudgetResult:
    passed: bool
    summary: str
    violations: list[str]
    observed: dict[str, Any]
    limits: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def load_budget(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def summarize_bundle(dist_dir: str | Path) -> BundleSummary:
    dist_path = Path(dist_dir)
    assets = [path for path in dist_path.rglob("*") if path.is_file() and path.suffix in {".js", ".css"}]
    if not assets:
        raise ValueError(f"no .js or .css assets found under {dist_path}")
    largest_asset = max(assets, key=lambda path: path.stat().st_size)
    return BundleSummary(
        total_bytes=sum(path.stat().st_size for path in assets),
        javascript_bytes=sum(path.stat().st_size for path in assets if path.suffix == ".js"),
        stylesheet_bytes=sum(path.stat().st_size for path in assets if path.suffix == ".css"),
        largest_asset_bytes=largest_asset.stat().st_size,
        largest_asset_path=largest_asset.relative_to(dist_path).as_posix(),
        asset_count=len(assets),
    )


def evaluate_bundle_budget(summary: BundleSummary, budget: dict[str, Any]) -> BudgetResult:
    violations: list[str] = []
    checks = {
        "total_bytes": ("total bundle", summary.total_bytes, int(budget["max_total_bytes"])),
        "javascript_bytes": ("javascript bundle", summary.javascript_bytes, int(budget["max_javascript_bytes"])),
        "stylesheet_bytes": ("stylesheet bundle", summary.stylesheet_bytes, int(budget["max_stylesheet_bytes"])),
        "largest_asset_bytes": ("largest asset", summary.largest_asset_bytes, int(budget["max_asset_bytes"])),
    }
    for _, (label, observed, limit) in checks.items():
        if observed > limit:
            violations.append(f"{label} {observed} B exceeds {limit} B")

    largest_asset_label = f"{summary.largest_asset_path} ({summary.largest_asset_bytes} B)"
    summary_text = (
        f"bundle totals: total={summary.total_bytes} B, js={summary.javascript_bytes} B, "
        f"css={summary.stylesheet_bytes} B, largest={largest_asset_label}"
    )
    return BudgetResult(
        passed=not violations,
        summary=summary_text,
        violations=violations,
        observed={
            "total_bytes": summary.total_bytes,
            "javascript_bytes": summary.javascript_bytes,
            "stylesheet_bytes": summary.stylesheet_bytes,
            "largest_asset_bytes": summary.largest_asset_bytes,
            "largest_asset_path": summary.largest_asset_path,
            "asset_count": summary.asset_count,
        },
        limits={
            "max_total_bytes": int(budget["max_total_bytes"]),
            "max_javascript_bytes": int(budget["max_javascript_bytes"]),
            "max_stylesheet_bytes": int(budget["max_stylesheet_bytes"]),
            "max_asset_bytes": int(budget["max_asset_bytes"]),
        },
    )


def evaluate_latency_budget(observed_p95_ms: float, budget: dict[str, Any]) -> BudgetResult:
    baseline_p95_ms = float(budget["baseline_p95_ms"])
    allowed_ratio = float(budget["max_regression_ratio"])
    allowed_p95_ms = baseline_p95_ms * allowed_ratio
    violations: list[str] = []
    if observed_p95_ms > allowed_p95_ms:
        violations.append(
            f"/analyze p95 {observed_p95_ms:.2f} ms exceeds {allowed_p95_ms:.2f} ms "
            f"(baseline {baseline_p95_ms:.2f} ms × {allowed_ratio:.2f})"
        )

    return BudgetResult(
        passed=not violations,
        summary=(
            f"/analyze p95={observed_p95_ms:.2f} ms "
            f"(baseline={baseline_p95_ms:.2f} ms, allowed_ratio={allowed_ratio:.2f}, "
            f"allowed_p95={allowed_p95_ms:.2f} ms)"
        ),
        violations=violations,
        observed={"observed_p95_ms": observed_p95_ms},
        limits={
            "baseline_p95_ms": baseline_p95_ms,
            "max_regression_ratio": allowed_ratio,
            "allowed_p95_ms": allowed_p95_ms,
        },
    )


def _write_output(path: str | Path | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Archmorph performance budgets.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bundle_parser = subparsers.add_parser("bundle", help="Check the built frontend asset budget.")
    bundle_parser.add_argument("--dist", required=True)
    bundle_parser.add_argument("--budget", required=True)
    bundle_parser.add_argument("--output")

    latency_parser = subparsers.add_parser("latency", help="Check the backend /analyze p95 budget.")
    latency_parser.add_argument("--budget", required=True)
    latency_parser.add_argument("--observed-p95-ms", required=True, type=float)
    latency_parser.add_argument("--output")

    args = parser.parse_args(argv)
    if args.command == "bundle":
        budget = load_budget(args.budget)
        result = evaluate_bundle_budget(summarize_bundle(args.dist), budget)
    else:
        budget = load_budget(args.budget)
        result = evaluate_latency_budget(args.observed_p95_ms, budget)

    payload = result.to_payload()
    _write_output(getattr(args, "output", None), payload)
    print(result.summary)
    if result.violations:
        for violation in result.violations:
            print(f"ERROR: {violation}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
