# Cloud Services Catalog
import json
import logging
from pathlib import Path

from .aws_services import AWS_SERVICES as _AWS_STATIC
from .azure_services import AZURE_SERVICES as _AZURE_STATIC
from .gcp_services import GCP_SERVICES as _GCP_STATIC
from .mappings import CROSS_CLOUD_MAPPINGS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Merge static catalogs with dynamically discovered services from JSON
# ---------------------------------------------------------------------------
_DISCOVERED_FILE = Path(__file__).resolve().parent.parent / "data" / "discovered_services.json"


def _load_discovered() -> dict[str, list[dict]]:
    """Load discovered services from the JSON data file.

    Issue #647 — also consults the durable Azure Blob mirror (when configured)
    via service_updater._load_discovered_from_blob, so a fresh container that
    boots before its first refresh still picks up the cumulative discoveries
    rather than serving the static-only catalog.
    """
    # Try blob first when available — this is the source of truth on stateless
    # container deployments (Azure Container Apps wipe the disk on restart).
    try:
        # Local import to avoid module-load circular: service_updater imports
        # this module's _load_discovered when called from run_update_now after
        # write, but it does not need the blob loader at import time.
        from service_updater import _load_discovered_from_blob

        blob_data = _load_discovered_from_blob()
        if blob_data is not None:
            return blob_data
    except Exception:  # noqa: BLE001
        # service_updater unavailable (test isolation, etc.) — fall through to disk.
        pass

    try:
        with open(_DISCOVERED_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, dict):
                return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return {}


def _merge(static: list[dict], discovered: list[dict]) -> list[dict]:
    """Merge discovered services into the static catalog, deduplicating by id."""
    existing_ids = {s.get("id") for s in static}
    merged = list(static)
    for svc in discovered:
        if svc.get("id") not in existing_ids:
            merged.append(svc)
            existing_ids.add(svc["id"])
    return merged


# ---------------------------------------------------------------------------
# Module-level catalog lists (issue #647 — kept as the same list objects across
# reload() calls so existing `from services import AWS_SERVICES` references
# stay valid; reload mutates in place via clear()+extend()).
# ---------------------------------------------------------------------------
AWS_SERVICES: list[dict] = []
AZURE_SERVICES: list[dict] = []
GCP_SERVICES: list[dict] = []


def reload() -> dict[str, int]:
    """Re-merge static + discovered catalogs in place.

    Issue #647 — the merged lists were previously bound once at module-import
    time, so refreshes that wrote to ``discovered_services.json`` after boot
    were invisible to ``/api/services/providers`` until container restart.
    ``service_updater.run_update_now`` calls this on success so live API
    responses reflect the latest discoveries.

    Returns a dict of ``{provider: total_count}`` after reload.
    """
    discovered = _load_discovered()

    new_aws = _merge(_AWS_STATIC, discovered.get("aws", []))
    new_azure = _merge(_AZURE_STATIC, discovered.get("azure", []))
    new_gcp = _merge(_GCP_STATIC, discovered.get("gcp", []))

    # Mutate in place so existing `from services import AWS_SERVICES` references
    # see the new entries without needing a re-import.
    AWS_SERVICES.clear()
    AWS_SERVICES.extend(new_aws)
    AZURE_SERVICES.clear()
    AZURE_SERVICES.extend(new_azure)
    GCP_SERVICES.clear()
    GCP_SERVICES.extend(new_gcp)

    counts = {
        "aws": len(AWS_SERVICES),
        "azure": len(AZURE_SERVICES),
        "gcp": len(GCP_SERVICES),
    }

    if any(discovered.get(p) for p in ("aws", "azure", "gcp")):
        added = (
            (len(AWS_SERVICES) - len(_AWS_STATIC))
            + (len(AZURE_SERVICES) - len(_AZURE_STATIC))
            + (len(GCP_SERVICES) - len(_GCP_STATIC))
        )
        if added > 0:
            logger.info(
                "Catalog reloaded: %d discovered services merged (aws=%d azure=%d gcp=%d)",
                added,
                counts["aws"],
                counts["azure"],
                counts["gcp"],
            )

    return counts


# Initial load at module import.
reload()

__all__ = [
    "AWS_SERVICES",
    "AZURE_SERVICES",
    "GCP_SERVICES",
    "CROSS_CLOUD_MAPPINGS",
    "reload",
]
