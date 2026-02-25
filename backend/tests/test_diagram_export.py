"""Tests for diagram_export module (#281)."""
import pytest
from diagram_export import generate_diagram, get_azure_stencil_id


SAMPLE_ANALYSIS = {
    "source_provider": "AWS",
    "target_provider": "azure",
    "services_detected": 3,
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
    def test_excalidraw_format(self):
        result = generate_diagram(SAMPLE_ANALYSIS, format="excalidraw")
        assert "content" in result or "filename" in result

    def test_drawio_format(self):
        result = generate_diagram(SAMPLE_ANALYSIS, format="drawio")
        assert "content" in result or "filename" in result

    def test_vsdx_format(self):
        result = generate_diagram(SAMPLE_ANALYSIS, format="vsdx")
        assert "content" in result or "filename" in result

    def test_invalid_format_raises(self):
        with pytest.raises((ValueError, KeyError)):
            generate_diagram(SAMPLE_ANALYSIS, format="invalid_format")
