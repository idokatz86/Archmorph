"""Rendered Helm contracts for required PostgreSQL and Redis secrets (#1237)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "charts" / "archmorph"
pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


def _render(*args: str, expect_success: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["helm", "template", "contract", str(CHART), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if expect_success:
        assert result.returncode == 0, result.stderr
    return result


def _documents(output: str) -> list[dict]:
    return [document for document in yaml.safe_load_all(output) if document]


def test_production_renders_external_secret_and_database_redis_env_refs():
    rendered = _render("-f", str(CHART / "values-production.yaml"))
    documents = _documents(rendered.stdout)
    external_secret = next(document for document in documents if document["kind"] == "ExternalSecret")
    deployment = next(document for document in documents if document["kind"] == "Deployment")

    remote_keys = {
        item["secretKey"]: item["remoteRef"]["key"]
        for item in external_secret["spec"]["data"]
    }
    assert remote_keys["DATABASE_URL"] == "database-url"
    assert remote_keys["REDIS_URL"] == "redis-url"
    env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
    refs = {
        item["name"]: item["valueFrom"]["secretKeyRef"]
        for item in env
    }
    assert refs["DATABASE_URL"] == {"name": "contract-archmorph-secrets", "key": "DATABASE_URL"}
    assert refs["REDIS_URL"] == {"name": "contract-archmorph-secrets", "key": "REDIS_URL"}


def test_existing_secret_contract_renders_without_external_secret():
    rendered = _render(
        "--set", "externalSecrets.enabled=false",
        "--set", "existingSecret.name=runtime-secrets",
    )
    documents = _documents(rendered.stdout)
    assert all(document["kind"] != "ExternalSecret" for document in documents)
    deployment = next(document for document in documents if document["kind"] == "Deployment")
    refs = {
        item["name"]: item["valueFrom"]["secretKeyRef"]
        for item in deployment["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    assert refs["DATABASE_URL"]["name"] == "runtime-secrets"
    assert refs["REDIS_URL"]["name"] == "runtime-secrets"


def test_render_fails_when_no_secret_contract_is_configured():
    rendered = _render(expect_success=False)
    assert rendered.returncode != 0
    assert "externalSecrets.enabled=true or existingSecret.name" in rendered.stderr


def test_render_fails_when_external_secret_omits_database_or_redis_key():
    rendered = _render(
        "--set", "externalSecrets.enabled=true",
        "--set", "externalSecrets.secretStoreRef.name=test-store",
        "--set", "externalSecrets.data[0].secretKey=AZURE_OPENAI_API_KEY",
        "--set", "externalSecrets.data[0].remoteRef.key=openai-api-key",
        expect_success=False,
    )
    assert rendered.returncode != 0
    assert "externalSecrets.data must map required key DATABASE_URL" in rendered.stderr
