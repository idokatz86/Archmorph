#!/usr/bin/env python3
"""Verify an immutable Static Web Apps rollback bundle before any mutation."""

from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
import os
import posixpath
import re
import tempfile
import unicodedata
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RESTORE_IMAGE_RE = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
_REQUIRED_API_FILES = frozenset(
    {
        "api/host.json",
        "api/package.json",
        "api/package-lock.json",
        "api/src/functions/swa-session.js",
    }
)
_CSS_REFERENCE_RE = re.compile(
    r"(?:url\(\s*|@import\s+)(?:['\"])?([^'\")\s;]+)", re.IGNORECASE
)
_JS_REFERENCE_RE = re.compile(
    r"(?:\bfrom\s*|\bimport\s*\(|\bimport\s*)(?:['\"])([^'\"]+)",
    re.MULTILINE,
)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(
                f"frontend rollback manifest contains duplicate key: {key}"
            )
        payload[key] = value
    return payload


def _safe_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        raise ValueError("frontend rollback manifest contains an unsafe path")
    if unquote(value) != value:
        raise ValueError("frontend rollback manifest contains an encoded path")
    path = PurePosixPath(value)
    if path.is_absolute() or path.parts[0] not in {"dist", "api"}:
        raise ValueError("frontend rollback manifest contains an unsafe path")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("frontend rollback manifest contains an unsafe path")
    normalized = posixpath.normpath(value)
    if normalized != value or normalized.startswith("../"):
        raise ValueError("frontend rollback manifest contains an unsafe path")
    return value


def _scan_files(root: Path) -> dict[str, Path]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("frontend rollback artifact root must be a real directory")
    files: dict[str, Path] = {}
    casefolded: dict[str, str] = {}

    def visit(directory: Path) -> None:
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError(
                f"frontend rollback artifact is missing directory: {directory.name}"
            )
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                entry_path = Path(entry.path)
                if entry.is_symlink():
                    raise ValueError("frontend rollback artifact contains a symlink")
                if entry.is_dir(follow_symlinks=False):
                    visit(entry_path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    raise ValueError(
                        "frontend rollback artifact contains a non-regular file"
                    )
                relative = _safe_relative_path(entry_path.relative_to(root).as_posix())
                folded = unicodedata.normalize("NFC", relative).casefold()
                if folded in casefolded:
                    raise ValueError(
                        "frontend rollback artifact contains a duplicate case-collision"
                    )
                casefolded[folded] = relative
                files[relative] = entry_path

    visit(root / "dist")
    visit(root / "api")
    if not files:
        raise ValueError("frontend rollback artifact has no files")
    return files


class _ReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[str] = []

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if not value:
                continue
            lowered = name.lower()
            if lowered in {"src", "href", "poster"}:
                self.references.append(value)
            elif lowered == "srcset":
                self.references.extend(
                    candidate.strip().split()[0]
                    for candidate in value.split(",")
                    if candidate.strip() and not candidate.strip().startswith("data:")
                )


def _resolve_reference(source: str, reference: str) -> str | None:
    raw = reference.strip()
    if not raw or raw.startswith(("#", "//")):
        return None
    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        return None
    decoded = unquote(parsed.path)
    if not decoded:
        return None
    candidate = (
        f"dist/{decoded.lstrip('/')}"
        if decoded.startswith("/")
        else posixpath.join(posixpath.dirname(source), decoded)
    )
    normalized = posixpath.normpath(candidate)
    if not normalized.startswith("dist/"):
        raise ValueError(
            f"frontend static asset graph contains unsafe path: {reference}"
        )
    return _safe_relative_path(normalized)


def _references(path: Path, relative: str) -> list[str]:
    suffix = path.suffix.lower()
    if suffix not in {".html", ".css", ".js", ".mjs"}:
        return []
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"frontend text asset is not UTF-8: {relative}") from error
    if suffix == ".html":
        parser = _ReferenceParser()
        parser.feed(content)
        return parser.references
    if suffix == ".css":
        return _CSS_REFERENCE_RE.findall(content)
    return [
        reference
        for reference in _JS_REFERENCE_RE.findall(content)
        if reference.startswith(("./", "../", "/"))
    ]


def _validate_static_graph(files: dict[str, Path]) -> None:
    pending = ["dist/index.html"]
    visited: set[str] = set()
    while pending:
        relative = pending.pop()
        if relative in visited:
            continue
        path = files.get(relative)
        if path is None or path.stat().st_size == 0:
            raise ValueError(
                f"frontend static asset graph is missing required file: {relative}"
            )
        visited.add(relative)
        for reference in _references(path, relative):
            resolved = _resolve_reference(relative, reference)
            if resolved is None:
                continue
            if resolved not in files:
                raise ValueError(
                    f"frontend static asset graph is missing referenced file: {resolved}"
                )
            pending.append(resolved)


def validate_bundle(root: Path) -> dict[str, str]:
    """Validate the complete deployable dist/API graph and return exact digests."""
    files = _scan_files(root)
    if "dist/index.html" not in files:
        raise ValueError("frontend rollback artifact does not contain dist/index.html")
    missing_api = sorted(_REQUIRED_API_FILES - set(files))
    if missing_api:
        raise ValueError(
            "frontend rollback artifact is missing required API files: "
            + ", ".join(missing_api)
        )
    for relative in ("api/host.json", "api/package.json", "api/package-lock.json"):
        path = files[relative]
        if path.stat().st_size == 0:
            raise ValueError(f"frontend rollback API file is empty: {relative}")
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError(
                f"frontend rollback API JSON is invalid: {relative}"
            ) from error
    if files["api/src/functions/swa-session.js"].stat().st_size == 0:
        raise ValueError("frontend rollback API function is empty")
    _validate_static_graph(files)
    digests = {relative: _file_hash(path) for relative, path in sorted(files.items())}
    if not digests or any(
        not _SHA256_RE.fullmatch(digest) for digest in digests.values()
    ):
        raise ValueError(
            "frontend rollback artifact digest manifest is empty or invalid"
        )
    return digests


def verify_snapshot(
    root: Path,
    manifest_path: Path,
    trusted_restore_image: str,
) -> dict:
    """Require the prior artifact and bind its image to trusted workflow config."""
    if not _RESTORE_IMAGE_RE.fullmatch(trusted_restore_image):
        raise ValueError(
            "trusted frontend restore image must be pinned by immutable digest"
        )
    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object
    )
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("frontend rollback manifest schema is unsupported")
    image = str(manifest.get("restore_image") or "")
    if not _RESTORE_IMAGE_RE.fullmatch(image):
        raise ValueError("frontend restore image must be pinned by immutable digest")
    if image != trusted_restore_image:
        raise ValueError(
            "frontend restore image does not match trusted workflow configuration"
        )
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("frontend rollback manifest has no artifact files")
    folded: set[str] = set()
    for relative, expected_hash in files.items():
        safe = _safe_relative_path(relative)
        collision_key = unicodedata.normalize("NFC", safe).casefold()
        if collision_key in folded:
            raise ValueError(
                "frontend rollback manifest contains a duplicate case-collision"
            )
        folded.add(collision_key)
        if not _SHA256_RE.fullmatch(str(expected_hash)):
            raise ValueError("frontend rollback manifest contains an invalid file hash")
    actual = validate_bundle(root)
    if files != actual:
        missing = sorted(set(files) - set(actual))
        changed = sorted(
            relative
            for relative in set(files) & set(actual)
            if files[relative] != actual[relative]
        )
        extra = sorted(set(actual) - set(files))
        detail = ", ".join((missing + changed + extra)[:5]) or "manifest mismatch"
        raise ValueError(f"frontend rollback artifact failed integrity check: {detail}")
    return manifest


def _write_json_atomic(output: Path, payload: object) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            json.dump(payload, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, output)
        directory_fd = os.open(
            output.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def write_manifest(root: Path, restore_image: str, output: Path) -> None:
    if not _RESTORE_IMAGE_RE.fullmatch(restore_image):
        raise ValueError("frontend restore image must be pinned by immutable digest")
    files = validate_bundle(root)
    manifest = {
        "schema_version": 1,
        "restore_image": restore_image,
        "files": files,
    }
    _write_json_atomic(output, manifest)


def _merge_values(base: dict, overlay: dict) -> dict:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_values(merged[key], value)
        else:
            merged[key] = value
    return merged


def chart_schema_contract(path: Path | list[Path]) -> dict:
    import yaml

    paths = [path] if isinstance(path, Path) else path
    if not paths:
        raise ValueError("chart migration schema contract requires values files")
    values: dict = {}
    for values_path in paths:
        payload = yaml.safe_load(values_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("chart values must be a JSON object")
        values = _merge_values(values, payload)
    migrations = values.get("migrations", {}) if isinstance(values, dict) else {}
    head = str(migrations.get("expectedAlembicHead") or "")
    accepted = migrations.get("acceptedCurrentAlembicRevisions")
    def valid(value: str) -> bool:
        return bool(value) and all(
            character.isalnum() or character in "_-" for character in value
        )
    if not valid(head) or not isinstance(accepted, list) or not accepted:
        raise ValueError("chart migration schema contract is incomplete")
    accepted = [str(item) for item in accepted]
    if any(not valid(item) for item in accepted):
        raise ValueError("chart migration schema contract contains an invalid revision")
    if len(accepted) != len(set(accepted)) or head not in accepted:
        raise ValueError("chart migration schema contract must be unique and include head")
    return {"expected_head": head, "accepted_current": accepted}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--root", required=True, type=Path)
    verify.add_argument("--manifest", required=True, type=Path)
    verify.add_argument("--restore-image", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--root", required=True, type=Path)
    write = subparsers.add_parser("write")
    write.add_argument("--root", required=True, type=Path)
    write.add_argument("--restore-image", required=True)
    write.add_argument("--output", required=True, type=Path)
    chart = subparsers.add_parser("chart-schema")
    chart.add_argument("--values", required=True, type=Path, action="append")
    chart.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "verify":
        print(
            json.dumps(
                verify_snapshot(args.root, args.manifest, args.restore_image),
                sort_keys=True,
            )
        )
    elif args.command == "validate":
        print(json.dumps(validate_bundle(args.root), sort_keys=True))
    elif args.command == "write":
        write_manifest(args.root, args.restore_image, args.output)
    else:
        args.output.write_text(
            json.dumps(chart_schema_contract(args.values), indent=2) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
