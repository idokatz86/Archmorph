"""Draw.io / diagrams.net library builder.

Produces a custom shape library XML file that can be loaded into diagrams.net.
Supports two embed modes:
- ``reference``: Icons referenced by stencil name (lightweight).
- ``full``: SVG icons embedded as Base64 data URIs inside shapes (portable).

Output is deterministic: same input icons → byte-identical XML.
"""


from __future__ import annotations

from utils.logger_utils import sanitize_log

import base64
import logging
import time
import xml.etree.ElementTree as ET  # nosec B405  # nosemgrep: python.lang.security.use-defused-xml.use-defused-xml
from typing import Optional

from icons.models import IconEntry
from icons.registry import get_cached_asset, get_pack_icons, set_cached_asset, _metrics

logger = logging.getLogger(__name__)


def build_drawio_library(
    pack_id: str,
    *,
    embed_mode: str = "reference",
    title: Optional[str] = None,
) -> bytes:
    """Build a draw.io custom shape library XML from a registered icon pack.

    Parameters
    ----------
    pack_id
        The icon pack to build from.
    embed_mode
        ``"reference"`` — icons reference mxgraph stencils.
        ``"full"`` — SVGs embedded as data URIs for full portability.
    title
        Library title. Defaults to pack_id.

    Returns
    -------
    bytes
        XML content of the .xml library file.
    """
    t0 = time.monotonic()

    # Check cache
    cache_key = f"drawio:{pack_id}:{embed_mode}"
    cached = get_cached_asset(cache_key)
    if cached is not None:
        logger.info("Returning cached draw.io library for %s", str(pack_id).replace("\n", "").replace("\r", ""))  # lgtm[py/log-injection]
        return cached

    icons = get_pack_icons(pack_id)
    if not icons:
        raise ValueError(f"No icons found for pack '{pack_id}'")


    # Build mxlibrary JSON array
    # Each entry: {"xml": "<mxGraphModel>...</mxGraphModel>", "w": W, "h": H, "title": "Name", "aspect": "fixed"}
    entries: list[dict] = []

    for icon in icons:
        entry = _build_library_entry(icon, embed_mode)
        entries.append(entry)

    # Stable sort by title for deterministic output
    entries.sort(key=lambda e: e["title"])

    # Wrap in <mxlibrary> tag
    import json
    json_str = json.dumps(entries, separators=(",", ":"), sort_keys=True)

    xml_content = f"<mxlibrary>{json_str}</mxlibrary>"

    result = xml_content.encode("utf-8")
    set_cached_asset(cache_key, result)
    _metrics["library_builds"] += 1

    elapsed = time.monotonic() - t0
    logger.info(
        "Built draw.io library '%s' (%d icons, %s mode, %.2fs)",
        sanitize_log(pack_id), sanitize_log(len(entries)), sanitize_log(embed_mode), sanitize_log(elapsed),  # lgtm[py/log-injection]
    )

    return result


def _build_library_entry(icon: IconEntry, embed_mode: str) -> dict:
    """Build a single draw.io library entry for an icon."""
    w = icon.meta.width
    h = icon.meta.height
    name = icon.meta.name

    if embed_mode == "full":
        # Embed SVG as a data URI image inside an mxGraphModel
        svg_b64 = base64.b64encode(icon.svg.encode("utf-8")).decode("ascii")
        data_uri = f"data:image/svg+xml;base64,{svg_b64}"

        style = (
            f"shape=image;verticalLabelPosition=bottom;labelBackgroundColor=default;"
            f"verticalAlign=top;aspect=fixed;imageAspect=0;"
            f"image={data_uri};"
        )
    else:
        # Reference mode — use a stencil-like shape identifier
        stencil_id = f"archmorph.{icon.meta.provider}.{icon.meta.category}.{_slug(icon.meta.name)}"
        style = (
            f"shape={stencil_id};whiteSpace=wrap;html=1;"
            f"verticalLabelPosition=bottom;verticalAlign=top;aspect=fixed;"
        )

    # Build minimal mxGraphModel XML for the library entry
    graph_model = ET.Element("mxGraphModel")
    root = ET.SubElement(graph_model, "root")
    ET.SubElement(root, "mxCell", id="0")
    ET.SubElement(root, "mxCell", id="1", parent="0")
    cell = ET.SubElement(root, "mxCell", id="2", value=name, style=style,
                          vertex="1", parent="1")
    geom = ET.SubElement(cell, "mxGeometry", width=str(w), height=str(h))
    geom.set("as", "geometry")

    xml_str = ET.tostring(graph_model, encoding="unicode")

    return {
        "xml": xml_str,
        "w": w,
        "h": h,
        "title": name,
        "aspect": "fixed",
    }


def _slug(name: str) -> str:
    """Create a safe slug from a name."""
    import re
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
