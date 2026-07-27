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
    "brace-expansion-5.0.8.tgz": PackageContract(
        "brace-expansion",
        "5.0.8",
        "0d089af987938109a964ad09ecf0977c3c6fdd7469f6183be7766ebad0858ce1",
        ("package/dist/commonjs/index.js", "package/dist/esm/index.js"),
    ),
    "brace-expansion-5.0.8-compat.tgz": PackageContract(
        "brace-expansion",
        "5.0.8",
        "3d2d5a992096e7faf5c8271dc457fb6f77b200ae8218c1255fffce5fc6b20467",
        ("package/dist/commonjs/index.js", "package/dist/esm/index.js"),
    ),
    "js-yaml-4.3.0.tgz": PackageContract(
        "js-yaml",
        "4.3.0",
        "d7cc333d5361acfcb551e1279e090326b4e3dbe4831059aa85dc85b401a2e8c8",
        ("package/index.js", "package/dist/js-yaml.mjs"),
    ),
    "nanoid-3.3.16.tgz": PackageContract(
        "nanoid",
        "3.3.16",
        "7b1def0fea02c173bd29096bc22737ba517471b6cca361cdba2b05c74676649e",
        ("package/index.cjs", "package/index.js", "package/non-secure/index.js"),
    ),
    "postcss-8.5.20.tgz": PackageContract(
        "postcss",
        "8.5.20",
        "106e5ae35933848f8912f3395c17952a72867cf88c28176efc773f1ffeb87590",
        ("package/lib/postcss.js", "package/lib/postcss.mjs"),
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
    source = packages["brace-expansion-5.0.8.tgz"]
    compat = packages["brace-expansion-5.0.8-compat.tgz"]
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
