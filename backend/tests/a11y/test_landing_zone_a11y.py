"""Accessibility guards for landing-zone SVG output (#598)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from azure_landing_zone import (
    COLOR_DB,
    COLOR_GREEN,
    COLOR_INK,
    COLOR_INK_2,
    COLOR_K8S,
    COLOR_PRIMARY,
    COLOR_PURPLE,
    COLOR_RED,
    generate_landing_zone_svg,
)
from tests.test_azure_landing_zone import SAMPLE_ANALYSIS


SVG_NS = "{http://www.w3.org/2000/svg}"


def _relative_luminance(hex_color: str) -> float:
    value = hex_color.strip().lstrip("#")
    channels = [int(value[index:index + 2], 16) / 255 for index in (0, 2, 4)]

    def linear(channel: float) -> float:
        if channel <= 0.03928:
            return channel / 12.92
        return ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = [linear(channel) for channel in channels]
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast_ratio(foreground: str, background: str) -> float:
    first = _relative_luminance(foreground)
    second = _relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def _children_by_tag(element: ET.Element, tag: str) -> list[ET.Element]:
    return [child for child in list(element) if child.tag == f"{SVG_NS}{tag}"]


def test_landing_zone_svg_has_accessible_root_label():
    result = generate_landing_zone_svg(SAMPLE_ANALYSIS, dr_variant="primary")
    root = ET.fromstring(result["content"])

    assert root.tag == f"{SVG_NS}svg"
    assert root.get("role") == "img"
    assert root.get("aria-labelledby") == "lz-title lz-desc"

    titles = _children_by_tag(root, "title")
    descs = _children_by_tag(root, "desc")
    assert titles and titles[0].get("id") == "lz-title"
    assert titles[0].text == SAMPLE_ANALYSIS["title"]
    assert descs and descs[0].get("id") == "lz-desc"
    assert "Regions:" in (descs[0].text or "")


def test_service_groups_have_title_and_description():
    result = generate_landing_zone_svg(SAMPLE_ANALYSIS, dr_variant="primary")
    root = ET.fromstring(result["content"])
    service_groups = [
        group for group in root.iter(f"{SVG_NS}g")
        if "lz-service" in (group.get("class") or "").split()
    ]

    assert len(service_groups) >= 8
    for group in service_groups:
        titles = _children_by_tag(group, "title")
        descs = _children_by_tag(group, "desc")
        assert titles and (titles[0].text or "").strip()
        assert descs and (descs[0].text or "").strip()


def test_landing_zone_key_text_colors_pass_wcag_aa_contrast():
    white = "#FFFFFF"
    pale_canvas = "#FAFBFC"
    dark_header_colors = [
        COLOR_PRIMARY,
        COLOR_PURPLE,
        COLOR_GREEN,
        COLOR_RED,
        COLOR_K8S,
        COLOR_DB,
        COLOR_INK_2,
    ]

    for color in dark_header_colors:
        assert _contrast_ratio(white, color) >= 4.5

    for color in (COLOR_INK, COLOR_INK_2, COLOR_GREEN, COLOR_RED, COLOR_DB):
        assert _contrast_ratio(color, pale_canvas) >= 4.5