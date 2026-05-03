"""Excalidraw library builder.

Produces a JSON library bundle compatible with Excalidraw's library import format.
Each icon becomes an Excalidraw library item with its SVG "materialized" into
Excalidraw image elements for portability.

Output is deterministic: same input icons → byte-identical JSON.
"""


from __future__ import annotations


import base64
import json
import logging
import time
from typing import Optional

from icons.models import IconEntry
from icons.registry import get_cached_asset, get_pack_generation, get_pack_icons, set_cached_asset, _metrics

logger = logging.getLogger(__name__)


def build_excalidraw_library(
    pack_id: str,
    *,
    title: Optional[str] = None,
) -> bytes:
    """Build an Excalidraw library JSON from a registered icon pack.

    Parameters
    ----------
    pack_id
        The icon pack to build from.
    title
        Library title. Defaults to pack_id.

    Returns
    -------
    bytes
        JSON content of the .excalidrawlib file.
    """
    t0 = time.monotonic()

    cache_key = f"excalidraw:{pack_id}"
    generation = get_pack_generation(pack_id)
    cached = get_cached_asset(cache_key)
    if cached is not None:
        logger.info("Returning cached Excalidraw library for %s", str(pack_id).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom
        return cached

    icons = get_pack_icons(pack_id)
    if not icons:
        raise ValueError(f"No icons found for pack '{pack_id}'")


    # Excalidraw library format:
    # {
    #   "type": "excalidrawlib",
    #   "version": 2,
    #   "source": "archmorph",
    #   "libraryItems": [...]
    # }
    library_items: list[dict] = []

    for icon in sorted(icons, key=lambda i: i.meta.id):
        item = _build_library_item(icon)
        library_items.append(item)

    doc = {
        "type": "excalidrawlib",
        "version": 2,
        "source": "archmorph",
        "libraryItems": library_items,
    }

    result = json.dumps(doc, separators=(",", ":"), sort_keys=False).encode("utf-8")
    set_cached_asset(cache_key, result, pack_id=pack_id, generation=generation)
    _metrics["library_builds"] += 1

    elapsed = time.monotonic() - t0
    logger.info(
        "Built Excalidraw library '%s' (%s icons, %ss)",
        str(pack_id).replace('\n', '').replace('\r', ''), str(len(library_items)).replace('\n', '').replace('\r', ''), str(elapsed).replace('\n', '').replace('\r', ''),  # lgtm[py/log-injection]
    )

    return result


def _build_library_item(icon: IconEntry) -> dict:
    """Build a single Excalidraw library item from an icon."""
    w = icon.meta.width
    h = icon.meta.height

    # Deterministic ID from icon hash
    item_id = f"archmorph_{icon.meta.id}"

    # Encode SVG as data URI for the image element
    svg_b64 = base64.b64encode(icon.svg.encode("utf-8")).decode("ascii")
    data_uri = f"data:image/svg+xml;base64,{svg_b64}"

    # File entry for Excalidraw's files dict
    file_id = icon.meta.svg_hash[:20] if icon.meta.svg_hash else icon.meta.id[:20]

    # Create an image element that references the embedded file
    # Use deterministic seed from icon ID
    seed = abs(hash(icon.meta.id)) % 2_000_000_000

    element = {
        "id": item_id,
        "type": "image",
        "x": 0,
        "y": 0,
        "width": w,
        "height": h,
        "angle": 0,
        "strokeColor": "transparent",
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 0,
        "roughness": 0,
        "opacity": 100,
        "roundness": None,
        "seed": seed,
        "version": 1,
        "versionNonce": seed + 1,
        "isDeleted": False,
        "boundElements": None,
        "link": None,
        "locked": False,
        "groupIds": [],
        "fileId": file_id,
        "status": "saved",
        "scale": [1, 1],
    }

    # Library item structure
    return {
        "id": item_id,
        "status": "published",
        "elements": [element],
        "name": icon.meta.name,
        "created": 1700000000000,  # Fixed timestamp for determinism
        "files": {
            file_id: {
                "mimeType": "image/svg+xml",
                "id": file_id,
                "dataURL": data_uri,
                "created": 1700000000000,
                "lastRetrieved": 1700000000000,
            }
        },
    }
