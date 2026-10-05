from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import subprocess
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest
import yaml


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ensure_private_release_staging.py"
SPEC = importlib.util.spec_from_file_location("private_release_staging", SCRIPT)
assert SPEC and SPEC.loader
staging = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(staging)

REPOSITORY = "example/archmorph"
REGISTRY = "ghcr.io/example"
PRIVATE = {
    "package_type": "container",
    "visibility": "private",
    "repository": {"full_name": REPOSITORY},
}


def test_existing_private_packages_do_not_publish_bootstrap(monkeypatch):
    metadata = Mock(return_value=PRIVATE)
    publish = Mock()
    monkeypatch.setattr(staging, "package_metadata", metadata)
    monkeypatch.setattr(staging, "publish_empty_package", publish)

    staging.ensure_private_staging(REPOSITORY, REGISTRY, "test-token")

    assert metadata.call_count == len(staging.STAGING_PACKAGES)
    publish.assert_not_called()


def test_missing_packages_publish_only_empty_bootstrap_then_verify(monkeypatch):
    metadata = Mock(side_effect=[None, None, PRIVATE, None, PRIVATE])
    publish = Mock()
    sleep = Mock()
    monkeypatch.setattr(staging, "package_metadata", metadata)
    monkeypatch.setattr(staging, "publish_empty_package", publish)
    monkeypatch.setattr(staging.time, "sleep", sleep)

    staging.ensure_private_staging(REPOSITORY, REGISTRY, "test-token")

    assert [call.args for call in publish.call_args_list] == [
        (REGISTRY, REPOSITORY, package) for package in staging.STAGING_PACKAGES
    ]
    sleep.assert_called_once_with(5)


@pytest.mark.parametrize(
    "metadata",
    [
        {**PRIVATE, "visibility": "public"},
        {**PRIVATE, "visibility": "internal"},
        {**PRIVATE, "package_type": "npm"},
        {**PRIVATE, "repository": {"full_name": "example/unrelated"}},
        {**PRIVATE, "repository": None},
    ],
)
def test_existing_untrusted_package_fails_before_any_publish(monkeypatch, metadata):
    publish = Mock()
    monkeypatch.setattr(staging, "package_metadata", Mock(return_value=metadata))
    monkeypatch.setattr(staging, "publish_empty_package", publish)

    with pytest.raises(staging.StagingError, match="not private and bound"):
        staging.ensure_private_staging(REPOSITORY, REGISTRY, "test-token")
    publish.assert_not_called()


def test_public_bootstrap_fails_before_application_upload_or_second_package(monkeypatch):
    publish = Mock()
    monkeypatch.setattr(
        staging, "package_metadata",
        Mock(side_effect=[None, {**PRIVATE, "visibility": "public"}]),
    )
    monkeypatch.setattr(staging, "publish_empty_package", publish)

    with pytest.raises(staging.StagingError, match="not private and bound"):
        staging.ensure_private_staging(REPOSITORY, REGISTRY, "test-token")
    assert publish.call_count == 1


def test_failed_bootstrap_push_stops_package_verification(monkeypatch):
    metadata = Mock(return_value=None)
    monkeypatch.setattr(staging, "package_metadata", metadata)
    monkeypatch.setattr(
        staging, "publish_empty_package",
        Mock(side_effect=subprocess.CalledProcessError(1, ["docker", "push"])),
    )
    with pytest.raises(subprocess.CalledProcessError):
        staging.ensure_private_staging(REPOSITORY, REGISTRY, "test-token")
    assert metadata.call_count == 1


def test_bootstrap_metadata_timeout_is_not_success(monkeypatch):
    publish = Mock()
    sleep = Mock()
    metadata = Mock(return_value=None)
    monkeypatch.setattr(staging, "package_metadata", metadata)
    monkeypatch.setattr(staging, "publish_empty_package", publish)
    monkeypatch.setattr(staging.time, "sleep", sleep)

    with pytest.raises(staging.StagingError, match="did not become available"):
        staging.ensure_private_staging(REPOSITORY, REGISTRY, "test-token")
    assert metadata.call_count == 13
    assert publish.call_count == 1
    assert sleep.call_count == 11


@pytest.mark.parametrize(
    ("repository", "registry", "token"),
    [
        ("example/repo\nRUN command", REGISTRY, "token"),
        (REPOSITORY, "ghcr.io/unrelated", "token"),
        (REPOSITORY, REGISTRY, ""),
    ],
)
def test_invalid_inputs_fail_before_network_or_publish(monkeypatch, repository, registry, token):
    metadata = Mock()
    monkeypatch.setattr(staging, "package_metadata", metadata)
    with pytest.raises(staging.StagingError):
        staging.ensure_private_staging(repository, registry, token)
    metadata.assert_not_called()


def test_bootstrap_context_contains_only_scratch_and_repository_label(monkeypatch):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert kwargs["check"] is True
        if command[1] == "build":
            context = Path(command[-1])
            assert [path.name for path in context.iterdir()] == ["Dockerfile"]
            assert (context / "Dockerfile").read_text() == (
                'FROM scratch\nLABEL org.opencontainers.image.source="https://github.com/example/archmorph"\n'
            )
            assert "--network=none" in command
            assert "--platform=linux/amd64" in command

    monkeypatch.setattr(staging.subprocess, "run", run)
    staging.publish_empty_package(REGISTRY, REPOSITORY, staging.STAGING_PACKAGES[0])
    assert commands[1] == [
        "docker", "push", f"{REGISTRY}/{staging.STAGING_PACKAGES[0]}:privacy-bootstrap",
    ]
    assert not Path(commands[0][-1]).exists()


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_api_failures_are_not_treated_as_missing_packages(monkeypatch, status):
    failure = HTTPError("https://api.github.com/", status, "failure", {}, None)
    monkeypatch.setattr(staging, "urlopen", Mock(side_effect=failure))
    with pytest.raises(staging.StagingError, match=f"HTTP {status}"):
        staging.package_metadata("example", staging.STAGING_PACKAGES[0], "test-token")


def test_only_not_found_allows_bootstrap(monkeypatch):
    failure = HTTPError("https://api.github.com/", 404, "not found", {}, None)
    monkeypatch.setattr(staging, "urlopen", Mock(side_effect=failure))
    assert staging.package_metadata("example", staging.STAGING_PACKAGES[0], "test-token") is None


def test_network_failure_is_reported_without_secret_details(monkeypatch):
    monkeypatch.setattr(staging, "urlopen", Mock(side_effect=URLError("sensitive detail")))
    with pytest.raises(staging.StagingError, match="URLError") as error:
        staging.package_metadata("example", staging.STAGING_PACKAGES[0], "test-token")
    assert "sensitive detail" not in str(error.value)


@pytest.mark.parametrize("payload", [b"not json", b"[]"])
def test_invalid_metadata_fails_closed(monkeypatch, payload):
    monkeypatch.setattr(staging, "urlopen", Mock(return_value=io.BytesIO(payload)))
    with pytest.raises(staging.StagingError, match="metadata"):
        staging.package_metadata("example", staging.STAGING_PACKAGES[0], "test-token")


def test_metadata_request_uses_exact_github_host_and_bounded_timeout(monkeypatch):
    request = Mock(return_value=io.BytesIO(json.dumps(PRIVATE).encode()))
    monkeypatch.setattr(staging, "urlopen", request)
    assert staging.package_metadata("example", staging.STAGING_PACKAGES[0], "test-token") == PRIVATE
    assert request.call_args.kwargs == {"timeout": 30}
    assert request.call_args.args[0].full_url == (
        f"https://api.github.com/users/example/packages/container/{staging.STAGING_PACKAGES[0]}"
    )


def test_bootstrap_build_scanning_attestation_deploy_and_cleanup_share_package_names():
    root = SCRIPT.parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
    cleanup = (root / ".github/workflows/emergency-delete-public-release-packages.yml").read_text()
    jobs = workflow["jobs"]
    final, bridge = staging.STAGING_PACKAGES
    build_steps = {step.get("name"): step for step in jobs["build-backend-release"]["steps"]}
    for step_name, package in (
        ("Build and push final staging image", final),
        ("Build and push schema bridge overlay", bridge),
    ):
        assert build_steps[step_name]["with"]["tags"] == (
            "${{ env.GHCR_BUILD_REGISTRY }}/" + package + ":${{ github.sha }}"
        )
    for job_name in (
        "build-backend-release", "scan-backend-release", "attest-backend-release", "deploy-backend",
    ):
        scripts = "\n".join(step.get("run", "") for step in jobs[job_name]["steps"])
        for package in staging.STAGING_PACKAGES:
            assert package in scripts
            assert package in cleanup
        assert "archmorph-api-release-build" not in scripts
        assert "archmorph-api-bridge-release-build" not in scripts
