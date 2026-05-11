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


def run_gate_via_mock_curl(
    tmp_path: Path,
    *,
    health_api_key: str | None = None,
    archmorph_api_key: str | None = None,
    admin_key: str | None = None,
    mode: str = "healthy",
) -> tuple[subprocess.CompletedProcess[str], str]:
    curl_stub = tmp_path / "curl"
    curl_stub.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" > "${MOCK_CURL_ARGS_FILE}"
if [[ "${MOCK_CURL_MODE:-healthy}" == "unauthorized" ]]; then
  printf '%s' '{"error":{"code":"UNAUTHORIZED","message":"Invalid or missing API key","details":null}}'
else
  printf '%s' '{"status":"healthy","version":"4.0.0","checks":{"redis":"disabled_optional","redis_readiness":{"scale_blocked":false}},"service_catalog_refresh":{"stale":false},"scheduled_jobs":[]}'
fi
""",
        encoding="utf-8",
    )
    curl_stub.chmod(0o755)

    curl_args_file = tmp_path / "curl-args.txt"
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:{env.get('PATH', '')}"
    env["HEALTH_URL"] = "https://example.test/api/health"
    env["HEALTH_RETRIES"] = "1"
    env["MOCK_CURL_MODE"] = mode
    env["MOCK_CURL_ARGS_FILE"] = str(curl_args_file)
    env.pop("HEALTH_BODY", None)
    env.pop("HEALTH_API_KEY", None)
    env.pop("ARCHMORPH_API_KEY", None)
    env.pop("ADMIN_KEY", None)
    if health_api_key is not None:
        env["HEALTH_API_KEY"] = health_api_key
    if archmorph_api_key is not None:
        env["ARCHMORPH_API_KEY"] = archmorph_api_key
    if admin_key is not None:
        env["ADMIN_KEY"] = admin_key

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    curl_args = curl_args_file.read_text(encoding="utf-8")
    return result, curl_args


def healthy_payload() -> dict:
    return {
        "status": "healthy",
        "version": "4.0.0",
        "checks": {
            "openai": "ok",
            "storage": "ok",
            "redis": "disabled_optional",
            "redis_readiness": {
                "backend": "file",
                "redis_configured": False,
                "require_redis": False,
                "production_like": True,
                "multi_worker": False,
                "declared_replica_count": 1,
                "multi_replica": False,
                "requires_redis_for_scale": False,
                "ready_for_horizontal_scale": False,
                "scale_blocked": False,
                "scale_blocked_reason": None,
            },
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
    assert "Redis is disabled as an optional dependency" in result.stdout


def test_health_gate_fails_required_redis_missing_even_if_status_is_wrongly_healthy():
    payload = healthy_payload()
    payload["checks"]["redis"] = "missing_required"
    payload["checks"]["redis_readiness"]["require_redis"] = True

    result = run_gate(payload)

    assert result.returncode == 1
    assert "Redis is required but not configured" in result.stdout


def test_health_gate_fails_redis_scale_blocker_even_if_status_is_wrongly_healthy():
    payload = healthy_payload()
    payload["checks"]["redis_readiness"]["multi_worker"] = True
    payload["checks"]["redis_readiness"]["requires_redis_for_scale"] = True
    payload["checks"]["redis_readiness"]["scale_blocked"] = True
    payload["checks"]["redis_readiness"]["scale_blocked_reason"] = (
        "Redis is required when WEB_CONCURRENCY/UVICORN_WORKERS or declared replicas exceed 1"
    )

    result = run_gate(payload)

    assert result.returncode == 1
    assert "Redis is required before horizontal scale" in result.stdout
    assert "scale_blocked" in result.stdout


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


def test_health_gate_adds_x_api_key_header_when_health_api_key_set(tmp_path: Path):
    result, curl_args = run_gate_via_mock_curl(tmp_path, health_api_key="super-secret")

    assert result.returncode == 0
    assert "X-API-Key: super-secret" in curl_args


def test_health_gate_uses_archmorph_api_key_fallback_for_curl_header(tmp_path: Path):
    result, curl_args = run_gate_via_mock_curl(tmp_path, archmorph_api_key="fallback-secret")

    assert result.returncode == 0
    assert "X-API-Key: fallback-secret" in curl_args


def test_health_gate_uses_admin_key_fallback_for_curl_header(tmp_path: Path):
    result, curl_args = run_gate_via_mock_curl(tmp_path, admin_key="admin-secret")

    assert result.returncode == 0
    assert "X-API-Key: admin-secret" in curl_args


def test_health_gate_reports_unauthorized_payload_without_api_key(tmp_path: Path):
    result, curl_args = run_gate_via_mock_curl(tmp_path, mode="unauthorized")

    assert result.returncode == 1
    assert "X-API-Key:" not in curl_args
    assert "Invalid or missing API key" in result.stdout
