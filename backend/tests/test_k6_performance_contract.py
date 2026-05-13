from pathlib import Path


K6_SCRIPT = Path(__file__).parent / "performance" / "api_load_test.js"
SLA_SPINE_SCRIPT = Path(__file__).parent / "performance" / "sla_spine_locust.py"
LANDING_ZONE_LOCUST = Path(__file__).parents[2] / "tests" / "perf" / "locustfile_landing_zone.py"
SLA_WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "sla-spine.yml"
PERF_SOAK_WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "perf-soak.yml"
CI_WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "ci.yml"
ALERTS_TF = Path(__file__).parents[2] / "infra" / "observability" / "alerts.tf"
SLO_DOC = Path(__file__).parents[2] / "docs" / "SLO.md"
LANDING_ZONE_SLO_DOC = Path(__file__).parents[2] / "docs" / "runbooks" / "landing_zone_slo.md"


def test_k6_summary_exposes_endpoint_latency_breakdown():
    script = K6_SCRIPT.read_text(encoding="utf-8")

    assert "static_endpoint_latency_ms" in script
    assert "static_endpoint_p95_ms" in script
    assert "catalog_response_chars_p95" in script
    for endpoint_name in ("health", "services", "flags", "roadmap", "versions"):
        assert f"static_{endpoint_name}_latency" in script


def test_k6_catalog_ci_threshold_matches_documented_fast_endpoint_budget():
    script = K6_SCRIPT.read_text(encoding="utf-8")

    assert "isCI ? 4000 : 1500" in script
    assert "catalog_latency" in script


def test_k6_requests_tag_static_endpoints():
    script = K6_SCRIPT.read_text(encoding="utf-8")

    assert "tags:" in script
    assert "endpoint:" in script
    assert "ep.name" in script


def test_sla_spine_locust_enforces_endpoint_p95s():
    script = SLA_SPINE_SCRIPT.read_text(encoding="utf-8")

    assert "constant_throughput" in script
    assert "SLO_SPINE_SUMMARY_PATH" in script
    assert "achieved_rps" in script
    assert "SLO_SPINE_MIN_RPS_RATIO" in script
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


def test_ci_workflow_enforces_frontend_perf_budgets():
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "Bundle size budget" in workflow
    assert 'LHCI_PORT: "4173"' in workflow
    assert "python3 ../scripts/perf_budget.py bundle --dist dist --budget perf/bundle-budget.json" in workflow
    assert "Run frontend tests with Live coverage gate" in workflow
    assert "npx vitest run --coverage" in workflow
    assert '@lhci/cli@0.15.1 autorun --config=./lighthouserc.json' in workflow
    assert 'python3 -m http.server "$LHCI_PORT" -d dist' in workflow
    assert 'kill "$SERVER_PID" 2>/dev/null || true' in workflow
    assert "SERVER_READY=0" in workflow
    assert "frontend-lighthouse-report" in workflow


def test_ci_workflow_enforces_risk_based_backend_coverage_floors():
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "Risk-based module coverage floors" in workflow
    assert "run_risk_coverage_floor" in workflow
    assert 'run_risk_coverage_floor "diagram_export" "tests/test_diagram_export.py" "70"' in workflow
    assert 'run_risk_coverage_floor "export_capabilities" "tests/test_export_capabilities.py" "70"' in workflow
    assert 'run_risk_coverage_floor "iac_generator" "tests/test_iac_generator.py" "70"' in workflow
    assert 'run_risk_coverage_floor "session_store" "tests/test_session_store.py" "75"' in workflow
    assert 'run_risk_coverage_floor "job_queue" "tests/test_job_queue.py" "70"' in workflow
    assert 'run_risk_coverage_floor "services.azure_pricing" "tests/test_pricing_blob.py" "65"' in workflow
    assert "--cov-fail-under=\"$floor\"" in workflow
    assert "coverage-risk-report" in workflow


def test_landing_zone_locust_enforces_primary_and_dr_slos():
    script = LANDING_ZONE_LOCUST.read_text(encoding="utf-8")

    assert "LANDING_ZONE_SOAK_SUMMARY_PATH" in script
    assert "LANDING_ZONE_TARGET_RPS" in script
    assert "memory_ceiling_mb_per_worker" in script
    assert "X-API-Key" in script
    assert "X-Export-Capability" in script
    assert "export_capability" in script
    assert "worker_memory_mb" in script
    assert "_FIRST_EXPORT_STARTED_AT" in script
    expected = {
        "landing_zone_primary": 1500,
        "landing_zone_dr": 3000,
    }
    for endpoint_name, threshold_ms in expected.items():
        assert f'"{endpoint_name}"' in script
        assert f'"threshold_ms": {threshold_ms}' in script
    assert "dr_variant=primary" in script
    assert "dr_variant=dr" in script


def test_perf_soak_workflow_runs_nightly_landing_zone_locust():
    workflow = PERF_SOAK_WORKFLOW.read_text(encoding="utf-8")

    assert "name: Landing Zone Perf Soak" in workflow
    assert "cron:" in workflow
    assert "EVENT_NAME: ${{ github.event_name }}" in workflow
    assert "tests/perf/locustfile_landing_zone.py" in workflow
    assert "PERF_SOAK_BASE_URL" in workflow
    assert "PERF_SOAK_API_KEY" in workflow
    assert "PERF_SOAK_RATE_LIMIT_PROFILE" in workflow
    assert "target staging must disable or raise per-IP limits" in workflow
    assert "LANDING_ZONE_TARGET_RPS" in workflow
    assert "landing-zone-soak-summary" in workflow


def test_perf_soak_workflow_skips_scheduled_when_unconfigured():
    workflow = PERF_SOAK_WORKFLOW.read_text(encoding="utf-8")

    assert "skip_scheduled()" in workflow
    assert "Landing Zone soak skipped" in workflow
    assert "echo \"should_run=false\" >> \"$GITHUB_OUTPUT\"" in workflow
    assert "if [ \"$EVENT_NAME\" = \"schedule\" ]; then" in workflow
    assert "PERF_SOAK_BASE_URL is not configured" in workflow
    assert "Configure PERF_SOAK_BASE_URL and PERF_SOAK_RATE_LIMIT_PROFILE=soak" in workflow


def test_perf_soak_workflow_keeps_manual_dispatch_strict_and_gates_locust():
    workflow = PERF_SOAK_WORKFLOW.read_text(encoding="utf-8")

    assert "PERF_SOAK_BASE_URL must be configured" in workflow
    assert "PERF_SOAK_RATE_LIMIT_PROFILE=soak is required" in workflow
    assert "echo \"should_run=true\" >> \"$GITHUB_OUTPUT\"" in workflow
    assert "if: ${{ steps.config.outputs.should_run == 'true' }}" in workflow
    assert "if: ${{ always() && steps.config.outputs.should_run == 'true' }}" in workflow


def test_observability_alerts_cover_full_spine_p95_and_burn_rate():
    alerts = ALERTS_TF.read_text(encoding="utf-8")

    for resource_name in ("spine_request_p95_high", "spine_burn_rate_high"):
        assert resource_name in alerts
    for key in ("analyze", "iac_terraform", "iac_bicep", "drift_compare"):
        assert key in alerts
    for threshold in ("threshold_ms = 8000", "threshold_ms = 12000", "threshold_ms = 5000"):
        assert threshold in alerts
    assert "timestamp > ago(5m)" in alerts
    assert "timestamp > ago(1h)" in alerts
    assert "(/v1)?" in alerts
    assert "customDimensions.format" in alerts
    assert "threshold               = 2" in alerts


def test_landing_zone_alerts_cover_variant_p95_and_multi_window_burn_rate():
    alerts = ALERTS_TF.read_text(encoding="utf-8")

    for resource_name in ("landing_zone_variant_p95_high", "landing_zone_burn_rate_high"):
        assert resource_name in alerts
    for text in (
        "landing_zone_variant_slos",
        "threshold_ms = 1500",
        "threshold_ms = 3000",
        "customDimensions.dr_variant",
        "format == 'landing-zone-svg'",
        "timestamp > ago(1h)",
        "timestamp > ago(24h)",
        "error_budget = 0.001",
    ):
        assert text in alerts


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


def test_landing_zone_slo_runbook_publishes_soak_contract():
    doc = LANDING_ZONE_SLO_DOC.read_text(encoding="utf-8")

    for text in (
        "p95 < 1.5s",
        "p95 < 3s",
        "100 RPS for 5 min",
        "Error rate < 0.1%",
        "512 MB per worker",
        "LANDING_ZONE_API_KEY",
        "X-Export-Capability",
        "PERF_SOAK_RATE_LIMIT_PROFILE=soak",
        "tests/perf/locustfile_landing_zone.py",
        "1-hour window",
        "24-hour window",
        ):
        assert text in doc
