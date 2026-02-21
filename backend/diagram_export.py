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
import xml.etree.ElementTree as ET  # nosec B405 - generates XML, doesn't parse untrusted input
from typing import Any

# ---------------------------------------------------------------------------
# Azure stencil / icon mapping (30+ services)
# ---------------------------------------------------------------------------
AZURE_STENCILS: dict[str, dict[str, str]] = {
    "IoT Hub": {
        "drawio": "mxgraph.azure.iot_hub",
        "visio": "Azure IoT Hub",
    },
    "Event Hubs": {
        "drawio": "mxgraph.azure.event_hubs",
        "visio": "Azure Event Hubs",
    },
    "Blob Storage": {
        "drawio": "mxgraph.azure.storage",
        "visio": "Azure Blob Storage",
    },
    "Data Factory": {
        "drawio": "mxgraph.azure.data_factory",
        "visio": "Azure Data Factory",
    },
    "Synapse Analytics": {
        "drawio": "mxgraph.azure.synapse_analytics",
        "visio": "Azure Synapse Analytics",
    },
    "Azure Functions": {
        "drawio": "mxgraph.azure.function_apps",
        "visio": "Azure Functions",
    },
    "Cosmos DB": {
        "drawio": "mxgraph.azure.cosmos_db",
        "visio": "Azure Cosmos DB",
    },
    "Machine Learning": {
        "drawio": "mxgraph.azure.machine_learning",
        "visio": "Azure Machine Learning",
    },
    "API Management": {
        "drawio": "mxgraph.azure.api_management",
        "visio": "Azure API Management",
    },
    "Container Apps": {
        "drawio": "mxgraph.azure.kubernetes_services",
        "visio": "Azure Container Apps",
    },
    "Key Vault": {
        "drawio": "mxgraph.azure.key_vaults",
        "visio": "Azure Key Vault",
    },
    "AI Search": {
        "drawio": "mxgraph.azure.search",
        "visio": "Azure AI Search",
    },
    "ExpressRoute": {
        "drawio": "mxgraph.azure.expressroute_circuits",
        "visio": "Azure ExpressRoute",
    },
    "Power BI": {
        "drawio": "mxgraph.azure.analysis_services",
        "visio": "Microsoft Power BI",
    },
    "Purview": {
        "drawio": "mxgraph.azure.general",
        "visio": "Microsoft Purview",
    },
    "Container Instances": {
        "drawio": "mxgraph.azure.container_instances",
        "visio": "Azure Container Instances",
    },
    "HDInsight": {
        "drawio": "mxgraph.azure.hdinsight_cluster",
        "visio": "Azure HDInsight",
    },
    "IoT Edge": {
        "drawio": "mxgraph.azure.iot_edge",
        "visio": "Azure IoT Edge",
    },
    "Stack Edge": {
        "drawio": "mxgraph.azure.stack_edge",
        "visio": "Azure Stack Edge",
    },
    "SQL Database": {
        "drawio": "mxgraph.azure.sql_databases",
        "visio": "Azure SQL Database",
    },
    "App Service": {
        "drawio": "mxgraph.azure.app_services",
        "visio": "Azure App Service",
    },
    "Virtual Machines": {
        "drawio": "mxgraph.azure.virtual_machines",
        "visio": "Azure Virtual Machines",
    },
    "Virtual Network": {
        "drawio": "mxgraph.azure.virtual_networks",
        "visio": "Azure Virtual Network",
    },
    "Load Balancer": {
        "drawio": "mxgraph.azure.load_balancers",
        "visio": "Azure Load Balancer",
    },
    "Application Gateway": {
        "drawio": "mxgraph.azure.application_gateways",
        "visio": "Azure Application Gateway",
    },
    "Service Bus": {
        "drawio": "mxgraph.azure.service_bus",
        "visio": "Azure Service Bus",
    },
    "Logic Apps": {
        "drawio": "mxgraph.azure.logic_apps",
        "visio": "Azure Logic Apps",
    },
    "Cognitive Services": {
        "drawio": "mxgraph.azure.cognitive_services",
        "visio": "Azure Cognitive Services",
    },
    "Monitor": {
        "drawio": "mxgraph.azure.monitor",
        "visio": "Azure Monitor",
    },
    "Front Door": {
        "drawio": "mxgraph.azure.front_doors",
        "visio": "Azure Front Door",
    },
    "DNS": {
        "drawio": "mxgraph.azure.dns",
        "visio": "Azure DNS",
    },
    "Firewall": {
        "drawio": "mxgraph.azure.firewalls",
        "visio": "Azure Firewall",
    },
    "Redis Cache": {
        "drawio": "mxgraph.azure.cache_redis",
        "visio": "Azure Cache for Redis",
    },
    "Notification Hubs": {
        "drawio": "mxgraph.azure.notification_hubs",
        "visio": "Azure Notification Hubs",
    },
    "Stream Analytics": {
        "drawio": "mxgraph.azure.stream_analytics",
        "visio": "Azure Stream Analytics",
    },
    "Databricks": {
        "drawio": "mxgraph.azure.databricks",
        "visio": "Azure Databricks",
    },
}

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

def get_azure_stencil_id(service_name: str, target: str = "drawio") -> str:
    """Return the stencil / shape identifier for *service_name*.

    Parameters
    ----------
    service_name:
        Azure service display name (e.g. ``"IoT Hub"``).
    target:
        ``"drawio"`` or ``"visio"``.

    Returns
    -------
    str
        The stencil string, or a generic fallback when the service is unknown.
    """
    entry = AZURE_STENCILS.get(service_name)
    if entry:
        return entry.get(target, "mxgraph.azure.general")
    # Fuzzy fallback – try partial match
    lower = service_name.lower()
    for name, ids in AZURE_STENCILS.items():
        if lower in name.lower() or name.lower() in lower:
            return ids.get(target, "mxgraph.azure.general")

    # Fallback to Icon Registry (405 icons vs 36 hardcoded)
    try:
        from icons.registry import resolve_icon

        icon_entry = resolve_icon(service_name, provider="azure")
        if icon_entry:
            # Return the canonical ID as a reference; callers can embed the SVG
            return icon_entry.meta.id
    except Exception:  # noqa: BLE001  # nosec B110 - falls through to default icon
        pass

    return "mxgraph.azure.general" if target == "drawio" else "Azure General"


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
    return gen(analysis_result)


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
            _exc_text(mid_x, mid_y - 14, label, size=12, color=color)
        )
    return elements


def _generate_excalidraw(analysis: dict) -> dict:
    zones = analysis.get("zones", [])
    mappings = analysis.get("mappings", [])
    title = analysis.get("title", "Azure Architecture Diagram")

    elements: list[dict] = []

    # Layout constants
    zone_w = 320
    zone_h_base = 160
    svc_h = 44
    svc_spacing = 52
    zone_pad = 60
    cols = min(len(zones), 4) or 1
    margin_x = 80
    margin_y = 120
    title_h = 50

    # ── Title ──
    elements.append(
        _exc_text(margin_x, 20, title, size=28, color=_AZURE_PRIMARY, bold=True)
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

    elements.append(
        _exc_rect(
            cloud_x, cloud_y, cloud_w, cloud_h,
            stroke=_AZURE_PRIMARY, dash=[8, 4], opacity=60,
        )
    )
    elements.append(
        _exc_text(cloud_x + 10, cloud_y + 6, "Azure Cloud", size=14, color=_AZURE_PRIMARY)
    )

    # ── Zone rectangles + services ──
    zone_center_map: dict[int, tuple[float, float]] = {}
    for zp in zone_positions:
        idx = zp["idx"]
        zone = zp["zone"]
        zx, zy, zw, zh = zp["x"], zp["y"], zp["w"], zp["h"]
        bg = _ZONE_COLORS[idx % len(_ZONE_COLORS)]
        gid = _uid()

        zone_name = zone.get("name", f"Zone {idx + 1}")
        zone_number = zone.get("number", idx + 1)

        # Zone rect
        elements.append(
            _exc_rect(zx, zy, zw, zh, stroke=_AZURE_PRIMARY, bg=bg, fill="solid", radius=12, group=gid)
        )
        # Zone label
        elements.append(
            _exc_text(zx + 10, zy + 8, f"{zone_name} (#{zone_number})", size=16, color=_AZURE_PRIMARY, group=gid, bold=True)
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
                file_id = hashlib.md5(azure_name.encode()).hexdigest()[:20]  # nosec B324 - non-security ID generation for diagram icons
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
                # Label beside icon
                label = f"{aws_name} → {azure_name}" if aws_name != azure_name else azure_name
                elements.append(
                    _exc_text(sx + 44, sy + 6, label, size=13, color="#1a1a1a", group=gid)
                )
                elements.append(
                    _exc_text(sx + 44, sy + 26, f"[{confidence}]", size=10, color=conf_color, group=gid)
                )
            else:
                label = f"{aws_name} → {azure_name}" if aws_name != azure_name else azure_name
                elements.append(
                    _exc_text(sx + 8, sy + 6, label, size=13, color="#1a1a1a", group=gid)
                )
                # small confidence indicator text
                elements.append(
                    _exc_text(sx + 8, sy + 26, f"[{confidence}]", size=10, color=conf_color, group=gid)
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
        _exc_text(margin_x, legend_y, "Confidence:", size=14, color="#333333", bold=True)
    )
    for li, (level, color) in enumerate(_CONFIDENCE_COLORS.items()):
        lx = margin_x + 120 + li * 140
        elements.append(
            _exc_rect(lx, legend_y, 16, 16, stroke=color, bg=color, fill="solid")
        )
        elements.append(
            _exc_text(lx + 22, legend_y, level.capitalize(), size=13, color=color)
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

            stencil = get_azure_stencil_id(azure_name, "drawio")
            icon_uri = _resolve_icon_svg(azure_name)
            label = f"{aws_name} → {azure_name}" if aws_name != azure_name else azure_name

            sx = 16
            sy = 40 + si * svc_spacing
            sw = zone_w - 32
            sh = svc_h

            # Use embedded icon image when available, fall back to stencil shape
            if icon_uri:
                # Icon cell (left side)
                icon_id = next_id()
                icon_style = (
                    f"shape=image;image={icon_uri};"
                    f"verticalLabelPosition=bottom;verticalAlign=top;"
                    f"aspect=fixed;imageAspect=0;"
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
            else:
                svc_style = (
                    f"shape={stencil};whiteSpace=wrap;html=1;rounded=1;"
                    f"strokeColor={conf_color};fillColor=#FFFFFF;fontSize=12;"
                    f"fontColor=#1a1a1a;align=left;spacingLeft=8;"
                )
                sid = next_id()
                svc_cell = ET.SubElement(
                    root_cell, "mxCell",
                    id=sid,
                    value=label,
                    style=svc_style,
                    vertex="1", parent=zid,
                )
                svc_cell.append(_mx_geom(sx, sy, sw, sh))

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
