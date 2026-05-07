"""Tests for the #602/#781 model evaluation harness.

The suite covers:
1. Bench harness is structurally correct in dry-run mode (offline,
   deterministic, no Foundry calls).
2. The CLI is wired up.
3. The #781 benchmark plan captures regional availability, workload lanes,
   managed-identity auth posture, and the no-production-routing guardrail.
4. The cache-key versioning AC from #602 is satisfied —
   `_compute_cache_key` already includes `model`, so swapping models
   automatically invalidates cache entries. Lock that with an explicit
   test against the production code path.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# Make backend/ importable for `import openai_client`
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import openai_client  # noqa: E402

from eval import model_bench  # noqa: E402


class TestDryRunHarness:
    def test_full_dry_run_smoke(self) -> None:
        """Full sweep in dry mode finishes, has results for every cell, no errors."""
        report = model_bench.run_bench(dry_run=True)
        assert report.dry_run is True
        assert report.n_results > 0
        # Every (workload, model) cell that has both a corpus task and a
        # synthetic record should produce a non-error result.
        for r in report.task_results:
            assert r.error is None, f"unexpected error for {r.workload}/{r.task_id}/{r.model}: {r.error}"
            assert 0.0 <= r.accuracy <= 1.0
            assert 0.0 <= r.completeness <= 1.0
            assert 0.0 <= r.schema_validity <= 1.0
            assert r.cost_usd >= 0.0
            assert r.latency_seconds >= 0.0

    def test_summaries_match_workload_x_model_grid(self) -> None:
        report = model_bench.run_bench(dry_run=True)
        # Every summary corresponds to a (workload, model) pair we ran.
        seen = {(s.workload, s.model) for s in report.summaries}
        for wl, candidates in model_bench.WORKLOAD_CANDIDATES.items():
            for m in candidates:
                # Only assert the cell exists if the corpus has at least one task.
                if model_bench.CORPUS.get(wl):
                    assert (wl, m) in seen, f"missing summary for {wl}/{m}"

    def test_filtered_workloads(self) -> None:
        report = model_bench.run_bench(workloads=["mapping_suggester"], dry_run=True)
        for r in report.task_results:
            assert r.workload == "mapping_suggester"
        # 2 tasks × 2 candidates = 4 results
        assert report.n_results == 4

    def test_filtered_models(self) -> None:
        """Model filter should subset the candidates per workload."""
        report = model_bench.run_bench(
            workloads=["vision_analyzer"],
            models_filter=["gpt-4.1", "gpt-5.4"],
            dry_run=True,
        )
        models_in_results = {r.model for r in report.task_results}
        assert models_in_results == {"gpt-4.1", "gpt-5.4"}

    def test_composite_score_weighting(self) -> None:
        """Schema-invalid output cannot dominate accuracy alone."""
        # All 1s → 1.0
        assert model_bench._composite({"accuracy": 1.0, "completeness": 1.0, "schema_validity": 1.0, "safety": 1.0, "concision": 1.0}) == 1.0
        # Schema=0 with otherwise perfect: 1 - 0.15 = 0.85
        assert model_bench._composite({"accuracy": 1.0, "completeness": 1.0, "schema_validity": 0.0, "safety": 1.0, "concision": 1.0}) == pytest.approx(0.85)
        # Safety=0 with otherwise perfect: 1 - 0.15 = 0.85 (parity with schema)
        assert model_bench._composite({"accuracy": 1.0, "completeness": 1.0, "schema_validity": 1.0, "safety": 0.0, "concision": 1.0}) == pytest.approx(0.85)

    def test_cost_usd_uses_pricing_table(self) -> None:
        # gpt-4.1 → 2.50 in / 10.00 out per 1M tokens
        # 1000 in, 1000 out → 0.0025 + 0.010 = 0.0125
        assert model_bench._cost_usd("gpt-4.1", 1000, 1000) == pytest.approx(0.0125)
        # Unknown model → 0
        assert model_bench._cost_usd("unknown-model", 100, 100) == 0.0

    def test_percentile(self) -> None:
        assert model_bench._percentile([1.0], 0.95) == 1.0
        # Sorted [1,2,3,4,5], p95 → between idx 3.8 → 4 + 0.8*(5-4) = 4.8
        assert model_bench._percentile([5.0, 1.0, 2.0, 4.0, 3.0], 0.95) == pytest.approx(4.8)
        assert model_bench._percentile([], 0.5) == 0.0


class TestCorpusIntegrity:
    def test_every_workload_in_corpus(self) -> None:
        for wl in model_bench.WORKLOAD_CANDIDATES:
            assert wl in model_bench.CORPUS, f"corpus missing workload {wl}"
            assert len(model_bench.CORPUS[wl]) >= 1, f"workload {wl} has zero tasks"

    def test_corpus_tasks_have_required_fields(self) -> None:
        for wl, tasks in model_bench.CORPUS.items():
            for task in tasks:
                for key in ("task_id", "system", "user", "reference"):
                    assert key in task, f"task in {wl} missing {key}"

    def test_synthetic_records_present_for_every_cell(self) -> None:
        for wl, candidates in model_bench.WORKLOAD_CANDIDATES.items():
            for task in model_bench.CORPUS.get(wl, []):
                for model in candidates:
                    assert (model, task["task_id"]) in model_bench.SYNTHETIC_RESPONSES, (
                        f"missing synthetic record for ({model}, {task['task_id']})"
                    )

    def test_pricing_known_for_every_candidate(self) -> None:
        for candidates in model_bench.WORKLOAD_CANDIDATES.values():
            for model in candidates:
                assert model in model_bench.PRICING_PER_1M_TOKENS_USD, (
                    f"pricing table missing entry for {model}"
                )


class TestBenchmarkPlan781:
    def test_plan_has_at_least_five_archmorph_lanes(self) -> None:
        plan = model_bench.build_benchmark_plan()
        assert len(plan["benchmark_lanes"]) >= plan["minimum_required_lanes"] >= 5
        for required in (
            "diagram_image_understanding",
            "cloud_service_mapping",
            "iac_generation_repair",
            "hld_architecture_narrative",
            "cost_explanation",
        ):
            assert required in plan["benchmark_lanes"]

    def test_plan_keeps_current_baseline_and_no_routing_change(self) -> None:
        plan = model_bench.build_benchmark_plan()
        assert plan["production_routing_change"] is False
        assert plan["current_deployments"]["primary"]["deployment"] == "gpt-4.1"
        assert plan["current_deployments"]["fallback"]["deployment"] == "gpt-4o"
        assert "Keep current gpt-4.1/gpt-4o" in plan["decision_rule"]

    def test_plan_requires_managed_identity_not_keys(self) -> None:
        plan = model_bench.build_benchmark_plan()
        auth = plan["auth_requirements"]
        assert auth["local_auth_enabled"] is False
        assert auth["required_role"] == "Cognitive Services OpenAI User"
        assert any("API-key" in item for item in auth["forbidden"])

    def test_plan_records_west_europe_and_sweden_central_status(self) -> None:
        plan = model_bench.build_benchmark_plan()
        regional = plan["regional_availability"]
        assert "westeurope" in regional
        assert "swedencentral" in regional
        assert "gpt-5.4" in regional["westeurope"]["deployable_candidates"]
        assert regional["swedencentral"]["deployable_candidates"] == {}

    def test_recommendation_matrix_uses_allowed_decisions(self) -> None:
        plan = model_bench.build_benchmark_plan()
        allowed = {"keep_current", "add_routed_model_candidate", "defer"}
        assert plan["recommendation_matrix"]
        for row in plan["recommendation_matrix"]:
            assert row["decision"] in allowed


class TestCacheKeyVersioning:
    """Lock the AC: 'cached_chat_completion cache invalidates cleanly when
    model changes'.

    The production cache key includes `model` (see
    `openai_client._compute_cache_key`), so swapping a workload from
    `gpt-4.1` to `gpt-5.4` produces a fresh key — no stale cached
    responses leak across model swaps. This is the contract #603 will
    rely on when rolling out per-agent model picks.
    """

    def test_model_change_yields_different_key(self) -> None:
        msgs = [{"role": "user", "content": "what is the azure equivalent of S3?"}]
        k_old = openai_client._compute_cache_key(messages=msgs, model="gpt-4.1")
        k_new = openai_client._compute_cache_key(messages=msgs, model="gpt-5.4")
        assert k_old != k_new

    def test_model_change_does_not_collide_across_workloads(self) -> None:
        """Sanity: different prompts and different models all map to
        distinct keys."""
        keys = set()
        for prompt in ("a", "b", "c"):
            for m in ("gpt-4.1", "gpt-5.4", "gpt-5.5", "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.3-codex", "mistral-document-ai-2512"):
                keys.add(openai_client._compute_cache_key(
                    messages=[{"role": "user", "content": prompt}], model=m,
                ))
        # 3 prompts × 7 models = 21 unique keys
        assert len(keys) == 21


class TestCli:
    def test_cli_dry_run_to_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = model_bench.main(["--dry-run", "--workloads", "mapping_suggester"])
        assert rc == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["dry_run"] is True
        assert payload["workloads_run"] == ["mapping_suggester"]
        assert payload["n_results"] >= 1

    def test_cli_dry_run_to_file(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        out_path = tmp_path / "bench.json"
        rc = model_bench.main(["--dry-run", "--full", "--output", str(out_path)])
        assert rc == 0
        assert out_path.exists()
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        assert payload["dry_run"] is True
        # Full run touches every workload
        assert set(payload["workloads_run"]) == set(model_bench.WORKLOAD_CANDIDATES)
        assert payload["benchmark_plan"]["issue"] == 781

    def test_cli_plan_to_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = model_bench.main(["--plan"])
        assert rc == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["issue"] == 781
        assert payload["production_routing_change"] is False

    def test_cli_full_with_workloads_is_error(self) -> None:
        # Mutually exclusive flags
        rc = model_bench.main(["--full", "--workloads", "vision_analyzer"])
        assert rc == 2


class TestJudgePromptIsLoadable:
    def test_judge_prompt_file_exists(self) -> None:
        p = Path(__file__).parent.parent / "eval" / "judge_prompt.txt"
        assert p.exists(), f"missing {p}"
        body = p.read_text(encoding="utf-8")
        # Spot-check: the rubric must mention all 5 axes the harness reads.
        for axis in ("accuracy", "completeness", "schema_validity", "safety", "concision", "refusal"):
            assert axis in body, f"judge prompt missing axis '{axis}'"
