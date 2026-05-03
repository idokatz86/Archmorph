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
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

from cachetools import TTLCache

from icons.models import IconEntry, IconMeta, IconPackManifest, IconPackItem
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
_ICON_STORE: OrderedDict[str, IconEntry] = OrderedDict()  # canonical_id → IconEntry
_PACK_INDEX: dict[str, list[str]] = {}  # pack_id → [canonical_id, …]
_BUILTIN_PACK_IDS: set[str] = set()
_BUILTIN_ICON_IDS: set[str] = set()
_PACK_GENERATIONS: dict[str, int] = {}
_DEFAULT_MAX_ICONS = 5000

# Cache for transformed assets (library outputs)
_ASSET_CACHE: TTLCache = TTLCache(maxsize=200, ttl=3600)

# Thread lock for mutable state (reentrant for nested calls)
_LOCK = threading.RLock()

# Persistence file path — resolved at CALL time so test fixtures that
# monkeypatch `ICON_REGISTRY_DATA_DIR` after import (transitive imports via
# `azure_landing_zone` happen before fixture setup runs) still take effect.
# Same lesson as `_autoload_disabled()` above (#587).
_DEFAULT_PERSIST_DIR = Path(__file__).resolve().parent.parent / "data"


def _max_icons() -> int:
    try:
        return max(int(os.getenv("ICON_REGISTRY_MAX_ICONS", str(_DEFAULT_MAX_ICONS))), 1)
    except ValueError:
        return _DEFAULT_MAX_ICONS


def _evict_icons_if_needed() -> None:
    evicted_ids: list[str] = []
    protected_ids = _protected_icon_ids()
    while len(_ICON_STORE) > _max_icons():
        evicted_id = next((cid for cid in _ICON_STORE if cid not in protected_ids), None)
        if evicted_id is None:
            break
        _ICON_STORE.pop(evicted_id, None)
        evicted_ids.append(evicted_id)

    if not evicted_ids:
        return

    evicted = set(evicted_ids)
    affected_packs: set[str] = set()
    for pid, ids in list(_PACK_INDEX.items()):
        retained = [cid for cid in ids if cid not in evicted]
        if len(retained) != len(ids):
            affected_packs.add(pid)
        if retained:
            _PACK_INDEX[pid] = retained
        else:
            _PACK_INDEX.pop(pid, None)

    for pid in affected_packs:
        _bump_pack_generation(pid)
    _ASSET_CACHE.clear()
    _invalidate_external_icon_caches()
    logger.info("Icon registry evicted %s icons after reaching maxsize", len(evicted_ids))


def _sample_pack_ids() -> set[str]:
    samples_dir = Path(__file__).resolve().parent.parent / "samples"
    if not samples_dir.is_dir():
        return set()
    return {path.name.lower() for path in samples_dir.iterdir() if path.is_dir()}


def _reserved_builtin_pack_ids() -> set[str]:
    return _BUILTIN_PACK_IDS | _sample_pack_ids()


def _protected_icon_ids() -> set[str]:
    return {cid for cid in _BUILTIN_ICON_IDS if cid in _ICON_STORE}


def _assert_custom_pack_fits_atomically(pid: str, ingested_ids: list[str]) -> None:
    max_icons = _max_icons()
    current_ids = set(_ICON_STORE)
    old_ids = set(_PACK_INDEX.get(pid, []))
    final_ids = (current_ids - old_ids) | set(ingested_ids)
    if len(final_ids) <= max_icons:
        return

    protected_ids = _protected_icon_ids()
    evictable_existing = [
        cid
        for cid in _ICON_STORE
        if cid in final_ids and cid not in protected_ids and cid not in ingested_ids
    ]
    if len(final_ids) - len(evictable_existing) > max_icons:
        raise ValueError("Icon pack exceeds registry capacity and cannot be ingested atomically")


def _mark_builtin_pack(pack_id: str, icon_ids: list[str]) -> None:
    _BUILTIN_PACK_IDS.add(pack_id)
    _BUILTIN_ICON_IDS.update(icon_ids)


def _bump_pack_generation(pack_id: str) -> None:
    _PACK_GENERATIONS[pack_id] = _PACK_GENERATIONS.get(pack_id, 0) + 1


def get_pack_generation(pack_id: str) -> int:
    with _LOCK:
        return _PACK_GENERATIONS.get(pack_id, 0)


def _invalidate_pack_asset_cache(pack_id: str) -> None:
    _bump_pack_generation(pack_id)
    stale_keys = [key for key in _ASSET_CACHE if _cache_key_matches_pack(key, pack_id)]
    for key in stale_keys:
        _ASSET_CACHE.pop(key, None)
    _invalidate_external_icon_caches()


def _cache_key_matches_pack(cache_key: Any, pack_id: str) -> bool:
    if isinstance(cache_key, tuple):
        return len(cache_key) >= 2 and cache_key[0] in {"drawio", "excalidraw", "visio"} and cache_key[1] == pack_id
    if not isinstance(cache_key, str):
        return False
    if cache_key == f"excalidraw:{pack_id}":
        return True
    for prefix in ("drawio:", "visio:"):
        if cache_key.startswith(prefix):
            payload = cache_key[len(prefix):]
            if ":" not in payload:
                return False
            cached_pack_id, _variant = payload.rsplit(":", 1)
            return cached_pack_id == pack_id
    return False


def _invalidate_external_icon_caches() -> None:
    try:
        from azure_landing_zone import clear_icon_cache
    except Exception:  # noqa: BLE001 — optional renderer cache
        return
    clear_icon_cache()


def _persist_dir() -> Path:
    return Path(os.getenv("ICON_REGISTRY_DATA_DIR", str(_DEFAULT_PERSIST_DIR)))


def _persist_file() -> Path:
    return _persist_dir() / "icon_registry.json"


# Lazy-load gate (#587 — D1 fix).
# Set True once `_ensure_loaded()` has run, regardless of whether disk-load
# or builtin-pack ingestion succeeded. Prevents unbounded reload attempts on
# every lookup if the disk cache is empty / corrupted, while still letting
# tests and explicit callers force a reload via `clear_all()` or
# `ensure_registry_loaded(force=True)`.
_LOAD_ATTEMPTED: bool = False


class IconPackChangedDuringBuild(RuntimeError):
    """Raised when a pack changes repeatedly while a library is being built."""


def _autoload_disabled() -> bool:
    """Whether autoload is disabled via env var.

    Read at call-time (not module-import time) so test setup that mutates
    `os.environ` after a transitive import via `azure_landing_zone` still
    takes effect. Cheap enough for the lookup hot path.
    """
    return os.getenv("ICON_REGISTRY_AUTOLOAD", "1").lower() in ("0", "false", "no")


def _ensure_loaded(*, force: bool = False) -> None:
    """Idempotently bootstrap the icon registry on first lookup (#587).

    Originally `_load_from_disk()` and `load_builtin_packs()` ran only from
    the FastAPI startup hook in `main.lifespan`, so any cold-import context
    (CLI scripts, isolated workers, unit tests, the SVG generator imported
    before the app spins up) saw `_ICON_STORE = {}` and `resolve_icon` returned
    `None` for every service. The CTO E2E review on May 1, 2026 measured a
    100% icon-miss rate on the `landing-zone-svg` pipeline as a result.

    This function is the single bootstrap entry point: thread-safe via
    `_LOCK`, gated on `_LOAD_ATTEMPTED` so the load happens at most once per
    process, and a no-op when the store already has icons. `clear_all()`
    resets the gate so tests start fresh.
    """
    global _LOAD_ATTEMPTED
    if _autoload_disabled() and not force:
        return
    if _LOAD_ATTEMPTED and not force:
        return
    with _LOCK:
        if _LOAD_ATTEMPTED and not force:
            return
        # If somebody already ingested icons via `ingest_icon_pack(...)` we
        # respect that and just flip the gate — don't double-load.
        if _ICON_STORE:
            _LOAD_ATTEMPTED = True
            return
        try:
            if _load_from_disk():
                logger.info("Icon registry lazily restored from disk on first lookup")
            else:
                loaded = load_builtin_packs()
                if loaded:
                    logger.info("Icon registry lazily auto-loaded %s builtin pack(s)", str(loaded))
        except Exception as exc:  # noqa: BLE001 — bootstrap is best-effort, never raise on lookup paths
            logger.warning("Icon registry lazy-load failed: %s", str(exc).replace('\n', '').replace('\r', ''))
        finally:
            _LOAD_ATTEMPTED = True


def ensure_registry_loaded(*, force: bool = False) -> int:
    """Public wrapper around the lazy-load gate.

    Use from non-FastAPI entry points (CLI tools, batch jobs, scripts) when
    you want a deterministic load before the first lookup. Returns the icon
    count after loading. Pass ``force=True`` to bypass the gate (e.g. after
    ingesting a new pack to disk and wanting a process-local refresh).
    """
    _ensure_loaded(force=force)
    return len(_ICON_STORE)


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
    builtin: bool = False,
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
    logger.info("Ingesting icon pack from %s", str(type(source).__name__).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom

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
    if not builtin and pid in _reserved_builtin_pack_ids():
        raise ValueError(f"Pack id '{pid}' is reserved for built-in icon packs")
    if builtin:
        with _LOCK:
            _BUILTIN_PACK_IDS.add(pid)
    ingested_ids: list[str] = []
    new_entries: list[tuple[str, IconEntry]] = []
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
            logger.warning("Validation failed for %s: %s", str(rel_path).replace('\n', '').replace('\r', ''), str(exc).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom
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
        ingested_ids.append(cid)
        new_entries.append((cid, entry))

    with _LOCK:
        old_ids = set(_PACK_INDEX.get(pid, []))
        if not builtin:
            reserved_ids = [cid for cid in ingested_ids if cid in _BUILTIN_ICON_IDS]
            if reserved_ids:
                raise ValueError(f"Icon id '{reserved_ids[0]}' is reserved for built-in icon packs")
            duplicate_ids = [cid for cid in ingested_ids if cid in _ICON_STORE and cid not in old_ids]
            if duplicate_ids:
                raise ValueError(f"Icon id '{duplicate_ids[0]}' is already registered by another icon pack")
            _assert_custom_pack_fits_atomically(pid, ingested_ids)
        for cid, entry in new_entries:
            _ICON_STORE[cid] = entry
            _ICON_STORE.move_to_end(cid)
        stale_ids = old_ids.difference(ingested_ids)
        for stale_id in stale_ids:
            if stale_id not in _BUILTIN_ICON_IDS or builtin:
                _ICON_STORE.pop(stale_id, None)
        _PACK_INDEX[pid] = ingested_ids
        if builtin:
            _mark_builtin_pack(pid, ingested_ids)
        _invalidate_pack_asset_cache(pid)
        _evict_icons_if_needed()
        retained_ids = [cid for cid in ingested_ids if cid in _ICON_STORE]
        _metrics["packs_ingested"] += 1
        _metrics["icons_ingested"] += len(retained_ids)

    elapsed = time.monotonic() - t0
    logger.info(
        "Icon pack '%s' ingested: %s icons, %s failed (%ss)",
        str(pid).replace('\n', '').replace('\r', ''), str(len(ingested_ids)).replace('\n', '').replace('\r', ''), str(failed).replace('\n', '').replace('\r', ''), str(elapsed).replace('\n', '').replace('\r', ''),  # lgtm[py/log-injection]
    )

    result = {
        "pack_id": pid,
        "ingested": len(retained_ids),
        "failed": failed,
        "icons": [_ICON_STORE[cid].meta.model_dump() for cid in retained_ids],
    }
    _save_to_disk()
    return result


def get_icon(icon_id: str) -> Optional[IconEntry]:
    """Look up a single icon by canonical ID."""
    _ensure_loaded()
    with _LOCK:
        return _ICON_STORE.get(icon_id)


def resolve_icon(
    service_id: str,
    provider: str = "azure",
    style_theme: str = "default",
) -> Optional[IconEntry]:
    """Resolve the best icon for a given service.

    Searches by ``service_id`` first, then falls back to fuzzy name match.
    Lazily bootstraps the registry on first lookup (#587).
    """
    _ensure_loaded()
    with _LOCK:
        entries = list(_ICON_STORE.values())

    # Exact service_id match
    for entry in entries:
        if entry.meta.service_id and entry.meta.service_id.lower() == service_id.lower():
            if entry.meta.provider == provider:
                return entry

    # Fuzzy name match
    target = service_id.lower()
    for entry in entries:
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
    _ensure_loaded()
    results: list[IconMeta] = []

    # Restrict to pack if specified
    with _LOCK:
        if pack_id is not None:
            candidates = [_ICON_STORE[cid] for cid in _PACK_INDEX.get(pack_id, []) if cid in _ICON_STORE]
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
    with _LOCK:
        ids = _PACK_INDEX.get(pack_id, [])
        return [_ICON_STORE[cid] for cid in sorted(ids) if cid in _ICON_STORE]


def list_packs() -> list[dict[str, Any]]:
    """Return all registered pack IDs and their icon counts."""
    _ensure_loaded()
    with _LOCK:
        return [
            {"pack_id": pid, "icon_count": len(ids)}
            for pid, ids in sorted(_PACK_INDEX.items())
        ]


def get_cached_asset(
    cache_key: Any,
    *,
    pack_id: Optional[str] = None,
    generation: Optional[int] = None,
) -> Optional[bytes]:
    """Retrieve a cached library asset."""
    with _LOCK:
        if pack_id is not None and generation is not None:
            if _PACK_GENERATIONS.get(pack_id, 0) != generation:
                return None
        return _ASSET_CACHE.get(cache_key)


def set_cached_asset(
    cache_key: Any,
    data: Optional[bytes],
    *,
    pack_id: Optional[str] = None,
    generation: Optional[int] = None,
) -> bool:
    """Store a library asset in cache."""
    with _LOCK:
        if pack_id is not None and generation is not None:
            if _PACK_GENERATIONS.get(pack_id, 0) != generation:
                return False
        if data is None:
            _ASSET_CACHE.pop(cache_key, None)
            return True
        _ASSET_CACHE[cache_key] = data
    return True


def clear_all() -> None:
    """Clear all icons, packs, and caches, and reset the lazy-load gate.

    For testing. Resetting `_LOAD_ATTEMPTED` is essential — without it, tests
    that clear the store after a load would leave the gate flipped, hiding
    a regression where lookups silently miss because the lazy-load no longer
    runs.
    """
    global _LOAD_ATTEMPTED
    with _LOCK:
        _ICON_STORE.clear()
        _PACK_INDEX.clear()
        _BUILTIN_PACK_IDS.clear()
        _BUILTIN_ICON_IDS.clear()
        _PACK_GENERATIONS.clear()
        _ASSET_CACHE.clear()
        _LOAD_ATTEMPTED = False
    _invalidate_external_icon_caches()


def delete_pack(pack_id: str) -> dict[str, Any]:
    """Remove an icon pack and all its icons from the registry."""
    with _LOCK:
        if pack_id in _reserved_builtin_pack_ids():
            return {"deleted": False, "reason": "built-in pack cannot be deleted"}
        icon_ids = _PACK_INDEX.pop(pack_id, None)
        if icon_ids is None:
            return {"deleted": False, "reason": "pack not found"}
        removed = 0
        for cid in icon_ids:
            if _ICON_STORE.pop(cid, None) is not None:
                removed += 1
        _invalidate_pack_asset_cache(pack_id)
    _save_to_disk()
    logger.info("Deleted pack '%s': %s icons removed", str(pack_id).replace('\n', '').replace('\r', ''), str(removed).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom
    return {"deleted": True, "pack_id": pack_id, "icons_removed": removed}


# ─────────────────────────────────────────────────────────────
# Persistence helpers
# ─────────────────────────────────────────────────────────────

def _save_to_disk() -> None:
    """Persist the current icon registry state to a JSON sidecar file."""
    persist_file = _persist_file()
    try:
        persist_file.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            snapshot = {
                "builtin_packs": sorted(_BUILTIN_PACK_IDS),
                "packs": {pid: ids for pid, ids in _PACK_INDEX.items()},
                "icons": {
                    cid: {
                        "meta": entry.meta.model_dump(),
                        "svg": entry.svg,
                    }
                    for cid, entry in _ICON_STORE.items()
                },
            }
        persist_file.write_text(
            json.dumps(snapshot, indent=2, default=str),
            encoding="utf-8",
        )
        logger.debug("Registry persisted to %s (%s icons)", str(persist_file).replace('\n', '').replace('\r', ''), str(len(snapshot["icons"])).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom
    except Exception as exc:  # noqa: BLE001 — icon pack loading is best-effort
        logger.warning("Failed to persist registry: %s", str(exc).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom


def _load_from_disk() -> bool:
    """Load registry state from the JSON sidecar file if it exists."""
    persist_file = _persist_file()
    if not persist_file.is_file():
        return False
    try:
        raw = json.loads(persist_file.read_text(encoding="utf-8"))
        has_builtin_marker = "builtin_packs" in raw
        persisted_builtin_packs = set(raw.get("builtin_packs", []))
        with _LOCK:
            for cid, data in raw.get("icons", {}).items():
                meta = IconMeta(**data["meta"])
                _ICON_STORE[cid] = IconEntry(meta=meta, svg=data["svg"])
                _ICON_STORE.move_to_end(cid)
            for pid, ids in raw.get("packs", {}).items():
                _PACK_INDEX[pid] = ids
                if pid in persisted_builtin_packs and pid in _sample_pack_ids():
                    _mark_builtin_pack(pid, [cid for cid in ids if cid in _ICON_STORE])
            _evict_icons_if_needed()
        if not has_builtin_marker:
            loaded = load_builtin_packs()
            if loaded:
                logger.info("Registry backfilled %s builtin pack(s) after legacy disk restore", str(loaded))
        logger.info("Registry loaded from disk: %s icons, %s packs", str(len(_ICON_STORE)).replace('\n', '').replace('\r', ''), str(len(_PACK_INDEX)).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom
        return True
    except Exception as exc:  # noqa: BLE001 — icon metadata parsing is best-effort
        logger.warning("Failed to load registry from disk: %s", str(exc).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom
        return False


def load_builtin_packs() -> int:
    """Auto-load sample icon packs from the samples/ directory.

    Returns the number of packs loaded.
    """
    samples_dir = Path(__file__).resolve().parent.parent / "samples"
    if not samples_dir.is_dir():
        logger.debug("No samples/ directory found at %s", str(samples_dir).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom
        return 0

    loaded = 0
    for provider_dir in sorted(samples_dir.iterdir()):
        if not provider_dir.is_dir():
            continue
        provider_name = provider_dir.name.lower()
        # Skip if already loaded
        if provider_name in _PACK_INDEX:
            with _LOCK:
                already_builtin = provider_name in _BUILTIN_PACK_IDS
                if already_builtin:
                    _mark_builtin_pack(provider_name, _PACK_INDEX.get(provider_name, []))
            if already_builtin:
                logger.debug("Pack '%s' already loaded, skipping", str(provider_name).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom
                continue
        try:
            ingest_icon_pack(provider_dir, pack_id=provider_name, builtin=True)
            loaded += 1
        except Exception as exc:  # noqa: BLE001 — icon resolution is best-effort
            logger.warning("Failed to load builtin pack '%s': %s", str(provider_name).replace('\n', '').replace('\r', ''), str(exc).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom
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
                    logger.warning("Skipping suspicious ZIP entry: %s", str(name).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom
                    continue
                files[name] = zf.read(name)

    return files, manifest
