"""IconRegistry — central icon catalog with ingestion, normalization, and lookup.

Manages a normalized icon catalog (Azure/AWS/GCP + custom) as SVG sources.
Supports ingestion from folders or ZIP archives, icon normalization with
deterministic IDs, and hash-based caching for transformed assets.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, Optional

from cachetools import TTLCache

from icons.models import IconEntry, IconMeta, IconPackManifest, IconPackItem, Provider
from icons.svg_sanitizer import (
    SVGSanitizationError,
    extract_svg_dimensions,
    validate_svg,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Metrics (in-memory counters for observability)
# ─────────────────────────────────────────────────────────────
_metrics: dict[str, int] = {
    "packs_ingested": 0,
    "icons_ingested": 0,
    "validation_failures": 0,
    "library_builds": 0,
}


def get_icon_metrics() -> dict[str, Any]:
    """Return current icon-system metrics."""
    return {**_metrics, "total_icons": len(_ICON_STORE)}


# Alias for route compatibility
get_metrics = get_icon_metrics


# ─────────────────────────────────────────────────────────────
# Storage (in-memory; production would back with DB/blob)
# ─────────────────────────────────────────────────────────────
_ICON_STORE: dict[str, IconEntry] = {}  # canonical_id → IconEntry
_PACK_INDEX: dict[str, list[str]] = {}  # pack_id → [canonical_id, …]

# Cache for transformed assets (library outputs)
_ASSET_CACHE: TTLCache = TTLCache(maxsize=200, ttl=3600)

# Thread lock for mutable state (reentrant for nested calls)
_LOCK = threading.RLock()

# Persistence file path (alongside this module)
_PERSIST_DIR = Path(os.getenv(
    "ICON_REGISTRY_DATA_DIR",
    str(Path(__file__).resolve().parent.parent / "data"),
))
_PERSIST_FILE = _PERSIST_DIR / "icon_registry.json"


def _canonical_id(name: str, provider: str, category: str) -> str:
    """Generate a deterministic canonical ID from name + provider + category."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    cat_slug = re.sub(r"[^a-z0-9]+", "_", category.lower()).strip("_")
    return f"{provider}_{cat_slug}_{slug}"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────


def ingest_icon_pack(
    source: str | Path | bytes,
    *,
    manifest: Optional[dict] = None,
    pack_id: Optional[str] = None,
) -> dict[str, Any]:
    """Ingest an icon pack from a folder path, ZIP bytes, or ZIP file path.

    Parameters
    ----------
    source
        Path to a folder of SVGs, path to a ZIP, or raw ZIP bytes.
    manifest
        Optional manifest dict (parsed ``metadata.json``).
        If *None*, the function looks for ``metadata.json`` in the source.
    pack_id
        Explicit pack ID.  Auto-generated from manifest name if omitted.

    Returns
    -------
    dict
        ``{"pack_id": ..., "ingested": N, "failed": N, "icons": [...]}``
    """
    t0 = time.monotonic()
    logger.info("Ingesting icon pack from %s", type(source).__name__)

    # Collect {relative_path: svg_bytes}
    files: dict[str, bytes] = {}

    if isinstance(source, bytes):
        files, manifest = _read_zip(io.BytesIO(source), manifest)
    elif isinstance(source, (str, Path)):
        p = Path(source)
        if p.is_dir():
            files, manifest = _read_folder(p, manifest)
        elif p.suffix.lower() == ".zip" and p.is_file():
            files, manifest = _read_zip(open(p, "rb"), manifest)
        else:
            raise ValueError(f"Source must be a directory or .zip file: {p}")
    else:
        raise TypeError(f"Unsupported source type: {type(source)}")

    # Parse manifest
    if manifest is None:
        manifest = {}
    pack_manifest = IconPackManifest(
        name=manifest.get("name", "unnamed-pack"),
        provider=manifest.get("provider", "custom"),
        version=manifest.get("version", "1.0.0"),
        description=manifest.get("description", ""),
        icons=[IconPackItem(**i) for i in manifest.get("icons", [])],
    )

    # Build file→manifest-item lookup
    item_lookup: dict[str, IconPackItem] = {
        item.file: item for item in pack_manifest.icons
    }

    pid = pack_id or re.sub(r"[^a-z0-9_-]", "_", pack_manifest.name.lower())
    ingested_ids: list[str] = []
    failed = 0

    for rel_path, svg_bytes in sorted(files.items()):
        item = item_lookup.get(rel_path)
        name = item.name if item and item.name else Path(rel_path).stem
        category = item.category if item else "general"
        tags = list(item.tags) if item else []
        service_id = item.service_id if item else None

        try:
            sanitized_svg = validate_svg(svg_bytes)
        except SVGSanitizationError as exc:
            logger.warning("Validation failed for %s: %s", rel_path, exc)
            _metrics["validation_failures"] += 1
            failed += 1
            continue

        svg_hash = _sha256(svg_bytes)
        w, h = extract_svg_dimensions(sanitized_svg)

        cid = _canonical_id(name, pack_manifest.provider, category)

        entry = IconEntry(
            meta=IconMeta(
                id=cid,
                name=name,
                provider=pack_manifest.provider,
                category=category,
                tags=tags,
                version=pack_manifest.version,
                service_id=service_id,
                svg_hash=svg_hash,
                width=w,
                height=h,
            ),
            svg=sanitized_svg,
        )
        with _LOCK:
            _ICON_STORE[cid] = entry
        ingested_ids.append(cid)

    with _LOCK:
        _PACK_INDEX[pid] = ingested_ids
        _metrics["packs_ingested"] += 1
        _metrics["icons_ingested"] += len(ingested_ids)

    elapsed = time.monotonic() - t0
    logger.info(
        "Icon pack '%s' ingested: %d icons, %d failed (%.2fs)",
        pid, len(ingested_ids), failed, elapsed,
    )

    result = {
        "pack_id": pid,
        "ingested": len(ingested_ids),
        "failed": failed,
        "icons": [_ICON_STORE[cid].meta.model_dump() for cid in ingested_ids],
    }
    _save_to_disk()
    return result


def get_icon(icon_id: str) -> Optional[IconEntry]:
    """Look up a single icon by canonical ID."""
    return _ICON_STORE.get(icon_id)


def resolve_icon(
    service_id: str,
    provider: str = "azure",
    style_theme: str = "default",
) -> Optional[IconEntry]:
    """Resolve the best icon for a given service.

    Searches by ``service_id`` first, then falls back to fuzzy name match.
    """
    # Exact service_id match
    for entry in _ICON_STORE.values():
        if entry.meta.service_id and entry.meta.service_id.lower() == service_id.lower():
            if entry.meta.provider == provider:
                return entry

    # Fuzzy name match
    target = service_id.lower()
    for entry in _ICON_STORE.values():
        if entry.meta.provider == provider and target in entry.meta.name.lower():
            return entry

    return None


def search_icons(
    *,
    provider: Optional[str] = None,
    query: Optional[str] = None,
    category: Optional[str] = None,
    pack_id: Optional[str] = None,
) -> list[IconMeta]:
    """Search registered icons with optional filters."""
    results: list[IconMeta] = []

    # Restrict to pack if specified
    if pack_id and pack_id in _PACK_INDEX:
        candidates = [_ICON_STORE[cid] for cid in _PACK_INDEX[pack_id] if cid in _ICON_STORE]
    else:
        candidates = list(_ICON_STORE.values())

    for entry in candidates:
        if provider and entry.meta.provider != provider:
            continue
        if category and entry.meta.category.lower() != category.lower():
            continue
        if query:
            q = query.lower()
            searchable = f"{entry.meta.name} {entry.meta.category} {' '.join(entry.meta.tags)}".lower()
            if q not in searchable:
                continue
        results.append(entry.meta)

    # Stable sort for deterministic output
    results.sort(key=lambda m: m.id)
    return results


def get_pack_icons(pack_id: str) -> list[IconEntry]:
    """Return all icons for a given pack, sorted by ID."""
    ids = _PACK_INDEX.get(pack_id, [])
    entries = [_ICON_STORE[cid] for cid in sorted(ids) if cid in _ICON_STORE]
    return entries


def list_packs() -> list[dict[str, Any]]:
    """Return all registered pack IDs and their icon counts."""
    return [
        {"pack_id": pid, "icon_count": len(ids)}
        for pid, ids in sorted(_PACK_INDEX.items())
    ]


def get_cached_asset(cache_key: str) -> Optional[bytes]:
    """Retrieve a cached library asset."""
    return _ASSET_CACHE.get(cache_key)


def set_cached_asset(cache_key: str, data: bytes) -> None:
    """Store a library asset in cache."""
    with _LOCK:
        _ASSET_CACHE[cache_key] = data


def clear_all() -> None:
    """Clear all icons, packs, and caches. For testing."""
    with _LOCK:
        _ICON_STORE.clear()
        _PACK_INDEX.clear()
        _ASSET_CACHE.clear()


def delete_pack(pack_id: str) -> dict[str, Any]:
    """Remove an icon pack and all its icons from the registry."""
    with _LOCK:
        icon_ids = _PACK_INDEX.pop(pack_id, None)
        if icon_ids is None:
            return {"deleted": False, "reason": "pack not found"}
        removed = 0
        for cid in icon_ids:
            if _ICON_STORE.pop(cid, None) is not None:
                removed += 1
        # Invalidate cached assets that reference this pack
        stale_keys = [k for k in _ASSET_CACHE if pack_id in str(k)]
        for k in stale_keys:
            _ASSET_CACHE.pop(k, None)
    _save_to_disk()
    logger.info("Deleted pack '%s': %d icons removed", pack_id, removed)
    return {"deleted": True, "pack_id": pack_id, "icons_removed": removed}


# ─────────────────────────────────────────────────────────────
# Persistence helpers
# ─────────────────────────────────────────────────────────────

def _save_to_disk() -> None:
    """Persist the current icon registry state to a JSON sidecar file."""
    try:
        _PERSIST_DIR.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            snapshot = {
                "packs": {pid: ids for pid, ids in _PACK_INDEX.items()},
                "icons": {
                    cid: {
                        "meta": entry.meta.model_dump(),
                        "svg": entry.svg,
                    }
                    for cid, entry in _ICON_STORE.items()
                },
            }
        _PERSIST_FILE.write_text(
            json.dumps(snapshot, indent=2, default=str),
            encoding="utf-8",
        )
        logger.debug("Registry persisted to %s (%d icons)", _PERSIST_FILE, len(snapshot["icons"]))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to persist registry: %s", exc)


def _load_from_disk() -> bool:
    """Load registry state from the JSON sidecar file if it exists."""
    if not _PERSIST_FILE.is_file():
        return False
    try:
        raw = json.loads(_PERSIST_FILE.read_text(encoding="utf-8"))
        with _LOCK:
            for cid, data in raw.get("icons", {}).items():
                meta = IconMeta(**data["meta"])
                _ICON_STORE[cid] = IconEntry(meta=meta, svg=data["svg"])
            for pid, ids in raw.get("packs", {}).items():
                _PACK_INDEX[pid] = ids
        logger.info("Registry loaded from disk: %d icons, %d packs", len(_ICON_STORE), len(_PACK_INDEX))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load registry from disk: %s", exc)
        return False


def load_builtin_packs() -> int:
    """Auto-load sample icon packs from the samples/ directory.

    Returns the number of packs loaded.
    """
    samples_dir = Path(__file__).resolve().parent.parent / "samples"
    if not samples_dir.is_dir():
        logger.debug("No samples/ directory found at %s", samples_dir)
        return 0

    loaded = 0
    for provider_dir in sorted(samples_dir.iterdir()):
        if not provider_dir.is_dir():
            continue
        provider_name = provider_dir.name.lower()
        # Skip if already loaded
        if provider_name in _PACK_INDEX:
            logger.debug("Pack '%s' already loaded, skipping", provider_name)
            continue
        try:
            files, manifest_raw = _read_folder(provider_dir, None)
            if not files:
                continue
            manifest = manifest_raw or {}
            pack_manifest = IconPackManifest(
                name=manifest.get("name", provider_name),
                provider=manifest.get("provider", provider_name),
                version=manifest.get("version", "1.0.0"),
                description=manifest.get("description", f"Built-in {provider_name} icon pack"),
            )
            items = []
            for item_data in manifest.get("icons", []):
                items.append(IconPackItem(**item_data))
            ingest_icon_pack(pack_manifest, files, items=items, pack_id=provider_name)
            loaded += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load builtin pack '%s': %s", provider_name, exc)
    return loaded


# ─────────────────────────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────────────────────────


def _read_folder(
    folder: Path,
    manifest: Optional[dict],
) -> tuple[dict[str, bytes], Optional[dict]]:
    """Read SVGs from a local folder, optionally loading metadata.json."""
    files: dict[str, bytes] = {}

    # Try to load manifest from folder
    meta_path = folder / "metadata.json"
    if manifest is None and meta_path.is_file():
        manifest = json.loads(meta_path.read_text(encoding="utf-8"))

    for svg_path in sorted(folder.rglob("*.svg")):
        rel = svg_path.relative_to(folder).as_posix()
        files[rel] = svg_path.read_bytes()

    return files, manifest


def _read_zip(
    fp: Any,
    manifest: Optional[dict],
) -> tuple[dict[str, bytes], Optional[dict]]:
    """Read SVGs from a ZIP archive."""
    files: dict[str, bytes] = {}

    with zipfile.ZipFile(fp, "r") as zf:
        # Try to load manifest
        if manifest is None:
            for name in ("metadata.json", "manifest.json"):
                if name in zf.namelist():
                    manifest = json.loads(zf.read(name).decode("utf-8"))
                    break

        for name in sorted(zf.namelist()):
            if name.lower().endswith(".svg") and not name.startswith("__MACOSX"):
                # Prevent ZIP slip path traversal
                if ".." in name or name.startswith("/"):
                    logger.warning("Skipping suspicious ZIP entry: %s", name)
                    continue
                files[name] = zf.read(name)

    return files, manifest
