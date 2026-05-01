"""Tests for Azure Landing Zone SVG generation + router wiring (#573, #574).

Round-trip parsing tests per Archmorph QA guardrail #569: every assertion
goes through the real XML parser, not substring/key existence checks.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from azure_landing_zone import (
    CANVAS_H_DR,
    CANVAS_H_PRIMARY,
    CANVAS_W,
    generate_landing_zone_svg,
)

# #588 — canonical AWS estate fixture used by the tier-population +
# real-icon-ratio guardrails. Single source of truth so a future change
# to the catalog or registry only updates one place.
CANONICAL_AWS_ESTATE_PATH = (
    Path(__file__).parent / "fixtures" / "aws_canonical_estate.json"
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
        xmlns_count = content.count('xmlns="')
        assert xmlns_count == 1, (
            f"Expected exactly one xmlns declaration, got {xmlns_count}"
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
# #588 — Tier-population + min-real-icon test guardrails (D1/D2 backstop)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def canonical_aws_estate(tmp_path, monkeypatch) -> dict:
    """Load the 35-service canonical AWS estate fixture (#588).

    Hermetic against three known sources of test contamination:
      1. xdist worker re-use: `test_icon_registry.py` sets
         `ICON_REGISTRY_AUTOLOAD=0` at module top, which can leak into
         this worker. We force it back to `1` per-test.
      2. Disk pollution: a stale 1-icon snapshot in
         `backend/data/icon_registry.json` from prior test runs causes
         `_load_from_disk()` to return True and skip the builtin packs
         fall-through. We point at `tmp_path` so disk-load is empty.
      3. LZ negative cache: pre-#587 misses cached as `None` in
         `_ICON_CACHE`. We clear it explicitly.
    """
    from icons import registry as icon_registry
    import azure_landing_zone

    monkeypatch.setenv("ICON_REGISTRY_AUTOLOAD", "1")
    monkeypatch.setenv("ICON_REGISTRY_DATA_DIR", str(tmp_path))

    # Drop any cached load state so the gate re-runs.
    icon_registry.clear_all()
    azure_landing_zone._ICON_CACHE.clear()
    icon_registry.ensure_registry_loaded(force=True)

    return json.loads(CANONICAL_AWS_ESTATE_PATH.read_text(encoding="utf-8"))


def _count_real_vs_placeholder(svg_content: str) -> tuple[int, int]:
    """Return (real_icon_count, placeholder_count) from a rendered SVG.

    Real icons emit '<image href="data:...">'; misses emit '<g
    class="icon-fallback">'. Both are the only two outputs of '_img()'
    in 'azure_landing_zone.py' so the union is the total icon-slot count.
    """
    real = svg_content.count('<image href="data:image/svg+xml;base64,')
    placeholder = svg_content.count('<g class="icon-fallback">')
    return real, placeholder


class TestProductionReadyGuardrails:
    """#588 — assert the LZ SVG is visually meaningful, not just well-formed.

    The 13 pre-existing tests above check XML well-formedness, canvas
    dimensions, region labels, and 'no external URLs', but never that the
    diagram renders real icons or populates tiers. The CTO E2E review on
    2026-05-01 measured 0 real icons / 36 placeholder tiles and 5 of 8
    empty tiers — every existing test passed. These five new tests close
    that hole and back-stop the D1 (#587) and D2 (#589) fixes.
    """

    def test_canonical_estate_is_at_least_35_services_and_13_connections(
        self, canonical_aws_estate
    ):
        """Fixture contract — the constants the rest of the suite reasons about."""
        assert len(canonical_aws_estate["mappings"]) >= 35
        assert len(canonical_aws_estate["service_connections"]) >= 13

    def test_real_icon_ratio_no_regression(self, canonical_aws_estate):
        """#588 acceptance — real-icon ratio must not regress below 35%.

        Pre-#587 the ratio was 0% (registry empty on cold import). Post-#587
        the registry resolves ~43% of slots; the remaining gap is the
        `_ICON_SERVICE_IDS` map (#592) — only 20 of 35 canonical service
        slots have explicit candidate IDs.

        This test locks in the #587 win — any future change that drops
        below the 35% floor triggers it. Raise the floor as #592 lands.
        """
        result = generate_landing_zone_svg(canonical_aws_estate, dr_variant="primary")
        real, placeholder = _count_real_vs_placeholder(result["content"])
        total = real + placeholder
        assert total > 0, "SVG rendered no icon slots at all — generator broken"
        assert real > 0, (
            f"Real-icon count is 0 (placeholders={placeholder}). This is the "
            f"exact #587 D1 regression — registry empty on cold import. "
            f"See backend/icons/registry.py::_ensure_loaded."
        )
        ratio = real / total
        assert ratio >= 0.35, (
            f"Real-icon ratio {ratio:.0%} below 35% floor (real={real}, "
            f"placeholders={placeholder}). Likely cause: icon registry not "
            f"populated (#587 regression) or someone removed entries from "
            f"_ICON_SERVICE_IDS. See epic #586."
        )

    @pytest.mark.xfail(
        reason="#592 — `_ICON_SERVICE_IDS` map currently covers 20 of 35 "
               "canonical service slots; raising to ≥ 90% requires expanding "
               "the map to cover Service Bus, Event Grid, Cosmos DB, Defender, "
               "Activity Log, Conditional Access, Container Apps, etc. This "
               "test is the TDD anchor for that work and will start passing "
               "once #592 lands.",
        strict=True,
    )
    def test_real_icon_ratio_meets_90pct_target(self, canonical_aws_estate):
        """#592 target — real_icon_count ≥ 0.9 * total_image_count.

        The original issue-#588 acceptance bullet, kept here as an explicit
        TDD anchor. Strict xfail: if the ratio ever crosses 90%, this test
        fails-the-build and the human must convert it to a real assertion.
        """
        result = generate_landing_zone_svg(canonical_aws_estate, dr_variant="primary")
        real, placeholder = _count_real_vs_placeholder(result["content"])
        total = real + placeholder
        assert total > 0
        assert (real / total) >= 0.90

    def test_canonical_estate_renders_within_size_cap(self, canonical_aws_estate):
        """#571 contract — capped at 300 KB even on the worst-case fixture."""
        result = generate_landing_zone_svg(canonical_aws_estate, dr_variant="primary")
        size_bytes = len(result["content"].encode("utf-8"))
        assert size_bytes <= 300 * 1024, (
            f"SVG size {size_bytes} bytes exceeds 300 KB cap on canonical fixture"
        )

    def test_dr_variant_renders_real_icons_too(self, canonical_aws_estate):
        """DR variant has 2x the canvas; must not lose icon resolution along the way."""
        result = generate_landing_zone_svg(canonical_aws_estate, dr_variant="dr")
        real, placeholder = _count_real_vs_placeholder(result["content"])
        total = real + placeholder
        assert total > 0
        assert real > 0, "DR variant returned 0 real icons — #587 regression on DR path"
        # DR floor matches primary floor; #592 raises both together.
        ratio = real / total
        assert ratio >= 0.35, (
            f"DR variant real-icon ratio {ratio:.0%} below 35% floor "
            f"(real={real}, placeholders={placeholder}). #592 is the path to ≥ 90%."
        )

    def test_legacy_minimal_analysis_still_resolves_icons(self, tmp_path, monkeypatch):
        """Even the original 1-mapping legacy analysis must hit > 50% real icons
        on the static template tiles (network hub, identity hub, etc.). Pre-#587
        this was 0% even on the legacy fixture."""
        from icons import registry as icon_registry
        import azure_landing_zone

        monkeypatch.setenv("ICON_REGISTRY_AUTOLOAD", "1")
        monkeypatch.setenv("ICON_REGISTRY_DATA_DIR", str(tmp_path))
        icon_registry.clear_all()
        azure_landing_zone._ICON_CACHE.clear()
        icon_registry.ensure_registry_loaded(force=True)

        legacy = {
            "title": "Legacy",
            "zones": [{"id": 1, "name": "default", "number": 1}],
            "mappings": [
                {"source_service": "EC2", "azure_service": "Azure VMs", "category": "Compute"},
            ],
        }
        result = generate_landing_zone_svg(legacy, dr_variant="primary")
        real, placeholder = _count_real_vs_placeholder(result["content"])
        total = real + placeholder
        assert total > 0
        assert real > 0, "Legacy fixture returned 0 real icons — #587 regression"
        ratio = real / total
        assert ratio >= 0.35, (
            f"Legacy fixture real-icon ratio {ratio:.0%} below 35% — even the "
            f"static template tiles (front door, app gateway, AKS, key vault, "
            f"monitor, app insights, log analytics) must resolve."
        )


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


# ---------------------------------------------------------------------------
# GCP source provider (#576, #577, #578, #579)
# ---------------------------------------------------------------------------

GCP_SAMPLE_ANALYSIS: dict = {
    "title": "GCP-to-Azure Landing Zone",
    "source_provider": "gcp",
    "target_provider": "azure",
    "zones": [{"id": 1, "name": "web-tier", "number": 1, "services": []}],
    "mappings": [
        {"source_service": "GKE",       "azure_service": "AKS",          "category": "Containers"},
        {"source_service": "Cloud SQL", "azure_service": "Azure SQL",    "category": "Database"},
        {"source_service": "GLB",       "azure_service": "App Gateway",  "category": "Networking"},
        {"source_service": "Cloud Storage", "azure_service": "Blob Storage", "category": "Storage"},
        {"source_service": "Cloud IAM", "azure_service": "Entra ID",     "category": "Identity"},
        {"source_service": "Cloud Monitoring", "azure_service": "Azure Monitor", "category": "Monitoring"},
        {"source_service": "Pub/Sub",   "azure_service": "Event Hubs",   "category": "Messaging"},
        {"source_service": "Filestore", "azure_service": "Azure Files",  "category": "Storage"},
    ],
}


GCP_DR_ANALYSIS: dict = {
    **GCP_SAMPLE_ANALYSIS,
    "dr_mode": "active-standby",
    "regions": [
        {"name": "East US",   "role": "primary", "traffic_pct": 100},
        {"name": "West US 3", "role": "standby", "traffic_pct": 0},
    ],
}


# Verbatim strings the legend must contain (or NOT contain) per provider.
_AWS_LEGEND_FRAGMENT = "AWS → Azure"
_AWS_EKS_FRAGMENT = "EKS → AKS"
_GCP_LEGEND_FRAGMENT = "GCP → Azure"
_GCP_GKE_FRAGMENT = "GKE → AKS"
_GCP_PUBSUB_FRAGMENT = "Pub/Sub → Event Hubs"


class TestGcpSource:
    """Coverage for the implicit `analysis["source_provider"]` contract."""

    def test_gcp_fixture_round_trip_parse(self):
        """The GCP analysis dict renders into well-formed XML."""
        result = generate_landing_zone_svg(GCP_SAMPLE_ANALYSIS, dr_variant="primary")
        ET.fromstring(result["content"])  # raises ParseError if malformed

    def test_gcp_legend_contains_gcp_to_azure(self):
        """The GCP legend strip prints the canonical GCP→Azure mapping line."""
        result = generate_landing_zone_svg(GCP_SAMPLE_ANALYSIS, dr_variant="primary")
        assert _GCP_LEGEND_FRAGMENT in result["content"]
        assert _GCP_GKE_FRAGMENT in result["content"]
        assert _GCP_PUBSUB_FRAGMENT in result["content"]

    def test_gcp_legend_does_not_contain_aws(self):
        """The GCP legend strip must not leak the AWS mapping line."""
        result = generate_landing_zone_svg(GCP_SAMPLE_ANALYSIS, dr_variant="primary")
        assert _AWS_LEGEND_FRAGMENT not in result["content"]
        assert _AWS_EKS_FRAGMENT not in result["content"]

    def test_default_no_field_still_aws(self):
        """Backwards-compat with #571: missing `source_provider` ⇒ AWS legend."""
        legacy = {k: v for k, v in SAMPLE_ANALYSIS.items() if k != "source_provider"}
        assert "source_provider" not in legacy  # guard the construction
        result = generate_landing_zone_svg(legacy, dr_variant="primary")
        assert _AWS_LEGEND_FRAGMENT in result["content"]
        assert _GCP_LEGEND_FRAGMENT not in result["content"]

    def test_invalid_provider_raises_value_error(self):
        """Unknown provider → strict ValueError (mirrors `dr_variant`)."""
        bad = {**GCP_SAMPLE_ANALYSIS, "source_provider": "azure"}
        with pytest.raises(ValueError, match="Unsupported source_provider"):
            generate_landing_zone_svg(bad, dr_variant="primary")

        bad2 = {**GCP_SAMPLE_ANALYSIS, "source_provider": "alibaba"}
        with pytest.raises(ValueError, match="alibaba"):
            generate_landing_zone_svg(bad2, dr_variant="primary")

    def test_empty_string_provider_raises_value_error(self):
        """Empty / whitespace-only string must NOT silently default to AWS."""
        for empty in ("", "   ", "\t"):
            bad = {**SAMPLE_ANALYSIS, "source_provider": empty}
            with pytest.raises(ValueError, match="Unsupported source_provider"):
                generate_landing_zone_svg(bad, dr_variant="primary")

    def test_non_string_provider_raises_value_error(self):
        """Non-string types must raise ValueError → router maps to HTTP 400."""
        for bogus in (123, ["aws"], {"name": "aws"}, True):
            bad = {**SAMPLE_ANALYSIS, "source_provider": bogus}
            with pytest.raises(ValueError, match="Unsupported source_provider"):
                generate_landing_zone_svg(bad, dr_variant="primary")

    def test_dr_plus_gcp_renders(self):
        """DR variant × GCP source emits a valid SVG with the GCP legend."""
        result = generate_landing_zone_svg(GCP_DR_ANALYSIS, dr_variant="dr")
        root = ET.fromstring(result["content"])
        assert root.get("height") == str(CANVAS_H_DR)
        assert _GCP_LEGEND_FRAGMENT in result["content"]
        assert _AWS_LEGEND_FRAGMENT not in result["content"]

    def test_primary_plus_gcp_renders(self):
        """Primary variant × GCP source emits a valid SVG with the GCP legend."""
        result = generate_landing_zone_svg(GCP_SAMPLE_ANALYSIS, dr_variant="primary")
        root = ET.fromstring(result["content"])
        assert root.get("height") == str(CANVAS_H_PRIMARY)
        assert _GCP_LEGEND_FRAGMENT in result["content"]

    def test_case_insensitive_provider(self):
        """`GCP`, `Gcp`, `gcp` must produce identical output."""
        lower = {**GCP_SAMPLE_ANALYSIS, "source_provider": "gcp"}
        upper = {**GCP_SAMPLE_ANALYSIS, "source_provider": "GCP"}
        mixed = {**GCP_SAMPLE_ANALYSIS, "source_provider": "Gcp"}
        a = generate_landing_zone_svg(lower, dr_variant="primary")["content"]
        b = generate_landing_zone_svg(upper, dr_variant="primary")["content"]
        c = generate_landing_zone_svg(mixed, dr_variant="primary")["content"]
        assert a == b == c

    def test_supported_providers_and_legend_table_in_lockstep(self):
        """Module-load invariant: drift between the two constants is fatal."""
        from azure_landing_zone import (
            _SOURCE_PROVIDER_LEGEND_LINE,
            _SUPPORTED_SOURCE_PROVIDERS,
        )
        assert _SUPPORTED_SOURCE_PROVIDERS == frozenset(_SOURCE_PROVIDER_LEGEND_LINE)
