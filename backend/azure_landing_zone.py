"""Azure Landing Zone SVG generator (#573).

Renders a region-aware, Microsoft-iconography landing-zone diagram from the
Archmorph analysis dict.  Output is a single self-contained SVG with all
icons embedded as ``data:image/svg+xml;base64,...`` data URIs (no external
references).

Public API::

    generate_landing_zone_svg(analysis, *, dr_variant="primary") -> dict[str, str]

Returns ``{"format": "landing-zone-svg", "filename": ..., "content": ...}``.

Sub-issue: https://github.com/idokatz86/Archmorph/issues/573
Parent epic: https://github.com/idokatz86/Archmorph/issues/571
"""

from __future__ import annotations

import base64
import re
import time
import xml.etree.ElementTree as ET
from typing import Any, Literal, Optional

from azure_landing_zone_schema import (
    infer_actors,
    infer_dr_mode,
    infer_regions,
    infer_replication,
    infer_tiers_from_mappings,
)

# #595 — Observability for the landing-zone-svg pipeline. The observability
# module is a thin wrapper around the OpenTelemetry SDK + an in-memory store
# for the admin dashboard. All four helpers below are best-effort and never
# raise on instrumentation failure (verified by the observability test
# suite), so it is safe to import unconditionally — even from contexts where
# the OTel SDK is not configured (e.g. CLI scripts, unit tests).
from observability import (
    increment_counter,
    record_histogram,
    trace_span,
)

# ---------------------------------------------------------------------------
# Constants — palette, fonts, dimensions
# ---------------------------------------------------------------------------

# Microsoft Fluent palette (same swatches used in the parity-target build.py).
COLOR_PRIMARY      = "#0078D4"   # Azure blue
COLOR_PURPLE       = "#5C2D91"   # Subnet purple
COLOR_GREEN        = "#107C10"   # Active / success
COLOR_RED          = "#C73E1D"   # DR / standby
COLOR_DEEP_PURPLE  = "#742774"   # Event Hubs
COLOR_K8S          = "#326CE5"   # AKS
COLOR_CYAN         = "#3CCBF4"   # Front Door
COLOR_TEAL         = "#00BFB3"   # AVA
COLOR_AMBER        = "#B25E00"   # Cross-region replication
COLOR_DB           = "#1A5DAB"   # Managed DB
COLOR_INK          = "#1B2541"   # Primary text
COLOR_INK_2        = "#3a4a6e"   # Secondary edges
COLOR_BG           = "#FAFBFC"   # Canvas

FONT_STACK = "'Segoe UI','Segoe UI Variable',system-ui,-apple-system,Helvetica,Arial,sans-serif"

CANVAS_W = 1800
CANVAS_H_PRIMARY = 1330
CANVAS_H_DR = 2120

# Hard cap on returned SVG size — protect downstream renderers and HTTP layer.
MAX_SVG_BYTES = 300 * 1024


# ---------------------------------------------------------------------------
# Source-provider contract (#576) — implicit, read from analysis dict.
# ---------------------------------------------------------------------------
# The schema is vendor-neutral; the only thing that varies per source provider
# is the legend mapping line. Callers set ``analysis["source_provider"]`` to
# one of the values in ``_SUPPORTED_SOURCE_PROVIDERS``. Missing → "aws"
# (backwards-compatible with #571). Unknown → ValueError.

_SUPPORTED_SOURCE_PROVIDERS: frozenset[str] = frozenset({"aws", "gcp"})

_SOURCE_PROVIDER_LEGEND_LINE: dict[str, str] = {
    "aws": (
        "AWS → Azure · ALB → App Gateway · EKS → AKS · "
        "EFS → Azure Files · Kafka → Event Hubs · RDS → Managed DB"
    ),
    "gcp": (
        "GCP → Azure · GLB → App Gateway · GKE → AKS · "
        "Filestore → Azure Files · Pub/Sub → Event Hubs · Cloud SQL → Managed DB"
    ),
}

# Lockstep invariant — the supported set must match the legend table exactly.
assert _SUPPORTED_SOURCE_PROVIDERS == frozenset(_SOURCE_PROVIDER_LEGEND_LINE), (
    "source-provider constants drifted: "
    f"{_SUPPORTED_SOURCE_PROVIDERS} vs {set(_SOURCE_PROVIDER_LEGEND_LINE)}"
)


def _validate_source_provider(value: object) -> str:
    """Lowercase, default to ``"aws"`` only when ``None``, else strict-validate.

    Contract:
      * ``None`` (key missing in ``analysis``) → defaults to ``"aws"``.
      * Non-string types → ``ValueError`` (mapped to HTTP 400 by the router).
      * Empty / whitespace-only string → ``ValueError`` (do NOT silently default).
      * Unknown known-string → ``ValueError``.
    """
    if value is None:
        return "aws"
    if not isinstance(value, str):
        raise ValueError(
            f"Unsupported source_provider: {value!r}. "
            f"Expected a string in {sorted(_SUPPORTED_SOURCE_PROVIDERS)}."
        )
    provider = value.strip().lower()
    if not provider or provider not in _SUPPORTED_SOURCE_PROVIDERS:
        raise ValueError(
            f"Unsupported source_provider: {value!r}. "
            f"Expected one of {sorted(_SUPPORTED_SOURCE_PROVIDERS)}."
        )
    return provider


# ---------------------------------------------------------------------------
# Icon resolution — registry-first, fallback to coloured-tile placeholder
# ---------------------------------------------------------------------------

# Logical icon keys map → Azure service IDs known to the icon registry.
# When the registry has no match the placeholder is used; the SVG is always
# renderable.
_ICON_SERVICE_IDS: dict[str, list[str]] = {
    "frontdoor":    ["azure-front-door", "Front Door", "frontdoor"],
    "appgw":        ["application-gateway", "App Gateway", "appgw"],
    "storage":      ["azure-storage", "storage-account", "blob"],
    "aks":          ["aks", "kubernetes-service", "azure-kubernetes-service"],
    "files":        ["azure-files", "storage-files", "files"],
    "sql":          ["azure-sql", "sql-database", "azure-sql-database"],
    "eventhub":     ["event-hubs", "eventhub", "azure-event-hubs"],
    "monitor":      ["azure-monitor", "monitor"],
    "appinsights":  ["application-insights", "app-insights", "appinsights"],
    "loganalytics": ["log-analytics", "loganalytics"],
    "dns":          ["private-dns", "azure-dns", "dns"],
    "avd":          ["avd", "azure-virtual-desktop", "virtual-desktop"],
    "entra":        ["entra-id", "azure-active-directory", "aad"],
    "keyvault":     ["key-vault", "keyvault"],
    "region":       ["region", "azure-region"],
    "subnet":       ["subnet", "virtual-network-subnet"],
    "vm":           ["virtual-machine", "vm"],
    "vnet":         ["virtual-network", "vnet"],
    "rg":           ["resource-group", "rg"],
    "user":         ["user", "person"],
}

# Per-key fallback tile color so the placeholder still reads at a glance.
_ICON_TILE_COLOR: dict[str, str] = {
    "frontdoor":    COLOR_CYAN,
    "appgw":        COLOR_PRIMARY,
    "storage":      COLOR_PRIMARY,
    "aks":          COLOR_K8S,
    "files":        COLOR_PRIMARY,
    "sql":          COLOR_DB,
    "eventhub":     COLOR_DEEP_PURPLE,
    "monitor":      COLOR_PRIMARY,
    "appinsights":  COLOR_PRIMARY,
    "loganalytics": COLOR_PRIMARY,
    "dns":          COLOR_PURPLE,
    "avd":          COLOR_PRIMARY,
    "entra":        COLOR_PRIMARY,
    "keyvault":     COLOR_PRIMARY,
    "region":       COLOR_GREEN,
    "subnet":       COLOR_PURPLE,
    "vm":           COLOR_PRIMARY,
    "vnet":         COLOR_GREEN,
    "rg":           COLOR_PRIMARY,
    "user":         COLOR_INK_2,
}


def _resolve_data_uri(icon_key: str) -> Optional[str]:
    """Look the icon up in Archmorph's icon registry and return a data URI."""
    try:
        from icons.registry import resolve_icon  # type: ignore
    except Exception:  # nosec B110 - registry optional
        return None

    candidates = _ICON_SERVICE_IDS.get(icon_key, [icon_key])
    for sid in candidates:
        try:
            entry = resolve_icon(sid, provider="azure")
        except Exception:  # nosec B110 - any registry error → placeholder
            entry = None
        if entry and entry.svg:
            try:
                b64 = base64.b64encode(entry.svg.encode("utf-8")).decode("ascii")
            except Exception:  # nosec B110 - encoding errors → placeholder
                continue
            return f"data:image/svg+xml;base64,{b64}"
    return None


_ICON_CACHE: dict[str, Optional[str]] = {}


def _icon_data_uri(icon_key: str) -> Optional[str]:
    """Cached registry lookup.

    The registry can be empty at first lookup (lazy-loaded on demand by
    `icons.registry._ensure_loaded`, see #587). To avoid permanently caching
    a `None` from a pre-bootstrap miss, we only cache successful resolutions.
    Subsequent lookups for unresolved keys re-hit the registry, which is
    cheap once the store is populated.
    """
    cached = _ICON_CACHE.get(icon_key)
    if cached is not None:
        return cached
    uri = _resolve_data_uri(icon_key)
    if uri is not None:
        _ICON_CACHE[icon_key] = uri
    return uri


def _img(icon_key: str, x: float, y: float, w: float, h: float) -> str:
    """Render an icon, falling back to a labelled tile when registry misses.

    #595 — emit ``archmorph.lz.icon_resolution_total{result="hit"|"fallback"}``
    on every icon-slot render. This is the single source of truth for the
    icon-resolution observability metric: the SLO + alert in
    ``infra/observability/alerts.tf`` reads off these labels directly.
    """
    uri = _icon_data_uri(icon_key)
    if uri:
        increment_counter(
            "archmorph.lz.icon_resolution_total",
            tags={"result": "hit", "icon_key": icon_key},
        )
        return (
            f'<image href="{uri}" x="{x}" y="{y}" '
            f'width="{w}" height="{h}" preserveAspectRatio="xMidYMid meet"/>'
        )
    increment_counter(
        "archmorph.lz.icon_resolution_total",
        tags={"result": "fallback", "icon_key": icon_key},
    )
    # Placeholder: filled rectangle with two-letter glyph.
    color = _ICON_TILE_COLOR.get(icon_key, COLOR_PRIMARY)
    glyph = _placeholder_glyph(icon_key)
    return (
        f'<g class="icon-fallback">'
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="3" '
        f'fill="{color}" stroke="{COLOR_INK}" stroke-width="0.5" stroke-opacity="0.2"/>'
        f'<text x="{x + w / 2}" y="{y + h / 2 + h * 0.12}" '
        f'fill="#FFFFFF" font-family="{FONT_STACK}" font-size="{max(8, h * 0.5):.1f}" '
        f'font-weight="700" text-anchor="middle">{_xml_escape(glyph)}</text>'
        f'</g>'
    )


def _placeholder_glyph(icon_key: str) -> str:
    """Two-character glyph used in placeholder tiles."""
    table = {
        "frontdoor": "FD", "appgw": "AG", "storage": "ST", "aks": "AK",
        "files": "AF", "sql": "DB", "eventhub": "EH", "monitor": "AM",
        "appinsights": "AI", "loganalytics": "LA", "dns": "DN", "avd": "VD",
        "entra": "ID", "keyvault": "KV", "region": "RG", "subnet": "SN",
        "vm": "VM", "vnet": "VN", "rg": "RG", "user": "U",
    }
    return table.get(icon_key, icon_key[:2].upper())


# ---------------------------------------------------------------------------
# SVG primitives
# ---------------------------------------------------------------------------

_INVALID_XML_CHARS = re.compile(
    r'[\x00-\x08\x0b\x0c\x0e-\x1f]'
)


def _xml_escape(s: str) -> str:
    """Escape a string for inclusion as XML text content."""
    s = _INVALID_XML_CHARS.sub("", s or "")
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
         .replace("'", "&apos;")
    )


def _tx(x: float, y: float, text: str, cls: str, anchor: str = "start", weight: str = "") -> str:
    """Single text element."""
    weight_attr = f' font-weight="{weight}"' if weight else ""
    return (
        f'<text x="{x}" y="{y}" class="{cls}" text-anchor="{anchor}"{weight_attr}>'
        f'{_xml_escape(text)}</text>'
    )


def _card(x: float, y: float, w: float, h: float, *, stroke: str = COLOR_PRIMARY,
          fill: str = "#FFFFFF", rx: int = 6) -> str:
    """White rounded card."""
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
    )


def _defs() -> str:
    """SVG <defs> with style sheet, arrow markers."""
    return f"""<defs>
<style><![CDATA[
text {{ font-family: {FONT_STACK}; }}
.t-title {{ font-size: 22px; font-weight: 700; fill: {COLOR_INK}; }}
.t-sub   {{ font-size: 13px; fill: #44506b; }}
.t-banner {{ font-size: 12px; font-weight: 700; fill: #FFFFFF; }}
.t-card-h-lg {{ font-size: 14px; font-weight: 700; fill: {COLOR_INK}; }}
.t-card-h    {{ font-size: 12px; font-weight: 700; fill: {COLOR_INK}; }}
.t-meta      {{ font-size: 11px; fill: #44506b; }}
.t-tiny      {{ font-size: 10px; fill: #44506b; }}
.t-tinier    {{ font-size:  9px; fill: #44506b; }}
.t-edge      {{ font-size: 11px; fill: {COLOR_INK_2}; }}
.t-edge-g    {{ font-size: 11px; font-weight: 700; fill: {COLOR_GREEN}; }}
.t-edge-r    {{ font-size: 11px; font-weight: 700; fill: {COLOR_RED}; }}
.t-legend-h  {{ font-size: 13px; font-weight: 700; fill: {COLOR_INK}; }}
.t-legend    {{ font-size: 11px; fill: {COLOR_INK}; }}
.t-mapnote   {{ font-size: 11px; fill: #44506b; }}
.t-actor-h   {{ font-size: 12px; font-weight: 700; fill: {COLOR_INK}; }}
.t-traffic-g {{ font-size: 12px; font-weight: 700; fill: {COLOR_GREEN}; }}
.t-traffic-r {{ font-size: 12px; font-weight: 700; fill: {COLOR_RED}; }}
]]></style>
<marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
  <path d="M 0 0 L 10 5 L 0 10 z" fill="{COLOR_INK_2}"/>
</marker>
<marker id="ag" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
  <path d="M 0 0 L 10 5 L 0 10 z" fill="{COLOR_GREEN}"/>
</marker>
<marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
  <path d="M 0 0 L 10 5 L 0 10 z" fill="{COLOR_RED}"/>
</marker>
</defs>"""


# ---------------------------------------------------------------------------
# Rendering — actors / front door / region stamp / legend
# ---------------------------------------------------------------------------

def _actors_row(actors: list[dict[str, Any]]) -> str:
    """Top swimlane of actors, evenly distributed across the canvas."""
    out = ['<g id="actors">']
    if not actors:
        return "</g>".join(out + [""])

    # Distribute up to 6 actors across canvas width.
    visible = actors[:6]
    span = CANVAS_W - 200
    step = span / max(1, len(visible))
    for i, actor in enumerate(visible):
        cx = 100 + step * (i + 0.5)
        out.append(f'<g transform="translate({cx - 60}, 86)">')
        out.append(_card(0, 0, 120, 56, stroke=COLOR_INK_2))
        out.append(_img("user", 8, 8, 28, 28))
        out.append(_tx(44, 22, actor.get("name", ""), "t-actor-h"))
        if actor.get("subtitle"):
            out.append(_tx(44, 38, actor["subtitle"], "t-tiny"))
        kind = actor.get("kind", "external")
        out.append(_tx(44, 50, f"({kind})", "t-tinier"))
        out.append('</g>')
        # Actor → Front Door arrow
        out.append(
            f'<line x1="{cx}" y1="142" x2="{cx}" y2="208" '
            f'stroke="{COLOR_INK_2}" stroke-width="1.4" '
            f'stroke-dasharray="3 3" marker-end="url(#a)"/>'
        )
        edge = actor.get("edge_label", "HTTPS")
        if edge:
            out.append(_tx(cx + 6, 180, edge, "t-edge"))
    out.append('</g>')
    return "\n".join(out)


def _front_door(regions: list[dict[str, Any]], dr_mode: str) -> str:
    """Front Door banner with traffic chips per region."""
    x, y, w, h = 560, 208, 900, 56
    out = [f'<g id="front-door" transform="translate({x}, {y})">',
           _card(0, 0, w, h, stroke=COLOR_CYAN),
           _img("frontdoor", 12, 12, 32, 32),
           _tx(54, 24, "Azure Front Door + WAF", "t-card-h-lg"),
           _tx(54, 40, "Global edge · TLS termination · path-based routing · health probes",
               "t-meta")]

    # Traffic chips for up to two regions.
    chip_x = [660, 770]
    for i, region in enumerate(regions[:2]):
        try:
            pct = int(round(float(region.get("traffic_pct", 0))))
        except (TypeError, ValueError):
            pct = 0
        active = pct > 0 if dr_mode != "single-region" else True
        color = COLOR_GREEN if active else COLOR_RED
        cls = "t-traffic-g" if active else "t-traffic-r"
        cx = chip_x[i] if i < len(chip_x) else 660 + i * 110
        out.append(
            f'<rect x="{cx}" y="12" width="100" height="32" rx="6" '
            f'fill="#FFFFFF" stroke="{color}" stroke-width="1.5"/>'
        )
        out.append(_tx(cx + 50, 30, f"{pct}% → R{i + 1}", cls, anchor="middle"))
    out.append('</g>')
    return "\n".join(out)


def _legend(y: int, source_provider: str = "aws") -> str:
    """7-column × 2-row icon grid + line-style key + source→Azure mapping line.

    ``source_provider`` selects the canonical mapping line printed in the
    bottom-right of the legend. Must be one of
    ``_SUPPORTED_SOURCE_PROVIDERS`` — validation should happen at the
    public entry point (``generate_landing_zone_svg``).
    """
    if source_provider not in _SOURCE_PROVIDER_LEGEND_LINE:
        # Defensive guard — callers should validate up front.
        raise ValueError(f"Unsupported source_provider: {source_provider!r}")
    mapping_line = _SOURCE_PROVIDER_LEGEND_LINE[source_provider]
    H = 124
    out = [
        f'<rect x="20" y="{y}" width="1760" height="{H}" rx="6" '
        f'fill="#FFFFFF" stroke="#5b6b8c" stroke-width="1"/>',
        _tx(40, y + 20, "Legend", "t-legend-h"),
    ]
    items = [
        ("frontdoor",    "Front Door + WAF"),
        ("appgw",        "App Gateway WAFv2"),
        ("storage",      "Storage (Blob/SFTP)"),
        ("aks",          "Azure Kubernetes Service"),
        ("files",        "Azure Files (SMB)"),
        ("sql",          "Managed Relational DB"),
        ("eventhub",     "Event Hubs"),
        ("monitor",      "Azure Monitor"),
        ("appinsights",  "App Insights"),
        ("loganalytics", "Log Analytics"),
        ("dns",          "Private DNS"),
        ("avd",          "Azure Virtual Desktop"),
        ("entra",        "Entra ID"),
        ("keyvault",     "Key Vault"),
    ]
    cols = 7
    col_w = 240
    row_h = 28
    base_x = 40
    base_y = y + 30
    for i, (k, lbl) in enumerate(items):
        r = i // cols
        c = i % cols
        cx = base_x + c * col_w
        cy = base_y + r * row_h
        out.append(_img(k, cx, cy, 18, 18))
        out.append(_tx(cx + 24, cy + 13, lbl, "t-legend"))

    # Line-style key row.
    line_y = y + 92
    out.append(f'<rect x="40"  y="{line_y}" width="14" height="3" fill="{COLOR_GREEN}"/>')
    out.append(_tx(60, line_y + 6, "Active path", "t-legend"))
    out.append(f'<rect x="160" y="{line_y}" width="14" height="3" fill="{COLOR_RED}"/>')
    out.append(_tx(180, line_y + 6, "DR / standby", "t-legend"))
    out.append(f'<rect x="280" y="{line_y}" width="14" height="3" fill="{COLOR_INK_2}"/>')
    out.append(_tx(300, line_y + 6, "Data flow", "t-legend"))
    out.append(
        f'<line x1="380" y1="{line_y + 1}" x2="394" y2="{line_y + 1}" '
        f'stroke="{COLOR_DB}" stroke-width="2" stroke-dasharray="4 2"/>'
    )
    out.append(_tx(400, line_y + 6, "HA replication", "t-legend"))
    out.append(
        f'<line x1="500" y1="{line_y + 1}" x2="514" y2="{line_y + 1}" '
        f'stroke="{COLOR_AMBER}" stroke-width="2"/>'
    )
    out.append(_tx(520, line_y + 6, "Cross-region replication", "t-legend"))
    out.append(_tx(720, line_y + 6, "Mapping:", "t-mapnote", weight="700"))
    out.append(_tx(780, line_y + 6, mapping_line, "t-mapnote"))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Region stamp — the bulk of the diagram
# ---------------------------------------------------------------------------

# Layout constants for region stamp.
REGION_W = 1740
REGION_H = 760

# Tier-1 card slots (left → right) — must total to width REGION_W.
# (relative_x, width, icon_key, default_label)
_TIER1_CARDS: list[tuple[int, int, str, str]] = [
    (50,   220, "storage", "Storage"),
    (360,  270, "appgw",   "Application Gateway"),
    (660,  240, "avd",     "Azure Virtual Desktop"),
    (910,  350, "monitor", "Observability"),
    (1290, 170, "dns",     "Private DNS"),
    (1480, 220, "entra",   "Identity"),
]


def _region_stamp(x: int, y: int, region: dict[str, Any], tiers: dict[str, list[dict[str, Any]]],
                  *, status: str = "primary", role_text: str = "") -> str:
    """One region container with tiered services."""
    out = [f'<g transform="translate({x}, {y})">']

    # Outer region card.
    region_color = COLOR_GREEN if status == "primary" else COLOR_RED
    out.append(
        f'<rect x="0" y="0" width="{REGION_W}" height="{REGION_H}" rx="10" '
        f'fill="#FFFFFF" stroke="{region_color}" stroke-width="2"/>'
    )
    # Region header strip.
    out.append(
        f'<rect x="0" y="0" width="{REGION_W}" height="34" rx="2" '
        f'fill="{region_color}"/>'
    )
    out.append(_img("region", 8, 8, 18, 18))
    out.append(_tx(34, 22, region.get("name", "Region"), "t-banner"))
    if role_text:
        out.append(_tx(REGION_W - 16, 22, role_text, "t-banner", anchor="end"))

    # Resource Group container.
    rg_w, rg_h = 1700, 706
    out.append(
        f'<rect x="20" y="38" width="{rg_w}" height="{rg_h}" rx="8" '
        f'fill="#F7F9FC" stroke="{COLOR_PRIMARY}" stroke-width="1"/>'
    )
    out.append(
        f'<rect x="20" y="38" width="280" height="22" rx="2" '
        f'fill="{COLOR_PRIMARY}"/>'
    )
    out.append(_img("rg", 24, 40, 16, 16))
    out.append(_tx(46, 54, "Resource Group · landing-zone", "t-banner"))

    # Tier-1 cards (top row).
    out.append(_tier1_row(tiers))

    # VNet + subnets (centre band).
    out.append(_vnet_block(tiers))

    # Files banner + Data subnet.
    out.append(_data_band(tiers))

    out.append('</g>')
    return "\n".join(out)


def _tier1_row(tiers: dict[str, list[dict[str, Any]]]) -> str:
    """Top tier — ingress / observability / identity / DNS / storage."""
    out: list[str] = []

    # Resolve a per-slot service name from tiers when available.
    ingress_names    = [s["name"] for s in tiers.get("ingress", [])]
    storage_names    = [s["name"] for s in tiers.get("storage", [])]
    identity_names   = [s["name"] for s in tiers.get("identity", [])]
    obs_names        = [s["name"] for s in tiers.get("observability", [])]

    slot_overrides = {
        "storage": storage_names[0] if storage_names else None,
        "appgw":   ingress_names[0] if ingress_names else None,
        "entra":   identity_names[0] if identity_names else None,
    }

    for rel_x, w, icon_key, default_label in _TIER1_CARDS:
        h = 100
        y = 76
        label = slot_overrides.get(icon_key) or default_label
        out.append(_card(rel_x, y, w, h, stroke=COLOR_PRIMARY))
        # The Observability tile gets a row of 5 sub-icons.
        if icon_key == "monitor":
            out.append(_tx(rel_x + w / 2, y + 22, "Observability", "t-card-h-lg",
                           anchor="middle"))
            sub_icons = ["monitor", "appinsights", "loganalytics", "monitor", "monitor"]
            sub_labels = ["Monitor", "App Insights", "Log Analytics", "Alerts", "Workbooks"]
            for i, (sic, slabel) in enumerate(zip(sub_icons, sub_labels)):
                cx = rel_x + 22 + i * 64
                out.append(_img(sic, cx - 11, y + 32, 22, 22))
                out.append(_tx(cx, y + 70, slabel, "t-tinier", anchor="middle"))
            # Provide one summary line listing what we found for observability.
            summary = ", ".join(obs_names[:3]) if obs_names else "centralised"
            out.append(_tx(rel_x + w / 2, y + 88, summary, "t-tinier", anchor="middle"))
        else:
            out.append(_img(icon_key, rel_x + 12, y + 12, 28, 28))
            out.append(_tx(rel_x + 48, y + 28, label, "t-card-h"))
            # Subtitle from tiers if available.
            subtitle = ""
            if icon_key == "storage" and tiers.get("storage"):
                subtitle = tiers["storage"][0].get("subtitle", "")
            elif icon_key == "appgw" and tiers.get("ingress"):
                subtitle = tiers["ingress"][0].get("subtitle", "")
            elif icon_key == "entra" and tiers.get("identity"):
                subtitle = tiers["identity"][0].get("subtitle", "")
            elif icon_key == "dns":
                subtitle = "Private DNS zones · service discovery"
            elif icon_key == "avd":
                subtitle = "Bastion · session host · just-in-time"
            if subtitle:
                out.append(_tx(rel_x + 48, y + 44, subtitle, "t-tiny"))
            out.append(_tx(rel_x + 48, y + 64, "Zone-redundant", "t-tinier"))

    return "\n".join(out)


def _vnet_block(tiers: dict[str, list[dict[str, Any]]]) -> str:
    """VNet container with Application Subnet + AKS + 3 AZ columns."""
    out: list[str] = []
    vnet_x, vnet_y, vnet_w, vnet_h = 40, 200, 1480, 540
    out.append(
        f'<rect x="{vnet_x}" y="{vnet_y}" width="{vnet_w}" height="{vnet_h}" rx="8" '
        f'fill="#F0FAF0" stroke="{COLOR_GREEN}" stroke-width="1.5"/>'
    )
    out.append(
        f'<rect x="{vnet_x}" y="{vnet_y}" width="240" height="22" rx="2" '
        f'fill="{COLOR_GREEN}"/>'
    )
    out.append(_img("vnet", vnet_x + 4, vnet_y + 3, 16, 16))
    out.append(_tx(vnet_x + 26, vnet_y + 17, "VNet · 10.0.0.0/16", "t-banner"))

    # Application Subnet.
    app_x, app_y, app_w, app_h = 60, 234, 1440, 396
    out.append(
        f'<rect x="{app_x}" y="{app_y}" width="{app_w}" height="{app_h}" rx="6" '
        f'fill="#F4F2FA" stroke="{COLOR_PURPLE}" stroke-width="1.5"/>'
    )
    out.append(
        f'<rect x="{app_x}" y="{app_y}" width="280" height="20" rx="2" '
        f'fill="{COLOR_PURPLE}"/>'
    )
    out.append(_img("subnet", app_x + 4, app_y + 1, 16, 16))
    out.append(_tx(app_x + 26, app_y + 15, "Application Subnet · 10.0.1.0/24", "t-banner"))

    # AKS container inside Application subnet.
    aks_x, aks_y, aks_w, aks_h = 246, 272, 1000, 304
    out.append(
        f'<rect x="{aks_x}" y="{aks_y}" width="{aks_w}" height="{aks_h}" rx="6" '
        f'fill="#FFFFFF" stroke="{COLOR_K8S}" stroke-width="1.5"/>'
    )
    out.append(
        f'<rect x="{aks_x}" y="{aks_y}" width="340" height="22" rx="2" '
        f'fill="{COLOR_K8S}"/>'
    )
    out.append(_img("aks", aks_x + 4, aks_y + 2, 18, 18))
    aks_label_names = [s["name"] for s in tiers.get("compute", [])][:1]
    aks_title = f"{aks_label_names[0]} · 3 zones" if aks_label_names else "Azure Kubernetes Service · 3 zones"
    out.append(_tx(aks_x + 28, aks_y + 16, aks_title, "t-banner"))

    # 3 AZ columns. Pull workload pod names from compute tier when available.
    compute_pods = [s["name"] for s in tiers.get("compute", [])]
    az_pods_default = [
        ["Workload pods", "Background workers", "Service mesh", "Sidecars", "Init pods", None],
        ["Workload pods", "Background workers", "Service mesh", None, None, None],
        ["Workload pods", None, "Service mesh", None, None, None],
    ]
    # If we have explicit compute services, surface up to 5 in AZ1.
    if compute_pods:
        custom = compute_pods[:5] + [None] * (6 - min(5, len(compute_pods)))
        az_pods_default[0] = custom

    for i in range(3):
        ax = 260 + i * 330
        ay = 304
        out.append(_az_column(ax, ay, f"Availability Zone {i + 1}", az_pods_default[i]))

    # Files banner.
    fb_x, fb_y, fb_w, fb_h = 80, 588, 1404, 38
    out.append(_card(fb_x, fb_y, fb_w, fb_h, stroke=COLOR_PRIMARY))
    out.append(_img("files", fb_x + 8, fb_y + 4, 30, 30))
    files_name = "Azure Files (SMB)"
    files_subtitle = "Shared file storage · zone-redundant"
    for s in tiers.get("storage", []):
        if "files" in s["name"].lower() or "smb" in s["name"].lower():
            files_name = s["name"]
            if s.get("subtitle"):
                files_subtitle = s["subtitle"]
            break
    out.append(_tx(fb_x + 48, fb_y + 18, files_name, "t-card-h"))
    out.append(_tx(fb_x + 48, fb_y + 32, files_subtitle, "t-meta"))
    return "\n".join(out)


def _az_column(x: int, y: int, label: str, pods: list[Optional[str]]) -> str:
    """Single AZ column with header + 6 pod cells."""
    out = [f'<g transform="translate({x}, {y})">']
    col_w, col_h = 320, 260
    out.append(_card(0, 0, col_w, col_h, stroke=COLOR_INK_2))
    out.append(
        f'<rect x="0" y="0" width="{col_w}" height="22" rx="2" fill="{COLOR_INK_2}"/>'
    )
    out.append(_tx(8, 16, label, "t-banner"))

    visible_pods = [pod for pod in pods[:6] if pod]
    if not visible_pods:
        visible_pods = ["Workload not inferred"]

    cell_h = 36
    for i, pod in enumerate(visible_pods[:6]):
        cy = 30 + i * cell_h
        out.append(
            f'<rect x="8" y="{cy}" width="{col_w - 16}" height="{cell_h - 4}" rx="4" '
            f'fill="#FFFFFF" stroke="#cdd5e3" stroke-width="1"/>'
        )
        out.append(_tx(col_w / 2, cy + 20, pod, "t-tiny", anchor="middle"))
    out.append('</g>')
    return "\n".join(out)


def _data_band(tiers: dict[str, list[dict[str, Any]]]) -> str:
    """Data subnet — primary + standby DB pair."""
    out: list[str] = []
    ds_x, ds_y, ds_w, ds_h = 60, 652, 1440, 88
    out.append(
        f'<rect x="{ds_x}" y="{ds_y}" width="{ds_w}" height="{ds_h}" rx="6" '
        f'fill="#F4F2FA" stroke="{COLOR_PURPLE}" stroke-width="1.5"/>'
    )
    out.append(
        f'<rect x="{ds_x}" y="{ds_y}" width="240" height="20" rx="2" '
        f'fill="{COLOR_PURPLE}"/>'
    )
    out.append(_img("subnet", ds_x + 4, ds_y + 1, 16, 16))
    out.append(_tx(ds_x + 26, ds_y + 15, "Data Subnet · 10.0.2.0/24", "t-banner"))

    db_names = [s["name"] for s in tiers.get("data", [])]
    primary_label = db_names[0] if db_names else "Managed Relational DB"
    secondary_label = db_names[1] if len(db_names) > 1 else f"{primary_label} · Standby"

    # Primary DB.
    out.append(f'<g transform="translate({ds_x + 300}, {ds_y + 28})">')
    out.append(_card(0, 0, 320, 50, stroke=COLOR_DB))
    out.append(_img("sql", 8, 8, 36, 36))
    out.append(_tx(50, 22, f"{primary_label} · Primary", "t-card-h"))
    out.append(_tx(50, 38, "Zone 1 · synchronous HA · zone-redundant", "t-meta"))
    out.append('</g>')

    # HA replication arrow.
    arrow_x1 = ds_x + 620
    arrow_x2 = ds_x + 820
    out.append(
        f'<line x1="{arrow_x1}" y1="{ds_y + 53}" x2="{arrow_x2}" y2="{ds_y + 53}" '
        f'stroke="{COLOR_DB}" stroke-width="1.8" stroke-dasharray="6 4"/>'
    )
    out.append(_tx((arrow_x1 + arrow_x2) / 2, ds_y + 46,
                   "HA replication · Multi-AZ sync", "t-edge", anchor="middle", weight="700"))

    # Standby DB.
    out.append(f'<g transform="translate({ds_x + 820}, {ds_y + 28})">')
    out.append(_card(0, 0, 320, 50, stroke=COLOR_DB))
    out.append(_img("sql", 8, 8, 36, 36))
    out.append(_tx(50, 22, secondary_label, "t-card-h"))
    out.append(_tx(50, 38, "Zone 2 · HA replica · automatic failover", "t-meta"))
    out.append('</g>')
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Replication band (DR variant)
# ---------------------------------------------------------------------------

def _replication_band(y: int, replication: list[dict[str, Any]]) -> str:
    """Cross-region replication band between two regions."""
    height = 78
    out = [
        f'<rect x="20" y="{y}" width="1760" height="{height}" rx="8" '
        f'fill="#FFF8E1" stroke="{COLOR_AMBER}" stroke-width="1.5"/>',
        _tx(40, y + 22, "Cross-Region Replication & DR Plumbing", "t-card-h-lg"),
    ]
    items = replication[:6] if replication else []
    if not items:
        return "\n".join(out)
    col_w = 1760 // max(1, len(items))
    col_w = min(col_w, 290)
    for i, item in enumerate(items):
        cx = 40 + i * col_w
        out.append(
            f'<line x1="{cx - 6}" y1="{y + 34}" x2="{cx - 6}" y2="{y + 72}" '
            f'stroke="{COLOR_AMBER}" stroke-width="1.5"/>'
        )
        out.append(_tx(cx, y + 44, item.get("name", ""), "t-meta", weight="700"))
        out.append(_tx(cx, y + 60, item.get("mode", ""), "t-tiny"))

    # Failover arrow gestures.
    out.append(
        f'<path d="M 900 {y - 6} l 0 -10 m -8 0 l 8 -10 l 8 10" '
        f'stroke="{COLOR_AMBER}" stroke-width="2" fill="none"/>'
    )
    out.append(
        f'<path d="M 900 {y + height + 4} l 0 10 m -8 0 l 8 10 l 8 -10" '
        f'stroke="{COLOR_AMBER}" stroke-width="2" fill="none"/>'
    )
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_landing_zone_svg(
    analysis: dict[str, Any],
    *,
    dr_variant: Literal["primary", "dr"] = "primary",
) -> dict[str, str]:
    """Render the landing zone SVG for the given analysis.

    Returns ``{"format": "landing-zone-svg", "filename": ..., "content": ...}``.
    Raises :class:`ValueError` for invalid input or oversized output.

    #595 — fully OTel-instrumented:
      * Top-level span ``archmorph.lz.generate`` with attributes
        ``dr_variant``, ``source_provider``, ``svg_size_bytes``.
      * Sub-spans ``archmorph.lz.infer`` (schema inference) and
        ``archmorph.lz.render`` (SVG part assembly).
      * On success: ``archmorph.lz.svg_generation_duration_seconds`` +
        ``archmorph.lz.svg_size_bytes`` histograms.
      * On any raised exception: ``archmorph.lz.errors_total`` counter
        with ``{stage, error_type}`` tags.
      * Per-icon hit/fallback counter is emitted from ``_img()``.
    """
    start = time.monotonic()
    with trace_span(
        "archmorph.lz.generate",
        attributes={"dr_variant": str(dr_variant)},
    ) as top_span:
        try:
            if dr_variant not in ("primary", "dr"):
                increment_counter(
                    "archmorph.lz.errors_total",
                    tags={"stage": "validate", "error_type": "invalid_dr_variant"},
                )
                raise ValueError(
                    f"dr_variant must be 'primary' or 'dr', got {dr_variant!r}"
                )
            if not isinstance(analysis, dict):
                increment_counter(
                    "archmorph.lz.errors_total",
                    tags={"stage": "validate", "error_type": "bad_analysis_type"},
                )
                raise ValueError("analysis must be a dict")

            # #576: source_provider is implicit (read from the analysis payload) and
            # validated here. Default "aws" preserves backwards-compat with #571.
            try:
                source_provider = _validate_source_provider(
                    analysis.get("source_provider")
                )
            except ValueError:
                increment_counter(
                    "archmorph.lz.errors_total",
                    tags={"stage": "validate", "error_type": "bad_source_provider"},
                )
                raise
            top_span.set_attribute("source_provider", source_provider)

            with trace_span("archmorph.lz.infer"):
                regions = infer_regions(analysis, dr_variant=dr_variant)
                # Infer dr_mode and replication from the *effective* analysis (the regions
                # we will actually render). Without this, a legacy analysis with no
                # `regions`/`dr_mode` rendered as `dr_variant="dr"` would yield
                # `dr_mode="single-region"` and empty replication, contradicting the
                # two-region canvas.
                effective_analysis = {**analysis, "regions": regions}
                dr_mode = infer_dr_mode(effective_analysis)
                effective_analysis = {**effective_analysis, "dr_mode": dr_mode}
                tiers = infer_tiers_from_mappings(analysis)
                actors = infer_actors(analysis)
                replication = infer_replication(effective_analysis)
            top_span.set_attribute("dr_mode", dr_mode)

            with trace_span("archmorph.lz.render"):
                title = analysis.get("title") or "Azure Landing Zone"
                subtitle_bits = [
                    f"Regions: {', '.join(r['name'] for r in regions)}",
                    f"DR mode: {dr_mode}",
                ]
                if dr_variant == "dr":
                    subtitle_bits.append("Variant: full DR")
                subtitle = " · ".join(subtitle_bits)

                if dr_variant == "dr":
                    H = CANVAS_H_DR
                else:
                    H = CANVAS_H_PRIMARY

                parts: list[str] = [
                    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CANVAS_W} {H}" '
                    f'width="{CANVAS_W}" height="{H}">',
                    _defs(),
                    f'<rect width="{CANVAS_W}" height="{H}" fill="{COLOR_BG}"/>',
                    _tx(40, 38, _truncate(title, 90), "t-title"),
                    _tx(40, 60, _truncate(subtitle, 200), "t-sub"),
                    _actors_row(actors),
                    _front_door(regions, dr_mode),
                ]

                # Region 1 stamp.
                primary_role = regions[0].get("role", "primary")
                primary_role_text = (
                    f"Active · {regions[0].get('traffic_pct', 100)}% traffic"
                    if primary_role == "primary" else f"{primary_role.title()} role"
                )
                parts.append(_region_stamp(
                    20, 290, regions[0], tiers,
                    status="primary",
                    role_text=primary_role_text,
                ))

                if dr_variant == "primary":
                    # Collapsed Region 2 banner if a second region is configured.
                    if len(regions) >= 2:
                        r2 = regions[1]
                        parts.append(
                            f'<rect x="20" y="1064" width="1760" height="56" rx="8" '
                            f'fill="#FFF5F4" stroke="{COLOR_RED}" stroke-width="1.5" '
                            f'stroke-dasharray="6 4"/>'
                        )
                        parts.append(_img("region", 28, 1074, 22, 22))
                        parts.append(_tx(60, 1086, f"{r2['name']} (DR · {r2.get('traffic_pct', 0)}% traffic)",
                                         "t-card-h-lg"))
                        parts.append(_tx(60, 1108,
                                         "Symmetric stamp · paired region · standby for failover · "
                                         "GRS for Storage · geo-replica DB · KV replication",
                                         "t-meta"))
                        parts.append(_tx(1772, 1086, f"{r2.get('traffic_pct', 0)}% traffic",
                                         "t-edge-r", anchor="end"))
                    parts.append(_legend(1140, source_provider=source_provider))
                else:
                    # Full DR — replication band + Region 2 stamp + legend.
                    band_y = 1062
                    parts.append(_replication_band(band_y, replication))
                    r2_y = band_y + 78 + 12
                    if len(regions) >= 2:
                        r2 = regions[1]
                        parts.append(_region_stamp(
                            20, r2_y, r2, tiers,
                            status="standby",
                            role_text=f"Standby · {r2.get('traffic_pct', 0)}% traffic · automated failover",
                        ))
                    parts.append(_legend(r2_y + 776, source_provider=source_provider))

                parts.append('</svg>')

                svg_xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + "\n".join(parts)

            # Validate well-formed XML before returning.
            try:
                ET.fromstring(svg_xml)
            except ET.ParseError as exc:
                increment_counter(
                    "archmorph.lz.errors_total",
                    tags={"stage": "validate_xml", "error_type": "parse_error"},
                )
                raise ValueError(f"Generated SVG is not well-formed XML: {exc}") from exc

            svg_bytes = len(svg_xml.encode("utf-8"))
            if svg_bytes > MAX_SVG_BYTES:
                increment_counter(
                    "archmorph.lz.errors_total",
                    tags={"stage": "size_check", "error_type": "oversized"},
                )
                raise ValueError(
                    f"Generated SVG exceeds the {MAX_SVG_BYTES}-byte limit "
                    f"(got {svg_bytes} bytes)"
                )

            zone_name = "diagram"
            zones = analysis.get("zones") or []
            if zones and isinstance(zones[0], dict) and zones[0].get("name"):
                zone_name = _safe_filename_part(zones[0]["name"])

            # Success: emit size + duration histograms.
            duration_seconds = time.monotonic() - start
            record_histogram("archmorph.lz.svg_size_bytes", float(svg_bytes))
            record_histogram(
                "archmorph.lz.svg_generation_duration_seconds", duration_seconds
            )
            top_span.set_attribute("svg_size_bytes", svg_bytes)
            top_span.set_attribute("duration_seconds", round(duration_seconds, 4))

            return {
                "format": "landing-zone-svg",
                "filename": f"archmorph-{zone_name}-landing-zone-{dr_variant}.svg",
                "content": svg_xml,
            }
        except ValueError:
            # Already accounted for above (tagged with the offending stage).
            raise
        except Exception as exc:
            # Unexpected — bucket as render-stage with the exception class as
            # error_type so the alert can fire on the previously-unobserved
            # failure modes.
            increment_counter(
                "archmorph.lz.errors_total",
                tags={"stage": "render", "error_type": type(exc).__name__},
            )
            raise


def _truncate(text: str, n: int) -> str:
    text = (text or "").strip()
    if len(text) <= n:
        return text
    return text[: max(0, n - 1)].rstrip() + "…"


def _safe_filename_part(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return cleaned or "diagram"
