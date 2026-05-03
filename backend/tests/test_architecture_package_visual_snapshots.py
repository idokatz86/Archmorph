"""Visual snapshot guardrails for Architecture Package exports (#699)."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from architecture_package import generate_architecture_package


SNAPSHOT_PATH = (
    Path(__file__).parent / "fixtures" / "architecture_package_visual_snapshots.json"
)
MIXED_ANALYSIS_PATH = (
    Path(__file__).parent / "fixtures" / "architecture_package_mixed_analysis.json"
)
MIXED_ANALYSIS: dict = json.loads(MIXED_ANALYSIS_PATH.read_text(encoding="utf-8"))

def _svg_snapshot(content: str) -> dict:
    root = ET.fromstring(content)
    text_labels = []
    for elem in root.iter():
        if elem.tag.endswith("text") and elem.text and elem.text.strip():
            text = elem.text.strip()
            if len(text) > 1:
                text_labels.append(text)

    return {
        "width": root.attrib.get("width"),
        "height": root.attrib.get("height"),
        "viewBox": root.attrib.get("viewBox"),
        "semantic_text_labels": text_labels,
    }


def _html_snapshot(content: str) -> dict:
    css_vars_match = re.search(r":root \{([^}]+)\}", content)
    assert css_vars_match is not None
    required_text = [
        text
        for text in [
            "Mixed Source Package Test Architecture Package",
            "A — Target Azure Topology",
            "B — DR Topology",
            "C — Talking Points",
            "D — Services Limitations",
            "Customer Intent",
            "Assumptions And Constraints",
            "AWS/GCP → Azure",
        ]
        if text in content
    ]
    return {
        "svg_count": content.count("<svg"),
        "tab_labels": re.findall(r'<button class="tab"[^>]*>(.*?)<span>', content),
        "panel_ids": re.findall(r'<section id="([^"]+)" class="panel', content),
        "css_vars": css_vars_match.group(1).strip(),
        "required_text": required_text,
        "namespaced_ids_present": [
            item for item in ['id="a-primary"', 'id="a-dr"'] if item in content
        ],
    }


@pytest.fixture(scope="module")
def visual_snapshots():
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("snapshot_name", "kwargs", "snapshot_func"),
    [
        ("architecture_package_html", {"format": "html"}, _html_snapshot),
        (
            "architecture_package_target_svg",
            {"format": "svg", "diagram": "primary"},
            _svg_snapshot,
        ),
        (
            "architecture_package_dr_svg",
            {"format": "svg", "diagram": "dr"},
            _svg_snapshot,
        ),
    ],
)
def test_architecture_package_visual_snapshot(
    visual_snapshots,
    snapshot_name,
    kwargs,
    snapshot_func,
):
    result = generate_architecture_package(MIXED_ANALYSIS, **kwargs)

    assert snapshot_func(result["content"]) == visual_snapshots[snapshot_name]
