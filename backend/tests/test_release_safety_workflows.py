from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
ROLLBACK_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "rollback.yml"
MONITORING_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "monitoring.yml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _step_by_name(steps: list[dict], name: str) -> dict:
    for step in steps:
        if step.get("name") == name:
            return step
    raise AssertionError(f'Expected workflow step "{name}"')


def test_ci_includes_pgvector_alembic_migration_cycle():
    workflow = _load(CI_WORKFLOW)
    job = workflow["jobs"]["alembic-migration-smoke"]

    assert job["services"]["postgres"]["image"] == "pgvector/pgvector:pg16"
    assert job["services"]["redis"]["image"] == "redis:7.4-alpine"
    assert job["env"]["POSTGRES_USER"] == "archmorph"
    assert job["env"]["POSTGRES_DB"] == "archmorph"
    assert job["env"]["ARCHMORPH_TEST_REDIS_URL"] == "redis://127.0.0.1:6379/15"

    run_script = _step_by_name(job["steps"], "Run Alembic migration cycle")["run"]
    assert "python -m alembic heads" in run_script
    assert "python -m alembic upgrade head --sql" in run_script
    assert "python -m alembic upgrade head" in run_script
    assert "python -m alembic downgrade base" in run_script
    assert 'DATABASE_SCHEME="postgresql"' in run_script
    assert "printf -v DATABASE_URL '%s://%s:%s@127.0.0.1:5432/%s'" in run_script
    assert 'export DATABASE_URL ARCHMORPH_TEST_POSTGRES_URL="$DATABASE_URL"' in run_script

    contracts = _step_by_name(
        job["steps"],
        "Run canonical PostgreSQL, Redis, migration, and Helm contracts",
    )["run"]
    assert "tests/test_workspace_store_postgres.py" in contracts
    assert "tests/test_canonical_state_migration_postgres.py" in contracts
    assert "tests/test_helm_secret_contract.py" in contracts
    assert 'DATABASE_SCHEME="postgresql"' in contracts
    assert "printf -v DATABASE_URL '%s://%s:%s@127.0.0.1:5432/%s'" in contracts


def test_rollback_health_verification_uses_authenticated_api_health():
    workflow = _load(ROLLBACK_WORKFLOW)
    assert workflow["env"]["ARCHMORPH_API_KEY"] == "${{ secrets.ARCHMORPH_API_KEY }}"
    assert workflow["env"]["ADMIN_KEY"] == "${{ secrets.ADMIN_KEY }}"
    assert workflow["jobs"]["rollback"]["environment"] == "production"

    steps = workflow["jobs"]["rollback"]["steps"]
    verify_step = _step_by_name(steps, "Verify rollback health")
    run_script = verify_step["run"]

    assert 'HEALTH_API_KEY="${ARCHMORPH_API_KEY:-${ADMIN_KEY:-}}"' in run_script
    assert 'X-API-Key: ${HEALTH_API_KEY}' in run_script
    assert '"${BASE}/api/health"' in run_script
    assert 'if ! HTTP_CODE=$(curl "${_CURL_ARGS[@]}" -o health.json -w "%{http_code}"' in run_script


def test_monitoring_health_check_uses_authenticated_health_endpoint():
    workflow = _load(MONITORING_WORKFLOW)
    assert workflow["env"]["ARCHMORPH_API_KEY"] == "${{ secrets.ARCHMORPH_API_KEY }}"

    steps = workflow["jobs"]["api-health-check"]["steps"]
    health_step = _step_by_name(steps, "Check API Health")
    assert health_step["env"]["ADMIN_KEY"] == "${{ secrets.ADMIN_KEY }}"

    run_script = health_step["run"]
    assert 'HEALTH_API_KEY="${ARCHMORPH_API_KEY:-${ADMIN_KEY:-}}"' in run_script
    assert 'X-API-Key: ${HEALTH_API_KEY}' in run_script
    assert '"${{ env.API_URL }}/health"' in run_script
