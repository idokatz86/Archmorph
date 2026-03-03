"""Tests for visio_parser module (#281)."""
import io
import zipfile

from visio_parser import is_vsdx, VisioShape, VisioConnection


class TestIsVsdx:
    def test_valid_zip_signature(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("visio/pages/page1.xml", '<PageContents/>')
        assert is_vsdx(buf.getvalue()) is True

    def test_non_zip_returns_false(self):
        assert is_vsdx(b"not a zip file") is False

    def test_empty_bytes_returns_false(self):
        assert is_vsdx(b"") is False


class TestVisioShape:
    def test_to_dict(self):
        shape = VisioShape(
            shape_id="1", text="Web Server", master_name="Server",
            x=100, y=200, width=50, height=50, page="Page-1",
        )
        d = shape.to_dict()
        assert d["text"] == "Web Server"
        assert d["shape_id"] == "1"

    def test_shape_fields(self):
        shape = VisioShape("2", "DB", "Database", 0, 0, 40, 40, "Page-1")
        assert shape.text == "DB"
        assert shape.master_name == "Database"


class TestVisioConnection:
    def test_to_dict(self):
        conn = VisioConnection("1", "2", "data flow")
        d = conn.to_dict()
        assert d["from"] == "1"
        assert d["to"] == "2"
        assert d["label"] == "data flow"
