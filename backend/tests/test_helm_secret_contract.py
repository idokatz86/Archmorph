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
IMMUTABLE_DIGEST = "sha256:" + "a" * 64


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


def _render_environment(values_file: str, *args: str) -> subprocess.CompletedProcess[str]:
    return _render(
        "-f",
        str(CHART / values_file),
        "--set-string",
        f"image.digest={IMMUTABLE_DIGEST}",
        *args,
    )


@pytest.mark.parametrize("values_file", ["values-production.yaml", "values-staging.yaml"])
def test_environment_renders_all_fail_closed_auth_secret_refs(values_file):
    rendered = _render_environment(values_file)
    documents = _documents(rendered.stdout)
    external_secret = next(document for document in documents if document["kind"] == "ExternalSecret")
    deployment = next(document for document in documents if document["kind"] == "Deployment")
    config_map = next(document for document in documents if document["kind"] == "ConfigMap")

    remote_keys = {
        item["secretKey"]: item["remoteRef"]["key"]
        for item in external_secret["spec"]["data"]
    }
    assert remote_keys["DATABASE_URL"] == "database-url"
    assert remote_keys["REDIS_URL"] == "redis-url"
    assert remote_keys["ARCHMORPH_API_KEY"] == "api-key"
    assert remote_keys["ARCHMORPH_API_KEY_ROTATED"] == "api-key-rotated"
    assert remote_keys["ARCHMORPH_API_KEY_PRINCIPAL_ID"] == "api-key-principal-id"
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
    assert refs["ARCHMORPH_API_KEY_ROTATED"] == {
        "name": "contract-archmorph-secrets",
        "key": "ARCHMORPH_API_KEY_ROTATED",
    }
    assert refs["ARCHMORPH_API_KEY_PRINCIPAL_ID"] == {
        "name": "contract-archmorph-secrets",
        "key": "ARCHMORPH_API_KEY_PRINCIPAL_ID",
    }
    assert refs["JWT_SECRET"] == {
        "name": "contract-archmorph-secrets",
        "key": "JWT_SECRET",
    }
    assert config_map["data"]["ARCHMORPH_API_KEY_ALLOW_LEGACY_OVERLAP"] == "false"

    migration = next(document for document in documents if document["kind"] == "Job")
    assert migration["metadata"]["annotations"]["helm.sh/hook"] == "pre-install,pre-upgrade"
    assert migration["metadata"]["name"].endswith("-migrate-1")
    assert migration["metadata"]["annotations"]["helm.sh/hook-delete-policy"] == "hook-succeeded"
    container = migration["spec"]["template"]["spec"]["containers"][0]
    assert container["command"] == ["python", "run_migrations.py"]
    assert container["args"] == ["--expect-head", "014"]
    assert container["image"] == f"example.azurecr.io/archmorph-api@{IMMUTABLE_DIGEST}"
    assert container["env"][0]["valueFrom"]["secretKeyRef"] == {
        "name": "contract-archmorph-secrets",
        "key": "DATABASE_URL",
    }

    preflight = next(
        document
        for document in documents
        if document["kind"] == "Job" and document["metadata"]["name"].endswith("-secret-preflight-1")
    )
    assert preflight["metadata"]["annotations"]["helm.sh/hook"] == "pre-install,pre-upgrade"
    assert preflight["metadata"]["annotations"]["helm.sh/hook-weight"] == "-20"
    assert preflight["metadata"]["annotations"]["helm.sh/hook-delete-policy"] == "hook-succeeded"
    assert preflight["spec"]["template"]["spec"]["containers"][0]["image"] == (
        f"example.azurecr.io/archmorph-api@{IMMUTABLE_DIGEST}"
    )
    preflight_container = preflight["spec"]["template"]["spec"]["containers"][0]
    assert preflight_container["command"] == ["python", "run_migrations.py"]
    assert preflight_container["args"] == [
        "--preflight-only",
        "--accept-current",
        "013",
        "--accept-current",
        "014",
    ]
    assert preflight_container["env"][0]["valueFrom"]["secretKeyRef"] == {
        "name": "contract-archmorph-secrets",
        "key": "DATABASE_URL",
        "optional": False,
    }


def test_existing_secret_contract_renders_without_external_secret():
    rendered = _render(
        "--set", "externalSecrets.enabled=false",
        "--set", "existingSecret.name=runtime-secrets",
        "--set-string", f"image.digest={IMMUTABLE_DIGEST}",
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
    assert refs["ARCHMORPH_API_KEY_ROTATED"] == {
        "name": "runtime-secrets",
        "key": "ARCHMORPH_API_KEY_ROTATED",
        "optional": True,
    }
    assert refs["ARCHMORPH_API_KEY_PRINCIPAL_ID"] == {
        "name": "runtime-secrets",
        "key": "ARCHMORPH_API_KEY_PRINCIPAL_ID",
    }


def test_static_key_overlap_render_is_explicit_and_secret_values_absent():
    rendered = _render_environment(
        "values-production.yaml",
        "--set-string",
        "env.ARCHMORPH_API_KEY_ALLOW_LEGACY_OVERLAP=true",
    )
    documents = _documents(rendered.stdout)
    config_map = next(document for document in documents if document["kind"] == "ConfigMap")

    assert config_map["data"]["ARCHMORPH_API_KEY_ALLOW_LEGACY_OVERLAP"] == "true"
    assert "your-base-api-key" not in rendered.stdout
    assert "your-current-api-key" not in rendered.stdout


def test_first_install_creates_app_service_account_and_hooks_receive_pull_secret():
    rendered = _render_environment(
        "values-production.yaml",
        "--set",
        "imagePullSecrets[0].name=registry-auth",
    )
    documents = _documents(rendered.stdout)
    service_account = next(document for document in documents if document["kind"] == "ServiceAccount")
    deployment = next(document for document in documents if document["kind"] == "Deployment")
    hooks = [document for document in documents if document["kind"] == "Job"]

    assert service_account["metadata"]["name"] == "contract-archmorph"
    assert service_account["automountServiceAccountToken"] is False
    assert deployment["spec"]["template"]["spec"]["serviceAccountName"] == "contract-archmorph"
    assert deployment["spec"]["template"]["spec"]["imagePullSecrets"] == [{"name": "registry-auth"}]
    assert hooks
    assert all(job["spec"]["template"]["spec"]["imagePullSecrets"] == [{"name": "registry-auth"}] for job in hooks)


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


@pytest.mark.parametrize(
    "required_key",
    [
        "ARCHMORPH_API_KEY",
        "ARCHMORPH_API_KEY_ROTATED",
        "ARCHMORPH_API_KEY_PRINCIPAL_ID",
        "JWT_SECRET",
    ],
)
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
        {
            "secretKey": "ARCHMORPH_API_KEY_ROTATED",
            "remoteRef": {"key": "api-key-rotated"},
        },
        {
            "secretKey": "ARCHMORPH_API_KEY_PRINCIPAL_ID",
            "remoteRef": {"key": "api-key-principal-id"},
        },
        {"secretKey": "JWT_SECRET", "remoteRef": {"key": "jwt-secret"}},
    ]
    data = [item for item in data if item["secretKey"] != required_key]
    rendered = _render(
        "-f", str(CHART / "values-production.yaml"),
        "--set-string", f"image.digest={IMMUTABLE_DIGEST}",
        "--set-json",
        f"externalSecrets.data={json.dumps(data)}",
        expect_success=False,
    )
    assert rendered.returncode != 0
    assert f"externalSecrets.data must map required key {required_key}" in rendered.stderr


@pytest.mark.parametrize("values_file", ["values-production.yaml", "values-staging.yaml"])
def test_production_like_render_requires_immutable_digest(values_file):
    rendered = _render("-f", str(CHART / values_file), expect_success=False)
    assert rendered.returncode != 0
    assert "image.digest must be an immutable sha256 digest" in rendered.stderr


def test_first_install_external_secret_requires_pre_materialized_runtime_secret():
    documents = _documents(_render_environment("values-production.yaml").stdout)
    external_secret = next(document for document in documents if document["kind"] == "ExternalSecret")
    preflight = next(
        document
        for document in documents
        if document["kind"] == "Job" and "secret-preflight" in document["metadata"]["name"]
    )
    migration = next(
        document
        for document in documents
        if document["kind"] == "Job" and "-migrate-" in document["metadata"]["name"]
    )

    assert "helm.sh/hook" not in external_secret["metadata"].get("annotations", {})
    assert preflight["metadata"]["annotations"]["helm.sh/hook-weight"] == "-20"
    assert migration["metadata"]["annotations"]["helm.sh/hook-weight"] == "-10"
    assert preflight["spec"]["template"]["spec"]["containers"][0]["args"] == [
        "--preflight-only",
        "--accept-current",
        "013",
        "--accept-current",
        "014",
    ]
    assert "--bootstrap-empty-database" not in migration["spec"]["template"]["spec"][
        "containers"
    ][0]["args"]


def test_empty_database_bootstrap_requires_explicit_first_provisioning_value():
    documents = _documents(
        _render_environment(
            "values-production.yaml",
            "--set",
            "migrations.bootstrapEmptyDatabase=true",
        ).stdout
    )
    preflight = next(
        document
        for document in documents
        if document["kind"] == "Job" and "secret-preflight" in document["metadata"]["name"]
    )
    migration = next(
        document
        for document in documents
        if document["kind"] == "Job" and "-migrate-" in document["metadata"]["name"]
    )
    assert preflight["spec"]["template"]["spec"]["containers"][0]["args"][-1] == (
        "--bootstrap-empty-database"
    )
    assert migration["spec"]["template"]["spec"]["containers"][0]["args"] == [
        "--expect-head",
        "014",
        "--bootstrap-empty-database",
    ]


def test_revisioned_hooks_do_not_delete_an_active_prior_migration():
    first = _documents(_render_environment("values-production.yaml").stdout)
    first_jobs = [document for document in first if document["kind"] == "Job"]

    assert all(
        "before-hook-creation" not in job["metadata"]["annotations"].get("helm.sh/hook-delete-policy", "")
        for job in first_jobs
    )
    assert {job["metadata"]["name"] for job in first_jobs} == {
        "contract-archmorph-secret-preflight-1",
        "contract-archmorph-migrate-1",
    }


def test_render_rejects_schema_contract_that_omits_head_or_has_duplicates():
    missing_head = _render(
        "-f",
        str(CHART / "values-production.yaml"),
        "--set-string",
        f"image.digest={IMMUTABLE_DIGEST}",
        "--set-json",
        'migrations.acceptedCurrentAlembicRevisions=["013"]',
        expect_success=False,
    )
    assert "must include expectedAlembicHead" in missing_head.stderr

    duplicate = _render(
        "-f",
        str(CHART / "values-production.yaml"),
        "--set-string",
        f"image.digest={IMMUTABLE_DIGEST}",
        "--set-json",
        'migrations.acceptedCurrentAlembicRevisions=["014","014"]',
        expect_success=False,
    )
    assert "must be unique" in duplicate.stderr


def test_chart_documents_external_secret_controller_bootstrap_limitation():
    readme = (CHART / "README.md").read_text(encoding="utf-8")
    assert "executes `SELECT 1`" in readme
    assert "acceptedCurrentAlembicRevisions" in readme
    assert "External Secrets controller integration limitation" in readme
    assert "materialized before" in readme
    assert "running `helm install` or `helm upgrade`" in readme
    assert "`--atomic --wait`" in readme
    assert "serialize" in readme.lower()
    assert "migrations.bootstrapEmptyDatabase=true" in readme
    assert "no application" in readme
