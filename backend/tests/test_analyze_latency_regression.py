import time


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + (b"\0" * 100)


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    index = max(0, int(len(ordered) * 0.95) - 1)
    return ordered[index]


def test_ci_smoke_analyze_p95_under_200ms_regression_guard(test_client, monkeypatch):
    monkeypatch.setenv("ARCHMORPH_CI_SMOKE_MODE", "1")
    monkeypatch.setenv("ENVIRONMENT", "test")

    upload_response = test_client.post(
        "/api/projects/slo-regression/diagrams",
        files={"file": ("aws.png", PNG_BYTES, "image/png")},
    )
    assert upload_response.status_code == 200
    diagram_id = upload_response.json()["diagram_id"]

    durations_ms = []
    for _ in range(10):
        started = time.perf_counter()
        response = test_client.post(f"/api/diagrams/{diagram_id}/analyze")
        durations_ms.append((time.perf_counter() - started) * 1000)
        assert response.status_code == 200

    assert _p95(durations_ms) < 200
