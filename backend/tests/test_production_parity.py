"""Production-parity guard tests for database and session configuration."""

import json
import os
import subprocess
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]


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


def test_enforce_postgres_rejects_sqlite_in_production():
    result = run_backend_snippet(
        "import database",
        ENVIRONMENT="production",
        ENFORCE_POSTGRES="true",
        DATABASE_URL="sqlite:///./data/archmorph.db",
    )
    assert result.returncode != 0
    assert "ENFORCE_POSTGRES is set" in result.stderr


def test_postgres_readiness_is_production_ready_when_enforced():
    result = run_backend_snippet(
        "import json, database; print(json.dumps(database.database_readiness()))",
        ENVIRONMENT="production",
        ENFORCE_POSTGRES="true",
        DATABASE_URL="postgresql://archmorph:archmorph_dev@postgres:5432/archmorph",
    )
    assert result.returncode == 0, result.stderr
    readiness = json.loads(result.stdout)
    assert readiness["backend"] == "postgresql"
    assert readiness["postgres_configured"] is True
    assert readiness["sqlite_configured"] is False
    assert readiness["production_like"] is True
    assert readiness["enforce_postgres"] is True
    assert readiness["ready_for_production"] is True


def test_redis_readiness_is_horizontal_scale_ready_when_required():
    result = run_backend_snippet(
        "import json, session_store; print(json.dumps(session_store.session_store_readiness()))",
        ENVIRONMENT="production",
        REQUIRE_REDIS="true",
        REDIS_URL="redis://redis:6379/0",
        WEB_CONCURRENCY="2",
    )
    assert result.returncode == 0, result.stderr
    readiness = json.loads(result.stdout)
    assert readiness["backend"] == "redis"
    assert readiness["redis_configured"] is True
    assert readiness["require_redis"] is True
    assert readiness["production_like"] is True
    assert readiness["multi_worker"] is True
    assert readiness["ready_for_horizontal_scale"] is True


def test_require_redis_rejects_missing_redis_in_production():
    result = run_backend_snippet(
        'import session_store; session_store.get_store("parity")',
        ENVIRONMENT="production",
        REQUIRE_REDIS="true",
    )
    assert result.returncode != 0
    assert "REQUIRE_REDIS is set" in result.stderr