"""Establish empty GHCR packages before any application image is published."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


STAGING_PACKAGES = (
    "archmorph-api-release-staging-v2",
    "archmorph-api-bridge-release-staging-v2",
)


class StagingError(RuntimeError):
    """Private staging could not be established safely."""


def package_metadata(owner: str, package: str, token: str) -> dict[str, Any] | None:
    request = Request(
        f"https://api.github.com/users/{owner}/packages/container/{package}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            metadata = json.load(response)
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise StagingError(f"Package metadata request failed: HTTP {exc.code}") from None
    except (URLError, TimeoutError) as exc:
        raise StagingError(f"Package metadata request failed: {type(exc).__name__}") from None
    except (ValueError, UnicodeDecodeError):
        raise StagingError("Package metadata is not valid JSON") from None
    if not isinstance(metadata, dict):
        raise StagingError("Package metadata must be a JSON object")
    return metadata


def verify_private_package(metadata: dict[str, Any], repository: str) -> None:
    linked_repository = metadata.get("repository")
    if (
        metadata.get("package_type") != "container"
        or metadata.get("visibility") != "private"
        or not isinstance(linked_repository, dict)
        or linked_repository.get("full_name") != repository
    ):
        raise StagingError("Staging package is not private and bound to this repository")


def publish_empty_package(registry: str, repository: str, package: str) -> None:
    image = f"{registry}/{package}:privacy-bootstrap"
    with tempfile.TemporaryDirectory(prefix="archmorph-staging-bootstrap-") as directory:
        dockerfile = Path(directory) / "Dockerfile"
        dockerfile.write_text(
            "FROM scratch\n"
            f'LABEL org.opencontainers.image.source="https://github.com/{repository}"\n',
            encoding="utf-8",
        )
        subprocess.run(
            [
                "docker", "build", "--platform=linux/amd64", "--network=none",
                "--tag", image, directory,
            ],
            check=True,
            timeout=120,
        )
        subprocess.run(["docker", "push", image], check=True, timeout=120)


def ensure_private_staging(repository: str, registry: str, token: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", repository):
        raise StagingError("Invalid GitHub repository identity")
    owner = repository.split("/", 1)[0]
    if registry != f"ghcr.io/{owner.lower()}":
        raise StagingError("Staging registry must belong to the source repository owner")
    if not token:
        raise StagingError("GH_TOKEN is required for private package verification")

    for package in STAGING_PACKAGES:
        metadata = package_metadata(owner, package, token)
        if metadata is None:
            publish_empty_package(registry, repository, package)
            for attempt in range(12):
                metadata = package_metadata(owner, package, token)
                if metadata is not None:
                    break
                if attempt < 11:
                    time.sleep(5)
        if metadata is None:
            raise StagingError("Bootstrap package metadata did not become available")
        verify_private_package(metadata, repository)
        print(f"Verified private repository-linked staging package: {package}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--registry", required=True)
    args = parser.parse_args()
    try:
        ensure_private_staging(args.repository, args.registry, os.getenv("GH_TOKEN", ""))
    except (StagingError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        if isinstance(exc, StagingError):
            parser.exit(1, f"Private staging verification failed: {exc}\n")
        parser.exit(1, f"Empty staging bootstrap failed: {type(exc).__name__}\n")


if __name__ == "__main__":
    main()
