"""
Archmorph — Icon Registry & Library Builder Tests

Unit tests covering:
  - SVG sanitization (script removal, external href blocking, dimension extraction)
  - Icon normalization and canonical IDs
  - Draw.io XML library output validity
  - Excalidraw library JSON schema
  - Visio stencil pack structure
  - API route responses
  - Registry search / resolve
"""

import base64
import io
import json
import os
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ensure backend is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Disable rate limiting for tests
os.environ["RATE_LIMIT_ENABLED"] = "false"
# Disable lazy auto-load of builtin packs (#587) so fixture-driven tests
# don't get contaminated by 400+ pre-loaded icons. The new lazy-load tests
# in `test_icon_registry_lazy_load.py` exercise that path explicitly.
os.environ["ICON_REGISTRY_AUTOLOAD"] = "0"

from icons.svg_sanitizer import (
    SVGSanitizationError,
    validate_svg,
    extract_svg_dimensions,
    MAX_SVG_SIZE,
)
from icons.models import Provider, IconMeta, IconPackManifest, IconPackItem
from icons import registry
from icons.builders.drawio import build_drawio_library
from icons.builders.excalidraw import build_excalidraw_library
from icons.builders.visio import build_visio_stencil_pack


# ────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────

VALID_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48"><rect width="48" height="48" fill="#0078D4"/></svg>'
VALID_SVG_NO_DIMS = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><circle cx="32" cy="32" r="16" fill="red"/></svg>'
SCRIPT_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48"><script>alert("xss")</script><rect width="48" height="48"/></svg>'
ONLOAD_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" onload="alert(1)"><rect width="48" height="48"/></svg>'
EXTERNAL_HREF_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="48" height="48"><image href="https://evil.com/steal.png"/></svg>'
FOREIGNOBJECT_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48"><foreignObject><body xmlns="http://www.w3.org/1999/xhtml"><script>alert(1)</script></body></foreignObject></svg>'
STYLE_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48"><style>rect{background:url(https://evil.example/x)}</style><rect width="48" height="48"/></svg>'

API_HEADERS = {"X-API-Key": "test-api-key"}


SAMPLE_DIR = Path(__file__).parent.parent / "samples"


@pytest.fixture(autouse=True)
def _clean_registry():
    """Reset registry between tests."""
    registry.clear_all()
    yield
    registry.clear_all()


@pytest.fixture
def azure_pack_path():
    """Path to the Azure sample pack."""
    return SAMPLE_DIR / "azure"


@pytest.fixture
def small_zip_pack():
    """Create a minimal in-memory ZIP icon pack."""
    buf = io.BytesIO()
    manifest = {
        "name": "Test Pack",
        "provider": "azure",
        "version": "1.0.0",
        "description": "Test icon pack",
        "icons": [
            {
                "file": "test_icon.svg",
                "name": "Test Icon",
                "category": "compute",
                "tags": ["test"],
                "service_id": "test-svc-1",
            }
        ],
    }
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("metadata.json", json.dumps(manifest))
        zf.writestr("test_icon.svg", VALID_SVG.decode())
    return buf.getvalue()


def _zip_pack(icon_file: str, icon_name: str) -> bytes:
    return _zip_pack_with_svg(icon_file, icon_name, VALID_SVG)


def _zip_pack_with_svg(icon_file: str, icon_name: str, svg: bytes) -> bytes:
    buf = io.BytesIO()
    manifest = {
        "name": icon_name,
        "provider": "azure",
        "version": "1.0.0",
        "icons": [
            {
                "file": icon_file,
                "name": icon_name,
                "category": "compute",
                "tags": ["test"],
            }
        ],
    }
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("metadata.json", json.dumps(manifest))
        zf.writestr(icon_file, svg.decode())
    return buf.getvalue()


# ────────────────────────────────────────────────────────────
# SVG Sanitization Tests
# ────────────────────────────────────────────────────────────

class TestSVGSanitizer:
    """SVG validation and sanitization."""

    def test_valid_svg_passes(self):
        result = validate_svg(VALID_SVG)
        assert "svg" in result
        assert "rect" in result

    def test_script_tag_stripped(self):
        """Sanitizer strips scripts — result should not contain <script>."""
        result = validate_svg(SCRIPT_SVG)
        assert "script" not in result.lower()
        assert "alert" not in result

    def test_onload_handler_stripped(self):
        """Sanitizer strips on* attrs — result should not contain onload."""
        result = validate_svg(ONLOAD_SVG)
        assert "onload" not in result.lower()

    def test_external_href_stripped(self):
        """Sanitizer strips external hrefs."""
        result = validate_svg(EXTERNAL_HREF_SVG)
        assert "evil.com" not in result

    def test_foreignobject_stripped(self):
        """Sanitizer strips foreignObject elements."""
        result = validate_svg(FOREIGNOBJECT_SVG)
        assert "foreignobject" not in result.lower()
        assert "alert" not in result

    def test_style_block_stripped(self):
        """Sanitizer strips style blocks from uploaded SVGs."""
        result = validate_svg(STYLE_SVG)
        assert "style" not in result.lower()
        assert "evil.example" not in result

    def test_oversized_svg_rejected(self):
        huge = b'<svg xmlns="http://www.w3.org/2000/svg">' + b"x" * (MAX_SVG_SIZE + 1) + b"</svg>"
        with pytest.raises(SVGSanitizationError, match="(?i)size"):
            validate_svg(huge)

    def test_empty_input_rejected(self):
        with pytest.raises(SVGSanitizationError):
            validate_svg(b"")

    def test_non_svg_xml_rejected(self):
        with pytest.raises(SVGSanitizationError):
            validate_svg(b"<html><body>hello</body></html>")

    def test_extract_dimensions_explicit(self):
        w, h = extract_svg_dimensions(VALID_SVG.decode())
        assert w == 48
        assert h == 48

    def test_extract_dimensions_from_viewbox(self):
        w, h = extract_svg_dimensions(VALID_SVG_NO_DIMS.decode())
        assert w == 64
        assert h == 64

    def test_extract_dimensions_default(self):
        minimal = '<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'
        w, h = extract_svg_dimensions(minimal)
        assert w == 64  # default (no width/height/viewBox)
        assert h == 64


# ────────────────────────────────────────────────────────────
# Registry Tests
# ────────────────────────────────────────────────────────────

class TestIconRegistry:
    """Icon registry ingestion, lookup, and search."""

    def test_ingest_folder_pack(self, azure_pack_path):
        if not azure_pack_path.exists():
            pytest.skip("Sample azure pack not found")
        result = registry.ingest_icon_pack(azure_pack_path, pack_id="azure-core")
        assert result["pack_id"] == "azure-core"
        assert result["ingested"] > 0

    def test_ingest_zip_pack(self, small_zip_pack):
        result = registry.ingest_icon_pack(small_zip_pack, pack_id="test-zip")
        assert result["pack_id"] == "test-zip"
        assert result["ingested"] == 1
        assert result["failed"] == 0

    def test_canonical_id_deterministic(self):
        id1 = registry._canonical_id("Virtual Machine", "azure", "compute")
        id2 = registry._canonical_id("Virtual Machine", "azure", "compute")
        assert id1 == id2
        assert "virtual_machine" in id1
        assert "azure" in id1

    def test_canonical_id_normalized(self):
        """Name and category are lowered; provider is used as-is."""
        id1 = registry._canonical_id("App Service", "azure", "compute")
        id2 = registry._canonical_id("app service", "azure", "Compute")
        assert id1 == id2

    def test_get_icon_after_ingest(self, small_zip_pack):
        registry.ingest_icon_pack(small_zip_pack, pack_id="t1")
        icons = registry.get_pack_icons("t1")
        assert len(icons) == 1
        icon = icons[0]
        assert icon.meta.name == "Test Icon"
        assert icon.meta.service_id == "test-svc-1"
        # Can also retrieve by ID
        fetched = registry.get_icon(icon.meta.id)
        assert fetched is not None
        assert fetched.svg == icon.svg

    def test_resolve_icon_by_service_id(self, small_zip_pack):
        registry.ingest_icon_pack(small_zip_pack, pack_id="t2")
        icon = registry.resolve_icon("test-svc-1")
        assert icon is not None
        assert icon.meta.service_id == "test-svc-1"

    def test_resolve_icon_not_found(self):
        result = registry.resolve_icon("nonexistent-service")
        assert result is None

    def test_search_by_provider(self, small_zip_pack):
        registry.ingest_icon_pack(small_zip_pack, pack_id="t3")
        results = registry.search_icons(provider="azure")
        assert len(results) >= 1
        # search_icons returns IconMeta directly
        assert all(r.provider == "azure" for r in results)

    def test_search_by_query(self, small_zip_pack):
        registry.ingest_icon_pack(small_zip_pack, pack_id="t4")
        results = registry.search_icons(query="test")
        assert len(results) >= 1

    def test_search_empty(self):
        results = registry.search_icons(query="zzz_nonexistent_zzz")
        assert len(results) == 0

    def test_list_packs_empty(self):
        packs = registry.list_packs()
        assert packs == []

    def test_list_packs_after_ingest(self, small_zip_pack):
        registry.ingest_icon_pack(small_zip_pack, pack_id="pack-a")
        packs = registry.list_packs()
        pack_ids = [p["pack_id"] for p in packs]
        assert "pack-a" in pack_ids

    def test_asset_cache_roundtrip(self):
        registry.set_cached_asset("k1", b"data123")
        assert registry.get_cached_asset("k1") == b"data123"

    def test_clear_all_resets(self, small_zip_pack):
        registry.ingest_icon_pack(small_zip_pack, pack_id="c1")
        assert len(registry.list_packs()) > 0
        registry.clear_all()
        assert len(registry.list_packs()) == 0

    def test_metrics_tracked(self, small_zip_pack):
        registry.ingest_icon_pack(small_zip_pack, pack_id="m1")
        metrics = registry.get_metrics()
        assert metrics["packs_ingested"] >= 1
        assert metrics["icons_ingested"] >= 1

    def test_duplicate_ingest_idempotent(self, small_zip_pack):
        registry.ingest_icon_pack(small_zip_pack, pack_id="dup")
        r2 = registry.ingest_icon_pack(small_zip_pack, pack_id="dup")
        # Second ingest should still work (overwrite)
        assert r2["ingested"] == 1

    def test_duplicate_ingest_invalidates_cached_libraries(self):
        registry.ingest_icon_pack(_zip_pack("cache.svg", "Cache Icon"), pack_id="cache-refresh")
        first = build_excalidraw_library("cache-refresh")

        changed_svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48"><circle cx="24" cy="24" r="20" fill="#ff0000"/></svg>'
        registry.ingest_icon_pack(
            _zip_pack_with_svg("cache.svg", "Cache Icon", changed_svg),
            pack_id="cache-refresh",
        )
        second = build_excalidraw_library("cache-refresh")

        assert second != first
        doc = json.loads(second)
        data_url = next(iter(doc["libraryItems"][0]["files"].values()))["dataURL"]
        decoded_svg = base64.b64decode(data_url.split(",", 1)[1])
        assert b"ff0000" in decoded_svg

    def test_registry_evicts_oldest_icons_when_maxsize_reached(self, monkeypatch):
        monkeypatch.setenv("ICON_REGISTRY_MAX_ICONS", "1")
        registry.ingest_icon_pack(_zip_pack("first.svg", "First Icon"), pack_id="first-pack")
        registry.ingest_icon_pack(_zip_pack("second.svg", "Second Icon"), pack_id="second-pack")

        packs = registry.list_packs()
        assert packs == [{"pack_id": "second-pack", "icon_count": 1}]
        assert registry.get_icon_metrics()["total_icons"] == 1


# ────────────────────────────────────────────────────────────
# Draw.io Library Builder Tests
# ────────────────────────────────────────────────────────────

class TestDrawioBuilder:
    """Draw.io custom shape library generation."""

    def test_drawio_reference_mode(self, small_zip_pack):
        registry.ingest_icon_pack(small_zip_pack, pack_id="dio-ref")
        data = build_drawio_library("dio-ref", embed_mode="reference")
        text = data.decode("utf-8")
        assert text.startswith("<mxlibrary>")
        assert text.endswith("</mxlibrary>")
        # Parse the JSON inside
        inner = text[len("<mxlibrary>"):-len("</mxlibrary>")]
        entries = json.loads(inner)
        assert len(entries) == 1
        assert "title" in entries[0]
        assert "xml" in entries[0]
        assert entries[0]["w"] > 0
        assert entries[0]["h"] > 0

    def test_drawio_full_embed_mode(self, small_zip_pack):
        registry.ingest_icon_pack(small_zip_pack, pack_id="dio-full")
        data = build_drawio_library("dio-full", embed_mode="full")
        text = data.decode("utf-8")
        inner = text[len("<mxlibrary>"):-len("</mxlibrary>")]
        entries = json.loads(inner)
        assert len(entries) == 1
        # Full mode should have base64 embedded SVG
        xml_str = entries[0]["xml"]
        assert "data:image/svg+xml;base64," in xml_str

    def test_drawio_empty_pack_raises(self):
        with pytest.raises(ValueError, match="(?i)no icons"):
            build_drawio_library("nonexistent-pack")

    def test_drawio_xml_valid(self, small_zip_pack):
        registry.ingest_icon_pack(small_zip_pack, pack_id="dio-xml")
        data = build_drawio_library("dio-xml", embed_mode="full")
        text = data.decode("utf-8")
        inner = text[len("<mxlibrary>"):-len("</mxlibrary>")]
        entries = json.loads(inner)
        # Each entry's xml should be valid XML
        for entry in entries:
            ET.fromstring(entry["xml"])  # should not raise

    def test_drawio_deterministic(self, small_zip_pack):
        registry.ingest_icon_pack(small_zip_pack, pack_id="dio-det")
        d1 = build_drawio_library("dio-det", embed_mode="reference")
        # Clear cache
        registry.set_cached_asset("drawio:dio-det:reference", None)
        d2 = build_drawio_library("dio-det", embed_mode="reference")
        assert d1 == d2


# ────────────────────────────────────────────────────────────
# Excalidraw Library Builder Tests
# ────────────────────────────────────────────────────────────

class TestExcalidrawBuilder:
    """Excalidraw library JSON bundle generation."""

    def test_excalidraw_schema(self, small_zip_pack):
        registry.ingest_icon_pack(small_zip_pack, pack_id="exc-1")
        data = build_excalidraw_library("exc-1")
        doc = json.loads(data)
        assert doc["type"] == "excalidrawlib"
        assert doc["version"] == 2
        assert doc["source"] == "archmorph"
        assert "libraryItems" in doc
        assert len(doc["libraryItems"]) == 1

    def test_excalidraw_item_structure(self, small_zip_pack):
        registry.ingest_icon_pack(small_zip_pack, pack_id="exc-2")
        data = build_excalidraw_library("exc-2")
        doc = json.loads(data)
        item = doc["libraryItems"][0]
        assert "id" in item
        assert item["id"].startswith("archmorph_")
        assert "elements" in item
        assert len(item["elements"]) > 0
        assert "name" in item
        assert item["status"] == "published"

    def test_excalidraw_has_files(self, small_zip_pack):
        registry.ingest_icon_pack(small_zip_pack, pack_id="exc-3")
        data = build_excalidraw_library("exc-3")
        doc = json.loads(data)
        item = doc["libraryItems"][0]
        assert "files" in item
        files = item["files"]
        assert len(files) > 0
        # Each file should have a data URI
        for fid, fdata in files.items():
            assert fdata["dataURL"].startswith("data:image/svg+xml;base64,")

    def test_excalidraw_empty_pack_raises(self):
        with pytest.raises(ValueError, match="(?i)no icons"):
            build_excalidraw_library("nonexistent-pack")

    def test_excalidraw_deterministic(self, small_zip_pack):
        registry.ingest_icon_pack(small_zip_pack, pack_id="exc-det")
        d1 = build_excalidraw_library("exc-det")
        registry.set_cached_asset("excalidraw:exc-det", None)
        d2 = build_excalidraw_library("exc-det")
        assert d1 == d2


# ────────────────────────────────────────────────────────────
# Visio Stencil Pack Tests
# ────────────────────────────────────────────────────────────

class TestVisioBuilder:
    """Visio sidecar stencil pack generation."""

    def test_visio_pack_is_zip(self, small_zip_pack):
        registry.ingest_icon_pack(small_zip_pack, pack_id="vis-1")
        data = build_visio_stencil_pack("vis-1")
        assert data[:4] == b"PK\x03\x04"

    def test_visio_pack_contents(self, small_zip_pack):
        registry.ingest_icon_pack(small_zip_pack, pack_id="vis-2")
        data = build_visio_stencil_pack("vis-2")
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            assert "stencil_manifest.json" in names
            assert "README_VISIO.md" in names
            svg_files = [n for n in names if n.startswith("svg/") and n.endswith(".svg")]
            assert len(svg_files) == 1

    def test_visio_manifest_valid(self, small_zip_pack):
        registry.ingest_icon_pack(small_zip_pack, pack_id="vis-3")
        data = build_visio_stencil_pack("vis-3")
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            manifest = json.loads(zf.read("stencil_manifest.json"))
            assert manifest["format"] == "visio_stencil_pack"
            assert manifest["icon_count"] == 1
            master = manifest["masters"][0]
            assert "master_id" in master
            assert "svg_data_uri" in master
            assert master["svg_data_uri"].startswith("data:image/svg+xml;base64,")

    def test_visio_empty_pack_raises(self):
        with pytest.raises(ValueError, match="(?i)no icons"):
            build_visio_stencil_pack("nonexistent-pack")

    def test_visio_readme_present(self, small_zip_pack):
        registry.ingest_icon_pack(small_zip_pack, pack_id="vis-4")
        data = build_visio_stencil_pack("vis-4")
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            readme = zf.read("README_VISIO.md").decode()
            assert "Visio Stencil Pack" in readme
            assert "Import into Visio" in readme


# ────────────────────────────────────────────────────────────
# API Route Tests
# ────────────────────────────────────────────────────────────

class TestIconAPI:
    """API endpoint tests for icon registry routes."""

    @pytest.fixture(autouse=True)
    def _setup_client(self, monkeypatch):
        from routers import shared as shared_router
        from main import app
        monkeypatch.setattr(shared_router, "API_KEY", API_HEADERS["X-API-Key"])
        self.client = TestClient(app)

    def test_list_packs_initially_empty(self):
        resp = self.client.get("/api/icons/packs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0

    def test_search_icons_empty(self):
        resp = self.client.get("/api/icons?provider=azure")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_icon_metrics_endpoint(self):
        resp = self.client.get("/api/icons/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "packs_ingested" in data

    def test_upload_zip_pack(self, small_zip_pack):
        resp = self.client.post(
            "/api/icon-packs?pack_id=api-test",
            files={"file": ("test.zip", small_zip_pack, "application/zip")},
            headers=API_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["pack_id"] == "api-test"
        assert data["ingested"] == 1

    def test_upload_zip_pack_requires_api_key(self, small_zip_pack):
        resp = self.client.post(
            "/api/icon-packs?pack_id=api-anon",
            files={"file": ("test.zip", small_zip_pack, "application/zip")},
        )
        assert resp.status_code == 401
        assert registry.list_packs() == []

    def test_upload_zip_pack_fails_closed_without_key_in_production(self, small_zip_pack, monkeypatch):
        from routers import shared as shared_router
        monkeypatch.setattr(shared_router, "API_KEY", "")
        monkeypatch.setenv("ENVIRONMENT", "production")

        resp = self.client.post(
            "/api/icon-packs?pack_id=api-prod-open",
            files={"file": ("test.zip", small_zip_pack, "application/zip")},
        )

        assert resp.status_code == 500
        assert registry.list_packs() == []

    def test_delete_icon_pack_requires_api_key(self, small_zip_pack):
        upload = self.client.post(
            "/api/icon-packs?pack_id=api-delete-auth",
            files={"file": ("test.zip", small_zip_pack, "application/zip")},
            headers=API_HEADERS,
        )
        assert upload.status_code == 200

        resp = self.client.delete("/api/icon-packs/api-delete-auth")

        assert resp.status_code == 401
        assert registry.list_packs() == [{"pack_id": "api-delete-auth", "icon_count": 1}]

    def test_delete_icon_pack_with_api_key(self, small_zip_pack):
        upload = self.client.post(
            "/api/icon-packs?pack_id=api-delete-ok",
            files={"file": ("test.zip", small_zip_pack, "application/zip")},
            headers=API_HEADERS,
        )
        assert upload.status_code == 200

        resp = self.client.delete("/api/icon-packs/api-delete-ok", headers=API_HEADERS)

        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        assert registry.list_packs() == []

    def test_upload_then_search(self, small_zip_pack):
        self.client.post(
            "/api/icon-packs?pack_id=api-search",
            files={"file": ("test.zip", small_zip_pack, "application/zip")},
            headers=API_HEADERS,
        )
        resp = self.client.get("/api/icons?provider=azure")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 1

    def test_upload_then_download_drawio(self, small_zip_pack):
        self.client.post(
            "/api/icon-packs?pack_id=api-drawio",
            files={"file": ("pack.zip", small_zip_pack, "application/zip")},
            headers=API_HEADERS,
        )
        resp = self.client.get("/api/libraries/drawio?packId=api-drawio&embedMode=full")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/xml")
        assert b"<mxlibrary>" in resp.content

    def test_upload_then_download_excalidraw(self, small_zip_pack):
        self.client.post(
            "/api/icon-packs?pack_id=api-exc",
            files={"file": ("pack.zip", small_zip_pack, "application/zip")},
            headers=API_HEADERS,
        )
        resp = self.client.get("/api/libraries/excalidraw?packId=api-exc")
        assert resp.status_code == 200
        doc = resp.json()
        assert doc["type"] == "excalidrawlib"

    def test_upload_then_download_visio(self, small_zip_pack):
        self.client.post(
            "/api/icon-packs?pack_id=api-vis",
            files={"file": ("pack.zip", small_zip_pack, "application/zip")},
            headers=API_HEADERS,
        )
        resp = self.client.get("/api/libraries/visio?packId=api-vis")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        assert resp.content[:4] == b"PK\x03\x04"

    def test_get_icon_svg(self, small_zip_pack):
        self.client.post(
            "/api/icon-packs?pack_id=api-svg",
            files={"file": ("pack.zip", small_zip_pack, "application/zip")},
            headers=API_HEADERS,
        )
        # Find the icon ID
        search = self.client.get("/api/icons?packId=api-svg")
        icon_id = search.json()["icons"][0]["id"]
        resp = self.client.get(f"/api/icons/{icon_id}/svg")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/svg+xml"
        assert b"svg" in resp.content

    def test_get_icon_svg_not_found(self):
        resp = self.client.get("/api/icons/nonexistent-id/svg")
        assert resp.status_code == 404

    def test_drawio_missing_pack(self):
        resp = self.client.get("/api/libraries/drawio?packId=nope")
        assert resp.status_code == 404

    def test_drawio_invalid_embed_mode(self, small_zip_pack):
        self.client.post(
            "/api/icon-packs?pack_id=api-bad",
            files={"file": ("pack.zip", small_zip_pack, "application/zip")},
            headers=API_HEADERS,
        )
        resp = self.client.get("/api/libraries/drawio?packId=api-bad&embedMode=invalid")
        assert resp.status_code == 400

    def test_upload_empty_file(self):
        resp = self.client.post(
            "/api/icon-packs",
            files={"file": ("empty.zip", b"", "application/zip")},
            headers=API_HEADERS,
        )
        assert resp.status_code == 400


# ────────────────────────────────────────────────────────────
# Pydantic Model Tests
# ────────────────────────────────────────────────────────────

class TestIconModels:
    """Pydantic model validation."""

    def test_provider_enum(self):
        assert Provider.azure.value == "azure"
        assert Provider.aws.value == "aws"
        assert Provider.gcp.value == "gcp"
        assert Provider.custom.value == "custom"

    def test_icon_meta_valid(self):
        meta = IconMeta(
            id="test-id",
            name="Test",
            provider="azure",
            category="compute",
            tags=["test"],
            version="1.0",
            service_id="svc-1",
            svg_hash="abc123",
        )
        assert meta.width == 64  # default
        assert meta.height == 64

    def test_icon_pack_manifest(self):
        m = IconPackManifest(
            name="Pack",
            provider="aws",
            version="1.0",
            icons=[
                IconPackItem(file="a.svg", name="A", category="compute", tags=["a"]),
            ],
        )
        assert len(m.icons) == 1
        assert m.provider == "aws"
