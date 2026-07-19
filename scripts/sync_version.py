#!/usr/bin/env python3
"""Synchronize all first-party Archmorph version signals from root VERSION."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class VersionSyncError(ValueError):
    """Raised when a version target cannot be synchronized safely."""


def read_canonical_version(repo_root: Path = REPO_ROOT) -> str:
    version = (repo_root / "VERSION").read_text(encoding="utf-8").strip()
    if not SEMVER_PATTERN.fullmatch(version):
        raise VersionSyncError(f"VERSION must contain a stable semantic version, received {version!r}")
    return version


def _replace_exactly(
    text: str,
    pattern: str,
    replacement: str,
    *,
    path: Path,
    count: int = 1,
    flags: int = 0,
) -> str:
    matches = list(re.finditer(pattern, text, flags))
    if len(matches) != count:
        raise VersionSyncError(
            f"Expected {count} version signal(s) in {path.relative_to(REPO_ROOT)}, found {len(matches)}"
        )
    updated, replacements = re.subn(pattern, replacement, text, count=count, flags=flags)
    if replacements != count:  # pragma: no cover - defensive parity with match count
        raise VersionSyncError(f"Unable to replace version signal in {path.relative_to(REPO_ROOT)}")
    return updated


def _sync_package(path: Path, version: str) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["version"] = version
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _sync_package_lock(path: Path, version: str) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    root_package = payload.get("packages", {}).get("")
    if not isinstance(root_package, dict):
        raise VersionSyncError(f"Missing root package entry in {path.relative_to(REPO_ROOT)}")
    if "version" not in payload or "version" not in root_package:
        raise VersionSyncError(f"Missing package-lock version field in {path.relative_to(REPO_ROOT)}")
    payload["version"] = version
    root_package["version"] = version
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _sync_openapi_snapshot(path: Path, version: str) -> str:
    text = path.read_text(encoding="utf-8")
    payload = json.loads(text)
    if not isinstance(payload.get("info"), dict) or "version" not in payload["info"]:
        raise VersionSyncError(f"Missing OpenAPI info.version in {path.relative_to(REPO_ROOT)}")
    paths_offset = text.find('  "paths":')
    if paths_offset < 0:
        raise VersionSyncError(f"Missing OpenAPI paths block in {path.relative_to(REPO_ROOT)}")
    header = _replace_exactly(
        text[:paths_offset],
        r'("version"\s*:\s*")[^"]+("\s*)',
        rf"\g<1>{version}\g<2>",
        path=path,
    )
    return header + text[paths_offset:]


def rendered_targets(repo_root: Path, version: str) -> dict[Path, str]:
    targets: dict[Path, str] = {}

    for relative in ("package.json", "frontend/package.json"):
        path = repo_root / relative
        targets[path] = _sync_package(path, version)

    for relative in ("package-lock.json", "frontend/package-lock.json"):
        path = repo_root / relative
        targets[path] = _sync_package_lock(path, version)

    backend_version = repo_root / "backend/version.py"
    targets[backend_version] = (
        '"""Generated from root VERSION by scripts/sync_version.py."""\n\n'
        f'__version__ = "{version}"\n'
    )

    constants = repo_root / "frontend/src/constants.js"
    targets[constants] = _replace_exactly(
        constants.read_text(encoding="utf-8"),
        r"export const APP_VERSION = '[^']+';",
        f"export const APP_VERSION = '{version}';",
        path=constants,
    )

    readme = repo_root / "README.md"
    targets[readme] = _replace_exactly(
        readme.read_text(encoding="utf-8"),
        r"!\[Version\]\(https://img\.shields\.io/badge/version-[^)]*-22C55E\.svg\)",
        f"![Version](https://img.shields.io/badge/version-{version}-22C55E.svg)",
        path=readme,
    )

    prd = repo_root / "docs/PRD.md"
    targets[prd] = _replace_exactly(
        prd.read_text(encoding="utf-8"),
        r"\*\*Version:\*\*\s*[^\n]+",
        f"**Version:** {version}",
        path=prd,
    )

    changelog = repo_root / "CHANGELOG.md"
    changelog_text = changelog.read_text(encoding="utf-8")
    marker = f"<!-- target-version: {version} -->"
    if re.search(r"<!-- target-version: [^ ]+ -->", changelog_text):
        changelog_text = _replace_exactly(
            changelog_text,
            r"<!-- target-version: [^ ]+ -->",
            marker,
            path=changelog,
        )
    else:
        changelog_text = _replace_exactly(
            changelog_text,
            r"(## \[Unreleased\]\n)",
            rf"\g<1>\n{marker}\n",
            path=changelog,
        )
    targets[changelog] = changelog_text

    for relative in ("docs/application-flow.excalidraw", "docs/architecture.excalidraw"):
        path = repo_root / relative
        text = path.read_text(encoding="utf-8")
        text = _replace_exactly(
            text,
            r'("source"\s*:\s*"archmorph-v)[^"]+("\s*,)',
            rf"\g<1>{version}\g<2>",
            path=path,
        )
        text = _replace_exactly(
            text,
            r'("text"\s*:\s*"Archmorph v)[^ ]+( (?:\\u2014|—))',
            rf"\g<1>{version}\g<2>",
            path=path,
        )
        targets[path] = text

    openapi_snapshot = repo_root / "backend/openapi.snapshot.json"
    targets[openapi_snapshot] = _sync_openapi_snapshot(openapi_snapshot, version)

    return targets


def synchronize(
    repo_root: Path = REPO_ROOT,
    *,
    write: bool = False,
    version_override: str | None = None,
) -> list[Path]:
    version = version_override or read_canonical_version(repo_root)
    if not SEMVER_PATTERN.fullmatch(version):
        raise VersionSyncError(f"Version override must be stable semantic version, received {version!r}")
    drifted: list[Path] = []
    rendered = rendered_targets(repo_root, version)
    if version_override is not None:
        rendered[repo_root / "VERSION"] = version + "\n"
    for path, expected in rendered.items():
        if path.read_text(encoding="utf-8") == expected:
            continue
        drifted.append(path)
    if write:
        staged: dict[Path, Path] = {}
        try:
            for path in drifted:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=path.parent,
                    prefix=f".{path.name}.",
                    delete=False,
                ) as handle:
                    handle.write(rendered[path])
                    staged[path] = Path(handle.name)
            for path in sorted(staged, key=lambda item: item.name == "VERSION"):
                staged[path].replace(path)
        finally:
            for temp_path in staged.values():
                temp_path.unlink(missing_ok=True)
    return drifted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Validate generated version signals (default)")
    mode.add_argument("--write", action="store_true", help="Rewrite generated version signals")
    parser.add_argument("--version", help="Set VERSION before rewriting generated signals")
    args = parser.parse_args(argv)

    if args.version and not args.write:
        parser.error("--version requires --write")
    if args.version:
        if not SEMVER_PATTERN.fullmatch(args.version):
            parser.error("--version must be a stable semantic version (MAJOR.MINOR.PATCH)")

    try:
        drifted = synchronize(write=args.write, version_override=args.version)
    except (OSError, json.JSONDecodeError, VersionSyncError) as exc:
        print(f"Version metadata error: {exc}", file=sys.stderr)
        return 1

    if drifted and not args.write:
        print("Version metadata drift detected:", file=sys.stderr)
        for path in drifted:
            print(f"  - {path.relative_to(REPO_ROOT)}", file=sys.stderr)
        print("Run: python3 scripts/sync_version.py --write", file=sys.stderr)
        return 1

    action = "Synchronized" if args.write else "Validated"
    print(f"{action} Archmorph version {args.version or read_canonical_version()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
