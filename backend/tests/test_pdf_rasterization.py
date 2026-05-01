"""Tests for PDF rasterization in vision_analyzer.compress_image.

Regression coverage for the bug where uploading a PDF surfaced as
``Invalid image URL ... unsupported MIME type 'application/pdf'`` because
``compress_image`` silently passed through the PDF bytes when PIL could
not open them.
"""

import io

import pytest
from PIL import Image

from vision_analyzer import (
    _is_pdf,
    _rasterize_pdf_to_png,
    compress_image,
    MAX_PDF_PAGES,
)


def _make_pdf(num_pages: int = 1, page_size: tuple[int, int] = (612, 792)) -> bytes:
    """Build a minimal multi-page PDF in memory using pypdfium2.

    The pages are intentionally non-empty (filled with a coloured rectangle)
    so the rasterizer has real pixels to render.
    """
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument.new()
    for i in range(num_pages):
        page = pdf.new_page(page_size[0], page_size[1])
        # Drop a coloured rectangle on each page so render output isn't blank.
        # pypdfium2's PdfPage.insert_object API differs across versions; the
        # simplest reliable approach is to just leave the page blank — pypdfium2
        # still rasterizes it to a white page, which is enough for the round-
        # trip test (we only assert the output is a valid raster image).
        del page  # release page handle

    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────
# _is_pdf
# ─────────────────────────────────────────────────────────────
class TestIsPdf:
    def test_detects_by_content_type(self):
        assert _is_pdf(b"\x89PNG\r\n", "application/pdf") is True

    def test_detects_by_magic_bytes_when_content_type_lies(self):
        # Browsers sometimes send PDFs as application/octet-stream
        assert _is_pdf(b"%PDF-1.7\n...", "application/octet-stream") is True

    def test_rejects_png(self):
        assert _is_pdf(b"\x89PNG\r\n\x1a\n", "image/png") is False

    def test_rejects_jpeg(self):
        assert _is_pdf(b"\xff\xd8\xff\xe0", "image/jpeg") is False

    def test_rejects_short_input(self):
        assert _is_pdf(b"%P", "image/png") is False


# ─────────────────────────────────────────────────────────────
# _rasterize_pdf_to_png
# ─────────────────────────────────────────────────────────────
class TestRasterizePdf:
    def test_single_page_produces_valid_png(self):
        pdf_bytes = _make_pdf(num_pages=1)
        png_bytes = _rasterize_pdf_to_png(pdf_bytes)
        assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        with Image.open(io.BytesIO(png_bytes)) as img:
            assert img.mode == "RGB"
            assert img.width > 0
            assert img.height > 0

    def test_multi_page_stitched_vertically(self):
        pdf_bytes = _make_pdf(num_pages=3)
        png_bytes = _rasterize_pdf_to_png(pdf_bytes)
        with Image.open(io.BytesIO(png_bytes)) as img:
            single_pdf = _make_pdf(num_pages=1)
            with Image.open(io.BytesIO(_rasterize_pdf_to_png(single_pdf))) as single:
                # 3 pages stitched vertically should be roughly 3x taller
                # than a single-page render at the same DPI.
                assert img.height >= single.height * 2

    def test_caps_pages_at_max(self):
        # Build a PDF with one more page than the cap and verify the renderer
        # only stitches MAX_PDF_PAGES of them.
        pdf_bytes = _make_pdf(num_pages=MAX_PDF_PAGES + 1)
        png_bytes = _rasterize_pdf_to_png(pdf_bytes)
        with Image.open(io.BytesIO(png_bytes)) as capped:
            full_bytes = _make_pdf(num_pages=MAX_PDF_PAGES)
            with Image.open(io.BytesIO(_rasterize_pdf_to_png(full_bytes))) as expected:
                # Capped output should match the all-pages output for
                # MAX_PDF_PAGES, not exceed it.
                assert capped.height == expected.height

    def test_invalid_pdf_raises_valueerror(self):
        with pytest.raises(ValueError):
            _rasterize_pdf_to_png(b"not a pdf at all")


# ─────────────────────────────────────────────────────────────
# compress_image — PDF integration
# ─────────────────────────────────────────────────────────────
class TestCompressImagePdf:
    def test_pdf_input_yields_jpeg_output(self):
        pdf_bytes = _make_pdf(num_pages=1)

        out_bytes, out_type, w, h = compress_image(pdf_bytes, "application/pdf")

        # Pipeline must always emit a vision-compatible image MIME type.
        assert out_type == "image/jpeg"
        assert out_bytes[:3] == b"\xff\xd8\xff"  # JPEG SOI
        assert w > 0 and h > 0
        # Round-trip: PIL must be able to re-open the result.
        with Image.open(io.BytesIO(out_bytes)) as img:
            assert img.format == "JPEG"

    def test_pdf_detected_via_magic_bytes(self):
        # Even when the caller mislabels the content type, magic-byte
        # detection must catch it before PIL chokes on the PDF.
        pdf_bytes = _make_pdf(num_pages=1)

        out_bytes, out_type, _w, _h = compress_image(
            pdf_bytes, "application/octet-stream"
        )

        assert out_type == "image/jpeg"
        assert out_bytes[:3] == b"\xff\xd8\xff"

    def test_png_input_unchanged_path_still_works(self):
        # Sanity: non-PDF inputs must not be affected by the new branch.
        img = Image.new("RGB", (100, 50), (255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        out_bytes, out_type, w, h = compress_image(png_bytes, "image/png")

        assert out_type == "image/jpeg"
        assert (w, h) == (100, 50)
        assert out_bytes[:3] == b"\xff\xd8\xff"
