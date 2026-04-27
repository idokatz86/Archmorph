"""Tests for the environmental drift detector."""

from services.drift_detection import DriftDetector


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


def test_empty_states_are_healthy_noop():
    detector = DriftDetector()

    result = detector.detect_environmental_drift({"nodes": []}, {"nodes": []})

    assert result["overall_score"] == 1.0
    assert result["summary"]["status"] == "healthy"
    assert result["detailed_findings"] == []