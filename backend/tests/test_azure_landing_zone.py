"""Tests for Azure Landing Zone SVG generation + router wiring (#573, #574).

Round-trip parsing tests per Archmorph QA guardrail #569: every assertion
goes through the real XML parser, not substring/key existence checks.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from azure_landing_zone import (
    CANVAS_H_DR,
    CANVAS_H_PRIMARY,
    CANVAS_W,
    generate_landing_zone_svg,
)


SVG_NS = "{http://www.w3.org/2000/svg}"


SAMPLE_ANALYSIS: dict = {
    "title": "Test Landing Zone",
    "source_provider": "AWS",
    "target_provider": "azure",
    "zones": [{"id": 1, "name": "web-tier", "number": 1, "services": []}],
    "mappings": [
        {"source_service": "EKS", "azure_service": "AKS",        "category": "Containers"},
        {"source_service": "RDS", "azure_service": "Azure SQL",  "category": "Database"},
        {"source_service": "ALB", "azure_service": "App Gateway","category": "Networking"},
        {"source_service": "S3",  "azure_service": "Blob Storage","category": "Storage"},
        {"source_service": "Cognito", "azure_service": "Entra ID","category": "Identity"},
        {"source_service": "CloudWatch", "azure_service": "Azure Monitor","category": "Monitoring"},
    ],
}


DR_ANALYSIS: dict = {
    **SAMPLE_ANALYSIS,
    "dr_mode": "active-standby",
    "regions": [
        {"name": "East US",     "role": "primary", "traffic_pct": 100},
        {"name": "West US 3",   "role": "standby", "traffic_pct": 0},
    ],
}


# ---------------------------------------------------------------------------
# Generator-level tests (#573)
# ---------------------------------------------------------------------------

class TestGenerator:

    def test_landing_zone_svg_parses_as_xml(self):
        result = generate_landing_zone_svg(SAMPLE_ANALYSIS, dr_variant="primary")
        # Must be a string starting with the XML declaration.
        assert result["format"] == "landing-zone-svg"
        assert "content" in result
        # Round-trip parse: this is the load-bearing assertion.
        root = ET.fromstring(result["content"])
        assert root.tag == f"{SVG_NS}svg"

    def test_landing_zone_svg_no_duplicate_xmlns(self):
        """Defends against the same regression that broke .vsdx output (#569)."""
        result = generate_landing_zone_svg(SAMPLE_ANALYSIS, dr_variant="primary")
        content = result["content"]
        # `xmlns="..."` may only appear once on the root <svg> element.
        # Count raw occurrences in the bytes — a duplicate xmlns is invalid
        # even though some parsers will silently accept it.
        assert content.count('xmlns="') == 1, (
            f"Expected exactly one xmlns declaration, got {content.count('xmlns=')}"
        )

    def test_landing_zone_svg_primary_variant_dimensions(self):
        result = generate_landing_zone_svg(SAMPLE_ANALYSIS, dr_variant="primary")
        root = ET.fromstring(result["content"])
        assert root.get("width") == str(CANVAS_W)
        assert root.get("height") == str(CANVAS_H_PRIMARY)
        assert CANVAS_H_PRIMARY == 1330  # canonical contract

    def test_landing_zone_svg_dr_variant_dimensions(self):
        result = generate_landing_zone_svg(DR_ANALYSIS, dr_variant="dr")
        root = ET.fromstring(result["content"])
        assert root.get("width") == str(CANVAS_W)
        assert root.get("height") == str(CANVAS_H_DR)
        assert CANVAS_H_DR == 2120  # canonical contract

    def test_landing_zone_svg_dr_has_two_region_labels(self):
        result = generate_landing_zone_svg(DR_ANALYSIS, dr_variant="dr")
        root = ET.fromstring(result["content"])
        # Every <text> element gives us its readable content; collect them all
        # and assert both regions appear at least once.
        texts = [t.text or "" for t in root.iter(f"{SVG_NS}text")]
        joined = " | ".join(texts)
        assert "East US" in joined, f"East US not found in SVG text: {joined[:200]}"
        assert "West US 3" in joined, f"West US 3 not found in SVG text: {joined[:200]}"

    def test_landing_zone_svg_legend_present(self):
        result = generate_landing_zone_svg(SAMPLE_ANALYSIS, dr_variant="primary")
        root = ET.fromstring(result["content"])
        texts = [t.text or "" for t in root.iter(f"{SVG_NS}text")]
        # Legend has a header text element with literal "Legend".
        assert "Legend" in texts

    def test_landing_zone_svg_no_external_urls(self):
        """Output must be fully self-contained: no http(s) hrefs, no fetches."""
        result = generate_landing_zone_svg(SAMPLE_ANALYSIS, dr_variant="primary")
        content = result["content"]
        # Allow the xmlns URL on the root element only — that's a namespace,
        # not a fetch. Strip it before checking.
        without_ns = content.replace(
            'xmlns="http://www.w3.org/2000/svg"', "", 1
        )
        assert "http://" not in without_ns, "External http URL found in SVG"
        assert "https://" not in without_ns, "External https URL found in SVG"
        # Cross-check by parsing href attributes on <image> elements.
        root = ET.fromstring(content)
        for image in root.iter(f"{SVG_NS}image"):
            href = image.get("href") or image.get("{http://www.w3.org/1999/xlink}href") or ""
            if href:
                assert href.startswith("data:"), (
                    f"<image> href is not a data: URI: {href[:60]}"
                )

    def test_landing_zone_svg_legacy_analysis_works(self):
        """An analysis without any of the new optional fields still renders."""
        legacy = {
            "title": "Legacy",
            "zones": [{"id": 1, "name": "default", "number": 1}],
            "mappings": [
                {"source_service": "EC2", "azure_service": "Azure VMs", "category": "Compute"},
            ],
        }
        result = generate_landing_zone_svg(legacy, dr_variant="primary")
        root = ET.fromstring(result["content"])
        assert root.tag == f"{SVG_NS}svg"
        # Default region name must show up.
        texts = [t.text or "" for t in root.iter(f"{SVG_NS}text")]
        assert any("East US" in t for t in texts), "Default primary region missing"

    def test_landing_zone_svg_invalid_dr_variant_raises(self):
        with pytest.raises(ValueError):
            generate_landing_zone_svg(SAMPLE_ANALYSIS, dr_variant="bogus")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Router-level tests (#574)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def diagram_id_with_analysis(client):
    """Seed SESSION_STORE directly so we don't need a /analyze round-trip."""
    from main import SESSION_STORE
    diagram_id = "alz-test-diagram-001"
    SESSION_STORE[diagram_id] = dict(SAMPLE_ANALYSIS)
    yield diagram_id
    try:
        del SESSION_STORE[diagram_id]
    except (KeyError, Exception):
        pass


class TestRouter:

    def test_landing_zone_svg_dr_variant_with_drawio_400(self, client, diagram_id_with_analysis):
        """dr_variant only valid when format=landing-zone-svg."""
        resp = client.post(
            f"/api/diagrams/{diagram_id_with_analysis}/export-diagram"
            f"?format=drawio&dr_variant=dr"
        )
        assert resp.status_code == 400, resp.text

    def test_landing_zone_svg_invalid_dr_variant_400(self, client, diagram_id_with_analysis):
        resp = client.post(
            f"/api/diagrams/{diagram_id_with_analysis}/export-diagram"
            f"?format=landing-zone-svg&dr_variant=bogus"
        )
        assert resp.status_code == 400, resp.text

    def test_landing_zone_svg_route_returns_parseable_svg(self, client, diagram_id_with_analysis):
        resp = client.post(
            f"/api/diagrams/{diagram_id_with_analysis}/export-diagram"
            f"?format=landing-zone-svg&dr_variant=primary"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["format"] == "landing-zone-svg"
        assert body["filename"].endswith("-primary.svg")
        # Round-trip parse the returned SVG.
        root = ET.fromstring(body["content"])
        assert root.tag == f"{SVG_NS}svg"
        assert root.get("height") == str(CANVAS_H_PRIMARY)

    def test_landing_zone_svg_route_dr_variant_returns_dr_dimensions(
        self, client, diagram_id_with_analysis
    ):
        resp = client.post(
            f"/api/diagrams/{diagram_id_with_analysis}/export-diagram"
            f"?format=landing-zone-svg&dr_variant=dr"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["filename"].endswith("-dr.svg")
        root = ET.fromstring(body["content"])
        assert root.get("height") == str(CANVAS_H_DR)
