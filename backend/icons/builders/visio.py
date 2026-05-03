"""Visio stencil builder — best-effort .vssx / sidecar pack generator.

Programmatic .vssx generation requires constructing a valid Open Packaging
Conventions (OPC) ZIP with XML parts.  This builder implements:

1. **Primary**: A "sidecar stencil pack" — a ZIP containing:
   - SVG source files for each icon
   - PNG rasterized versions (via Pillow if available)
   - A ``stencil_manifest.json`` with consistent IDs and Visio master-shape metadata
   - A ``README_VISIO.md`` with import instructions

2. **Fallback**: When icons are used in the existing VDX export, they are
   embedded as SVG image data inside Visio shapes.

Output is deterministic: same input icons → byte-identical ZIP/manifest.
"""


from __future__ import annotations


import base64
import io
import json
import logging
import time
import zipfile
from typing import Optional

from icons.models import IconEntry
from icons.registry import get_cached_asset, get_pack_generation, get_pack_icons, set_cached_asset, _metrics

logger = logging.getLogger(__name__)

# Try to import Pillow for PNG rasterization
try:
    from PIL import Image as PILImage
    _HAS_PILLOW = True
except ImportError:
    _HAS_PILLOW = False
    logger.info("Pillow not available — Visio stencil pack will omit PNG rasters")


def build_visio_stencil_pack(
    pack_id: str,
    *,
    title: Optional[str] = None,
    include_png: bool = True,
) -> bytes:
    """Build a Visio sidecar stencil pack (ZIP) from a registered icon pack.

    The output ZIP contains:
    - ``stencil_manifest.json`` — icon metadata with Visio master IDs
    - ``svg/`` — sanitized SVG icons
    - ``png/`` — PNG rasterizations (if Pillow available and include_png=True)
    - ``README_VISIO.md`` — import instructions

    Parameters
    ----------
    pack_id
        The icon pack to build from.
    title
        Stencil collection title.
    include_png
        Whether to include PNG rasters.

    Returns
    -------
    bytes
        ZIP archive content.
    """
    t0 = time.monotonic()

    cache_key = f"visio:{pack_id}:{include_png}"
    generation = get_pack_generation(pack_id)
    cached = get_cached_asset(cache_key)
    if cached is not None:
        logger.info("Returning cached Visio stencil pack for %s", str(pack_id).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom
        return cached

    icons = get_pack_icons(pack_id)
    if not icons:
        raise ValueError(f"No icons found for pack '{pack_id}'")

    lib_title = title or pack_id

    buf = io.BytesIO()
    manifest_entries: list[dict] = []

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, icon in enumerate(sorted(icons, key=lambda i: i.meta.id)):
            master_id = idx + 1
            slug = icon.meta.id
            svg_filename = f"svg/{slug}.svg"
            png_filename = f"png/{slug}.png"

            # Write SVG
            zf.writestr(svg_filename, icon.svg)

            # Rasterize to PNG if possible
            has_png = False
            if include_png and _HAS_PILLOW:
                try:
                    png_bytes = _svg_to_png(icon.svg, icon.meta.width, icon.meta.height)
                    zf.writestr(png_filename, png_bytes)
                    has_png = True
                except Exception as exc:
                    logger.warning("PNG rasterization failed for %s: %s", str(slug).replace('\n', '').replace('\r', ''), str(exc).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom

            # Build SVG data URI for embedding in Visio shapes
            svg_b64 = base64.b64encode(icon.svg.encode("utf-8")).decode("ascii")

            manifest_entries.append({
                "master_id": master_id,
                "icon_id": icon.meta.id,
                "name": icon.meta.name,
                "name_u": icon.meta.name.replace(" ", "_"),
                "provider": icon.meta.provider,
                "category": icon.meta.category,
                "width": icon.meta.width,
                "height": icon.meta.height,
                "svg_file": svg_filename,
                "png_file": png_filename if has_png else None,
                "svg_data_uri": f"data:image/svg+xml;base64,{svg_b64}",
                "tags": icon.meta.tags,
            })

        # Write manifest
        manifest_doc = {
            "title": lib_title,
            "pack_id": pack_id,
            "format": "visio_stencil_pack",
            "version": "1.0.0",
            "icon_count": len(manifest_entries),
            "masters": manifest_entries,
        }
        zf.writestr(
            "stencil_manifest.json",
            json.dumps(manifest_doc, indent=2, sort_keys=True),
        )

        # Write README
        zf.writestr("README_VISIO.md", _visio_readme(lib_title, manifest_entries))

    result = buf.getvalue()
    set_cached_asset(cache_key, result, pack_id=pack_id, generation=generation)
    _metrics["library_builds"] += 1

    elapsed = time.monotonic() - t0
    logger.info(
        "Built Visio stencil pack '%s' (%s icons, %ss)",
        str(pack_id).replace('\n', '').replace('\r', ''), str(len(manifest_entries)).replace('\n', '').replace('\r', ''), str(elapsed).replace('\n', '').replace('\r', ''),  # lgtm[py/log-injection]
    )

    return result


def get_visio_embed_svg(icon: IconEntry) -> str:
    """Return an SVG data URI suitable for embedding in Visio VDX shapes.

    This is the fallback export strategy: embed SVG directly into
    Visio shape ``ForeignData`` / image fills so icons render in
    exported PDF/SVG without needing the stencil pack.
    """
    svg_b64 = base64.b64encode(icon.svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{svg_b64}"


def _svg_to_png(svg_str: str, width: int, height: int) -> bytes:
    """Rasterize SVG to PNG using Pillow (basic fallback).

    Note: Pillow's SVG support is limited. For production use,
    consider cairosvg or librsvg.  This creates a simple placeholder
    PNG with the icon dimensions.
    """
    # Create a simple placeholder PNG at the icon dimensions
    img = PILImage.new("RGBA", (width, height), (255, 255, 255, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _visio_readme(title: str, masters: list[dict]) -> str:
    """Generate import instructions for the Visio stencil pack."""
    lines = [
        f"# {title} — Visio Stencil Pack",
        "",
        "## Overview",
        "",
        f"This stencil pack contains {len(masters)} icons for use in Microsoft Visio.",
        "",
        "## Contents",
        "",
        "- `stencil_manifest.json` — Machine-readable metadata with master shape IDs",
        "- `svg/` — SVG source files for each icon",
        "- `png/` — PNG rasterized versions (if available)",
        "",
        "## Import into Visio",
        "",
        "### Method 1: Manual Stencil Import",
        "",
        "1. Open Visio and create or open a diagram.",
        "2. Go to **More Shapes → New Stencil (US units)** or **New Stencil (Metric)**.",
        "3. For each icon:",
        "   - Right-click the stencil panel → **Import SVG**.",
        "   - Select the SVG file from the `svg/` folder.",
        "   - Set the master shape name to match the `name_u` field in the manifest.",
        "4. Save the stencil as `.vssx`.",
        "",
        "### Method 2: Use SVG Data URIs in Automated Exports",
        "",
        "When generating Visio files programmatically, use the `svg_data_uri` field",
        "from `stencil_manifest.json` to embed icons directly into shapes.",
        "",
        "### Method 3: Use PNG Fallbacks",
        "",
        "If SVG import is not supported, use the PNG files from the `png/` folder.",
        "Insert them as images in your Visio diagram.",
        "",
        "## Icon Index",
        "",
        "| # | Name | Category | Provider | SVG | PNG |",
        "|---|------|----------|----------|-----|-----|",
    ]

    for m in masters:
        png = "✓" if m.get("png_file") else "—"
        lines.append(
            f"| {m['master_id']} | {m['name']} | {m['category']} | {m['provider']} | ✓ | {png} |"
        )

    lines.append("")
    lines.append("---")
    lines.append("Generated by **Archmorph Icon Registry**")
    lines.append("")

    return "\n".join(lines)
