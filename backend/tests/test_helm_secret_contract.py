"""Rendered Helm contracts for required PostgreSQL and Redis secrets (#1237)."""

from __future__ import annotations

import json
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


@pytest.mark.parametrize("values_file", ["values-production.yaml", "values-staging.yaml"])
def test_environment_renders_all_fail_closed_auth_secret_refs(values_file):
    rendered = _render("-f", str(CHART / values_file))
    documents = _documents(rendered.stdout)
    external_secret = next(document for document in documents if document["kind"] == "ExternalSecret")
    deployment = next(document for document in documents if document["kind"] == "Deployment")

    remote_keys = {
        item["secretKey"]: item["remoteRef"]["key"]
        for item in external_secret["spec"]["data"]
    }
    assert remote_keys["DATABASE_URL"] == "database-url"
    assert remote_keys["REDIS_URL"] == "redis-url"
    assert remote_keys["ARCHMORPH_API_KEY"] == "api-key"
    assert remote_keys["JWT_SECRET"] == "jwt-secret"
    env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
    refs = {
        item["name"]: item["valueFrom"]["secretKeyRef"]
        for item in env
    }
    assert refs["DATABASE_URL"] == {"name": "contract-archmorph-secrets", "key": "DATABASE_URL"}
    assert refs["REDIS_URL"] == {"name": "contract-archmorph-secrets", "key": "REDIS_URL"}
    assert refs["ARCHMORPH_API_KEY"] == {
        "name": "contract-archmorph-secrets",
        "key": "ARCHMORPH_API_KEY",
    }
    assert refs["JWT_SECRET"] == {
        "name": "contract-archmorph-secrets",
        "key": "JWT_SECRET",
    }

    migration = next(document for document in documents if document["kind"] == "Job")
    assert migration["metadata"]["annotations"]["helm.sh/hook"] == "pre-install,pre-upgrade"
    container = migration["spec"]["template"]["spec"]["containers"][0]
    assert container["command"] == ["python", "run_migrations.py"]
    assert container["env"][0]["valueFrom"]["secretKeyRef"] == {
        "name": "contract-archmorph-secrets",
        "key": "DATABASE_URL",
    }


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
    assert refs["ARCHMORPH_API_KEY"]["name"] == "runtime-secrets"
    assert refs["JWT_SECRET"]["name"] == "runtime-secrets"


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


@pytest.mark.parametrize("required_key", ["ARCHMORPH_API_KEY", "JWT_SECRET"])
def test_render_fails_when_external_secret_omits_auth_key(required_key):
    data = [
        {"secretKey": "AZURE_OPENAI_API_KEY", "remoteRef": {"key": "openai-api-key"}},
        {"secretKey": "DATABASE_URL", "remoteRef": {"key": "database-url"}},
        {"secretKey": "REDIS_URL", "remoteRef": {"key": "redis-url"}},
        {
            "secretKey": "APPLICATIONINSIGHTS_CONNECTION_STRING",
            "remoteRef": {"key": "appinsights-connection-string"},
        },
        {"secretKey": "ARCHMORPH_ADMIN_KEY", "remoteRef": {"key": "admin-key"}},
        {"secretKey": "ARCHMORPH_API_KEY", "remoteRef": {"key": "api-key"}},
        {"secretKey": "JWT_SECRET", "remoteRef": {"key": "jwt-secret"}},
    ]
    data = [item for item in data if item["secretKey"] != required_key]
    rendered = _render(
        "-f", str(CHART / "values-production.yaml"),
        "--set-json",
        f"externalSecrets.data={json.dumps(data)}",
        expect_success=False,
    )
    assert rendered.returncode != 0
    assert f"externalSecrets.data must map required key {required_key}" in rendered.stderr
