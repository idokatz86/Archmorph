"""Regression contracts for cross-environment CI/runtime integration."""

from pathlib import Path

from sqlalchemy.engine import make_url
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_derived_postgres_urls_preserve_passwords_without_rendering_them_in_logs():
    password = "test-password-placeholder"
    base_url = make_url(
        f"postgresql://archmorph:{password}@127.0.0.1:5432/archmorph"
    )

    derived = base_url.set(database="archmorph_worker").render_as_string(
        hide_password=False
    )

    assert make_url(derived).password == password
    sources = {
        "test_bridge_overlay_postgres.py": 2,
        "test_workspace_store_postgres.py": 1,
    }
    for filename, expected_calls in sources.items():
        source = (REPO_ROOT / "backend" / "tests" / filename).read_text()
        assert "str(base_url.set(database=" not in source
        assert source.count("render_as_string(") == expected_calls
        assert source.count("hide_password=False") == expected_calls


def test_compose_uses_a_writable_metrics_path_outside_the_source_bind_mount():
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())
    backend = compose["services"]["backend"]

    assert backend["environment"]["USAGE_METRICS_DATA_DIR"] == (
        "/tmp/archmorph-metrics"
    )
    assert "./backend:/app" in backend["volumes"]
    source = (REPO_ROOT / "backend" / "usage_metrics.py").read_text()
    assert '"USAGE_METRICS_DATA_DIR"' in source


def test_terraform_validation_isolates_plugin_cache_per_root():
    workflow = yaml.safe_load(CI_WORKFLOW.read_text())
    steps = workflow["jobs"]["terraform-config-validate"]["steps"]
    validation = next(
        step
        for step in steps
        if step.get("name")
        == "Validate checked-in Terraform roots without remote backends"
    )["run"]

    assert 'TF_PLUGIN_CACHE_DIR="$RUNNER_TEMP/terraform-plugin-cache/$cache_name"' in validation
    assert 'mkdir -p "$TF_PLUGIN_CACHE_DIR"' in validation
    assert validation.index("export TF_PLUGIN_CACHE_DIR") < validation.index(
        "terraform -chdir=\"$dir\" init"
    )
    assert not any(
        step.get("name") == "Configure Terraform plugin cache" for step in steps
    )


def test_migration_bootstrap_lock_tracks_github_linux_provider_packages():
    lockfile = (
        REPO_ROOT / "infra" / "migration-bootstrap" / ".terraform.lock.hcl"
    ).read_text()

    assert "h1:3H8SVvm57gDJhpfCjUnZEU1ZRehkenKCwTfdxyL+PN0=" in lockfile
    assert "h1:4EThC3ocCFiFPMZQSUvSGSxoJqBcGWxMcFYmL67uS7Y=" in lockfile


def test_wall_clock_latency_budget_runs_once_without_xdist_or_coverage():
    workflow = yaml.safe_load(CI_WORKFLOW.read_text())
    backend_steps = workflow["jobs"]["backend-tests"]["steps"]
    coverage = next(
        step
        for step in backend_steps
        if step.get("name") == "Run tests with coverage"
    )["run"]
    latency_steps = workflow["jobs"]["backend-latency-budget"]["steps"]
    latency = next(
        step
        for step in latency_steps
        if step.get("name") == "Run latency regression budget serially"
    )["run"]

    assert '-m "not latency_budget"' in coverage
    assert not any(
        step.get("name") == "Run latency regression budget serially"
        for step in backend_steps
    )
    assert "-m latency_budget" in latency
    assert "-n 0" in latency
    assert "--no-cov" in latency
    assert workflow["jobs"]["backend-latency-budget"]["timeout-minutes"] == 10