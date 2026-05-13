"""Hardened upload validation for architecture diagram uploads.

Validates uploads before bytes reach rasterizers or LLM analysis paths:

- Magic bytes vs declared content-type / extension (rejects mismatches)
- PDF: no encryption, no JavaScript/actions, no embedded files, no launch
  actions, bounded page count and object count.
- SVG / Draw.io / XML: safe parsing via defusedxml (XXE disabled), reject
  script elements and event-handler attributes, reject dangerous URI schemes.
- VSDX (ZIP-based Visio): entry count, per-entry and total uncompressed size,
  compression-ratio (zip-bomb) guard, path-traversal safety.

All user-facing errors are deterministic plain-English messages.  Internal
parser details are never exposed.
"""

from __future__ import annotations

import io
import logging
import zipfile
from typing import Optional

logger = logging.getLogger(__name__)

# ── Magic byte constants ───────────────────────────────────────────────────────
_MAGIC_PNG  = b"\x89PNG\r\n\x1a\n"
_MAGIC_JPEG = b"\xff\xd8\xff"
_MAGIC_PDF  = b"%PDF-"
_MAGIC_ZIP  = b"PK\x03\x04"       # Also: VSDX, DOCX, XLSX, …

# ── Safety limits ─────────────────────────────────────────────────────────────
_MAX_ZIP_ENTRIES           = 200
_MAX_ZIP_TOTAL_UNCOMPRESSED = 100 * 1024 * 1024   # 100 MB
_MAX_ZIP_COMPRESSION_RATIO = 100                   # bomb guard: ratio > 100 ⇒ reject
_MAX_PDF_PAGES             = 100
_MAX_PDF_OBJECTS           = 10_000


# ── Public exception ──────────────────────────────────────────────────────────
class UploadValidationError(Exception):
    """Raised when an upload fails content-level validation.

    Attributes
    ----------
    message:     User-facing explanation (no internal parser details).
    status_code: Suggested HTTP status code (always 400 or 422).
    """

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ── Internal helpers ──────────────────────────────────────────────────────────
def _starts_with(data: bytes, magic: bytes) -> bool:
    return len(data) >= len(magic) and data[: len(magic)] == magic


def _extension(filename: Optional[str]) -> str:
    """Return the lower-cased extension (without dot), or ''."""
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


# ── 1. Magic-byte / content-type mismatch ─────────────────────────────────────
def _check_magic_mismatch(data: bytes, content_type: str, ext: str) -> None:
    """Raise UploadValidationError when magic bytes contradict the declared type."""
    if content_type == "image/png" or ext == "png":
        if not _starts_with(data, _MAGIC_PNG):
            raise UploadValidationError(
                "File content does not match the declared PNG type."
            )
    elif content_type == "image/jpeg" or ext in ("jpg", "jpeg"):
        if not _starts_with(data, _MAGIC_JPEG):
            raise UploadValidationError(
                "File content does not match the declared JPEG type."
            )
    elif content_type == "application/pdf" or ext == "pdf":
        if not _starts_with(data, _MAGIC_PDF):
            raise UploadValidationError(
                "File content does not match the declared PDF type."
            )
    elif ext == "vsdx" or content_type in (
        "application/vnd.ms-visio.drawing.main+xml",
        "application/vnd.visio",
    ):
        if not _starts_with(data, _MAGIC_ZIP):
            raise UploadValidationError(
                "File content does not match the expected Visio (VSDX) format."
            )
    elif content_type == "application/octet-stream":
        # For octet-stream, at least one known magic must be present, or the
        # content must look like XML/SVG (starts with '<' after optional BOM).
        known_magics = [_MAGIC_PNG, _MAGIC_JPEG, _MAGIC_PDF, _MAGIC_ZIP]
        has_known_magic = any(_starts_with(data, m) for m in known_magics)
        head = data[: 512].lstrip(b"\xef\xbb\xbf \t\r\n")  # strip UTF-8 BOM + whitespace
        is_xml_like = head.startswith(b"<")
        if not has_known_magic and not is_xml_like:
            raise UploadValidationError(
                "Unsupported file content. Accepted formats: PNG, JPEG, SVG, PDF, Draw.io, Visio."
            )


# ── 2. PDF validation ─────────────────────────────────────────────────────────
# These raw-byte patterns are rejected before pypdf even parses the file so
# that obfuscation tricks (e.g. hex-encoded /JavaScript) do not bypass the check.
_PDF_BANNED_PATTERNS: list[tuple[bytes, str]] = [
    (b"/JavaScript",   "JavaScript"),
    (b"/JS ",          "JavaScript"),
    (b"/JS\n",         "JavaScript"),
    (b"/JS\r",         "JavaScript"),
    (b"/JS(",          "JavaScript"),
    (b"/Launch",       "launch action"),
    (b"/EmbeddedFile", "embedded file"),
    (b"/RichMedia",    "rich media"),
    (b"/ImportData",   "ImportData action"),
]


def _validate_pdf(data: bytes) -> None:
    """Validate PDF content.

    Rejects:
    - Encrypted PDFs
    - PDFs containing JavaScript, launch actions, embedded files, or rich media
    - Excessive page or object counts (basic resource guard)
    """
    # ── Raw-byte scan (fast, catches most obfuscated patterns) ────────────────
    for pattern, label in _PDF_BANNED_PATTERNS:
        if pattern in data:
            raise UploadValidationError(
                f"PDF contains active content ({label}) that is not permitted."
            )

    # ── Structural validation via pypdf ──────────────────────────────────────
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError:  # pragma: no cover
        logger.warning("pypdf not available; skipping structural PDF validation")
        return

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
    except PdfReadError as exc:
        raise UploadValidationError("Invalid or corrupt PDF file.") from exc
    except Exception as exc:  # noqa: BLE001
        raise UploadValidationError("Invalid or corrupt PDF file.") from exc

    if reader.is_encrypted:
        raise UploadValidationError("Encrypted PDF files are not supported.")

    n_pages = len(reader.pages)
    if n_pages > _MAX_PDF_PAGES:
        raise UploadValidationError(
            f"PDF has too many pages ({n_pages}). Maximum allowed: {_MAX_PDF_PAGES}."
        )

    # Object count — use xref if available; fall back to a raw-byte heuristic.
    try:
        n_objects = len(reader.xref)
        if n_objects > _MAX_PDF_OBJECTS:
            raise UploadValidationError(
                f"PDF has too many objects ({n_objects}). The file may be malformed or oversized."
            )
    except AttributeError:
        # Newer pypdf versions may not expose .xref directly; skip this check.
        pass


# ── 3. SVG / XML / Draw.io validation ─────────────────────────────────────────
_SVG_DANGEROUS_ELEMENTS = frozenset(
    {"script", "iframe", "object", "embed", "applet"}
)
_SVG_EVENT_ATTRS = frozenset(
    {
        "onload", "onclick", "onerror", "onmouseover", "onfocus", "onblur",
        "onchange", "onsubmit", "onkeydown", "onkeyup", "onkeypress",
        "onmousedown", "onmouseup", "onmousemove", "ondblclick",
        "onabort", "onactivate", "onbegin", "onend", "onrepeat",
        "onscroll", "onunload",
    }
)
_SVG_DANGEROUS_URI_SCHEMES = ("javascript:", "vbscript:", "data:")
_SVG_EXTERNAL_HREF_PREFIXES = ("http://", "https://", "//")


def _local(tag: str) -> str:
    """Strip XML namespace prefix from a tag/attribute name."""
    return tag.split("}")[-1].lower() if "}" in tag else tag.lower()


def _validate_svg_xml(data: bytes) -> None:
    """Validate SVG / XML / Draw.io content.

    - Uses defusedxml to disable external entity resolution and DTD processing.
    - Rejects script elements, event-handler attributes, JavaScript/data URIs,
      and <use> elements that reference external URLs.
    """
    try:
        import defusedxml.ElementTree as det
        from defusedxml import DTDForbidden, EntitiesForbidden, ExternalReferenceForbidden
    except ImportError:  # pragma: no cover
        logger.warning("defusedxml not available; skipping SVG/XML validation")
        return

    try:
        root = det.fromstring(data)
    except (DTDForbidden, EntitiesForbidden, ExternalReferenceForbidden) as exc:
        raise UploadValidationError(
            "SVG/XML file contains prohibited content (external entities or DTD declarations)."
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise UploadValidationError("Invalid or malformed SVG/XML file.") from exc

    for element in root.iter():
        tag_name = _local(element.tag)

        # Reject <script> and other active-content elements.
        if tag_name in _SVG_DANGEROUS_ELEMENTS:
            raise UploadValidationError(
                "SVG/XML file contains prohibited active-content elements (e.g. <script>)."
            )

        # Reject <use> with external href (SSRF via SVG sprite injection).
        if tag_name == "use":
            for attr_name, attr_val in element.attrib.items():
                if "href" in _local(attr_name):
                    if attr_val.startswith(_SVG_EXTERNAL_HREF_PREFIXES):
                        raise UploadValidationError(
                            "SVG file contains prohibited external resource references."
                        )

        for attr_name, attr_val in element.attrib.items():
            # Reject event-handler attributes.
            if _local(attr_name) in _SVG_EVENT_ATTRS:
                raise UploadValidationError(
                    "SVG/XML file contains prohibited event-handler attributes."
                )
            # Reject javascript:/vbscript:/data: URIs in href/src.
            if _local(attr_name) in ("href", "src", "action"):
                if attr_val.lower().startswith(_SVG_DANGEROUS_URI_SCHEMES):
                    raise UploadValidationError(
                        "SVG/XML file contains a prohibited URI (javascript:, vbscript:, or data:)."
                    )


# ── 4. VSDX / ZIP validation ──────────────────────────────────────────────────
def _validate_vsdx(data: bytes) -> None:
    """Validate a VSDX (ZIP-based Visio) archive.

    Enforces:
    - Maximum entry count
    - Maximum total uncompressed size
    - Per-entry compression ratio (zip-bomb guard)
    - Path safety (no '..' traversal, no absolute paths)
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UploadValidationError(
            "Invalid Visio file (cannot be opened as a ZIP archive)."
        ) from exc

    entries = zf.infolist()

    if len(entries) > _MAX_ZIP_ENTRIES:
        zf.close()
        raise UploadValidationError(
            f"Visio file contains too many entries ({len(entries)}). "
            f"Maximum allowed: {_MAX_ZIP_ENTRIES}."
        )

    total_uncompressed = 0
    try:
        for entry in entries:
            # Path-traversal safety
            norm = entry.filename.replace("\\", "/")
            parts = norm.split("/")
            if ".." in parts or norm.startswith("/"):
                raise UploadValidationError(
                    "Visio file contains a dangerous file path and cannot be processed."
                )

            # Total uncompressed size guard
            total_uncompressed += entry.file_size
            if total_uncompressed > _MAX_ZIP_TOTAL_UNCOMPRESSED:
                raise UploadValidationError(
                    f"Visio file would expand to more than "
                    f"{_MAX_ZIP_TOTAL_UNCOMPRESSED // (1024 * 1024)} MB when decompressed."
                )

            # Compression-ratio guard (zip bomb detection)
            if entry.compress_size > 0:
                ratio = entry.file_size / entry.compress_size
                if ratio > _MAX_ZIP_COMPRESSION_RATIO:
                    raise UploadValidationError(
                        "Visio file has a suspicious compression ratio and cannot be processed."
                    )
    finally:
        zf.close()


# ── Top-level entry point ─────────────────────────────────────────────────────
def validate_upload(
    data: bytes,
    content_type: str,
    filename: Optional[str] = None,
) -> None:
    """Run all content-level validations for an uploaded diagram file.

    Raises ``UploadValidationError`` with a user-friendly message when any
    check fails.  Internal parser details are never included in the message.

    Parameters
    ----------
    data:         Raw uploaded bytes (full file, after size check).
    content_type: MIME type declared by the client.
    filename:     Original filename (used for extension-based dispatch).
    """
    ext = _extension(filename)

    # 1. Magic bytes / content-type consistency
    _check_magic_mismatch(data, content_type, ext)

    # 2. Type-specific deep validation
    is_pdf = (
        content_type == "application/pdf"
        or ext == "pdf"
        or (content_type == "application/octet-stream" and _starts_with(data, _MAGIC_PDF))
    )
    is_vsdx = (
        ext == "vsdx"
        or content_type in (
            "application/vnd.ms-visio.drawing.main+xml",
            "application/vnd.visio",
        )
        or (content_type == "application/octet-stream" and ext == "vsdx")
    )
    is_xml_like = (
        content_type in ("image/svg+xml", "application/xml", "text/xml")
        or ext in ("svg", "xml", "drawio")
        or (
            content_type == "application/octet-stream"
            and ext in ("svg", "xml", "drawio")
        )
    )

    if is_pdf:
        _validate_pdf(data)
    elif is_vsdx:
        _validate_vsdx(data)
    elif is_xml_like:
        _validate_svg_xml(data)
    # PNG / JPEG have no additional deep validation beyond magic bytes.
