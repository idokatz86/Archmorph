"""Tests for the environmental drift detector."""

from services.drift_detection import DriftDetector


SAMPLE_DESIGNED = {
    "nodes": [
        {"id": "web", "type": "static_web_app", "sku": "standard"},
        {"id": "api", "type": "container_app", "sku": "consumption"},
    ]
}

SAMPLE_LIVE = {
    "nodes": [
        {"resource_id": "web", "resource_type": "static_web_app", "sku": "standard"},
        {"resource_id": "api", "resource_type": "container_app", "sku": "dedicated"},
        {"resource_id": "redis", "resource_type": "redis", "sku": "basic"},
    ]
}


def test_detects_matched_modified_missing_and_shadow_resources():
    detector = DriftDetector()

    result = detector.detect_environmental_drift(
        designed_state={
            "nodes": [
                {"id": "web", "type": "static_web_app", "sku": "standard"},
                {"id": "api", "type": "container_app", "sku": "consumption"},
                {"id": "db", "type": "postgres", "sku": "b1ms"},
            ]
        },
        live_state={
            "nodes": [
                {"resource_id": "web", "resource_type": "static_web_app", "sku": "standard"},
                {"resource_id": "api", "resource_type": "container_app", "sku": "dedicated"},
                {"resource_id": "redis", "resource_type": "redis", "sku": "basic"},
            ]
        },
    )

    assert result["drift_counts"] == {"green": 1, "yellow": 1, "red": 1, "grey": 1}
    assert result["summary"]["status"] == "attention_required"
    assert result["summary"]["blocking_findings"] == 2
    assert result["overall_score"] == 0.38
    assert len(result["recommendations"]) == 3
    assert all("finding_id" in finding for finding in result["detailed_findings"])


def test_empty_states_are_healthy_noop():
    detector = DriftDetector()

    result = detector.detect_environmental_drift({"nodes": []}, {"nodes": []})

    assert result["overall_score"] == 1.0
    assert result["summary"]["status"] == "healthy"
    assert result["detailed_findings"] == []


def test_drift_baseline_compare_decision_and_report_api():
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    created = client.post(
        "/api/drift/baselines",
        json={
            "name": "Production baseline",
            "designed_state": SAMPLE_DESIGNED,
            "live_state": SAMPLE_LIVE,
            "source": "test",
        },
    )
    assert created.status_code == 200
    baseline = created.json()
    assert baseline["baseline_id"].startswith("baseline-")
    assert baseline["last_result"]["summary"]["modified"] == 1

    listed = client.get("/api/drift/baselines")
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1

    compared = client.post(
        f"/api/drift/baselines/{baseline['baseline_id']}/compare",
        json={"live_state": SAMPLE_LIVE},
    )
    assert compared.status_code == 200
    finding = next(
        item for item in compared.json()["detailed_findings"]
        if item["status"] == "yellow"
    )

    decided = client.patch(
        f"/api/drift/baselines/{baseline['baseline_id']}/findings/{finding['finding_id']}",
        json={"decision": "accepted", "note": "Approved SKU drift for load test."},
    )
    assert decided.status_code == 200
    assert decided.json()["resolution_status"] == "accepted"

    report = client.get(f"/api/drift/baselines/{baseline['baseline_id']}/report")
    assert report.status_code == 200
    assert "Drift Report: Production baseline" in report.json()["content"]