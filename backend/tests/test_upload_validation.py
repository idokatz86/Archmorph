"""Tests for hardened diagram-upload validation.

Covers: magic-byte mismatches, PDF active content/encryption, SVG script /
event-handler / XXE, VSDX zip-bomb / path-traversal, and octet-stream
mismatches.  All malicious payloads are generated in-process — no external
fixture files are needed.
"""

from __future__ import annotations

import io
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("ARCHMORPH_EXPORT_CAPABILITY_REQUIRED", "false")
os.environ.setdefault("ENVIRONMENT", "test")

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402
from upload_validator import (  # noqa: E402
    UploadValidationError,
    validate_upload,
)


# ─────────────────────────────────────────────────────────────
# Fixture helpers
# ─────────────────────────────────────────────────────────────

def _make_minimal_pdf() -> bytes:
    """Build a minimal valid PDF (no active content)."""
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _make_encrypted_pdf() -> bytes:
    """Build a minimal password-encrypted PDF."""
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=612, height=792)
    w.encrypt("secret")
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _make_pdf_with_js() -> bytes:
    """Build a PDF containing a /JavaScript OpenAction."""
    # Hand-crafted minimal PDF with /JavaScript in the catalog.
    # The xref offsets are approximate; pypdf opens it with strict=False.
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R /OpenAction 4 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
        b"4 0 obj\n<< /S /JavaScript /JS (app.alert(1);) >>\nendobj\n"
        b"xref\n0 5\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000068 00000 n \n"
        b"0000000125 00000 n \n"
        b"0000000206 00000 n \n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\n"
        b"startxref\n270\n%%EOF\n"
    )


def _make_pdf_with_launch() -> bytes:
    """Build a PDF with a /Launch action."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R /OpenAction 4 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
        b"4 0 obj\n<< /S /Launch /F (calc.exe) >>\nendobj\n"
        b"xref\n0 5\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000068 00000 n \n"
        b"0000000125 00000 n \n"
        b"0000000206 00000 n \n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\n"
        b"startxref\n270\n%%EOF\n"
    )


def _make_pdf_with_embedded_file() -> bytes:
    """Build a PDF with /EmbeddedFile in raw bytes."""
    return b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n/EmbeddedFile\n%%EOF\n"


def _make_zip_bomb_vsdx() -> bytes:
    """Build a VSDX (ZIP) whose single entry has a very high compression ratio."""
    # 5 MB of zeros compresses very well; ratio will far exceed 100.
    bomb_content = b"\x00" * (5 * 1024 * 1024)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("visio/pages/page1.xml", bomb_content)
    return buf.getvalue()


def _make_path_traversal_vsdx() -> bytes:
    """Build a VSDX (ZIP) with a path-traversal entry."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("../../../etc/passwd")
        zf.writestr(info, b"root:x:0:0:")
    return buf.getvalue()


def _make_too_many_entries_vsdx(n: int = 201) -> bytes:
    """Build a VSDX (ZIP) with more than the allowed number of entries."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(n):
            zf.writestr(f"entry_{i}.xml", b"<xml/>")
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────
# TestClient fixture
# ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _upload(client, filename: str, data: bytes, content_type: str) -> int:
    resp = client.post(
        "/api/projects/proj-001/diagrams",
        files={"file": (filename, io.BytesIO(data), content_type)},
    )
    return resp.status_code


# ─────────────────────────────────────────────────────────────
# Unit tests for validate_upload() directly
# ─────────────────────────────────────────────────────────────

class TestValidateUploadUnit:
    """Direct unit tests for the upload_validator module."""

    # ── PNG ──────────────────────────────────────────────────
    def test_valid_png_passes(self):
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        validate_upload(data, "image/png", "test.png")  # must not raise

    def test_png_wrong_magic_raises(self):
        data = b"\xff\xd8\xff" + b"\x00" * 50  # JPEG magic
        with pytest.raises(UploadValidationError, match="PNG"):
            validate_upload(data, "image/png", "test.png")

    def test_png_extension_wrong_magic_raises(self):
        data = b"RIFF" + b"\x00" * 50  # not PNG
        with pytest.raises(UploadValidationError):
            validate_upload(data, "application/octet-stream", "bad.png")

    # ── JPEG ─────────────────────────────────────────────────
    def test_valid_jpeg_passes(self):
        data = b"\xff\xd8\xff\xe0" + b"\x00" * 50
        validate_upload(data, "image/jpeg", "photo.jpg")

    def test_jpeg_wrong_magic_raises(self):
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        with pytest.raises(UploadValidationError, match="JPEG"):
            validate_upload(data, "image/jpeg", "photo.jpg")

    # ── PDF ───────────────────────────────────────────────────
    def test_valid_pdf_passes(self):
        pdf = _make_minimal_pdf()
        validate_upload(pdf, "application/pdf", "arch.pdf")

    def test_pdf_wrong_magic_raises(self):
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        with pytest.raises(UploadValidationError, match="PDF"):
            validate_upload(data, "application/pdf", "arch.pdf")

    def test_pdf_with_javascript_raises(self):
        pdf = _make_pdf_with_js()
        with pytest.raises(UploadValidationError, match="JavaScript"):
            validate_upload(pdf, "application/pdf", "arch.pdf")

    def test_pdf_with_launch_action_raises(self):
        pdf = _make_pdf_with_launch()
        with pytest.raises(UploadValidationError, match="launch action"):
            validate_upload(pdf, "application/pdf", "arch.pdf")

    def test_pdf_with_embedded_file_raises(self):
        pdf = _make_pdf_with_embedded_file()
        with pytest.raises(UploadValidationError, match="embedded file"):
            validate_upload(pdf, "application/pdf", "arch.pdf")

    def test_encrypted_pdf_raises(self):
        pdf = _make_encrypted_pdf()
        with pytest.raises(UploadValidationError, match="[Ee]ncrypt"):
            validate_upload(pdf, "application/pdf", "arch.pdf")

    # ── SVG / XML ─────────────────────────────────────────────
    def test_valid_svg_passes(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'
        validate_upload(svg, "image/svg+xml", "arch.svg")

    def test_svg_with_script_raises(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        with pytest.raises(UploadValidationError, match="script"):
            validate_upload(svg, "image/svg+xml", "arch.svg")

    def test_svg_with_onclick_raises(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><rect onclick="evil()"/></svg>'
        with pytest.raises(UploadValidationError, match="event-handler"):
            validate_upload(svg, "image/svg+xml", "arch.svg")

    def test_svg_with_javascript_href_raises(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><a href="javascript:alert(1)"><text>x</text></a></svg>'
        with pytest.raises(UploadValidationError, match="javascript"):
            validate_upload(svg, "image/svg+xml", "arch.svg")

    def test_svg_with_javascript_src_raises(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><image src="javascript:alert(1)"/></svg>'
        with pytest.raises(UploadValidationError, match="javascript"):
            validate_upload(svg, "image/svg+xml", "arch.svg")

    def test_svg_with_javascript_action_raises(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><form action="javascript:alert(1)"/></svg>'
        with pytest.raises(UploadValidationError, match="javascript"):
            validate_upload(svg, "image/svg+xml", "arch.svg")

    def test_svg_xxe_raises(self):
        xxe = (
            b'<?xml version="1.0"?>'
            b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
            b'<svg xmlns="http://www.w3.org/2000/svg"><text>&xxe;</text></svg>'
        )
        with pytest.raises(UploadValidationError, match="external entities|DTD"):
            validate_upload(xxe, "image/svg+xml", "arch.svg")

    def test_svg_external_use_href_raises(self):
        svg = (
            b'<svg xmlns="http://www.w3.org/2000/svg">'
            b'<use href="https://evil.example.com/icon.svg#icon"/>'
            b"</svg>"
        )
        with pytest.raises(UploadValidationError, match="external resource"):
            validate_upload(svg, "image/svg+xml", "arch.svg")

    def test_valid_drawio_passes(self):
        drawio = b'<mxGraphModel><root><mxCell id="0"/></root></mxGraphModel>'
        validate_upload(drawio, "application/xml", "arch.drawio")

    # ── VSDX / ZIP ────────────────────────────────────────────
    def test_valid_vsdx_passes(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("visio/pages/page1.xml", b"<xml/>")
        validate_upload(
            buf.getvalue(),
            "application/vnd.ms-visio.drawing.main+xml",
            "arch.vsdx",
        )

    def test_vsdx_wrong_magic_raises(self):
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        with pytest.raises(UploadValidationError, match="Visio"):
            validate_upload(
                data,
                "application/vnd.ms-visio.drawing.main+xml",
                "arch.vsdx",
            )

    def test_zip_bomb_vsdx_raises(self):
        vsdx = _make_zip_bomb_vsdx()
        with pytest.raises(UploadValidationError, match="compress"):
            validate_upload(
                vsdx,
                "application/vnd.ms-visio.drawing.main+xml",
                "arch.vsdx",
            )

    def test_path_traversal_vsdx_raises(self):
        vsdx = _make_path_traversal_vsdx()
        with pytest.raises(UploadValidationError, match="path"):
            validate_upload(
                vsdx,
                "application/vnd.ms-visio.drawing.main+xml",
                "arch.vsdx",
            )

    def test_too_many_entries_vsdx_raises(self):
        vsdx = _make_too_many_entries_vsdx(201)
        with pytest.raises(UploadValidationError, match="too many entries"):
            validate_upload(
                vsdx,
                "application/vnd.ms-visio.drawing.main+xml",
                "arch.vsdx",
            )

    # ── octet-stream ──────────────────────────────────────────
    def test_octet_stream_random_bytes_raises(self):
        data = b"\x00\x01\x02\x03\xfe\xff" + b"\xaa" * 100
        with pytest.raises(UploadValidationError, match="Unsupported"):
            validate_upload(data, "application/octet-stream", "mystery.bin")

    def test_octet_stream_pdf_magic_dispatches_to_pdf(self):
        """octet-stream with PDF magic is accepted if the PDF is clean."""
        pdf = _make_minimal_pdf()
        validate_upload(pdf, "application/octet-stream", "arch.pdf")

    def test_octet_stream_xml_like_accepted(self):
        xml = b'<mxGraphModel><root><mxCell id="0"/></root></mxGraphModel>'
        validate_upload(xml, "application/octet-stream", "arch.drawio")

    def test_octet_stream_vsdx_dispatches_to_zip(self):
        vsdx = _make_path_traversal_vsdx()
        with pytest.raises(UploadValidationError, match="path"):
            validate_upload(vsdx, "application/octet-stream", "arch.vsdx")


# ─────────────────────────────────────────────────────────────
# Integration tests via HTTP API
# ─────────────────────────────────────────────────────────────

class TestUploadValidationHTTP:
    """End-to-end validation tests via the FastAPI test client."""

    def test_valid_png_upload_succeeds(self, client):
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        assert _upload(client, "test.png", data, "image/png") == 200

    def test_png_with_jpeg_bytes_rejected(self, client):
        data = b"\xff\xd8\xff\xe0" + b"\x00" * 50
        assert _upload(client, "bad.png", data, "image/png") == 400

    def test_pdf_with_javascript_rejected_via_api(self, client):
        pdf = _make_pdf_with_js()
        assert _upload(client, "arch.pdf", pdf, "application/pdf") == 400

    def test_encrypted_pdf_rejected_via_api(self, client):
        pdf = _make_encrypted_pdf()
        assert _upload(client, "arch.pdf", pdf, "application/pdf") == 400

    def test_svg_script_rejected_via_api(self, client):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        assert _upload(client, "arch.svg", svg, "image/svg+xml") == 400

    def test_svg_xxe_rejected_via_api(self, client):
        xxe = (
            b'<?xml version="1.0"?>'
            b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
            b'<svg xmlns="http://www.w3.org/2000/svg"><text>&xxe;</text></svg>'
        )
        assert _upload(client, "arch.svg", xxe, "image/svg+xml") == 400

    def test_zip_bomb_vsdx_rejected_via_api(self, client):
        vsdx = _make_zip_bomb_vsdx()
        assert (
            _upload(client, "arch.vsdx", vsdx, "application/vnd.ms-visio.drawing.main+xml")
            == 400
        )

    def test_path_traversal_vsdx_rejected_via_api(self, client):
        vsdx = _make_path_traversal_vsdx()
        assert (
            _upload(client, "arch.vsdx", vsdx, "application/vnd.ms-visio.drawing.main+xml")
            == 400
        )

    def test_octet_stream_garbage_rejected_via_api(self, client):
        data = b"\x00\x01\x02\x03\xfe\xff" + b"\xaa" * 100
        assert _upload(client, "mystery.bin", data, "application/octet-stream") == 400

    def test_error_response_is_envelope(self, client):
        """Error responses must follow the ArchmorphException envelope shape."""
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        resp = client.post(
            "/api/projects/proj-001/diagrams",
            files={"file": ("arch.svg", io.BytesIO(svg), "image/svg+xml")},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert "error" in body
        assert "message" in body["error"]
        # Internal details must not leak into the user-facing message
        msg = body["error"]["message"]
        assert "Traceback" not in msg
        assert "Exception" not in msg

    def test_error_message_does_not_leak_internals(self, client):
        """The 400 message must be a plain-English user-facing string."""
        pdf = _make_pdf_with_js()
        resp = client.post(
            "/api/projects/proj-001/diagrams",
            files={"file": ("arch.pdf", io.BytesIO(pdf), "application/pdf")},
        )
        assert resp.status_code == 400
        msg = resp.json()["error"]["message"]
        # Must not contain raw exception class names or file paths
        assert "pypdf" not in msg.lower()
        assert "traceback" not in msg.lower()
        assert "file://" not in msg.lower()
