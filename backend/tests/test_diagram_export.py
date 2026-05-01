"""Tests for diagram_export module (#281).

These tests do real round-trip parsing of each exporter's output. The
previous coverage only checked that the result dict contained ``content`` or
``filename`` keys, which always passed regardless of whether the file was
valid — masking the broken Visio output (#xxx).
"""
import json
import xml.etree.ElementTree as ET

import pytest
from diagram_export import generate_diagram, get_azure_stencil_id


SAMPLE_ANALYSIS = {
    "source_provider": "AWS",
    "target_provider": "azure",
    "services_detected": 3,
    "title": "Round-Trip Test Diagram",
    "zones": [
        {
            "id": 1, "number": 1, "name": "Web Tier",
            "services": [
                {"source": "EC2", "source_service": "EC2", "azure_service": "Azure Virtual Machines"},
            ],
        },
    ],
    "mappings": [
        {
            "source_service": "EC2",
            "azure_service": "Azure Virtual Machines",
            "category": "Compute",
            "confidence": 0.95,
        },
        {
            "source_service": "S3",
            "azure_service": "Azure Blob Storage",
            "category": "Storage",
            "confidence": 0.98,
        },
    ],
}


class TestGetAzureStencilId:
    def test_known_service_drawio(self):
        stencil = get_azure_stencil_id("Azure Virtual Machines", target="drawio")
        assert isinstance(stencil, str)
        assert len(stencil) > 0

    def test_unknown_service_returns_fallback(self):
        stencil = get_azure_stencil_id("Nonexistent Service XYZ", target="drawio")
        assert isinstance(stencil, str)


class TestGenerateDiagram:
    def test_excalidraw_produces_valid_json_with_elements(self):
        result = generate_diagram(SAMPLE_ANALYSIS, format="excalidraw")
        assert result["format"] == "excalidraw"
        assert result["filename"].endswith(".excalidraw")
        # Must be parseable JSON conforming to the Excalidraw schema.
        doc = json.loads(result["content"])
        assert doc.get("type") == "excalidraw"
        assert isinstance(doc.get("elements"), list)
        assert len(doc["elements"]) > 0, "Excalidraw export was empty"

    def test_drawio_produces_valid_xml_with_mxgraph(self):
        result = generate_diagram(SAMPLE_ANALYSIS, format="drawio")
        assert result["format"] == "drawio"
        assert result["filename"].endswith(".drawio")
        # Must be parseable XML and contain at least one mxCell child.
        root = ET.fromstring(result["content"])
        assert root.tag in ("mxfile", "mxGraphModel"), f"Unexpected root: {root.tag}"
        cells = root.findall(".//mxCell")
        assert len(cells) > 0, "Draw.io export had no mxCell elements"

    def test_vsdx_produces_valid_vdx_xml_visio_can_open(self):
        """The Visio exporter emits legacy VDX 2003 XML. Output must be valid
        XML with a single ``xmlns`` declaration on the root element — a
        previous regression emitted duplicate xmlns attributes that broke
        every Visio open."""
        result = generate_diagram(SAMPLE_ANALYSIS, format="vsdx")
        assert result["format"] == "vsdx"
        # File extension must be .vdx (legacy XML format) — NOT .vsdx (which
        # is OOXML zip and would be a lie).
        assert result["filename"].endswith(".vdx")
        content = result["content"]
        # Detect the duplicate xmlns regression directly in the source bytes
        # before parsing — ET.fromstring will silently accept the second
        # ``xmlns`` only on some platforms, so we scan the root element's
        # opening tag manually.
        # Skip past any ``<?xml ...?>`` declaration to reach the root tag.
        rest = content
        if rest.lstrip().startswith("<?xml"):
            rest = rest.split("?>", 1)[1]
        root_open = rest[: rest.find(">") + 1]
        assert root_open.count('xmlns="') == 1, (
            f"VDX root must have exactly one xmlns declaration; got: {root_open}"
        )
        # Must be parseable XML.
        root = ET.fromstring(content)
        assert root.tag.endswith("VisioDocument")
        # Must contain at least one Page.
        ns = "{http://schemas.microsoft.com/visio/2003/core}"
        pages = root.find(f"{ns}Pages")
        assert pages is not None, "VDX missing <Pages> element"
        assert len(pages.findall(f"{ns}Page")) >= 1

    def test_invalid_format_raises(self):
        with pytest.raises((ValueError, KeyError)):
            generate_diagram(SAMPLE_ANALYSIS, format="invalid_format")

