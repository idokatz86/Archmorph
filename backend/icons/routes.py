"""Icon Registry — FastAPI routes.

Endpoints:
  POST /api/icon-packs             Upload a ZIP / JSON icon pack
  GET  /api/icons                  Search icons
  GET  /api/icons/packs            List registered packs
  GET  /api/icons/metrics          Observability counters
  GET  /api/libraries/drawio       Download draw.io custom library
  GET  /api/libraries/excalidraw   Download Excalidraw library bundle
  GET  /api/libraries/visio        Download Visio sidecar stencil pack
"""

from __future__ import annotations
from error_envelope import ArchmorphException

import json
import logging
import zipfile
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Request, UploadFile, File
from fastapi.responses import Response

from routers.shared import limiter, verify_api_key
from icons import registry
from icons.builders.drawio import build_drawio_library
from icons.builders.excalidraw import build_excalidraw_library
from icons.builders.visio import build_visio_stencil_pack

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["icons"])


def _api_key_header_for_schema(
    _x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> None:
    return None



# ─────────────────────────────────────────────────────────────
# Icon-pack ingestion
# ─────────────────────────────────────────────────────────────

@router.post("/icon-packs")
@limiter.limit("5/minute")
async def upload_icon_pack(
    request: Request,
    file: UploadFile = File(...),
    pack_id: Optional[str] = Query(None, description="Custom pack identifier"),
    _auth: None = Depends(verify_api_key),
    _api_key_header: None = Depends(_api_key_header_for_schema),
):
    """Ingest a ZIP or JSON icon pack.

    Accepted formats:
    - **ZIP**: Contains SVG files and an optional ``metadata.json``
    - **JSON**: A valid ``IconPackManifest`` with inline SVG data
    """
    content = await file.read()

    if not content:
        raise ArchmorphException(status_code=400, detail="Uploaded file is empty")

    # Limit upload size (50 MB)
    max_size = 50 * 1024 * 1024
    if len(content) > max_size:
        raise ArchmorphException(status_code=413, detail="Upload exceeds 50 MB limit")

    try:
        # Detect format
        if file.filename and file.filename.endswith(".json"):
            # JSON manifest with inline SVG data
            manifest_data = json.loads(content)
            result = registry.ingest_icon_pack(
                source=_json_manifest_to_zip_bytes(manifest_data),
                manifest=_metadata_without_inline_svg(manifest_data),
                pack_id=pack_id,
            )
        elif _is_zipfile(content):
            result = registry.ingest_icon_pack(
                source=content,
                pack_id=pack_id,
            )
        else:
            raise ArchmorphException(
                status_code=400,
                detail="Unsupported file format. Upload a ZIP or JSON file.",
            )
    except ValueError as exc:
        raise ArchmorphException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("Icon pack ingestion failed")
        raise ArchmorphException(status_code=500, detail="Icon pack ingestion failed. Please try again.")

    return result


# ─────────────────────────────────────────────────────────────
# Icon search / listing
# ─────────────────────────────────────────────────────────────

@router.get("/icons")
async def search_icons(
    provider: Optional[str] = Query(None),
    query: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    pack_id: Optional[str] = Query(None, alias="packId"),
):
    """Search or list icons in the registry."""
    icons = registry.search_icons(
        provider=provider,
        query=query,
        category=category,
        pack_id=pack_id,
    )
    # Return metadata only (no raw SVG) for the listing
    return {
        "count": len(icons),
        "icons": [
            {
                "id": icon.id,
                "name": icon.name,
                "provider": icon.provider,
                "category": icon.category,
                "tags": icon.tags,
                "service_id": icon.service_id,
                "width": icon.width,
                "height": icon.height,
            }
            for icon in icons
        ],
    }


@router.get("/icons/packs")
async def list_packs():
    """List all registered icon packs."""
    packs = registry.list_packs()
    return {"count": len(packs), "packs": packs}


@router.delete("/icon-packs/{pack_id}")
@limiter.limit("5/minute")
async def delete_icon_pack(
    request: Request,
    pack_id: str,
    _auth: None = Depends(verify_api_key),
    _api_key_header: None = Depends(_api_key_header_for_schema),
):
    """Remove an icon pack and all its icons from the registry."""
    result = registry.delete_pack(pack_id)
    if not result.get("deleted"):
        raise ArchmorphException(status_code=404, detail=f"Icon pack '{pack_id}' not found")
    return result


@router.get("/icons/metrics")
async def icon_metrics():
    """Return icon-registry observability counters."""
    return registry.get_metrics()


@router.get("/icons/{icon_id}/svg")
async def get_icon_svg(icon_id: str):
    """Return the raw SVG for a single icon."""
    icon = registry.get_icon(icon_id)
    if icon is None:
        raise ArchmorphException(status_code=404, detail=f"Icon '{icon_id}' not found")
    return Response(
        content=icon.svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ─────────────────────────────────────────────────────────────
# Library downloads
# ─────────────────────────────────────────────────────────────

@router.get("/libraries/drawio")
async def download_drawio_library(
    pack_id: str = Query(..., alias="packId"),
    embed_mode: str = Query("reference", alias="embedMode"),
    title: Optional[str] = Query(None),
):
    """Download a draw.io custom shape library (mxlibrary XML).

    Query parameters:
    - **packId**: Required. Icon pack to export.
    - **embedMode**: ``reference`` (stencil IDs) or ``full`` (embedded SVG).
    - **title**: Optional library title.
    """
    if embed_mode not in ("reference", "full"):
        raise ArchmorphException(status_code=400, detail="embedMode must be 'reference' or 'full'")

    try:
        data = build_drawio_library(pack_id, embed_mode=embed_mode, title=title)
    except ValueError as exc:
        raise ArchmorphException(status_code=404, detail=str(exc))

    filename = f"archmorph-{pack_id}.xml"
    return Response(
        content=data,
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get("/libraries/excalidraw")
async def download_excalidraw_library(
    pack_id: str = Query(..., alias="packId"),
    title: Optional[str] = Query(None),
):
    """Download an Excalidraw library bundle (.excalidrawlib JSON).

    Query parameters:
    - **packId**: Required. Icon pack to export.
    - **title**: Optional library title.
    """
    try:
        data = build_excalidraw_library(pack_id, title=title)
    except ValueError as exc:
        raise ArchmorphException(status_code=404, detail=str(exc))

    filename = f"archmorph-{pack_id}.excalidrawlib"
    return Response(
        content=data,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get("/libraries/visio")
async def download_visio_stencil_pack(
    pack_id: str = Query(..., alias="packId"),
    title: Optional[str] = Query(None),
    include_png: bool = Query(True, alias="includePng"),
):
    """Download a Visio sidecar stencil pack (ZIP).

    Query parameters:
    - **packId**: Required. Icon pack to export.
    - **title**: Optional stencil collection title.
    - **includePng**: Whether to include PNG rasters (default: true).
    """
    try:
        data = build_visio_stencil_pack(pack_id, title=title, include_png=include_png)
    except ValueError as exc:
        raise ArchmorphException(status_code=404, detail=str(exc))

    filename = f"archmorph-{pack_id}-visio.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "public, max-age=3600",
        },
    )


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _is_zipfile(data: bytes) -> bool:
    """Check if data starts with a ZIP magic number."""
    return data[:4] == b"PK\x03\x04"


def _json_manifest_to_zip_bytes(manifest_data: dict) -> bytes:
    """Convert a JSON icon-pack manifest with inline SVG entries into ZIP bytes."""
    icons = manifest_data.get("icons", [])
    if not isinstance(icons, list) or not icons:
        raise ValueError("JSON icon pack must include at least one icon")

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("metadata.json", json.dumps(_metadata_without_inline_svg(manifest_data)))
        for icon in icons:
            if not isinstance(icon, dict):
                raise ValueError("JSON icon entries must be objects")
            path = icon.get("file")
            svg = icon.get("svg")
            if not path or not isinstance(path, str):
                raise ValueError("JSON icon entries must include a file path")
            if not svg or not isinstance(svg, str):
                raise ValueError("JSON icon entries must include inline SVG data")
            zf.writestr(path, svg)
    return buf.getvalue()


def _metadata_without_inline_svg(manifest_data: dict) -> dict:
    metadata = dict(manifest_data)
    metadata["icons"] = [
        {key: value for key, value in icon.items() if key != "svg"}
        for icon in manifest_data.get("icons", [])
        if isinstance(icon, dict)
    ]
    return metadata
