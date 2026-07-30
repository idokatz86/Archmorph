"""Bounded, fail-closed scanning for authenticated durable exports.

Contract:
* Text (including UTF-16/Latin-1), ZIP/OOXML, PDF, PNG, and JPEG are scanned
  locally before any SQL or Blob persistence.
* Archives are bounded by depth, members, expanded bytes, member bytes, and
  compression ratio. Encryption and traversal are rejected.
* Unsupported opaque binary formats are rejected. Deployments may add a
  separately reviewed DLP integration in this boundary; there is deliberately
  no shell-command or arbitrary callback configuration.
"""

from __future__ import annotations

import io
import os
import posixpath
import zipfile
from pathlib import PurePosixPath

from error_envelope import ArchmorphException
from prompt_guard import sanitize_response


MAX_SCAN_BYTES = int(os.getenv("ARCHMORPH_EXPORT_SCAN_MAX_BYTES", str(64 * 1024 * 1024)))
MAX_ARCHIVE_MEMBERS = int(os.getenv("ARCHMORPH_EXPORT_SCAN_MAX_MEMBERS", "500"))
MAX_ARCHIVE_MEMBER_BYTES = int(
    os.getenv("ARCHMORPH_EXPORT_SCAN_MAX_MEMBER_BYTES", str(16 * 1024 * 1024))
)
MAX_ARCHIVE_DEPTH = int(os.getenv("ARCHMORPH_EXPORT_SCAN_MAX_ARCHIVE_DEPTH", "2"))
MAX_COMPRESSION_RATIO = int(os.getenv("ARCHMORPH_EXPORT_SCAN_MAX_RATIO", "100"))
MAX_IMAGE_PIXELS = int(os.getenv("ARCHMORPH_EXPORT_SCAN_MAX_IMAGE_PIXELS", "50000000"))

_TEXT_FORMATS = frozenset({
    "bicep", "csv", "drawio", "excalidraw", "hcl", "html", "json", "landing-zone-svg",
    "md", "markdown", "svg", "terraform", "text", "txt", "vdx", "vsdx", "xml",
})
_ARCHIVE_FORMATS = frozenset({"docx", "pptx", "zip"})
_IMAGE_FORMATS = frozenset({"jpeg", "jpg", "png"})
_ARCHIVE_TEXT_EXTENSIONS = frozenset({
    ".bicep", ".csv", ".drawio", ".hcl", ".html", ".json", ".md", ".rels",
    ".svg", ".terraform", ".tf", ".txt", ".vdx", ".xml",
})


def _reject(error: str, message: str) -> None:
    raise ArchmorphException(422, message, details={"error": error})


def _scan_text(text: str) -> None:
    if sanitize_response(text) != text:
        _reject(
            "artifact_secret_detected",
            "Generated export contains secret-like material and was not persisted.",
        )


def _decoded_text_candidates(content: bytes) -> list[str]:
    candidates: list[str] = []
    encodings = ["utf-8-sig"]
    if content.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in content[:256]:
        encodings.extend(["utf-16", "utf-16-le", "utf-16-be"])
    encodings.append("latin-1")
    for encoding in encodings:
        try:
            decoded = content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        if decoded not in candidates:
            candidates.append(decoded)
    return candidates


def _scan_text_bytes(content: bytes) -> None:
    for text in _decoded_text_candidates(content):
        _scan_text(text)


def _safe_member_name(name: str) -> bool:
    normalized = name.replace("\\", "/")
    first_part = PurePosixPath(normalized).parts[0] if normalized else ""
    return bool(
        normalized
        and "\x00" not in normalized
        and not normalized.startswith("/")
        and not normalized.startswith("../")
        and "/../" not in f"/{normalized}/"
        and not first_part.endswith(":")
        and posixpath.normpath(normalized) not in {".", ".."}
    )


def _scan_archive_member(name: str, content: bytes, *, depth: int, budget: dict[str, int]) -> None:
    suffix = PurePosixPath(name).suffix.lower()
    if content.startswith(b"PK\x03\x04"):
        _scan_archive(content, depth=depth + 1, budget=budget)
    elif content.startswith(b"%PDF-") or suffix == ".pdf":
        _scan_pdf(content)
    elif content.startswith(b"\x89PNG\r\n\x1a\n") or suffix == ".png":
        _scan_image(content, "png")
    elif content.startswith(b"\xff\xd8\xff") or suffix in {".jpg", ".jpeg"}:
        _scan_image(content, "jpeg")
    elif suffix in _ARCHIVE_TEXT_EXTENSIONS or name in {"[Content_Types].xml", "_rels/.rels"}:
        _scan_text_bytes(content)
    elif name.startswith("ppt/printerSettings/") and suffix == ".bin":
        # python-pptx emits a bounded binary framing header followed by UTF-8
        # PrintTicket XML. Arbitrary .bin members remain unsupported.
        xml_offset = content.find(b"<?xml")
        if xml_offset < 0:
            _reject(
                "artifact_archive_member_unscannable",
                "Generated archive contains unscannable printer settings.",
            )
        _scan_text_bytes(content[xml_offset:])
    else:
        _reject(
            "artifact_archive_member_unscannable",
            "Generated archive contains an opaque member with no configured scanner.",
        )


def _scan_archive(content: bytes, *, depth: int, budget: dict[str, int]) -> None:
    if depth > MAX_ARCHIVE_DEPTH:
        _reject("artifact_archive_depth_exceeded", "Generated archive nesting is too deep.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except (zipfile.BadZipFile, OSError) as exc:
        raise ArchmorphException(
            422,
            "Generated archive is invalid and was not persisted.",
            details={"error": "artifact_archive_invalid"},
        ) from exc
    with archive:
        members = archive.infolist()
        normalized_names = [member.filename.replace("\\", "/") for member in members]
        if len(normalized_names) != len(set(normalized_names)):
            _reject(
                "artifact_archive_duplicate_member",
                "Generated archive contains duplicate member names.",
            )
        budget["members"] += len(members)
        if budget["members"] > MAX_ARCHIVE_MEMBERS:
            _reject("artifact_archive_member_limit", "Generated archive has too many members.")
        for member in members:
            if not _safe_member_name(member.filename):
                _reject("artifact_archive_traversal", "Generated archive contains an unsafe path.")
            if member.flag_bits & 0x1:
                _reject("artifact_archive_encrypted", "Encrypted generated archives are not supported.")
            if member.is_dir():
                continue
            if member.file_size > MAX_ARCHIVE_MEMBER_BYTES:
                _reject("artifact_archive_member_too_large", "Generated archive member is too large.")
            compressed = max(1, member.compress_size)
            if member.file_size > compressed * MAX_COMPRESSION_RATIO:
                _reject("artifact_archive_bomb", "Generated archive exceeds the compression safety limit.")
            budget["bytes"] += member.file_size
            if budget["bytes"] > MAX_SCAN_BYTES:
                _reject("artifact_archive_expanded_too_large", "Generated archive expands beyond the scan limit.")
            try:
                member_bytes = archive.read(member)
            except (RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
                raise ArchmorphException(
                    422,
                    "Generated archive member could not be safely scanned.",
                    details={"error": "artifact_archive_unscannable"},
                ) from exc
            _scan_archive_member(
                member.filename,
                member_bytes,
                depth=depth,
                budget=budget,
            )


def _scan_pdf(content: bytes) -> None:
    from upload_validator import UploadValidationError, _validate_pdf

    try:
        _validate_pdf(content)
    except UploadValidationError as exc:
        raise ArchmorphException(
            422,
            "Generated PDF could not be safely persisted.",
            details={"error": "artifact_pdf_unsafe"},
        ) from exc
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content), strict=False)
        _scan_text_bytes(content)
        if reader.metadata:
            _scan_text("\n".join(str(value) for value in reader.metadata.values()))
        for page in reader.pages:
            text = page.extract_text() or ""
            if len(text.encode("utf-8", errors="ignore")) > MAX_ARCHIVE_MEMBER_BYTES:
                _reject("artifact_pdf_text_too_large", "Generated PDF text exceeds the scan limit.")
            _scan_text(text)
    except ArchmorphException:
        raise
    except Exception as exc:
        raise ArchmorphException(
            422,
            "Generated PDF could not be fully scanned.",
            details={"error": "artifact_pdf_unscannable"},
        ) from exc


def _scan_image(content: bytes, expected_format: str) -> None:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(content)) as image:
            actual = (image.format or "").lower()
            expected = "jpeg" if expected_format in {"jpg", "jpeg"} else expected_format
            if actual != expected:
                _reject("artifact_image_type_mismatch", "Generated image type does not match its format.")
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                _reject("artifact_image_too_large", "Generated image exceeds the pixel safety limit.")
            _scan_text("\n".join(str(value) for value in image.info.values()))
            image.verify()
    except ArchmorphException:
        raise
    except Exception as exc:
        raise ArchmorphException(
            422,
            "Generated image could not be safely scanned.",
            details={"error": "artifact_image_unscannable"},
        ) from exc


def scan_generated_export(content: bytes, *, format: str) -> None:
    """Scan exact generated bytes before any durable persistence occurs."""
    normalized_format = (format or "").strip().lower().lstrip(".")
    if not content:
        _reject("artifact_empty", "Generated export is empty and was not persisted.")
    if len(content) > MAX_SCAN_BYTES:
        _reject("artifact_scan_size_exceeded", "Generated export exceeds the scan size limit.")
    if content.startswith(b"PK\x03\x04"):
        _scan_archive(content, depth=0, budget={"bytes": 0, "members": 0})
        return
    if normalized_format in _ARCHIVE_FORMATS:
        if not content.startswith(b"PK\x03\x04"):
            _reject("artifact_archive_invalid", "Generated archive is invalid and was not persisted.")
    if normalized_format in _TEXT_FORMATS:
        _scan_text_bytes(content)
        return
    if normalized_format == "pdf":
        _scan_pdf(content)
        return
    if normalized_format in _IMAGE_FORMATS:
        _scan_image(content, normalized_format)
        return
    _reject(
        "artifact_binary_scan_unavailable",
        "This generated binary format has no configured durable-persistence scanner.",
    )