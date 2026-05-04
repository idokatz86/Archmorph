from pathlib import Path


K6_SCRIPT = Path(__file__).parent / "performance" / "api_load_test.js"
SLA_SPINE_SCRIPT = Path(__file__).parent / "performance" / "sla_spine_locust.py"
SLA_WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "sla-spine.yml"
ALERTS_TF = Path(__file__).parents[2] / "infra" / "observability" / "alerts.tf"
SLO_DOC = Path(__file__).parents[2] / "docs" / "SLO.md"


def test_k6_summary_exposes_endpoint_latency_breakdown():
    script = K6_SCRIPT.read_text(encoding="utf-8")

    assert "static_endpoint_latency_ms" in script
    assert "static_endpoint_p95_ms" in script
    assert "catalog_response_chars_p95" in script
    for endpoint_name in ("health", "services", "flags", "roadmap", "versions"):
        assert f"static_{endpoint_name}_latency" in script


def test_k6_requests_tag_static_endpoints():
    script = K6_SCRIPT.read_text(encoding="utf-8")

    assert "tags:" in script
    assert "endpoint:" in script
    assert "ep.name" in script


def test_sla_spine_locust_enforces_endpoint_p95s():
    script = SLA_SPINE_SCRIPT.read_text(encoding="utf-8")

    assert "constant_throughput" in script
    assert "SLO_SPINE_SUMMARY_PATH" in script
    expected = {
        "analyze": 8000,
        "generate_landing_zone": 1500,
        "generate_iac_terraform": 12000,
        "generate_iac_bicep": 12000,
        "drift_compare": 5000,
    }
    for endpoint_name, threshold_ms in expected.items():
        assert f'"{endpoint_name}"' in script
        assert f'"threshold_ms": {threshold_ms}' in script
    for route in (
        "/api/diagrams/{diagram_id}/analyze",
        "/api/diagrams/{diagram_id}/export-diagram?format=landing-zone-svg",
        "/api/diagrams/{diagram_id}/generate?format=terraform&force=true",
        "/api/diagrams/{diagram_id}/generate?format=bicep&force=true",
        "/api/drift/baselines/{baseline_id}/compare",
    ):
        assert route in script


def test_sla_spine_workflow_posts_pr_summary_and_runs_locust():
    workflow = SLA_WORKFLOW.read_text(encoding="utf-8")

    assert "name: sla-spine" in workflow
    assert "locust-venv" in workflow
    assert "locust==" in workflow
    assert "backend/tests/performance/sla_spine_locust.py" in workflow
    assert "ARCHMORPH_CI_SMOKE_MODE=1" in workflow
    assert "ENVIRONMENT=test" in workflow
    assert "Full-Spine SLO Gate" in workflow
    assert "issues: write" in workflow


def test_observability_alerts_cover_full_spine_p95_and_burn_rate():
    alerts = ALERTS_TF.read_text(encoding="utf-8")

    for resource_name in ("spine_request_p95_high", "spine_burn_rate_high"):
        assert resource_name in alerts
    for key in ("analyze", "iac_generate", "drift_compare"):
        assert key in alerts
    for threshold in ("threshold_ms = 8000", "threshold_ms = 12000", "threshold_ms = 5000"):
        assert threshold in alerts
    assert "timestamp > ago(5m)" in alerts
    assert "timestamp > ago(1h)" in alerts
    assert "threshold               = 2" in alerts


def test_slo_doc_publishes_full_spine_contract():
    doc = SLO_DOC.read_text(encoding="utf-8")

    for text in (
        "analyze",
        "generate_landing_zone",
        "generate_iac_terraform",
        "generate_iac_bicep",
        "drift_compare",
        "30 RPS",
        "2x",
    ):
        assert text in doc
