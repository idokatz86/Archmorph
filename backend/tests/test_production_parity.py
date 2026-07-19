"""Production-parity guard tests for database and session configuration."""

import json
import os
import subprocess
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent


def run_backend_snippet(code: str, **overrides: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for key in (
        "DATABASE_URL",
        "ENVIRONMENT",
        "ENFORCE_POSTGRES",
        "REDIS_URL",
        "REDIS_HOST",
        "REQUIRE_REDIS",
        "ENFORCE_REDIS",
        "WEB_CONCURRENCY",
        "UVICORN_WORKERS",
    ):
        env.pop(key, None)
    env.update(overrides)
    env["PYTHONPATH"] = str(BACKEND_DIR)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_production_rejects_sqlite_without_opt_in_flag():
    result = run_backend_snippet(
        "import database",
        ENVIRONMENT="production",
        DATABASE_URL="sqlite:///./data/archmorph.db",
    )
    assert result.returncode != 0
    assert "ENFORCE_POSTGRES is set" in result.stderr


def test_postgres_readiness_fails_closed_when_configured_but_unreachable():
    result = run_backend_snippet(
        "import json, database; print(json.dumps(database.database_readiness()))",
        ENVIRONMENT="production",
        DATABASE_URL="postgresql://placeholder:placeholder@127.0.0.1:1/archmorph",
    )
    assert result.returncode == 0, result.stderr
    readiness = json.loads(result.stdout)
    assert readiness["backend"] == "postgresql"
    assert readiness["postgres_configured"] is True
    assert readiness["sqlite_configured"] is False
    assert readiness["production_like"] is True
    assert readiness["enforce_postgres"] is True
    assert readiness["connection_ok"] is False
    assert readiness["connection_error"]
    assert readiness["ready_for_production"] is False


def test_redis_readiness_is_horizontal_scale_ready_when_required():
    result = run_backend_snippet(
        "import json, session_store; print(json.dumps(session_store.session_store_readiness()))",
        ENVIRONMENT="production",
        REQUIRE_REDIS="true",
        REDIS_URL="redis://127.0.0.1:1/0",
        WEB_CONCURRENCY="2",
    )
    assert result.returncode == 0, result.stderr
    readiness = json.loads(result.stdout)
    assert readiness["backend"] == "redis"
    assert readiness["redis_configured"] is True
    assert readiness["require_redis"] is True
    assert readiness["production_like"] is True
    assert readiness["multi_worker"] is True
    assert readiness["redis_reachable"] is False
    assert readiness["ready_for_horizontal_scale"] is False
    assert readiness["scale_blocked"] is True


def test_production_rejects_missing_redis_without_opt_in_flag():
    result = run_backend_snippet(
        'import session_store; session_store.get_store("parity")',
        ENVIRONMENT="production",
    )
    assert result.returncode != 0
    assert "REQUIRE_REDIS is set" in result.stderr


def test_terraform_and_helm_split_liveness_from_readiness():
    terraform = (REPO_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")
    variables = (REPO_ROOT / "infra" / "variables.tf").read_text(encoding="utf-8")
    dr_terraform = (REPO_ROOT / "infra" / "dr" / "main.tf").read_text(encoding="utf-8")
    helm_values = (REPO_ROOT / "charts" / "archmorph" / "values.yaml").read_text(encoding="utf-8")
    helm_prod = (REPO_ROOT / "charts" / "archmorph" / "values-production.yaml").read_text(encoding="utf-8")

    assert 'default     = "/healthz"' in variables
    assert 'default     = "/readyz"' in variables
    assert "readiness_probe {\n        path                    = var.readiness_probe_path" in terraform
    assert "liveness_probe {\n        path                    = var.health_probe_path" in terraform
    assert 'url = "https://${azurerm_container_app.backend.ingress[0].fqdn}${var.readiness_probe_path}"' in terraform
    assert "health_probe {\n    path                = var.readiness_probe_path" in terraform
    assert 'default     = "/readyz"' in dr_terraform
    assert "path                         = var.readiness_probe_path" in dr_terraform
    assert "readinessProbe:\n  httpGet:\n    path: /readyz" in helm_values
    assert "livenessProbe:\n  httpGet:\n    path: /healthz" in helm_values
    assert 'ENFORCE_POSTGRES: "true"' in helm_prod
    assert 'REQUIRE_REDIS: "true"' in helm_prod
    assert "secretKey: AZURE_OPENAI_API_KEY" in helm_prod
    assert "secretKey: DATABASE_URL" in helm_prod
    assert "secretKey: REDIS_URL" in helm_prod
