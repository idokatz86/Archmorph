#!/usr/bin/env python3
"""Verify the identity and safety contract for vendored npm packages."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from build_brace_expansion_compat import (
    COMMONJS_PATH,
    COMPAT_SUFFIX,
    POST_PATCH_SHA256,
    PRE_PATCH_SHA256,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_ROOT = REPO_ROOT / "vendor"
INSTALL_LIFECYCLE_HOOKS = {"preinstall", "install", "postinstall"}


@dataclass(frozen=True)
class PackageContract:
    name: str
    version: str
    sha256: str
    required_files: tuple[str, ...] = ()


PACKAGES = {
    "brace-expansion-5.0.12.tgz": PackageContract(
        "brace-expansion",
        "5.0.12",
        "ef8448ec78f20b692f04fa6d01f39b5ab34c66404bea3429f5a39c6c9e0be8b4",
        ("package/dist/commonjs/index.js", "package/dist/esm/index.js"),
    ),
    "brace-expansion-5.0.12-compat.tgz": PackageContract(
        "brace-expansion",
        "5.0.12",
        "f2d69051f00a8e90a2ba1d9190aacb5da7b3b82228c46d42bca0876b872d27ca",
        ("package/dist/commonjs/index.js", "package/dist/esm/index.js"),
    ),
    "source-map-js-1.2.2.tgz": PackageContract(
        "source-map-js",
        "1.2.2",
        "142746d239d522e0b907de3b029520ae8995b76fc6546fbe8847786963062b9f",
        ("package/LICENSE", "package/source-map.js", "package/lib/source-node.js"),
    ),
}


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_package(path: Path, contract: PackageContract) -> dict[str, bytes]:
    archive_bytes = path.read_bytes()
    actual_digest = sha256(archive_bytes)
    if actual_digest != contract.sha256:
        raise ValueError(
            f"{path.name}: expected SHA-256 {contract.sha256}, got {actual_digest}"
        )

    files: dict[str, bytes] = {}
    normalized_paths: set[PurePosixPath] = set()
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
        for member in archive.getmembers():
            normalized = PurePosixPath(member.name)
            if (
                normalized.is_absolute()
                or ".." in normalized.parts
                or not normalized.parts
            ):
                raise ValueError(f"{path.name}: unsafe archive member {member.name}")
            if normalized.parts[0] != "package":
                raise ValueError(
                    f"{path.name}: member outside package/ root: {member.name}"
                )
            if normalized in normalized_paths:
                raise ValueError(
                    f"{path.name}: duplicate normalized path {member.name}"
                )
            normalized_paths.add(normalized)
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise ValueError(f"{path.name}: unsupported member type {member.name}")
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError(f"{path.name}: unexpected member type {member.name}")
            source_file = archive.extractfile(member)
            if source_file is None:
                raise ValueError(f"{path.name}: unreadable member {member.name}")
            files[member.name] = source_file.read()

    for required_file in ("package/package.json", *contract.required_files):
        if required_file not in files:
            raise ValueError(f"{path.name}: missing {required_file}")

    metadata = json.loads(files["package/package.json"])
    if (metadata.get("name"), metadata.get("version")) != (
        contract.name,
        contract.version,
    ):
        raise ValueError(f"{path.name}: unexpected package identity")
    scripts = metadata.get("scripts", {})
    forbidden_hooks = INSTALL_LIFECYCLE_HOOKS.intersection(scripts)
    if forbidden_hooks:
        raise ValueError(
            f"{path.name}: install lifecycle hooks are forbidden: "
            f"{sorted(forbidden_hooks)}"
        )
    return files


def verify_compatibility_delta(packages: dict[str, dict[str, bytes]]) -> None:
    source = packages["brace-expansion-5.0.12.tgz"]
    compat = packages["brace-expansion-5.0.12-compat.tgz"]
    if source.keys() != compat.keys():
        raise ValueError("brace-expansion compatibility archive changed its file set")

    changed = [name for name in source if source[name] != compat[name]]
    if changed != [COMMONJS_PATH]:
        raise ValueError(f"Unexpected brace-expansion compatibility delta: {changed}")
    if sha256(source[COMMONJS_PATH]) != PRE_PATCH_SHA256:
        raise ValueError("Unexpected upstream brace-expansion CommonJS digest")
    if sha256(compat[COMMONJS_PATH]) != POST_PATCH_SHA256:
        raise ValueError("Unexpected compatible brace-expansion CommonJS digest")
    if compat[COMMONJS_PATH] != source[COMMONJS_PATH] + COMPAT_SUFFIX:
        raise ValueError(
            "brace-expansion compatibility delta is not the approved suffix"
        )


def main() -> None:
    package_paths = {path.name for path in VENDOR_ROOT.glob("*.tgz")}
    if package_paths != PACKAGES.keys():
        raise SystemExit(
            f"Vendored package set differs from contract: expected {sorted(PACKAGES)}, "
            f"got {sorted(package_paths)}"
        )

    packages = {
        filename: read_package(VENDOR_ROOT / filename, contract)
        for filename, contract in PACKAGES.items()
    }
    verify_compatibility_delta(packages)
    print(f"Verified {len(packages)} vendored npm package archives")


if __name__ == "__main__":
    main()
