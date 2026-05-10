from math import ceil
import time
from pathlib import Path

from tests.perf_budget_test_utils import load_perf_budget_module


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + (b"\0" * 100)
ANALYZE_BUDGET = Path(__file__).parent / "performance" / "analyze_latency_budget.json"


perf_budget = load_perf_budget_module()


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    index = max(ceil(len(ordered) * 0.95) - 1, 0)
    return ordered[index]


def test_ci_smoke_analyze_p95_stays_within_regression_budget(test_client, monkeypatch):
    monkeypatch.setenv("ARCHMORPH_CI_SMOKE_MODE", "1")
    monkeypatch.setenv("ENVIRONMENT", "test")
    budget = perf_budget.load_budget(ANALYZE_BUDGET)

    upload_response = test_client.post(
        "/api/projects/slo-regression/diagrams",
        files={"file": ("aws.png", PNG_BYTES, "image/png")},
    )
    assert upload_response.status_code == 200
    diagram_id = upload_response.json()["diagram_id"]

    for _ in range(int(budget["warmup_samples"])):
        response = test_client.post(f"/api/diagrams/{diagram_id}/analyze")
        assert response.status_code == 200

    durations_ms = []
    for _ in range(int(budget["samples"])):
        started = time.perf_counter()
        response = test_client.post(f"/api/diagrams/{diagram_id}/analyze")
        durations_ms.append((time.perf_counter() - started) * 1000)
        assert response.status_code == 200

    result = perf_budget.evaluate_latency_budget(_p95(durations_ms), budget)
    assert result.passed, f"{result.summary}; violations={result.violations}"
