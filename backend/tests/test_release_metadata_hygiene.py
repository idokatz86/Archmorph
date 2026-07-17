"""Release/version and public metadata contracts for issue #1240."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sync_version = _load_script("sync_version")
metadata_lint = _load_script("lint_public_metadata")
terraform_init = _load_script("init_terraform_backend")


def test_version_signals_match_canonical_source():
    assert sync_version.SEMVER_PATTERN.fullmatch(sync_version.read_canonical_version(REPO_ROOT))
    assert sync_version.synchronize(REPO_ROOT) == []


def test_version_source_requires_stable_semver(tmp_path):
    (tmp_path / "VERSION").write_text("4.3-main\n", encoding="utf-8")
    with pytest.raises(sync_version.VersionSyncError, match="stable semantic version"):
        sync_version.read_canonical_version(tmp_path)


def test_duplicate_version_signal_fails_instead_of_partially_rewriting():
    path = sync_version.REPO_ROOT / "duplicate-version-fixture.txt"
    with pytest.raises(sync_version.VersionSyncError, match="found 2"):
        sync_version._replace_exactly(
            'version="1.0.0"\nversion="2.0.0"\n',
            r'version="[^"]+"',
            'version="3.0.0"',
            path=path,
        )


def test_package_lock_sync_is_structural_when_dependency_versions_match(tmp_path):
    path = tmp_path / "package-lock.json"
    path.write_text(
        '{"name":"app","version":"1.0.0","packages":{"":{"version":"1.0.0"},'
        '"node_modules/dependency":{"version":"1.0.0"}}}',
        encoding="utf-8",
    )
    payload = __import__("json").loads(sync_version._sync_package_lock(path, "2.0.0"))
    assert payload["version"] == "2.0.0"
    assert payload["packages"][""]["version"] == "2.0.0"
    assert payload["packages"]["node_modules/dependency"]["version"] == "1.0.0"


def test_current_tree_passes_public_metadata_lint():
    assert metadata_lint.scan_repository(REPO_ROOT) == []


def test_generated_azure_hostname_is_rejected_without_echoing_value():
    violations = metadata_lint.scan_text(
        "docs/example.md",
        "Endpoint: https://live-instance.example-region.azurecontainerapps.io",
        {"archmorphai.com"},
    )
    assert [(item.category, item.guidance) for item in violations] == [
        (
            "generated-azure-hostname",
            "replace the deployment hostname with a placeholder or configuration variable",
        )
    ]
    assert all("live-instance" not in repr(item) for item in violations)


@pytest.mark.parametrize(
    ("path", "text", "category"),
    [
        ("frontend/src/config.js", 'export const host = "live-app.azurestaticapps.net"', "generated-azure-hostname"),
        ("infra/main.bicep", "param endpoint string = 'live-api.azurecontainerapps.io'", "generated-azure-hostname"),
        ("Dockerfile", "ENV API_HOST=test-live.azurefd.net", "generated-azure-hostname"),
        ("docs/config.md", "https://live-${ENV}.azurestaticapps.net", "generated-azure-hostname"),
        ("frontend/src/config.ts", 'const id = "/subscriptions/12345678/resourceGroups/rg"', "azure-resource-id"),
    ],
)
def test_common_metadata_bypasses_are_rejected(path, text, category):
    violations = metadata_lint.scan_text(path, text, {"archmorphai.com"})
    assert category in {item.category for item in violations}


def test_placeholders_and_reviewed_public_domains_are_allowed():
    text = "\n".join(
        [
            "AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/",
            "Frontend: https://frontend.example.com",
            "Product: https://archmorphai.com",
            '"resource_group": "<resource-group>"',
        ]
    )
    assert metadata_lint.scan_text("docs/example.md", text, {"archmorphai.com"}) == []


def test_local_paths_and_concrete_resource_fields_are_rejected():
    violations = metadata_lint.scan_text(
        "docs/example.md",
        '/Users/operator/project\n"account_name": "live-account-name"',
        {"archmorphai.com"},
    )
    assert {item.category for item in violations} == {
        "operator-local-path",
        "concrete-resource-field",
    }


def test_required_metadata_checks_run_in_required_backend_ci_job():
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "python ../scripts/sync_version.py --check" in workflow
    assert "python ../scripts/lint_public_metadata.py" in workflow


def test_terraform_backend_wrapper_keeps_environment_keys_distinct():
    environ = {
        "TFSTATE_RESOURCE_GROUP": "example-state-rg",
        "TFSTATE_STORAGE_ACCOUNT": "examplestate",
        "TFSTATE_CONTAINER": "state",
        "TFSTATE_KEY": "production.tfstate",
        "TFSTATE_STAGING_KEY": "staging.tfstate",
    }
    assert terraform_init.backend_config("production", environ)["key"] == "production.tfstate"
    assert terraform_init.backend_config("staging", environ)["key"] == "staging.tfstate"

    environ["TFSTATE_STAGING_KEY"] = environ["TFSTATE_KEY"]
    with pytest.raises(terraform_init.BackendConfigError, match="must be distinct"):
        terraform_init.backend_config("staging", environ)
