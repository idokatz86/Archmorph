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
    """Load discovered services from the JSON data file."""
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


_discovered = _load_discovered()
AWS_SERVICES = _merge(_AWS_STATIC, _discovered.get("aws", []))
AZURE_SERVICES = _merge(_AZURE_STATIC, _discovered.get("azure", []))
GCP_SERVICES = _merge(_GCP_STATIC, _discovered.get("gcp", []))

if any(_discovered.get(p) for p in ("aws", "azure", "gcp")):
    _total = (
        len(AWS_SERVICES) - len(_AWS_STATIC)
        + len(AZURE_SERVICES) - len(_AZURE_STATIC)
        + len(GCP_SERVICES) - len(_GCP_STATIC)
    )
    if _total > 0:
        logger.info("Merged %d discovered services from %s", _total, _DISCOVERED_FILE.name)

__all__ = ["AWS_SERVICES", "AZURE_SERVICES", "GCP_SERVICES", "CROSS_CLOUD_MAPPINGS"]
