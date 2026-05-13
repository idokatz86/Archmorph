from pathlib import Path


REPO_ROOT = Path(__file__).parents[2]
MUTATION_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "mutation-testing.yml"
MUTATION_BASELINE = REPO_ROOT / "docs" / "testing" / "mutation-baseline.json"


def test_mutation_workflow_targets_live_risk_modules():
    workflow = MUTATION_WORKFLOW.read_text(encoding="utf-8")

    assert '[job_queue]="tests/test_job_queue.py"' in workflow
    assert '[diagram_export]="tests/test_diagram_export.py"' in workflow
    assert '[export_capabilities]="tests/test_export_capabilities.py"' in workflow
    assert '[iac_generator]="tests/test_iac_generator.py"' in workflow
    assert '[services/azure_pricing]="tests/test_pricing_blob.py"' in workflow
    assert '[vision_analyzer]="tests/test_vision_analyzer.py"' in workflow
    assert "module_report_name" in workflow
    assert 'mutation-results/${module_report_name}.txt' in workflow


def test_mutation_baseline_tracks_live_risk_modules():
    baseline = MUTATION_BASELINE.read_text(encoding="utf-8")

    assert '"name": "session_store"' in baseline
    assert '"name": "job_queue"' in baseline
    assert '"name": "diagram_export"' in baseline
    assert '"name": "export_capabilities"' in baseline
    assert '"name": "iac_generator"' in baseline
    assert '"name": "services.azure_pricing"' in baseline
