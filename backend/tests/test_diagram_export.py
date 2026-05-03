"""Tests for diagram_export module (#281).

These tests do real round-trip parsing of each exporter's output. The
previous coverage only checked that the result dict contained ``content`` or
``filename`` keys, which always passed regardless of whether the file was
valid — masking the broken Visio output (#569).
"""
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from diagram_export import generate_diagram, get_azure_stencil_id
from service_connection_utils import service_key


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


CANONICAL_AWS_ESTATE_PATH = (
    Path(__file__).parent / "fixtures" / "aws_canonical_estate.json"
)


def _large_connection_analysis(count: int = 90) -> dict:
    mappings = [
        {
            "source_service": f"Source {i}",
            "azure_service": f"Service {i}",
            "category": "Compute",
            "confidence": 0.95,
        }
        for i in range(count + 1)
    ]
    return {
        "title": "Large Connection Export",
        "source_provider": "AWS",
        "target_provider": "azure",
        "zones": [{"id": 1, "number": 1, "name": "generated", "services": []}],
        "mappings": mappings,
        "service_connections": [
            {"source": f"Service {i}", "target": f"Service {i + 1}", "type": "traffic"}
            for i in range(count)
        ],
    }


MIXED_CLOUD_ANALYSIS = {
    "source_provider": "aws",
    "source_providers": ["aws", "gcp"],
    "target_provider": "azure",
    "services_detected": 4,
    "title": "Mixed Classic Handoff",
    "zones": [
        {
            "id": 1,
            "number": 1,
            "name": "Source Platform",
            "services": [
                {"source_provider": "aws", "source_service": "EKS", "azure_service": "AKS", "confidence": 0.94},
                {"source_provider": "gcp", "source_service": "Pub/Sub", "azure_service": "Event Hubs", "confidence": 0.87},
                {"source_provider": "gcp", "source_service": "Cloud Storage", "azure_service": "Unmapped GCP Archive Target", "confidence": 0.72},
            ],
        }
    ],
    "mappings": [
        {"source_provider": "aws", "source_service": "EKS", "azure_service": "AKS", "category": "Containers", "confidence": 0.94},
        {"source_provider": "gcp", "source_service": "Pub/Sub", "azure_service": "Event Hubs", "category": "Messaging", "confidence": 0.87},
        {"source_provider": "gcp", "source_service": "Cloud Storage", "azure_service": "Unmapped GCP Archive Target", "category": "Storage", "confidence": 0.72},
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


class TestServiceConnectionUtils:
    def test_service_key_strips_provider_labels_without_regex_backtracking(self):
        noisy = "[" * 5000 + "AWS] Azure Front Door"

        assert service_key(noisy) == "frontdoor"

    def test_service_key_normalizes_mixed_provider_labels(self):
        assert service_key("[GCP] Pub/Sub → Azure Event Hubs") == "pubsubeventhubs"


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

    def test_drawio_renders_service_connection_edges_from_canonical_fixture(self):
        analysis = json.loads(CANONICAL_AWS_ESTATE_PATH.read_text(encoding="utf-8"))

        result = generate_diagram(analysis, format="drawio")
        root = ET.fromstring(result["content"])
        edges = [cell for cell in root.findall(".//mxCell") if cell.get("edge") == "1"]

        expected = int(len(analysis["service_connections"]) * 0.8)
        assert len(edges) >= expected
        assert all((edge.get("value") or "") != "data flow" for edge in edges)

    def test_drawio_connection_edge_label_includes_protocol_and_type(self):
        analysis = {
            **SAMPLE_ANALYSIS,
            "zones": [{"id": 1, "number": 1, "name": "app", "services": []}],
            "service_connections": [
                {"from": "EC2", "to": "S3", "protocol": "HTTPS", "type": "storage"},
            ],
        }

        result = generate_diagram(analysis, format="drawio")
        root = ET.fromstring(result["content"])
        edge_values = [cell.get("value") or "" for cell in root.findall(".//mxCell") if cell.get("edge") == "1"]

        assert "HTTPS · storage" in edge_values

    def test_drawio_does_not_truncate_service_connections_above_80(self):
        analysis = _large_connection_analysis(count=90)

        result = generate_diagram(analysis, format="drawio")
        root = ET.fromstring(result["content"])
        edges = [cell for cell in root.findall(".//mxCell") if cell.get("edge") == "1"]

        assert len(edges) == len(analysis["service_connections"])

    def test_mixed_cloud_drawio_handoff_labels_sources_and_uses_deterministic_fallback(self):
        result = generate_diagram(MIXED_CLOUD_ANALYSIS, format="drawio")
        root = ET.fromstring(result["content"])
        cells = root.findall(".//mxCell")
        values = [cell.get("value") or "" for cell in cells]
        styles = [cell.get("style") or "" for cell in cells]

        assert "Azure Cloud" in values
        assert "[AWS] EKS → AKS" in values
        assert "[GCP] Pub/Sub → Event Hubs" in values
        assert "[GCP] Cloud Storage → Unmapped GCP Archive Target" in values
        assert any("image=img/lib/azure2/other/Targets_Management.svg;" in style for style in styles)

    def test_mixed_cloud_drawio_multi_page_handoff_labels_source_providers(self):
        analysis = {**MIXED_CLOUD_ANALYSIS, "multi_page": True}
        result = generate_diagram(analysis, format="drawio")
        root = ET.fromstring(result["content"])
        values = [cell.get("value") or "" for cell in root.findall(".//mxCell")]

        assert result["pages"] == 4
        assert root.tag == "mxfile"
        assert [diagram.get("name") for diagram in root.findall("diagram")] == [
            "1 - Migration Overview",
            "2 - Azure Target Architecture",
            "3 - Service Mapping Detail",
            "4 - Connection Topology",
        ]
        assert "[AWS] EKS" in values
        assert "[GCP] Pub/Sub" in values
        assert "[GCP] Cloud Storage" in values

    def test_mixed_cloud_excalidraw_handoff_labels_sources_and_parses(self):
        result = generate_diagram(MIXED_CLOUD_ANALYSIS, format="excalidraw")
        doc = json.loads(result["content"])
        texts = [element.get("text") for element in doc["elements"] if element.get("type") == "text"]

        assert doc["type"] == "excalidraw"
        assert "Azure Cloud" in texts
        assert "[AWS] EKS → AKS" in texts
        assert "[GCP] Pub/Sub → Event Hubs" in texts
        assert "[GCP] Cloud Storage → Unmapped GCP Archive Target" in texts

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

    def test_vsdx_renders_service_connection_connectors_from_canonical_fixture(self):
        analysis = json.loads(CANONICAL_AWS_ESTATE_PATH.read_text(encoding="utf-8"))

        result = generate_diagram(analysis, format="vsdx")
        root = ET.fromstring(result["content"])
        ns = "{http://schemas.microsoft.com/visio/2003/core}"
        connectors = [
            shape for shape in root.findall(f".//{ns}Shape")
            if (shape.get("NameU") or "").startswith("Connector_")
        ]
        connector_texts = [
            text.text or ""
            for shape in connectors
            for text in shape.findall(f"{ns}Text")
        ]

        expected = int(len(analysis["service_connections"]) * 0.8)
        assert len(connectors) >= expected
        assert "database" in connector_texts
        assert "auth" in connector_texts

    def test_vsdx_does_not_truncate_service_connections_above_80(self):
        analysis = _large_connection_analysis(count=90)

        result = generate_diagram(analysis, format="vsdx")
        root = ET.fromstring(result["content"])
        ns = "{http://schemas.microsoft.com/visio/2003/core}"
        connectors = [
            shape for shape in root.findall(f".//{ns}Shape")
            if (shape.get("NameU") or "").startswith("Connector_")
        ]

        assert len(connectors) == len(analysis["service_connections"])

    def test_invalid_format_raises(self):
        with pytest.raises((ValueError, KeyError)):
            generate_diagram(SAMPLE_ANALYSIS, format="invalid_format")

