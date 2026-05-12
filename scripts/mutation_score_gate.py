#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


COUNTED_STATUSES = ("killed", "survived", "timeout", "suspicious")
IGNORED_STATUSES = ("incompetent",)
SUMMARY_RE = re.compile(r"^\s*(killed|survived|timeout|suspicious|incompetent)\s*[:=]\s*(\d+)\b", re.I)
LINE_STATUS_RE = re.compile(r"^\s*(killed|survived|timeout|suspicious|incompetent)\b", re.I)


@dataclass(frozen=True)
class ModuleBaseline:
    name: str
    path: str
    report: str
    minimum_score: float


@dataclass(frozen=True)
class ModuleScore:
    baseline: ModuleBaseline
    counts: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.get(status, 0) for status in COUNTED_STATUSES)

    @property
    def score(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.counts.get("killed", 0) / self.total) * 100

    @property
    def passed(self) -> bool:
        return self.total > 0 and self.score >= self.baseline.minimum_score


def load_baseline(path: Path) -> list[ModuleBaseline]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    default_minimum = float(payload.get("minimum_score", 60))
    modules: list[ModuleBaseline] = []
    for item in payload.get("modules", []):
        name = str(item["name"])
        modules.append(
            ModuleBaseline(
                name=name,
                path=str(item["path"]),
                report=str(item.get("report", f"{name}.txt")),
                minimum_score=float(item.get("minimum_score", default_minimum)),
            )
        )
    if not modules:
        raise ValueError("mutation baseline must define at least one module")
    return modules


def parse_report(path: Path, module_name: str) -> dict[str, int]:
    if path.suffix == ".json":
        return _parse_json_report(path, module_name)
    return _parse_text_report(path)


def _empty_counts() -> dict[str, int]:
    return {status: 0 for status in (*COUNTED_STATUSES, *IGNORED_STATUSES)}


def _parse_json_report(path: Path, module_name: str) -> dict[str, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "modules" in payload:
        payload = _find_json_module(payload["modules"], module_name)
    counts = _empty_counts()
    for status in counts:
        counts[status] = int(payload.get(status, 0))
    return counts


def _find_json_module(modules: list[dict[str, Any]], module_name: str) -> dict[str, Any]:
    for module in modules:
        if module.get("name") == module_name:
            return module
    raise ValueError(f"mutation report is missing module {module_name!r}")


def _parse_text_report(path: Path) -> dict[str, int]:
    counts = _empty_counts()
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    matched_summary = False
    for line in lines:
        match = SUMMARY_RE.search(line)
        if match:
            counts[match.group(1).lower()] += int(match.group(2))
            matched_summary = True

    if matched_summary:
        return counts

    for line in lines:
        match = LINE_STATUS_RE.search(line)
        if match:
            counts[match.group(1).lower()] += 1
    return counts


def evaluate(baseline_path: Path, report_dir: Path) -> tuple[list[ModuleScore], list[str]]:
    scores: list[ModuleScore] = []
    errors: list[str] = []
    for baseline in load_baseline(baseline_path):
        report_path = report_dir / baseline.report
        if not report_path.is_file():
            errors.append(f"{baseline.name}: missing mutation report {report_path}")
            continue
        try:
            counts = parse_report(report_path, baseline.name)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{baseline.name}: could not parse {report_path}: {exc}")
            continue
        score = ModuleScore(baseline=baseline, counts=counts)
        scores.append(score)
        if score.total == 0:
            errors.append(f"{baseline.name}: mutation report contained no counted mutants")
        elif not score.passed:
            errors.append(
                f"{baseline.name}: mutation score {score.score:.1f}% is below "
                f"baseline {baseline.minimum_score:.1f}%"
            )
    return scores, errors


def render_markdown(scores: list[ModuleScore], errors: list[str]) -> str:
    lines = ["## Mutation Score Baseline", "", "| Module | Score | Baseline | Killed | Survived | Timeout | Suspicious |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for score in scores:
        counts = score.counts
        lines.append(
            "| {module} | {observed:.1f}% | {minimum:.1f}% | {killed} | {survived} | {timeout} | {suspicious} |".format(
                module=score.baseline.name,
                observed=score.score,
                minimum=score.baseline.minimum_score,
                killed=counts.get("killed", 0),
                survived=counts.get("survived", 0),
                timeout=counts.get("timeout", 0),
                suspicious=counts.get("suspicious", 0),
            )
        )
    if errors:
        lines.extend(["", "### Gate Failures"])
        lines.extend(f"- {error}" for error in errors)
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail when mutation scores drop below the committed baseline.")
    parser.add_argument("--baseline", default="docs/testing/mutation-baseline.json", type=Path)
    parser.add_argument("--report-dir", default="mutation-results", type=Path)
    parser.add_argument("--summary", type=Path, help="Optional GitHub step summary path.")
    args = parser.parse_args(argv)

    scores, errors = evaluate(args.baseline, args.report_dir)
    summary = render_markdown(scores, errors)
    print(summary, end="")
    if args.summary:
        args.summary.write_text(summary, encoding="utf-8")
    if errors:
        for error in errors:
            print(f"::error::{error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())