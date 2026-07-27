#!/usr/bin/env python3
"""Build the deterministic brace-expansion CommonJS compatibility archive."""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import io
import tarfile
from pathlib import Path, PurePosixPath


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ARCHIVE = REPO_ROOT / "vendor" / "brace-expansion-5.0.8.tgz"
DEFAULT_OUTPUT = REPO_ROOT / "vendor" / "brace-expansion-5.0.8-compat.tgz"
SOURCE_SHA256 = "0d089af987938109a964ad09ecf0977c3c6fdd7469f6183be7766ebad0858ce1"
COMMONJS_PATH = "package/dist/commonjs/index.js"
PRE_PATCH_SHA256 = "994eb761eca1c861f586ce6ab31bc2e7a6bc020dc4d6636d5e8b778c366d133f"
POST_PATCH_SHA256 = "7f522cad03cb277bcac25fb64f8e5ce640ff8d15fd19a47f21f3b07df2aef5f5"
COMPAT_SUFFIX = (
    b"\n// archmorph-commonjs-function-compat\n"
    b"module.exports = Object.assign(exports.expand, exports);\n"
)


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def validate_member(member: tarfile.TarInfo) -> None:
    path = PurePosixPath(member.name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"Unsafe archive member: {member.name}")
    if path.parts[0] != "package":
        raise ValueError(f"Archive member must be under package/: {member.name}")
    if member.issym() or member.islnk() or member.isdev() or member.isfifo():
        raise ValueError(f"Unsupported archive member type: {member.name}")
    if not (member.isdir() or member.isfile()):
        raise ValueError(f"Unexpected archive member type: {member.name}")


def build_archive(source_path: Path = SOURCE_ARCHIVE) -> bytes:
    source_bytes = source_path.read_bytes()
    if sha256(source_bytes) != SOURCE_SHA256:
        raise ValueError("Upstream brace-expansion archive failed SHA-256 verification")

    output = io.BytesIO()
    patched = False
    with tarfile.open(fileobj=io.BytesIO(source_bytes), mode="r:gz") as source:
        with gzip.GzipFile(
            fileobj=output, mode="wb", filename="", mtime=0
        ) as compressed:
            with tarfile.open(
                fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT
            ) as target:
                for source_member in source.getmembers():
                    validate_member(source_member)
                    member = copy.copy(source_member)
                    member.pax_headers = dict(source_member.pax_headers)

                    if member.isdir():
                        target.addfile(member)
                        continue

                    source_file = source.extractfile(source_member)
                    if source_file is None:
                        raise ValueError(
                            f"Unable to read archive member: {member.name}"
                        )
                    content = source_file.read()

                    if member.name == COMMONJS_PATH:
                        if sha256(content) != PRE_PATCH_SHA256:
                            raise ValueError(
                                "Unexpected upstream CommonJS implementation digest"
                            )
                        content += COMPAT_SUFFIX
                        if sha256(content) != POST_PATCH_SHA256:
                            raise ValueError(
                                "Unexpected compatibility implementation digest"
                            )
                        member.size = len(content)
                        patched = True

                    target.addfile(member, io.BytesIO(content))

    if not patched:
        raise ValueError(f"Missing expected archive member: {COMMONJS_PATH}")
    return output.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    expected = build_archive()
    if args.check:
        if not args.output.exists():
            raise SystemExit(f"{args.output} does not exist")
        actual = args.output.read_bytes()
        if actual != expected:
            raise SystemExit(
                f"{args.output} is not the byte-reproducible compatibility archive"
            )
        print(f"Verified reproducible compatibility archive: {sha256(actual)}")
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(expected)
    print(f"Wrote {args.output}: {sha256(expected)}")


if __name__ == "__main__":
    main()
