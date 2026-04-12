"""
Architecture diagram export module.

Generates architecture diagrams in Excalidraw, Draw.io, and Visio (VDX) formats
from cloud migration analysis results.
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
import xml.etree.ElementTree as ET  # nosec B405  # nosemgrep: python.lang.security.use-defused-xml.use-defused-xml
from typing import Any

# ---------------------------------------------------------------------------
# Azure stencil / icon mapping (30+ services)
# ---------------------------------------------------------------------------

import os
import re

_data_file_AZURE_STENCILS = os.path.join(os.path.dirname(__file__), 'assets', 'diagram_stencils.json')
try:
    with open(_data_file_AZURE_STENCILS, 'r') as _f:
        AZURE_STENCILS = json.load(_f)
except FileNotFoundError:
    AZURE_STENCILS = [] if False else {}

# ---------------------------------------------------------------------------
# Azure2 icon catalog (648 icons) for fuzzy matching
# ---------------------------------------------------------------------------

_AZURE2_CATALOG_PATH = os.path.join(
    os.path.dirname(__file__), '..', '.github', 'skills',
    'drawio-mcp-diagramming', 'references', 'azure2-complete-catalog.txt',
)
_AZURE2_CATALOG: list[str] = []
try:
    with open(_AZURE2_CATALOG_PATH, 'r') as _cf:
        for _line in _cf:
            _line = _line.strip()
            if _line and not _line.startswith('Matched') and _line.endswith('.svg'):
                _AZURE2_CATALOG.append(_line)
except FileNotFoundError:
    pass

_DRAWIO_DEFAULT_ICON = "img/lib/azure2/general/Module.svg"


# Pastel zone backgrounds
_ZONE_COLORS = [
    "#E3F2FD",  # light blue
    "#E8F5E9",  # light green
    "#FFF3E0",  # light orange
    "#F3E5F5",  # light purple
    "#E0F7FA",  # light cyan
    "#FBE9E7",  # light red
    "#F1F8E9",  # light lime
    "#EDE7F6",  # light deep-purple
]

_CONFIDENCE_COLORS = {
    "high": "#4CAF50",
    "medium": "#FF9800",
    "low": "#F44336",
}

_AZURE_PRIMARY = "#0078D4"
_AZURE_SECONDARY = "#50E6FF"


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def _search_azure2_catalog(service_name: str) -> str | None:
    """Fuzzy-match a service name against the Azure2 icon catalog (648 icons).

    Returns an ``img/lib/azure2/...`` path or None.
    """
    if not _AZURE2_CATALOG:
        return None
    # Normalise: "Azure Cosmos DB" → ["cosmos", "db"]
    tokens = re.split(r'[\s_\-/]+', service_name.lower())
    # Remove noise words
    tokens = [t for t in tokens if t not in ('azure', 'service', 'services', 'microsoft', 'for', 'the')]

    best: str | None = None
    best_score = 0
    for path in _AZURE2_CATALOG:
        path_lower = path.lower()
        score = sum(1 for t in tokens if t in path_lower)
        if score > best_score:
            best_score = score
            best = path
    if best and best_score >= 1:
        return f"img/lib/azure2/{best}"
    return None


def get_azure_stencil_id(service_name: str, target: str = "drawio") -> str:
    """Return the stencil / shape identifier for *service_name*.

    For ``target="drawio"`` returns an Azure2 image path
    (``img/lib/azure2/<category>/<Icon>.svg``).
    For ``target="visio"`` returns the Visio stencil name.
    """
    entry = AZURE_STENCILS.get(service_name)
    if entry:
        val = entry.get(target)
        if val:
            return val
    # Fuzzy fallback – try partial match against stencils JSON
    lower = service_name.lower()
    for name, ids in AZURE_STENCILS.items():
        if lower in name.lower() or name.lower() in lower:
            val = ids.get(target)
            if val:
                return val

    # Fallback to Azure2 catalog fuzzy search (648 icons)
    if target == "drawio":
        catalog_hit = _search_azure2_catalog(service_name)
        if catalog_hit:
            return catalog_hit

    # Fallback to Icon Registry
    try:
        from icons.registry import resolve_icon

        icon_entry = resolve_icon(service_name, provider="azure")
        if icon_entry:
            return icon_entry.meta.id
    except Exception:  # noqa: BLE001  # nosec B110 - falls through to default icon
        pass

    return _DRAWIO_DEFAULT_ICON if target == "drawio" else "Azure General"


def _resolve_icon_svg(azure_name: str) -> str | None:
    """Try to resolve an Azure icon SVG from the icon registry.

    Returns a base64 data URI ``data:image/svg+xml;base64,...`` or None.
    """
    try:
        from icons.registry import resolve_icon

        entry = resolve_icon(azure_name, provider="azure")
        if entry and entry.svg:
            b64 = base64.b64encode(entry.svg.encode("utf-8")).decode("ascii")
            return f"data:image/svg+xml;base64,{b64}"
    except Exception:  # nosec B110 - icon resolution is optional, falls through to None
        pass
    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_diagram(analysis_result: dict, format: str) -> dict:
    """Generate an architecture diagram from *analysis_result*.

    Parameters
    ----------
    analysis_result:
        Dict produced by the ``/analyze`` endpoint.  Expected keys:
        ``zones``, ``mappings``, ``diagram_type``, and optionally
        ``title``.
    format:
        One of ``"excalidraw"``, ``"drawio"``, ``"vsdx"``.

    Returns
    -------
    dict
        ``{"format": ..., "filename": ..., "content": ...}``

    Raises
    ------
    ValueError
        If *format* is not supported.
    """
    generators = {
        "excalidraw": _generate_excalidraw,
        "drawio": _generate_drawio,
        "vsdx": _generate_vsdx,
    }
    gen = generators.get(format)
    if gen is None:
        raise ValueError(
            f"Unsupported format '{format}'. Choose from: {', '.join(generators)}"
        )
    generators = {
        "excalidraw": _generate_excalidraw,
        "drawio": _generate_drawio,
        "vsdx": _generate_vsdx,
    }
    gen = generators.get(format)
    if gen is None:
        raise ValueError(
            f"Unsupported format '{format}'. Choose from: {', '.join(generators)}"
        )
    result = gen(analysis_result)

    # Multi-page support (#479): if multi_page requested and format supports it
    if analysis_result.get("multi_page") and format == "drawio":
        result = _generate_drawio_multi_page(analysis_result)

    return result


# ===================================================================== #
#  Multi-page Draw.io Export (#479)
# ===================================================================== #

def _generate_drawio_multi_page(analysis: dict) -> dict:
    """Generate a 4-page Draw.io export for presentation-ready diagrams.

    Pages:
      1. Migration Overview — source ghosted, target with migration arrows
      2. Azure Target Architecture — clean to-be state
      3. Service Mapping Detail — table with confidence/effort/gaps
      4. Connection Topology — protocol-labeled edges
    """
    mappings = analysis.get("mappings", [])
    zones = analysis.get("zones", [])
    title = analysis.get("title", "Architecture Migration")
    connections = analysis.get("service_connections", [])

    root = ET.Element("mxfile", host="archmorph", type="device")

    # ── Page 1: Migration Overview ──
    _drawio_page_migration_overview(root, title, mappings, zones)

    # ── Page 2: Azure Target Architecture ──
    _drawio_page_target_architecture(root, title, mappings, zones)

    # ── Page 3: Service Mapping Detail ──
    _drawio_page_mapping_detail(root, title, mappings)

    # ── Page 4: Connection Topology ──
    _drawio_page_connection_topology(root, title, mappings, connections)

    content = ET.tostring(root, encoding="unicode", xml_declaration=True)
    return {
        "format": "drawio",
        "filename": "architecture-migration.drawio",
        "content": content,
        "pages": 4,
    }


def _drawio_page_migration_overview(root, title, mappings, zones):
    """Page 1 — Source (ghosted) → Target with migration arrows."""
    diagram = ET.SubElement(root, "diagram", id=_uid(), name="1 - Migration Overview")
    gm = ET.SubElement(diagram, "mxGraphModel", dx="2400", dy="1600", grid="1",
                        gridSize="20", page="1", pageScale="1", pageWidth="4960", pageHeight="3508")
    rt = ET.SubElement(gm, "root")
    ET.SubElement(rt, "mxCell", id="0")
    ET.SubElement(rt, "mxCell", id="1", parent="0")

    cid = [2]
    def nid():
        r = str(cid[0])
        cid[0] += 1
        return r

    # Title cartouche
    tid = nid()
    cell = ET.SubElement(rt, "mxCell", id=tid, value=f"<b>{title}</b><br/><i>Migration Overview — Generated by Archmorph</i>",
                         style="text;html=1;fontSize=18;fontFamily=Segoe UI;align=left;fillColor=#F8FAFC;strokeColor=#E2E8F0;rounded=1;",
                         vertex="1", parent="1")
    ET.SubElement(cell, "mxGeometry", x="40", y="40", width="600", height="60", **{"as": "geometry"})

    # Source services (ghosted at 40% opacity on left)
    src_ids = {}
    for i, m in enumerate(mappings[:15]):
        src = m.get("source_service", "?")
        sid = nid()
        src_ids[src] = sid
        cell = ET.SubElement(rt, "mxCell", id=sid, value=src,
                             style="rounded=1;whiteSpace=wrap;html=1;opacity=40;fillColor=#F1F5F9;strokeColor=#CBD5E1;fontColor=#94A3B8;fontFamily=Segoe UI;fontSize=12;",
                             vertex="1", parent="1")
        y = 160 + i * 70
        ET.SubElement(cell, "mxGeometry", x="200", y=str(y), width="260", height="50", **{"as": "geometry"})

    # Target services (full opacity on right)
    tgt_ids = {}
    for i, m in enumerate(mappings[:15]):
        tgt = m.get("azure_service", "?")
        conf = m.get("confidence", 0)
        color = "#22C55E" if (conf if isinstance(conf, (int, float)) else 0.5) >= 0.85 else "#F59E0B" if (conf if isinstance(conf, (int, float)) else 0.5) >= 0.6 else "#EF4444"
        tid2 = nid()
        tgt_ids[tgt] = tid2
        cell = ET.SubElement(rt, "mxCell", id=tid2, value=f"<b>{tgt}</b>",
                             style=f"rounded=1;whiteSpace=wrap;html=1;fillColor=#EFF6FF;strokeColor={color};strokeWidth=2;fontFamily=Segoe UI;fontSize=12;",
                             vertex="1", parent="1")
        y = 160 + i * 70
        ET.SubElement(cell, "mxGeometry", x="700", y=str(y), width="280", height="50", **{"as": "geometry"})

    # Migration arrows
    for m in mappings[:15]:
        src = m.get("source_service", "?")
        tgt = m.get("azure_service", "?")
        if src in src_ids and tgt in tgt_ids:
            eid = nid()
            ET.SubElement(rt, "mxCell", id=eid, value="",
                          style="edgeStyle=orthogonalEdgeStyle;strokeColor=#3B82F6;strokeWidth=2;endArrow=block;endFill=1;dashed=1;",
                          edge="1", parent="1", source=src_ids[src], target=tgt_ids[tgt])


def _drawio_page_target_architecture(root, title, mappings, zones):
    """Page 2 — Clean Azure target architecture grouped by zone."""
    diagram = ET.SubElement(root, "diagram", id=_uid(), name="2 - Azure Target Architecture")
    gm = ET.SubElement(diagram, "mxGraphModel", dx="2400", dy="1600", grid="1",
                        gridSize="20", page="1", pageScale="1", pageWidth="4960", pageHeight="3508")
    rt = ET.SubElement(gm, "root")
    ET.SubElement(rt, "mxCell", id="0")
    ET.SubElement(rt, "mxCell", id="1", parent="0")

    cid = [2]
    def nid():
        r = str(cid[0])
        cid[0] += 1
        return r

    # Title
    tid = nid()
    cell = ET.SubElement(rt, "mxCell", id=tid, value=f"<b>{title}</b><br/><i>Azure Target Architecture</i>",
                         style="text;html=1;fontSize=18;fontFamily=Segoe UI;align=left;fillColor=#F8FAFC;strokeColor=#E2E8F0;rounded=1;",
                         vertex="1", parent="1")
    ET.SubElement(cell, "mxGeometry", x="40", y="40", width="600", height="60", **{"as": "geometry"})

    # Category colors
    cat_colors = {
        "Compute": "#3B82F6", "Network": "#A855F7", "Networking": "#A855F7",
        "Database": "#22C55E", "Data": "#22C55E", "Security": "#EF4444",
        "Storage": "#14B8A6", "Integration": "#F59E0B", "AI/ML": "#EC4899",
        "Monitoring": "#6366F1", "Management": "#64748B",
    }

    # Group mappings by category
    by_cat = {}
    for m in mappings:
        cat = m.get("category", "Other")
        by_cat.setdefault(cat, []).append(m)

    col = 0
    for cat_name, cat_mappings in by_cat.items():
        color = cat_colors.get(cat_name, "#64748B")
        zone_id = nid()
        x = 80 + col * 500
        h = max(180, 80 + len(cat_mappings) * 60)
        cell = ET.SubElement(rt, "mxCell", id=zone_id,
                             value=f"<b>{cat_name}</b>",
                             style=f"swimlane;startSize=30;fillColor={color}20;strokeColor={color};fontFamily=Segoe UI;fontSize=14;fontStyle=1;fontColor={color};",
                             vertex="1", parent="1")
        ET.SubElement(cell, "mxGeometry", x=str(x), y="140", width="440", height=str(h), **{"as": "geometry"})

        for j, m in enumerate(cat_mappings):
            sid = nid()
            azure = m.get("azure_service", "?")
            conf = m.get("confidence", 0)
            conf_pct = f"{int(conf * 100)}%" if isinstance(conf, (int, float)) and conf <= 1 else str(conf)
            cell = ET.SubElement(rt, "mxCell", id=sid,
                                 value=f"<b>{azure}</b><br/><font style='font-size:10px'>Confidence: {conf_pct}</font>",
                                 style=f"rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor={color};strokeWidth=2;fontFamily=Segoe UI;fontSize=12;align=left;spacingLeft=10;",
                                 vertex="1", parent=zone_id)
            ET.SubElement(cell, "mxGeometry", x="20", y=str(40 + j * 60), width="400", height="50", **{"as": "geometry"})

        col += 1


def _drawio_page_mapping_detail(root, title, mappings):
    """Page 3 — Service mapping table with confidence, effort, gaps."""
    diagram = ET.SubElement(root, "diagram", id=_uid(), name="3 - Service Mapping Detail")
    gm = ET.SubElement(diagram, "mxGraphModel", dx="2400", dy="1600", grid="1",
                        gridSize="20", page="1", pageScale="1", pageWidth="4960", pageHeight="3508")
    rt = ET.SubElement(gm, "root")
    ET.SubElement(rt, "mxCell", id="0")
    ET.SubElement(rt, "mxCell", id="1", parent="0")

    cid = [2]
    def nid():
        r = str(cid[0])
        cid[0] += 1
        return r

    # Title
    tid = nid()
    cell = ET.SubElement(rt, "mxCell", id=tid, value=f"<b>{title}</b><br/><i>Service Mapping Detail</i>",
                         style="text;html=1;fontSize=18;fontFamily=Segoe UI;align=left;fillColor=#F8FAFC;strokeColor=#E2E8F0;rounded=1;",
                         vertex="1", parent="1")
    ET.SubElement(cell, "mxGeometry", x="40", y="40", width="600", height="60", **{"as": "geometry"})

    # Table header
    headers = ["Source Service", "Azure Service", "Category", "Confidence", "Notes"]
    col_widths = [300, 300, 180, 140, 400]
    hx = 40
    for i, hdr in enumerate(headers):
        hid = nid()
        cell = ET.SubElement(rt, "mxCell", id=hid, value=f"<b>{hdr}</b>",
                             style="rounded=0;whiteSpace=wrap;html=1;fillColor=#1E293B;fontColor=#FFFFFF;fontFamily=Segoe UI;fontSize=12;fontStyle=1;",
                             vertex="1", parent="1")
        ET.SubElement(cell, "mxGeometry", x=str(hx), y="120", width=str(col_widths[i]), height="40", **{"as": "geometry"})
        hx += col_widths[i]

    # Table rows
    for row_idx, m in enumerate(mappings[:20]):
        src = m.get("source_service", "?")
        tgt = m.get("azure_service", "?")
        cat = m.get("category", "—")
        conf = m.get("confidence", 0)
        conf_str = f"{int(conf * 100)}%" if isinstance(conf, (int, float)) and conf <= 1 else str(conf)
        notes = m.get("notes", "")[:60]
        values = [src, tgt, cat, conf_str, notes]

        rx = 40
        y = 160 + row_idx * 36
        bg = "#FFFFFF" if row_idx % 2 == 0 else "#F8FAFC"
        for i, val in enumerate(values):
            rid = nid()
            cell = ET.SubElement(rt, "mxCell", id=rid, value=val,
                                 style=f"rounded=0;whiteSpace=wrap;html=1;fillColor={bg};strokeColor=#E2E8F0;fontFamily=Segoe UI;fontSize=11;align=left;spacingLeft=8;",
                                 vertex="1", parent="1")
            ET.SubElement(cell, "mxGeometry", x=str(rx), y=str(y), width=str(col_widths[i]), height="36", **{"as": "geometry"})
            rx += col_widths[i]

    # Summary stats
    total = len(mappings)
    avg_conf = sum(m.get("confidence", 0) for m in mappings if isinstance(m.get("confidence"), (int, float))) / max(total, 1)
    sid = nid()
    cell = ET.SubElement(rt, "mxCell", id=sid,
                         value=f"<b>Total:</b> {total} services | <b>Avg Confidence:</b> {int(avg_conf * 100)}%",
                         style="text;html=1;fontSize=12;fontFamily=Segoe UI;align=left;fillColor=#F0FDF4;strokeColor=#86EFAC;rounded=1;",
                         vertex="1", parent="1")
    y_summary = 160 + min(len(mappings), 20) * 36 + 20
    ET.SubElement(cell, "mxGeometry", x="40", y=str(y_summary), width="600", height="40", **{"as": "geometry"})


def _drawio_page_connection_topology(root, title, mappings, connections):
    """Page 4 — Network topology with protocol-labeled edges."""
    diagram = ET.SubElement(root, "diagram", id=_uid(), name="4 - Connection Topology")
    gm = ET.SubElement(diagram, "mxGraphModel", dx="2400", dy="1600", grid="1",
                        gridSize="20", page="1", pageScale="1", pageWidth="4960", pageHeight="3508")
    rt = ET.SubElement(gm, "root")
    ET.SubElement(rt, "mxCell", id="0")
    ET.SubElement(rt, "mxCell", id="1", parent="0")

    cid = [2]
    def nid():
        r = str(cid[0])
        cid[0] += 1
        return r

    # Title
    tid = nid()
    cell = ET.SubElement(rt, "mxCell", id=tid, value=f"<b>{title}</b><br/><i>Connection Topology</i>",
                         style="text;html=1;fontSize=18;fontFamily=Segoe UI;align=left;fillColor=#F8FAFC;strokeColor=#E2E8F0;rounded=1;",
                         vertex="1", parent="1")
    ET.SubElement(cell, "mxGeometry", x="40", y="40", width="600", height="60", **{"as": "geometry"})

    # Connection type styles
    conn_styles = {
        "traffic": "strokeColor=#3B82F6;strokeWidth=2;",
        "database": "strokeColor=#22C55E;strokeWidth=2;",
        "auth": "strokeColor=#A855F7;strokeWidth=2;dashed=1;",
        "control": "strokeColor=#94A3B8;strokeWidth=1.5;dashed=1;",
        "security": "strokeColor=#F97316;strokeWidth=2;dashed=1;dashPattern=2 2;",
        "storage": "strokeColor=#14B8A6;strokeWidth=1.5;",
    }

    # Place service nodes
    svc_ids = {}
    azure_names = list({m.get("azure_service", "?") for m in mappings})
    cols = max(int(len(azure_names) ** 0.5) + 1, 3)
    for i, svc in enumerate(azure_names[:30]):
        sid = nid()
        svc_ids[svc] = sid
        x = 100 + (i % cols) * 350
        y = 160 + (i // cols) * 120
        cell = ET.SubElement(rt, "mxCell", id=sid, value=f"<b>{svc}</b>",
                             style="rounded=1;whiteSpace=wrap;html=1;fillColor=#EFF6FF;strokeColor=#3B82F6;strokeWidth=2;fontFamily=Segoe UI;fontSize=12;",
                             vertex="1", parent="1")
        ET.SubElement(cell, "mxGeometry", x=str(x), y=str(y), width="280", height="50", **{"as": "geometry"})

    # Draw connections
    src_lookup = {m.get("source_service", ""): m.get("azure_service", "") for m in mappings}
    for conn in connections[:50]:
        from_svc = conn.get("from", "")
        to_svc = conn.get("to", "")
        protocol = conn.get("protocol", "")
        conn_type = conn.get("type", "traffic").lower()

        from_azure = src_lookup.get(from_svc, from_svc)
        to_azure = src_lookup.get(to_svc, to_svc)

        if from_azure in svc_ids and to_azure in svc_ids:
            eid = nid()
            style = conn_styles.get(conn_type, conn_styles["traffic"])
            ET.SubElement(rt, "mxCell", id=eid, value=protocol,
                          style=f"edgeStyle=orthogonalEdgeStyle;{style}endArrow=block;endFill=1;fontFamily=Segoe UI;fontSize=10;",
                          edge="1", parent="1", source=svc_ids[from_azure], target=svc_ids[to_azure])

    # Legend
    legend_y = 160 + ((len(azure_names[:30]) // cols) + 1) * 120 + 40
    lid = nid()
    legend_html = "<b>Connection Types</b><br/>"
    for ctype, style_val in conn_styles.items():
        color = style_val.split("strokeColor=")[1].split(";")[0] if "strokeColor=" in style_val else "#666"
        legend_html += f"<font color='{color}'>━━</font> {ctype.title()}&nbsp;&nbsp;"
    cell = ET.SubElement(rt, "mxCell", id=lid, value=legend_html,
                         style="text;html=1;fontSize=11;fontFamily=Segoe UI;align=left;fillColor=#F8FAFC;strokeColor=#E2E8F0;rounded=1;",
                         vertex="1", parent="1")
    ET.SubElement(cell, "mxGeometry", x="40", y=str(legend_y), width="800", height="50", **{"as": "geometry"})


# ===================================================================== #
#  Excalidraw generator                                                  #
# ===================================================================== #

def _uid() -> str:
    return uuid.uuid4().hex[:20]


def _exc_rect(
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    stroke: str = "#000000",
    bg: str = "transparent",
    fill: str = "hachure",
    dash: list | None = None,
    opacity: int = 100,
    radius: int = 0,
    group: str | None = None,
) -> dict:
    el: dict[str, Any] = {
        "id": _uid(),
        "type": "rectangle",
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "angle": 0,
        "strokeColor": stroke,
        "backgroundColor": bg,
        "fillStyle": fill if bg != "transparent" else "solid",
        "strokeWidth": 2,
        "roughness": 0,
        "opacity": opacity,
        "roundness": {"type": 3, "value": radius} if radius else None,
        "seed": abs(hash(_uid())) % 2_000_000_000,
        "version": 1,
        "versionNonce": abs(hash(_uid())) % 2_000_000_000,
        "isDeleted": False,
        "boundElements": [],
        "link": None,
        "locked": False,
    }
    if dash:
        el["strokeStyle"] = "dashed"
    else:
        el["strokeStyle"] = "solid"
    if group:
        el["groupIds"] = [group]
    else:
        el["groupIds"] = []
    return el


def _exc_text(
    x: float,
    y: float,
    text: str,
    *,
    size: int = 16,
    color: str = "#000000",
    group: str | None = None,
    bold: bool = False,
) -> dict:
    el: dict[str, Any] = {
        "id": _uid(),
        "type": "text",
        "x": x,
        "y": y,
        "width": max(len(text) * size * 0.6, 40),
        "height": size * 1.4,
        "angle": 0,
        "strokeColor": color,
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 1,
        "roughness": 0,
        "opacity": 100,
        "roundness": None,
        "seed": abs(hash(_uid())) % 2_000_000_000,
        "version": 1,
        "versionNonce": abs(hash(_uid())) % 2_000_000_000,
        "isDeleted": False,
        "boundElements": [],
        "link": None,
        "locked": False,
        "text": text,
        "fontSize": size,
        "fontFamily": 1,
        "textAlign": "left",
        "verticalAlign": "top",
        "groupIds": [group] if group else [],
        "originalText": text,
    }
    return el


def _exc_arrow(
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    *,
    color: str = _AZURE_PRIMARY,
    label: str = "",
) -> list[dict]:
    """Return an arrow element (and optional label text element)."""
    elements: list[dict] = []
    arrow: dict[str, Any] = {
        "id": _uid(),
        "type": "arrow",
        "x": start_x,
        "y": start_y,
        "width": end_x - start_x,
        "height": end_y - start_y,
        "angle": 0,
        "strokeColor": color,
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 2,
        "roughness": 0,
        "opacity": 100,
        "roundness": {"type": 2},
        "seed": abs(hash(_uid())) % 2_000_000_000,
        "version": 1,
        "versionNonce": abs(hash(_uid())) % 2_000_000_000,
        "isDeleted": False,
        "boundElements": [],
        "link": None,
        "locked": False,
        "points": [[0, 0], [end_x - start_x, end_y - start_y]],
        "lastCommittedPoint": None,
        "startBinding": None,
        "endBinding": None,
        "startArrowhead": None,
        "endArrowhead": "arrow",
        "groupIds": [],
        "strokeStyle": "solid",
    }
    elements.append(arrow)
    if label:
        mid_x = (start_x + end_x) / 2
        mid_y = (start_y + end_y) / 2
        elements.append(
            _exc_text(mid_x, mid_y - 14, label, size=14, color=color)
        )
    return elements


def _generate_excalidraw(analysis: dict) -> dict:
    zones = analysis.get("zones", [])
    mappings = analysis.get("mappings", [])
    title = analysis.get("title", "Azure Architecture Diagram")

    elements: list[dict] = []

    # Layout constants — aligned with Excalidraw MCP skill canvas-patterns
    zone_w = 360
    zone_h_base = 180
    svc_h = 52
    svc_spacing = 60
    zone_pad = 80
    cols = min(len(zones), 4) or 1
    margin_x = 80
    margin_y = 120
    title_h = 60

    # Semantic zone colours from Excalidraw MCP skill colour palette
    _EXC_ZONE_COLORS = [
        {"bg": "#a5d8ff", "stroke": "#1971c2"},   # Frontend / UI
        {"bg": "#d0bfff", "stroke": "#7048e8"},   # Backend / API
        {"bg": "#b2f2bb", "stroke": "#2f9e44"},   # Database
        {"bg": "#fff3bf", "stroke": "#fab005"},   # Queue / Events
        {"bg": "#e599f7", "stroke": "#9c36b5"},   # AI / ML
        {"bg": "#ffc9c9", "stroke": "#e03131"},   # External
        {"bg": "#ffe8cc", "stroke": "#fd7e14"},   # Cache
        {"bg": "#ffec99", "stroke": "#f08c00"},   # Storage
    ]

    # ── Title ── (fontSize ≥ 24 per skill typography rules)
    elements.append(
        _exc_text(margin_x, 20, title, size=24, color="#1e1e1e", bold=True)
    )

    # Build a mapping from service aws name → azure name + confidence
    svc_map: dict[str, dict] = {}
    for m in mappings:
        aws = m.get("source_service") or m.get("aws_service") or m.get("source", "")
        azure = m.get("azure_service") or m.get("target", "")
        confidence = m.get("confidence", "medium")
        svc_map[aws] = {"azure": azure, "confidence": confidence}

    # Excalidraw file attachments for embedded icons
    exc_files: dict[str, dict] = {}

    # ── Compute zone sizes ──
    zone_positions: list[dict] = []
    for idx, zone in enumerate(zones):
        services = zone.get("services", [])
        num_services = max(len(services), 1)
        this_h = zone_h_base + (num_services - 1) * svc_spacing
        col = idx % cols
        row = idx // cols
        zx = margin_x + col * (zone_w + zone_pad)
        zy = margin_y + title_h + row * (zone_h_base + 6 * svc_spacing + zone_pad)
        zone_positions.append({
            "x": zx, "y": zy, "w": zone_w, "h": this_h,
            "services": services, "zone": zone, "idx": idx,
        })

    # ── Cloud boundary ──
    if zone_positions:
        max_x = max(z["x"] + z["w"] for z in zone_positions) + zone_pad
        max_y = max(z["y"] + z["h"] for z in zone_positions) + zone_pad
    else:
        max_x = 800
        max_y = 600
    cloud_x = margin_x - 30
    cloud_y = margin_y + title_h - 30
    cloud_w = max_x - cloud_x + 30
    cloud_h = max_y - cloud_y + 30

    # ── Cloud boundary (zone background — dashed, low opacity per skill rules) ──
    elements.append(
        _exc_rect(
            cloud_x, cloud_y, cloud_w, cloud_h,
            stroke=_AZURE_PRIMARY, dash=[8, 4], opacity=30,
        )
    )
    elements.append(
        _exc_text(cloud_x + 10, cloud_y + 6, "Azure Cloud", size=16, color="#868e96")
    )

    # ── Zone rectangles + services ──
    zone_center_map: dict[int, tuple[float, float]] = {}
    for zp in zone_positions:
        idx = zp["idx"]
        zone = zp["zone"]
        zx, zy, zw, zh = zp["x"], zp["y"], zp["w"], zp["h"]
        zone_colors = _EXC_ZONE_COLORS[idx % len(_EXC_ZONE_COLORS)]
        gid = _uid()

        zone_name = zone.get("name", f"Zone {idx + 1}")
        zone_number = zone.get("number", idx + 1)

        # Zone rect — dashed stroke, opacity 30 per skill rules (zones are backgrounds)
        elements.append(
            _exc_rect(zx, zy, zw, zh, stroke=zone_colors["stroke"],
                       bg=zone_colors["bg"], fill="solid", radius=12,
                       group=gid, dash=[8, 4], opacity=35)
        )
        # Zone label (fontSize ≥ 16 per skill typography rules)
        elements.append(
            _exc_text(zx + 10, zy + 8, f"{zone_name} (#{zone_number})",
                       size=16, color=zone_colors["stroke"], group=gid, bold=True)
        )

        # Services inside zone
        for si, svc in enumerate(zp["services"]):
            if isinstance(svc, str):
                aws_name = svc
                info = svc_map.get(aws_name, {})
                azure_name = info.get("azure", aws_name)
                raw_conf = info.get("confidence", "medium")
            else:
                aws_name = svc.get("source", svc.get("aws", svc.get("gcp", svc.get("source_service", svc.get("name", "")))))
                azure_name = svc.get("azure", svc.get("azure_service", aws_name))
                raw_conf = svc.get("confidence", "medium")

            if isinstance(raw_conf, (int, float)):
                confidence = "high" if raw_conf >= 0.85 else "medium" if raw_conf >= 0.7 else "low"
            else:
                confidence = str(raw_conf)
            conf_color = _CONFIDENCE_COLORS.get(confidence, _CONFIDENCE_COLORS["medium"])

            sx = zx + 16
            sy = zy + 40 + si * svc_spacing
            sw = zw - 32
            sh = svc_h

            icon_uri = _resolve_icon_svg(azure_name)

            elements.append(
                _exc_rect(sx, sy, sw, sh, stroke=conf_color, bg="#FFFFFF", fill="solid", radius=8, group=gid)
            )

            if icon_uri:
                # Embed icon as an image element inside the service box
                file_id = hashlib.sha256(azure_name.encode()).hexdigest()[:20]  # nosec B324  # nosemgrep: python.lang.security.insecure-hash-algorithms-md5.insecure-hash-algorithm-md5
                exc_files[file_id] = {
                    "mimeType": "image/svg+xml",
                    "id": file_id,
                    "dataURL": icon_uri,
                    "created": 1,
                }
                img_el: dict[str, Any] = {
                    "id": _uid(),
                    "type": "image",
                    "x": sx + 4,
                    "y": sy + 4,
                    "width": 36,
                    "height": 36,
                    "angle": 0,
                    "strokeColor": "transparent",
                    "backgroundColor": "transparent",
                    "fillStyle": "solid",
                    "strokeWidth": 0,
                    "roughness": 0,
                    "opacity": 100,
                    "roundness": None,
                    "seed": abs(hash(_uid())) % 2_000_000_000,
                    "version": 1,
                    "versionNonce": abs(hash(_uid())) % 2_000_000_000,
                    "isDeleted": False,
                    "boundElements": [],
                    "link": None,
                    "locked": False,
                    "fileId": file_id,
                    "status": "saved",
                    "scale": [1, 1],
                    "groupIds": [gid],
                }
                elements.append(img_el)
                # Label beside icon (fontSize ≥ 14 per skill rules)
                label = f"{aws_name} → {azure_name}" if aws_name != azure_name else azure_name
                elements.append(
                    _exc_text(sx + 44, sy + 6, label, size=14, color="#1a1a1a", group=gid)
                )
                elements.append(
                    _exc_text(sx + 44, sy + 28, f"[{confidence}]", size=14, color=conf_color, group=gid)
                )
            else:
                label = f"{aws_name} → {azure_name}" if aws_name != azure_name else azure_name
                elements.append(
                    _exc_text(sx + 8, sy + 6, label, size=14, color="#1a1a1a", group=gid)
                )
                # confidence indicator (fontSize ≥ 14 per skill rules)
                elements.append(
                    _exc_text(sx + 8, sy + 28, f"[{confidence}]", size=14, color=conf_color, group=gid)
                )

        zone_center_map[idx] = (zx + zw / 2, zy + zh / 2)

    # ── Data-flow arrows between consecutive zones ──
    for i in range(len(zone_positions) - 1):
        src = zone_positions[i]
        dst = zone_positions[i + 1]
        sx = src["x"] + src["w"]
        sy = src["y"] + src["h"] / 2
        dx = dst["x"]
        dy = dst["y"] + dst["h"] / 2
        # If zones wrap to next row, draw downward
        if dst["x"] <= src["x"]:
            sx = src["x"] + src["w"] / 2
            sy = src["y"] + src["h"]
            dx = dst["x"] + dst["w"] / 2
            dy = dst["y"]
        elements.extend(
            _exc_arrow(sx, sy, dx, dy, color=_AZURE_SECONDARY, label="data flow")
        )

    # ── Legend ──
    legend_y = max_y + 30
    elements.append(
        _exc_text(margin_x, legend_y, "Confidence:", size=16, color="#495057", bold=True)
    )
    for li, (level, color) in enumerate(_CONFIDENCE_COLORS.items()):
        lx = margin_x + 140 + li * 160
        elements.append(
            _exc_rect(lx, legend_y, 18, 18, stroke=color, bg=color, fill="solid")
        )
        elements.append(
            _exc_text(lx + 24, legend_y, level.capitalize(), size=14, color=color)
        )

    doc = {
        "type": "excalidraw",
        "version": 2,
        "source": "archmorph",
        "elements": elements,
        "appState": {"viewBackgroundColor": "#FFFFFF"},
        "files": exc_files,
    }

    return {
        "format": "excalidraw",
        "filename": "architecture.excalidraw",
        "content": json.dumps(doc, indent=2),
    }


# ===================================================================== #
#  Draw.io / diagrams.net generator                                      #
# ===================================================================== #

def _drawio_style(base: str = "rounded=1;whiteSpace=wrap;html=1;", **kw: str) -> str:
    parts = [base]
    for k, v in kw.items():
        parts.append(f"{k}={v};")
    return "".join(parts)


def _generate_drawio(analysis: dict) -> dict:
    zones = analysis.get("zones", [])
    mappings = analysis.get("mappings", [])
    title = analysis.get("title", "Azure Architecture Diagram")

    # Build mapping lookup
    svc_map: dict[str, dict] = {}
    for m in mappings:
        aws = m.get("source_service") or m.get("aws_service") or m.get("source", "")
        azure = m.get("azure_service") or m.get("target", "")
        confidence = m.get("confidence", "medium")
        svc_map[aws] = {"azure": azure, "confidence": confidence}

    # Root XML
    root = ET.Element("mxfile", host="archmorph", type="device")
    diagram_el = ET.SubElement(root, "diagram", id=_uid(), name="Architecture")
    graph_model = ET.SubElement(diagram_el, "mxGraphModel", dx="1200", dy="800", grid="1",
                                gridSize="10", guides="1", tooltips="1", connect="1",
                                arrows="1", fold="1", page="1", pageScale="1",
                                pageWidth="2400", pageHeight="1600")
    root_cell = ET.SubElement(graph_model, "root")
    ET.SubElement(root_cell, "mxCell", id="0")
    ET.SubElement(root_cell, "mxCell", id="1", parent="0")

    cell_id = 2

    def next_id() -> str:
        nonlocal cell_id
        cid = str(cell_id)
        cell_id += 1
        return cid

    # Layout
    zone_w = 420
    zone_h_base = 160
    svc_h = 50
    svc_spacing = 60
    zone_pad = 60
    cols = min(len(zones), 4) or 1
    margin_x = 60
    margin_y = 100

    # ── Title ──
    tid = next_id()
    ET.SubElement(
        root_cell, "mxCell",
        id=tid, value=title, style="text;fontSize=24;fontColor=#0078D4;fontStyle=1;align=left;",
        vertex="1", parent="1",
    ).append(_mx_geom(margin_x, 20, 600, 40))

    # ── Cloud boundary ──
    cloud_id = next_id()
    # Will resize after laying out zones
    cloud_cell = ET.SubElement(
        root_cell, "mxCell",
        id=cloud_id,
        value="Azure Cloud",
        style="rounded=1;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4;"
              "strokeColor=#0078D4;fillColor=none;fontSize=14;fontColor=#0078D4;"
              "verticalAlign=top;align=left;spacingLeft=10;spacingTop=4;",
        vertex="1", parent="1",
    )

    zone_rects: list[dict] = []
    zone_ids: list[str] = []

    for idx, zone in enumerate(zones):
        services = zone.get("services", [])
        num_services = max(len(services), 1)
        zh = zone_h_base + (num_services - 1) * svc_spacing

        col = idx % cols
        row = idx // cols
        zx = margin_x + 20 + col * (zone_w + zone_pad)
        zy = margin_y + 60 + row * (zone_h_base + 6 * svc_spacing + zone_pad)

        bg = _ZONE_COLORS[idx % len(_ZONE_COLORS)]
        zone_name = zone.get("name", f"Zone {idx + 1}")
        zone_number = zone.get("number", idx + 1)

        zid = next_id()
        zone_ids.append(zid)
        zone_rects.append({"x": zx, "y": zy, "w": zone_w, "h": zh, "id": zid, "services": services})

        zone_style = (
            f"swimlane;startSize=30;fillColor={bg};strokeColor=#0078D4;"
            f"rounded=1;fontSize=14;fontColor=#0078D4;fontStyle=1;whiteSpace=wrap;html=1;"
        )
        zone_cell = ET.SubElement(
            root_cell, "mxCell",
            id=zid,
            value=f"{zone_name} (#{zone_number})",
            style=zone_style,
            vertex="1", parent="1",
        )
        zone_cell.append(_mx_geom(zx, zy, zone_w, zh))

        # Services
        for si, svc in enumerate(services):
            if isinstance(svc, str):
                aws_name = svc
                info = svc_map.get(aws_name, {})
                azure_name = info.get("azure", aws_name)
                raw_conf = info.get("confidence", "medium")
            else:
                aws_name = svc.get("source", svc.get("aws", svc.get("gcp", svc.get("source_service", svc.get("name", "")))))
                azure_name = svc.get("azure", svc.get("azure_service", aws_name))
                raw_conf = svc.get("confidence", "medium")

            # Normalise confidence to string key
            if isinstance(raw_conf, (int, float)):
                confidence = "high" if raw_conf >= 0.85 else "medium" if raw_conf >= 0.7 else "low"
            else:
                confidence = str(raw_conf)
            conf_color = _CONFIDENCE_COLORS.get(confidence, _CONFIDENCE_COLORS["medium"])

            azure2_icon = get_azure_stencil_id(azure_name, "drawio")
            label = f"{aws_name} → {azure_name}" if aws_name != azure_name else azure_name

            sx = 16
            sy = 40 + si * svc_spacing
            sw = zone_w - 32
            sh = svc_h

            # Azure2 icon cell (left side) — uses image style for reliable rendering
            icon_id = next_id()
            icon_style = (
                f"image;aspect=fixed;html=1;points=[];align=center;"
                f"image={azure2_icon};"
            )
            icon_cell = ET.SubElement(
                root_cell, "mxCell",
                id=icon_id, value="",
                style=icon_style,
                vertex="1", parent=zid,
            )
            icon_cell.append(_mx_geom(sx + 4, sy + 5, 40, 40))
            # Label cell (right of icon)
            lbl_id = next_id()
            lbl_style = (
                f"text;html=1;align=left;verticalAlign=middle;whiteSpace=wrap;"
                f"rounded=1;strokeColor={conf_color};fillColor=#FFFFFF;"
                f"fontSize=12;fontColor=#1a1a1a;spacingLeft=4;"
            )
            lbl_cell = ET.SubElement(
                root_cell, "mxCell",
                id=lbl_id, value=label,
                style=lbl_style,
                vertex="1", parent=zid,
            )
            lbl_cell.append(_mx_geom(sx + 48, sy, sw - 48, sh))

    # ── Cloud boundary geometry ──
    if zone_rects:
        bx = margin_x
        by = margin_y + 40
        bw = max(z["x"] + z["w"] for z in zone_rects) - bx + zone_pad
        bh = max(z["y"] + z["h"] for z in zone_rects) - by + zone_pad
    else:
        bx, by, bw, bh = margin_x, margin_y, 800, 600
    cloud_cell.append(_mx_geom(bx, by, bw, bh))

    # ── Arrows between consecutive zones ──
    for i in range(len(zone_rects) - 1):
        src = zone_rects[i]
        dst = zone_rects[i + 1]
        eid = next_id()
        arrow_style = (
            "edgeStyle=orthogonalEdgeStyle;rounded=1;strokeColor=#50E6FF;"
            "strokeWidth=2;fontSize=11;fontColor=#0078D4;"
        )
        edge = ET.SubElement(
            root_cell, "mxCell",
            id=eid,
            value="data flow",
            style=arrow_style,
            edge="1", parent="1",
            source=src["id"], target=dst["id"],
        )
        edge.append(_mx_geom(0, 0, 0, 0, relative=True))

    xml_str = ET.tostring(root, encoding="unicode", xml_declaration=True)
    return {
        "format": "drawio",
        "filename": "architecture.drawio",
        "content": xml_str,
    }


def _mx_geom(x: float, y: float, w: float, h: float, *, relative: bool = False) -> ET.Element:
    attrs: dict[str, str] = {
        "x": str(int(x)),
        "y": str(int(y)),
        "width": str(int(w)),
        "height": str(int(h)),
        "as": "geometry",
    }
    if relative:
        attrs["relative"] = "1"
    return ET.Element("mxGeometry", attrs)


# ===================================================================== #
#  Visio VDX generator                                                   #
# ===================================================================== #

_VDX_NS = "http://schemas.microsoft.com/visio/2003/core"


def _generate_vsdx(analysis: dict) -> dict:
    zones = analysis.get("zones", [])
    mappings = analysis.get("mappings", [])
    title = analysis.get("title", "Azure Architecture Diagram")

    svc_map: dict[str, dict] = {}
    for m in mappings:
        aws = m.get("source_service") or m.get("aws_service") or m.get("source", "")
        azure = m.get("azure_service") or m.get("target", "")
        confidence = m.get("confidence", "medium")
        svc_map[aws] = {"azure": azure, "confidence": confidence}

    # Register default namespace so output is cleaner
    ET.register_namespace("", _VDX_NS)

    vdx = ET.Element(
        f"{{{_VDX_NS}}}VisioDocument",
        attrib={
            "xmlns": _VDX_NS,
            "xmlns:vx": "http://schemas.microsoft.com/visio/2006/extension",
        },
    )

    # DocumentProperties
    doc_props = ET.SubElement(vdx, f"{{{_VDX_NS}}}DocumentProperties")
    ET.SubElement(doc_props, f"{{{_VDX_NS}}}Title").text = title
    ET.SubElement(doc_props, f"{{{_VDX_NS}}}Creator").text = "Archmorph"

    # FaceNames (font)
    face_names = ET.SubElement(vdx, f"{{{_VDX_NS}}}FaceNames")
    fn = ET.SubElement(face_names, f"{{{_VDX_NS}}}FaceName", ID="1", Name="Segoe UI")
    fn.set("CharSets", "0")

    # Masters (stencils)
    masters = ET.SubElement(vdx, f"{{{_VDX_NS}}}Masters")
    master_id = 0
    master_map: dict[str, str] = {}
    for svc_name in AZURE_STENCILS:
        master_id += 1
        visio_name = get_azure_stencil_id(svc_name, "visio")
        mid = str(master_id)
        m_el = ET.SubElement(masters, f"{{{_VDX_NS}}}Master", ID=mid, Name=visio_name)
        m_el.set("NameU", visio_name)
        master_map[svc_name] = mid

    # Pages
    pages = ET.SubElement(vdx, f"{{{_VDX_NS}}}Pages")
    page = ET.SubElement(pages, f"{{{_VDX_NS}}}Page", ID="0", Name="Architecture")

    # PageSheet
    page_sheet = ET.SubElement(page, f"{{{_VDX_NS}}}PageSheet")
    page_props = ET.SubElement(page_sheet, f"{{{_VDX_NS}}}PageProps")
    ET.SubElement(page_props, f"{{{_VDX_NS}}}PageWidth").text = "34"
    ET.SubElement(page_props, f"{{{_VDX_NS}}}PageHeight").text = "22"

    shapes = ET.SubElement(page, f"{{{_VDX_NS}}}Shapes")

    shape_id = 0

    def next_shape_id() -> str:
        nonlocal shape_id
        shape_id += 1
        return str(shape_id)

    # Layout
    zone_w_in = 4.5  # inches
    zone_h_base_in = 2.5
    svc_h_in = 0.6
    svc_spacing_in = 0.8
    zone_pad_in = 0.8
    cols = min(len(zones), 4) or 1
    margin_x_in = 1.0
    margin_y_in = 2.0

    zone_shapes: list[dict] = []

    for idx, zone in enumerate(zones):
        services = zone.get("services", [])
        num_services = max(len(services), 1)
        zh = zone_h_base_in + (num_services - 1) * svc_spacing_in

        col = idx % cols
        row = idx // cols
        zx = margin_x_in + col * (zone_w_in + zone_pad_in)
        zy = margin_y_in + row * (zone_h_base_in + 6 * svc_spacing_in + zone_pad_in)

        zone_name = zone.get("name", f"Zone {idx + 1}")
        zone_number = zone.get("number", idx + 1)
        bg = _ZONE_COLORS[idx % len(_ZONE_COLORS)]

        # Zone group shape
        zsid = next_shape_id()
        zone_shape = ET.SubElement(shapes, f"{{{_VDX_NS}}}Shape", ID=zsid, Type="Group",
                                   NameU=f"Zone_{zone_number}")
        _vdx_xform(zone_shape, zx + zone_w_in / 2, zy + zh / 2, zone_w_in, zh)
        _vdx_fill(zone_shape, bg)
        _vdx_text(zone_shape, f"{zone_name} (#{zone_number})")

        zone_shapes.append({"id": zsid, "x": zx, "y": zy, "w": zone_w_in, "h": zh})

        sub_shapes = ET.SubElement(zone_shape, f"{{{_VDX_NS}}}Shapes")

        for si, svc in enumerate(services):
            aws_name = svc if isinstance(svc, str) else svc.get("source", svc.get("aws", svc.get("gcp", svc.get("source_service", svc.get("name", "")))))
            info = svc_map.get(aws_name, {})
            azure_name = info.get("azure", svc.get("azure", aws_name) if isinstance(svc, dict) else aws_name)
            raw_conf = info.get("confidence", svc.get("confidence", "medium") if isinstance(svc, dict) else "medium")
            if isinstance(raw_conf, (int, float)):
                confidence = "high" if raw_conf >= 0.85 else ("medium" if raw_conf >= 0.7 else "low")
            else:
                confidence = str(raw_conf) if raw_conf else "medium"

            stencil_name = get_azure_stencil_id(azure_name, "visio")
            label = f"{aws_name} → {azure_name}" if aws_name != azure_name else azure_name

            sx_local = zone_w_in / 2
            sy_local = 0.6 + si * svc_spacing_in
            sw = zone_w_in - 0.6
            sh = svc_h_in

            ssid = next_shape_id()
            mid = master_map.get(azure_name, "")
            svc_el_attrs: dict[str, str] = {"ID": ssid, "Type": "Shape", "NameU": stencil_name}
            if mid:
                svc_el_attrs["Master"] = mid
            svc_el = ET.SubElement(sub_shapes, f"{{{_VDX_NS}}}Shape", **svc_el_attrs)
            _vdx_xform(svc_el, sx_local, sy_local, sw, sh)
            _vdx_fill(svc_el, "#FFFFFF")
            _vdx_line(svc_el, _CONFIDENCE_COLORS.get(confidence, "#FF9800"))
            _vdx_text(svc_el, label)

    # ── Connectors between consecutive zones ──
    connects = ET.SubElement(page, f"{{{_VDX_NS}}}Connects")
    for i in range(len(zone_shapes) - 1):
        csid = next_shape_id()
        conn = ET.SubElement(shapes, f"{{{_VDX_NS}}}Shape", ID=csid, Type="Shape",
                             NameU=f"Connector_{i}")
        # XForm1D
        xform1d = ET.SubElement(conn, f"{{{_VDX_NS}}}XForm1D")
        src_z = zone_shapes[i]
        dst_z = zone_shapes[i + 1]
        ET.SubElement(xform1d, f"{{{_VDX_NS}}}BeginX").text = str(src_z["x"] + src_z["w"])
        ET.SubElement(xform1d, f"{{{_VDX_NS}}}BeginY").text = str(src_z["y"] + src_z["h"] / 2)
        ET.SubElement(xform1d, f"{{{_VDX_NS}}}EndX").text = str(dst_z["x"])
        ET.SubElement(xform1d, f"{{{_VDX_NS}}}EndY").text = str(dst_z["y"] + dst_z["h"] / 2)
        _vdx_line(conn, _AZURE_SECONDARY)
        _vdx_text(conn, "data flow")

        # Connect elements
        ET.SubElement(connects, f"{{{_VDX_NS}}}Connect", FromSheet=csid, FromCell="BeginX",
                           ToSheet=src_z["id"])
        ET.SubElement(connects, f"{{{_VDX_NS}}}Connect", FromSheet=csid, FromCell="EndX",
                           ToSheet=dst_z["id"])

    xml_str = ET.tostring(vdx, encoding="unicode", xml_declaration=True)
    return {
        "format": "vsdx",
        "filename": "architecture.vdx",
        "content": xml_str,
    }


def _vdx_xform(parent: ET.Element, cx: float, cy: float, w: float, h: float) -> None:
    xform = ET.SubElement(parent, f"{{{_VDX_NS}}}XForm")
    ET.SubElement(xform, f"{{{_VDX_NS}}}PinX").text = str(round(cx, 4))
    ET.SubElement(xform, f"{{{_VDX_NS}}}PinY").text = str(round(cy, 4))
    ET.SubElement(xform, f"{{{_VDX_NS}}}Width").text = str(round(w, 4))
    ET.SubElement(xform, f"{{{_VDX_NS}}}Height").text = str(round(h, 4))
    ET.SubElement(xform, f"{{{_VDX_NS}}}LocPinX").text = str(round(w / 2, 4))
    ET.SubElement(xform, f"{{{_VDX_NS}}}LocPinY").text = str(round(h / 2, 4))


def _vdx_fill(parent: ET.Element, color: str) -> None:
    fill = ET.SubElement(parent, f"{{{_VDX_NS}}}Fill")
    ET.SubElement(fill, f"{{{_VDX_NS}}}FillForegnd").text = color
    ET.SubElement(fill, f"{{{_VDX_NS}}}FillPattern").text = "1"


def _vdx_line(parent: ET.Element, color: str) -> None:
    line = ET.SubElement(parent, f"{{{_VDX_NS}}}Line")
    ET.SubElement(line, f"{{{_VDX_NS}}}LineColor").text = color
    ET.SubElement(line, f"{{{_VDX_NS}}}LineWeight").text = "0.02"
    ET.SubElement(line, f"{{{_VDX_NS}}}LinePattern").text = "1"


def _vdx_text(parent: ET.Element, text: str) -> None:
    t = ET.SubElement(parent, f"{{{_VDX_NS}}}Text")
    t.text = text
