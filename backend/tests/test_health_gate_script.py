"""Tests for the production health gate used by deployment smoke."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "health_gate.sh"


def run_gate(payload: dict) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HEALTH_BODY"] = json.dumps(payload)
    env["HEALTH_RETRIES"] = "1"
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def healthy_payload() -> dict:
    return {
        "status": "healthy",
        "version": "4.0.0",
        "checks": {
            "openai": "ok",
            "storage": "ok",
            "redis": "not_configured",
            "service_catalog": "ok",
        },
        "service_catalog_refresh": {
            "age_hours": 0.1,
            "budget_hours": 36.0,
            "stale": False,
        },
        "scheduled_jobs": [
            {
                "name": "service_catalog_refresh",
                "age_hours": 0.1,
                "budget_hours": 36.0,
                "stale": False,
            }
        ],
    }


def test_health_gate_passes_healthy_with_optional_redis_warning():
    result = run_gate(healthy_payload())

    assert result.returncode == 0
    assert "Production health gate passed" in result.stdout
    assert "Redis is not configured" in result.stdout


def test_health_gate_fails_degraded_service_catalog_refresh():
    payload = healthy_payload()
    payload["status"] = "degraded"
    payload["checks"]["service_catalog_refresh"] = "never_ran"
    payload["service_catalog_refresh"]["stale"] = True
    payload["service_catalog_refresh"]["age_hours"] = None

    result = run_gate(payload)

    assert result.returncode == 1
    assert "requires status=healthy" in result.stdout
    assert "service_catalog_refresh" in result.stdout


def test_health_gate_fails_stale_service_catalog_refresh_even_if_status_is_wrongly_healthy():
    payload = healthy_payload()
    payload["service_catalog_refresh"]["stale"] = True
    payload["service_catalog_refresh"]["age_hours"] = None

    result = run_gate(payload)

    assert result.returncode == 1
    assert "service_catalog_refresh is stale" in result.stdout


def test_health_gate_fails_stale_scheduled_job_even_if_status_is_wrongly_healthy():
    payload = healthy_payload()
    payload["scheduled_jobs"][0]["stale"] = True

    result = run_gate(payload)

    assert result.returncode == 1
    assert "Scheduled jobs are stale" in result.stdout
    assert "service_catalog_refresh" in result.stdout


def test_health_gate_fails_invalid_json_with_clear_error():
    env = os.environ.copy()
    env["HEALTH_BODY"] = "<html>not json</html>"
    env["HEALTH_RETRIES"] = "1"

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "could not parse a valid health JSON status" in result.stdout