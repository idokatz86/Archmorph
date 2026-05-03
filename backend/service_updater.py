"""
Cloud Service Catalog Updater

Fetches service catalogs from AWS, Azure, and GCP discovery APIs,
compares them against the local catalogs, and writes newly discovered services
to ``data/discovered_services.json`` (with optional Azure Blob persistence so
discoveries survive container restarts on stateless platforms like Azure
Container Apps).

The services module merges this discovery file with the static Python catalogs
at import time, so no Python source files are modified at runtime.

Scheduling model (issue #571):
  Primary: external GitHub Actions cron (``.github/workflows/service-catalog-refresh.yml``)
           POSTs to ``/api/service-updates/run-now`` every day at 02:00 UTC.
           This is durable across container restarts and replica scaling.
  Backup:  In-process APScheduler ``BackgroundScheduler`` runs the same job at
           02:15 UTC. It is best-effort only — disabled when SCHEDULER_DISABLED=1
           (set this in multi-replica deployments to avoid duplicate runs).

Freshness contract:
  ``get_freshness()`` returns the age of the last successful run. The /health
  endpoint surfaces this and returns ``degraded`` when the age exceeds 36 hours.
"""

import importlib
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(handler)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_BASE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _BASE_DIR / "data"
_SERVICES_DIR = _BASE_DIR / "services"
_UPDATES_FILE = _DATA_DIR / "service_updates.json"
_DISCOVERED_FILE = _DATA_DIR / "discovered_services.json"


def _default_state() -> dict[str, Any]:
    return {
        "last_check": None,
        "checks": [],
        "new_services_found": {"aws": [], "azure": [], "gcp": []},
        "auto_added": {"aws": [], "azure": [], "gcp": []},
    }

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------
AWS_INDEX_URL = "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/index.json"
AZURE_PRICES_URL = (
    "https://prices.azure.com/api/retail/prices"
    "?api-version=2023-01-01-preview"
    "&$filter=priceType eq 'Consumption'"
)
# Issue #571 — replaces the retired Cloud Pricing Calculator pricelist.json
# (HTTP 404 since at least Q1 2026). Google APIs Discovery is public, requires
# no authentication, and lists every Cloud + Workspace API.
GCP_DISCOVERY_URL = "https://www.googleapis.com/discovery/v1/apis?preferred=true"

# Names that look like Workspace / non-infra APIs are filtered out so the catalog
# focuses on services with cross-cloud equivalents.
_GCP_NON_INFRA_PREFIXES = (
    "admin",
    "adsense",
    "androidenterprise",
    "androidmanagement",
    "androidpublisher",
    "books",
    "calendar",
    "chat",
    "chromemanagement",
    "chromepolicy",
    "classroom",
    "docs",
    "drive",
    "forms",
    "gmail",
    "keep",
    "meet",
    "oauth2",
    "people",
    "sheets",
    "slides",
    "tasks",
    "webfonts",
    "webmasters",
    "youtube",
)

# ---------------------------------------------------------------------------
# HTTP settings
# ---------------------------------------------------------------------------
_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)
_MAX_AZURE_PAGES = 20  # safety cap for Azure pagination


def _provider_fetch_attempts() -> int:
    raw = os.getenv("SERVICE_REFRESH_PROVIDER_ATTEMPTS", "3")
    try:
        attempts = int(raw)
    except ValueError:
        attempts = 3
    return max(1, min(attempts, 5))


def _provider_retry_delay_seconds() -> float:
    raw = os.getenv("SERVICE_REFRESH_PROVIDER_RETRY_DELAY_SECONDS", "2")
    try:
        delay = float(raw)
    except ValueError:
        delay = 2.0
    return max(0.0, min(delay, 30.0))


def _is_retryable_http_status(status_code: int) -> bool:
    return status_code in {408, 409, 425, 429} or status_code >= 500


def _fetch_provider_services_with_retries(
    provider: str,
    fetch_fn: Callable[[httpx.Client], set[str]],
    client: httpx.Client,
) -> tuple[set[str], int]:
    attempts = _provider_fetch_attempts()
    delay = _provider_retry_delay_seconds()

    for attempt in range(1, attempts + 1):
        try:
            services = fetch_fn(client)
            retries_used = attempt - 1
            if retries_used:
                logger.info(
                    "%s fetch recovered after %d retry attempt(s)",
                    provider.upper(),
                    retries_used,
                )
            return services, retries_used
        except httpx.HTTPStatusError as exc:
            retryable = _is_retryable_http_status(exc.response.status_code)
            if not retryable or attempt == attempts:
                raise
            logger.warning(
                "%s fetch returned retryable HTTP %d on attempt %d/%d",
                provider.upper(),
                exc.response.status_code,
                attempt,
                attempts,
            )
        except httpx.RequestError as exc:
            if attempt == attempts:
                raise
            logger.warning(
                "%s fetch request error on attempt %d/%d: %s",
                provider.upper(),
                attempt,
                attempts,
                exc,
            )

        if delay > 0:
            time.sleep(delay * attempt)

    raise RuntimeError(f"{provider.upper()} fetch retry loop exhausted")

# ---------------------------------------------------------------------------
# Provider -> catalog module config
# ---------------------------------------------------------------------------
_PROVIDER_CONFIG = {
    "aws": {
        "module": "services.aws_services",
        "variable": "AWS_SERVICES",
        "id_prefix": "aws",
        "icon_default": "cloud",
    },
    "azure": {
        "module": "services.azure_services",
        "variable": "AZURE_SERVICES",
        "id_prefix": "az",
        "icon_default": "cloud",
    },
    "gcp": {
        "module": "services.gcp_services",
        "variable": "GCP_SERVICES",
        "id_prefix": "gcp",
        "icon_default": "cloud",
    },
}

# ---------------------------------------------------------------------------
# Scheduler singleton
# ---------------------------------------------------------------------------
_scheduler: Optional[BackgroundScheduler] = None
_running: bool = False

# ---------------------------------------------------------------------------
# Helpers -- persistent state
# ---------------------------------------------------------------------------


def _read_state() -> dict[str, Any]:
    """Load the service_updates.json state file."""
    blob_state = _load_state_from_blob()
    if blob_state is not None:
        return blob_state
    try:
        with open(_UPDATES_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return _default_state()


def _write_state(state: dict[str, Any]) -> None:
    """Persist state to service_updates.json."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(_UPDATES_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, default=str)
    _save_state_to_blob(state)


# ---------------------------------------------------------------------------
# Durable blob persistence (issue #571)
# ---------------------------------------------------------------------------
#
# Stateless container deployments (Azure Container Apps, etc.) wipe the local
# filesystem on every restart, which previously caused all auto-discovered
# services to vanish on each redeploy. We mirror discoveries to Azure Blob
# Storage when configured, with the local file as fallback for dev / tests.
#
# Auth pattern matches services/azure_pricing.py:
#   1. RBAC via DefaultAzureCredential when AZURE_STORAGE_ACCOUNT_URL is set
#   2. Connection string when AZURE_STORAGE_CONNECTION_STRING is set
#   3. Otherwise: local-disk only (dev / tests)

DISCOVERED_BLOB_CONTAINER = os.getenv("DISCOVERED_BLOB_CONTAINER", "service-catalog")
DISCOVERED_BLOB_NAME = os.getenv(
    "DISCOVERED_BLOB_NAME", "discovered_services.json"
)
SERVICE_UPDATES_BLOB_NAME = os.getenv(
    "SERVICE_UPDATES_BLOB_NAME", "service_updates.json"
)
DISCOVERED_BLOB_TIMEOUT_SECONDS = 5


def _blob_timeout_seconds() -> int:
    """Return the bounded timeout used for blob catalog operations."""
    raw = os.getenv("DISCOVERED_BLOB_TIMEOUT_SECONDS", "")
    if not raw:
        return DISCOVERED_BLOB_TIMEOUT_SECONDS
    try:
        value = int(raw)
    except ValueError:
        return DISCOVERED_BLOB_TIMEOUT_SECONDS
    return max(1, min(value, 30))


def _get_service_catalog_blob_client(blob_name: str):
    """Return a BlobClient in the service-catalog container, or None."""
    account_url = os.getenv("AZURE_STORAGE_ACCOUNT_URL", "")
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
    if not account_url and not conn_str:
        return None
    timeout = _blob_timeout_seconds()
    try:
        from azure.storage.blob import BlobServiceClient

        if account_url:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential(
                managed_identity_client_id=os.getenv("AZURE_CLIENT_ID") or None
            )
            bsc = BlobServiceClient(
                account_url,
                credential=credential,
                connection_timeout=timeout,
                read_timeout=timeout,
            )
        else:
            bsc = BlobServiceClient.from_connection_string(
                conn_str,
                connection_timeout=timeout,
                read_timeout=timeout,
            )

        container = bsc.get_container_client(DISCOVERED_BLOB_CONTAINER)
        try:
            container.get_container_properties(timeout=timeout)
        except Exception:
            container.create_container(timeout=timeout)
            logger.info(
                "Created blob container '%s' for service catalog state",
                DISCOVERED_BLOB_CONTAINER,
            )
        return container.get_blob_client(blob_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Service-catalog blob client unavailable (falling back to disk): %s",
            exc,
        )
        return None


def _get_discovered_blob_client():
    """Return a BlobClient for discovered_services.json, or None."""
    return _get_service_catalog_blob_client(DISCOVERED_BLOB_NAME)


def _get_state_blob_client():
    """Return a BlobClient for service_updates.json, or None."""
    return _get_service_catalog_blob_client(SERVICE_UPDATES_BLOB_NAME)


def _get_service_catalog_managed_identity_container_client():
    """Return the service-catalog ContainerClient using managed identity only."""
    account_url = os.getenv("AZURE_STORAGE_ACCOUNT_URL", "")
    if not account_url:
        return None
    timeout = _blob_timeout_seconds()
    from azure.identity import ManagedIdentityCredential
    from azure.storage.blob import BlobServiceClient

    credential_kwargs = {}
    managed_identity_client_id = os.getenv("AZURE_CLIENT_ID")
    if managed_identity_client_id:
        credential_kwargs["client_id"] = managed_identity_client_id
    credential = ManagedIdentityCredential(**credential_kwargs)
    bsc = BlobServiceClient(
        account_url,
        credential=credential,
        connection_timeout=timeout,
        read_timeout=timeout,
    )
    return bsc.get_container_client(DISCOVERED_BLOB_CONTAINER)


def verify_service_catalog_blob_access() -> dict[str, Any]:
    """Verify managed-identity read/write/list access to service-catalog blobs."""
    account_url = os.getenv("AZURE_STORAGE_ACCOUNT_URL", "")
    if not account_url:
        return {
            "ok": False,
            "account_url_configured": False,
            "container": DISCOVERED_BLOB_CONTAINER,
            "error": "AZURE_STORAGE_ACCOUNT_URL is not configured",
        }

    probe_name = f".deployment-preflight/{uuid.uuid4().hex}.json"
    payload = json.dumps({
        "probe": "service-catalog-storage",
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    timeout = _blob_timeout_seconds()
    blob = None
    probe_uploaded = False
    try:
        container = _get_service_catalog_managed_identity_container_client()
        if container is None:
            raise RuntimeError("managed-identity container client is not configured")

        try:
            container.get_container_properties(timeout=timeout)
        except Exception:
            container.create_container(timeout=timeout)

        blob = container.get_blob_client(probe_name)
        blob.upload_blob(payload.encode("utf-8"), overwrite=True, timeout=timeout)
        probe_uploaded = True
        raw = blob.download_blob(timeout=timeout).readall()
        if raw.decode("utf-8") != payload:
            raise RuntimeError("preflight blob read did not match written payload")
        listed = any(
            item.name == probe_name
            for item in container.list_blobs(name_starts_with=probe_name, timeout=timeout)
        )
        if not listed:
            raise RuntimeError("preflight blob was not returned by list_blobs")
        blob.delete_blob(timeout=timeout)
        probe_uploaded = False
        return {
            "ok": True,
            "account_url_configured": True,
            "account_url": account_url,
            "container": DISCOVERED_BLOB_CONTAINER,
            "operations": ["write", "read", "list", "delete"],
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Service-catalog blob preflight failed: %s", exc)
        return {
            "ok": False,
            "account_url_configured": True,
            "account_url": account_url,
            "container": DISCOVERED_BLOB_CONTAINER,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    finally:
        if probe_uploaded and blob is not None:
            try:
                blob.delete_blob(timeout=timeout)
            except Exception as cleanup_exc:  # noqa: BLE001
                logger.warning(
                    "Failed to clean up service-catalog preflight blob %s: %s",
                    probe_name,
                    cleanup_exc,
                )


def _load_state_from_blob() -> Optional[dict[str, Any]]:
    """Load service_updates.json from Azure Blob Storage (or None)."""
    blob = _get_state_blob_client()
    if blob is None:
        return None
    try:
        raw = blob.download_blob(timeout=_blob_timeout_seconds()).readall()
        data = json.loads(raw)
        if isinstance(data, dict):
            try:
                _DATA_DIR.mkdir(parents=True, exist_ok=True)
                with open(_UPDATES_FILE, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2, default=str)
            except OSError:
                pass
            return data
    except Exception as exc:  # noqa: BLE001
        if type(exc).__name__ == "ResourceNotFoundError":
            logger.debug("No service-updates blob yet (%s)", type(exc).__name__)
        else:
            logger.warning(
                "Failed to load service update state from blob; falling back to disk",
                exc_info=True,
            )
    return None


def _save_state_to_blob(state: dict[str, Any]) -> None:
    """Mirror service_updates.json to Azure Blob Storage (best-effort)."""
    blob = _get_state_blob_client()
    if blob is None:
        return
    try:
        blob.upload_blob(
            json.dumps(state, indent=2, default=str).encode("utf-8"),
            overwrite=True,
        )
        logger.info(
            "Mirrored service update state to blob %s/%s",
            DISCOVERED_BLOB_CONTAINER,
            SERVICE_UPDATES_BLOB_NAME,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to mirror service update state to blob: %s", exc)


def _load_discovered_from_blob() -> Optional[dict[str, list[dict[str, str]]]]:
    """Load discovered_services.json from Azure Blob Storage (or None)."""
    blob = _get_discovered_blob_client()
    if blob is None:
        return None
    try:
        raw = blob.download_blob(timeout=_blob_timeout_seconds()).readall()
        data = json.loads(raw)
        if isinstance(data, dict):
            # Hydrate the local cache so import-time consumers see it too.
            try:
                _DATA_DIR.mkdir(parents=True, exist_ok=True)
                with open(_DISCOVERED_FILE, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2)
            except OSError:
                pass  # read-only filesystem is fine; blob is the source of truth
            return data
    except Exception as exc:  # noqa: BLE001
        # ResourceNotFoundError on a fresh deployment is expected.
        if type(exc).__name__ == "ResourceNotFoundError":
            logger.debug("No discovered-services blob yet (%s)", type(exc).__name__)
        else:
            logger.warning(
                "Failed to load discovered services from blob; falling back to disk",
                exc_info=True,
            )
    return None


def _save_discovered_to_blob(discovered: dict[str, list[dict[str, str]]]) -> None:
    """Mirror discovered_services.json to Azure Blob Storage (best-effort)."""
    blob = _get_discovered_blob_client()
    if blob is None:
        return
    try:
        blob.upload_blob(
            json.dumps(discovered, indent=2).encode("utf-8"),
            overwrite=True,
        )
        logger.info(
            "Mirrored discovered services to blob %s/%s",
            DISCOVERED_BLOB_CONTAINER,
            DISCOVERED_BLOB_NAME,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to mirror discoveries to blob: %s", exc)


# ---------------------------------------------------------------------------
# Local catalog loaders  (FIXED: uses actual attribute names)
# ---------------------------------------------------------------------------


def _normalise(name: str) -> str:
    """Normalise a service name for comparison: lowercase, strip non-alnum."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _load_local_catalog(provider: str) -> tuple[list[dict], set[str]]:
    """
    Load the local service catalog for a provider.

    Returns:
        (service_list, name_set) -- the full list of service dicts and
        a set of normalised service names for comparison.
    """
    config = _PROVIDER_CONFIG[provider]
    module_name = config["module"]
    var_name = config["variable"]

    try:
        module = importlib.import_module(module_name)
        # Force reload so we pick up any changes made during this process
        importlib.reload(module)
    except ModuleNotFoundError:
        logger.warning(
            "Could not import %s -- treating catalog as empty", module_name
        )
        return [], set()

    service_list = getattr(module, var_name, None)
    if service_list is None:
        logger.warning("Attribute %s not found in %s", var_name, module_name)
        return [], set()

    if not isinstance(service_list, list):
        logger.warning(
            "%s.%s is not a list (got %s)",
            module_name,
            var_name,
            type(service_list).__name__,
        )
        return [], set()

    # Build a normalised name set for comparison
    name_set: set[str] = set()
    for svc in service_list:
        # Add multiple normalised forms for fuzzy matching
        name = svc.get("name", "")
        full_name = svc.get("fullName", "")
        svc_id = svc.get("id", "")
        if name:
            name_set.add(_normalise(name))
        if full_name:
            name_set.add(_normalise(full_name))
        if svc_id:
            name_set.add(_normalise(svc_id))

    logger.info(
        "Loaded %d services from %s.%s", len(service_list), module_name, var_name
    )
    return service_list, name_set


# ---------------------------------------------------------------------------
# Service name -> catalog entry builder
# ---------------------------------------------------------------------------

_CATEGORY_HINTS = {
    # keyword fragments -> category
    "compute": "Compute",
    "vm": "Compute",
    "ec2": "Compute",
    "instance": "Compute",
    "server": "Compute",
    "machine": "Compute",
    "container": "Compute",
    "kubernetes": "Compute",
    "lambda": "Compute",
    "function": "Compute",
    "batch": "Compute",
    "storage": "Storage",
    "blob": "Storage",
    "s3": "Storage",
    "disk": "Storage",
    "file": "Storage",
    "archive": "Storage",
    "backup": "Storage",
    "database": "Database",
    "sql": "Database",
    "db": "Database",
    "redis": "Database",
    "dynamo": "Database",
    "cosmos": "Database",
    "cache": "Database",
    "network": "Networking",
    "vpc": "Networking",
    "dns": "Networking",
    "load balanc": "Networking",
    "cdn": "Networking",
    "firewall": "Networking",
    "gateway": "Networking",
    "route": "Networking",
    "iam": "Security",
    "security": "Security",
    "guard": "Security",
    "key vault": "Security",
    "kms": "Security",
    "waf": "Security",
    "certificate": "Security",
    "secrets": "Security",
    "monitor": "Monitoring",
    "log": "Monitoring",
    "metric": "Monitoring",
    "trace": "Monitoring",
    "alarm": "Monitoring",
    "insight": "Monitoring",
    "machine learning": "AI/ML",
    "ml": "AI/ML",
    "ai": "AI/ML",
    "sagemaker": "AI/ML",
    "cognitive": "AI/ML",
    "vision": "AI/ML",
    "bedrock": "AI/ML",
    "openai": "AI/ML",
    "translate": "AI/ML",
    "textract": "AI/ML",
    "rekognition": "AI/ML",
    "devops": "DevOps",
    "pipeline": "DevOps",
    "codebuild": "DevOps",
    "deploy": "DevOps",
    "cicd": "DevOps",
    "analytics": "Analytics",
    "kinesis": "Analytics",
    "stream": "Analytics",
    "data": "Analytics",
    "etl": "Analytics",
    "messaging": "Integration",
    "queue": "Integration",
    "event": "Integration",
    "notification": "Integration",
    "sns": "Integration",
    "sqs": "Integration",
    "bus": "Integration",
    "pub": "Integration",
    "migration": "Migration",
    "transfer": "Migration",
}

_ICON_HINTS = {
    "Compute": "server",
    "Storage": "storage",
    "Database": "database",
    "Networking": "network",
    "Security": "shield",
    "Monitoring": "monitor",
    "AI/ML": "brain",
    "DevOps": "pipeline",
    "Analytics": "chart",
    "Integration": "workflow",
    "Migration": "migration",
}


def _guess_category(service_name: str) -> str:
    """Guess the category of a service based on its name."""
    lower = service_name.lower()
    for hint, category in _CATEGORY_HINTS.items():
        if hint in lower:
            return category
    return "Other"


def _make_service_entry(
    raw_name: str,
    provider: str,
) -> dict[str, str]:
    """
    Build a catalog entry dict for a newly discovered service.

    Returns a dict like:
        {"id": "aws-new-service", "name": "New Service",
         "fullName": "AWS New Service", "category": "Other",
         "description": "Newly discovered service", "icon": "cloud"}
    """
    config = _PROVIDER_CONFIG[provider]
    prefix = config["id_prefix"]

    # Clean up the raw name
    display_name = raw_name.strip()

    # Build a slug id
    slug = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-")
    svc_id = f"{prefix}-{slug}"

    # Provider-specific full name prefix
    provider_label = {"aws": "AWS", "azure": "Azure", "gcp": "Google Cloud"}
    full_name = f"{provider_label.get(provider, provider)} {display_name}"

    category = _guess_category(display_name)
    icon = _ICON_HINTS.get(category, config["icon_default"])

    return {
        "id": svc_id,
        "name": display_name,
        "fullName": full_name,
        "category": category,
        "description": f"Newly discovered {provider.upper()} service",
        "icon": icon,
    }


# ---------------------------------------------------------------------------
# Auto-integration -- write discovered services to JSON data file
# ---------------------------------------------------------------------------


def _load_discovered_services() -> dict[str, list[dict[str, str]]]:
    """
    Load previously discovered services.

    Source priority (issue #571 — stateless container fix):
      1. Azure Blob Storage (durable across container restarts)
      2. Local disk (``data/discovered_services.json``)
      3. Empty

    Returns a dict keyed by provider ("aws", "azure", "gcp"),
    each containing a list of service entry dicts.
    """
    blob_data = _load_discovered_from_blob()
    if blob_data is not None:
        return blob_data

    try:
        with open(_DISCOVERED_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, dict):
                return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return {"aws": [], "azure": [], "gcp": []}


def _save_discovered_services(
    provider: str,
    new_entries: list[dict[str, str]],
) -> int:
    """
    Append newly discovered service entries to the JSON discovery file.

    Merges with any previously discovered services (deduplicated by id).
    Returns the number of services newly added.
    """
    if not new_entries:
        return 0

    discovered = _load_discovered_services()
    existing = discovered.get(provider, [])
    existing_ids = {entry["id"] for entry in existing}

    added = []
    for entry in new_entries:
        if entry["id"] not in existing_ids:
            added.append(entry)
            existing_ids.add(entry["id"])

    if not added:
        return 0

    existing.extend(added)
    discovered[provider] = existing

    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(_DISCOVERED_FILE, "w", encoding="utf-8") as fh:
        json.dump(discovered, fh, indent=2)

    # Mirror to durable blob storage so discoveries survive container restarts.
    _save_discovered_to_blob(discovered)

    logger.info(
        "Saved %d new discovered services for %s to %s",
        len(added),
        provider.upper(),
        _DISCOVERED_FILE.name,
    )
    return len(added)


# ---------------------------------------------------------------------------
# Provider fetchers
# ---------------------------------------------------------------------------


def _fetch_aws_services(client: httpx.Client) -> set[str]:
    """Fetch the AWS service catalog from the pricing index."""
    logger.info("Fetching AWS service index ...")
    resp = client.get(AWS_INDEX_URL)
    resp.raise_for_status()
    data = resp.json()
    offers = data.get("offers", {})
    # Extract offer codes (e.g. "AmazonEC2", "AWSLambda")
    services: set[str] = set(offers.keys())
    logger.info("AWS: fetched %d services", len(services))
    return services


def _fetch_azure_services(client: httpx.Client) -> set[str]:
    """Fetch Azure service names from the retail prices API (paginated)."""
    logger.info("Fetching Azure service names ...")
    services: set[str] = set()
    url: Optional[str] = AZURE_PRICES_URL
    page = 0

    while url and page < _MAX_AZURE_PAGES:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("Items", []):
            name = item.get("serviceName")
            if name:
                services.add(name)
        url = data.get("NextPageLink")
        page += 1

    logger.info(
        "Azure: fetched %d unique service names (%d pages)", len(services), page
    )
    return services


def _fetch_gcp_services(client: httpx.Client) -> set[str]:
    """Fetch GCP service names from the Google APIs Discovery service.

    Issue #571 — the legacy pricing calculator pricelist.json was retired and
    silently 404'd for months. The Discovery API is the canonical, public,
    unauthenticated catalog of every Google Cloud and Workspace API.
    """
    logger.info("Fetching GCP API discovery list ...")
    resp = client.get(GCP_DISCOVERY_URL)
    resp.raise_for_status()
    data = resp.json()
    items = data.get("items", [])

    services: set[str] = set()
    for item in items:
        name = (item.get("name") or "").strip()
        if not name:
            continue
        if name.startswith(_GCP_NON_INFRA_PREFIXES):
            continue  # Workspace / consumer surfaces — out of scope for the catalog
        services.add(name)

    logger.info("GCP: fetched %d infra-track service names", len(services))
    return services


# ---------------------------------------------------------------------------
# Core update logic
# ---------------------------------------------------------------------------


def run_update_now(*, auto_add: bool = True) -> dict[str, Any]:
    """
    Execute an immediate service catalog update for all three providers.

    Args:
        auto_add: If True, automatically append newly discovered services
                  to the Python catalog files.

    Returns a summary dict with timestamps and lists of new services found.
    If a single provider fails the remaining providers are still processed.
    """
    logger.info("Starting cloud service catalog update ...")
    timestamp = datetime.now(timezone.utc).isoformat()

    provider_results: dict[str, list[str]] = {"aws": [], "azure": [], "gcp": []}
    auto_added: dict[str, list[str]] = {"aws": [], "azure": [], "gcp": []}
    errors: dict[str, str] = {}
    retry_attempts: dict[str, int] = {}

    fetchers = {
        "aws": _fetch_aws_services,
        "azure": _fetch_azure_services,
        "gcp": _fetch_gcp_services,
    }

    with httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
        for provider, fetch_fn in fetchers.items():
            try:
                remote_services, retries_used = _fetch_provider_services_with_retries(
                    provider,
                    fetch_fn,
                    client,
                )
                if retries_used:
                    retry_attempts[provider] = retries_used
                _, local_names = _load_local_catalog(provider)

                # Find genuinely new services by normalised comparison
                new_services: list[str] = []
                for remote_name in sorted(remote_services):
                    norm = _normalise(remote_name)
                    if norm and norm not in local_names and len(norm) > 1:
                        new_services.append(remote_name)

                if new_services:
                    logger.info(
                        "%s: %d new service(s) detected: %s",
                        provider.upper(),
                        len(new_services),
                        ", ".join(new_services[:10])
                        + (" ..." if len(new_services) > 10 else ""),
                    )

                    # Save discovered services to JSON data file
                    if auto_add:
                        entries = [
                            _make_service_entry(name, provider)
                            for name in new_services
                        ]
                        added = _save_discovered_services(provider, entries)
                        if added > 0:
                            auto_added[provider] = [
                                e["name"] for e in entries[:added]
                            ]
                            logger.info(
                                "%s: saved %d discovered services to JSON",
                                provider.upper(),
                                added,
                            )
                else:
                    logger.info("%s: catalog is up-to-date", provider.upper())

                provider_results[provider] = new_services

            except httpx.HTTPStatusError as exc:
                msg = f"HTTP {exc.response.status_code} from {provider.upper()}"
                logger.error("%s fetch failed: %s", provider.upper(), msg)
                errors[provider] = msg

            except httpx.RequestError as exc:
                msg = f"Request error: {exc}"
                logger.error("%s fetch failed: %s", provider.upper(), msg)
                errors[provider] = msg

            except Exception as exc:  # noqa: BLE001
                msg = f"Unexpected error: {exc}"
                logger.error(
                    "%s fetch failed: %s", provider.upper(), msg, exc_info=True
                )
                errors[provider] = msg

    # Build check record
    check_record: dict[str, Any] = {
        "timestamp": timestamp,
        "new_services": provider_results,
        "auto_added": auto_added,
        "errors": errors if errors else None,
        "retry_attempts": retry_attempts if retry_attempts else None,
    }

    # Persist
    state = _read_state()
    state["last_check"] = timestamp
    state["checks"].append(check_record)

    # Keep only the last 90 check records to avoid unbounded growth
    if len(state["checks"]) > 90:
        state["checks"] = state["checks"][-90:]

    # Merge newly found services (deduplicated)
    for provider in ("aws", "azure", "gcp"):
        existing = set(state["new_services_found"].get(provider, []))
        existing.update(provider_results[provider])
        state["new_services_found"][provider] = sorted(existing)

    # Track auto-added services cumulatively
    if "auto_added" not in state:
        state["auto_added"] = {"aws": [], "azure": [], "gcp": []}
    for provider in ("aws", "azure", "gcp"):
        existing_added = set(state["auto_added"].get(provider, []))
        existing_added.update(auto_added[provider])
        state["auto_added"][provider] = sorted(existing_added)

    _write_state(state)

    # Issue #647 — re-merge static + discovered catalogs in place so live API
    # responses reflect new discoveries without requiring a container restart.
    # Best-effort: if reload fails (test isolation, partial init), log and continue.
    if any(auto_added[p] for p in ("aws", "azure", "gcp")):
        try:
            import services as _services_mod
            counts = _services_mod.reload()
            logger.info(
                "Live catalog reloaded after refresh: aws=%d azure=%d gcp=%d",
                counts["aws"], counts["azure"], counts["gcp"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Live catalog reload failed (non-fatal): %s",
                exc,
                exc_info=True,
            )

    # Issue #640 — publish freshness signal only for fully successful runs.
    # Partial provider failures remain visible as stale scheduled-job health.
    if not errors:
        try:
            from freshness_registry import mark_success
            mark_success(
                "service_catalog_refresh",
                when=datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("freshness_registry.mark_success failed: %s", exc)
    else:
        logger.warning(
            "Skipping service_catalog_refresh freshness success because providers failed: %s",
            ",".join(sorted(errors)),
        )

    logger.info("Service catalog update complete.")
    return check_record


# ---------------------------------------------------------------------------
# Status / query helpers
# ---------------------------------------------------------------------------


def get_last_update() -> dict[str, Any]:
    """
    Return information about the most recent catalog check.

    Returns a dict with ``last_check`` (ISO timestamp or None) and
    ``last_result`` (the check record, or None if no checks have been run).
    """
    state = _read_state()
    last_result = state["checks"][-1] if state["checks"] else None
    return {
        "last_check": state["last_check"],
        "last_result": last_result,
    }


def get_update_status() -> dict[str, Any]:
    """
    Return the overall status of the updater including scheduler state,
    total checks performed, and aggregate new services found.
    """
    state = _read_state()
    return {
        "scheduler_running": _running,
        "last_check": state["last_check"],
        "total_checks": len(state["checks"]),
        "new_services_found": {
            provider: len(services)
            for provider, services in state["new_services_found"].items()
        },
        "auto_added_total": {
            provider: len(services)
            for provider, services in state.get("auto_added", {}).items()
        },
    }


# Issue #571 — freshness contract surfaced via /health.
# A successful run must occur within FRESHNESS_BUDGET_HOURS or the system is
# considered degraded and the SLO is breached.
FRESHNESS_BUDGET_HOURS = float(os.getenv("SERVICE_REFRESH_BUDGET_HOURS", "36"))


def _parse_state_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _last_successful_refresh_timestamp_from_state(state: dict[str, Any]) -> Optional[datetime]:
    """Return the newest service-refresh timestamp with no provider errors."""
    for check_record in reversed(state.get("checks", [])):
        if check_record.get("errors"):
            continue
        parsed = _parse_state_timestamp(check_record.get("timestamp"))
        if parsed is not None:
            return parsed
    return None


def _last_successful_refresh_timestamp() -> Optional[datetime]:
    """Return the newest persisted service-refresh timestamp with no errors."""
    return _last_successful_refresh_timestamp_from_state(_read_state())


def _register_service_catalog_freshness(last_success: Optional[datetime] = None) -> None:
    """Register the service catalog refresh job, seeding durable state."""
    from freshness_registry import mark_success, register_with_last_success

    if last_success is None:
        last_success = _last_successful_refresh_timestamp()

    register_with_last_success(
        "service_catalog_refresh",
        budget_hours=FRESHNESS_BUDGET_HOURS,
        last_success=last_success,
        description="Daily AWS/Azure/GCP service catalog discovery (issue #571)",
    )
    if last_success is not None:
        mark_success("service_catalog_refresh", when=last_success)

# Issue #640 — register with the centralised freshness registry so this job
# shows up in the /api/health.scheduled_jobs block alongside any other periodic
# work, and is monitored by the freshness-watchdog GH Actions workflow.
try:
    _register_service_catalog_freshness()
except Exception:  # noqa: BLE001
    pass  # registry import failure is non-fatal


def get_freshness() -> dict[str, Any]:
    """Return last-successful-run age in hours and a stale flag.

    Returns:
        {
          "last_check": ISO timestamp or None,
          "age_hours": float or None,
          "budget_hours": float,
          "stale": bool,           # True when older than budget OR never run
          "last_errors": dict | None,
          "providers_failed": [str, ...]
        }
    """
    state = _read_state()
    last_success = _last_successful_refresh_timestamp_from_state(state)
    try:
        _register_service_catalog_freshness(last_success=last_success)
    except Exception:  # noqa: BLE001
        pass

    last = last_success.isoformat() if last_success else None
    last_check_record = state["checks"][-1] if state.get("checks") else None
    last_errors = (last_check_record or {}).get("errors") or None
    providers_failed = sorted(last_errors.keys()) if isinstance(last_errors, dict) else []

    age_hours: Optional[float] = None
    stale = True
    if last_success is not None:
        age_seconds = (datetime.now(timezone.utc) - last_success).total_seconds()
        age_hours = round(age_seconds / 3600, 2)
        stale = age_hours > FRESHNESS_BUDGET_HOURS

    return {
        "last_check": last,
        "age_hours": age_hours,
        "budget_hours": FRESHNESS_BUDGET_HOURS,
        "stale": stale,
        "last_errors": last_errors,
        "providers_failed": providers_failed,
    }


# ---------------------------------------------------------------------------
# Scheduler management
# ---------------------------------------------------------------------------


def start_scheduler() -> None:
    """Start the in-process backup scheduler.

    Issue #571 — this is the **backup** path. The primary scheduler is the
    GitHub Actions cron in ``.github/workflows/service-catalog-refresh.yml``
    which hits ``/api/service-updates/run-now`` daily at 02:00 UTC, durable
    across container restarts and replica scaling.

    Set ``SCHEDULER_DISABLED=1`` to opt out of the in-process backup, which
    you should do in any deployment that scales beyond a single replica
    (otherwise N replicas fire N duplicate jobs).
    """
    global _scheduler, _running  # noqa: PLW0603

    if os.getenv("SCHEDULER_DISABLED", "").lower() in ("1", "true", "yes"):
        logger.info(
            "In-process scheduler disabled via SCHEDULER_DISABLED env var. "
            "Relying on GitHub Actions cron (see workflow service-catalog-refresh.yml)."
        )
        _running = False
        return

    if _running and _scheduler is not None:
        logger.warning("Scheduler is already running.")
        return

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        run_update_now,
        # 02:15 UTC — 15 minutes after the GH Actions primary, so when both run
        # the backup is a no-op (catalog already fresh).
        trigger=CronTrigger(hour=2, minute=15, timezone="UTC"),
        id="cloud_service_update",
        name="Daily cloud service catalog update (backup)",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    _running = True
    logger.info(
        "Backup scheduler started — next run at 02:15 UTC daily "
        "(primary is GitHub Actions cron at 02:00 UTC)."
    )


def stop_scheduler() -> None:
    """Gracefully shut down the background scheduler."""
    global _scheduler, _running  # noqa: PLW0603

    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")
    _scheduler = None
    _running = False


# ---------------------------------------------------------------------------
# CLI convenience
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Cloud service catalog updater")
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Run an immediate update instead of starting the scheduler",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect new services but don't write to catalog files",
    )
    args = parser.parse_args()

    if args.run_now or args.dry_run:
        result = run_update_now(auto_add=not args.dry_run)
        print(json.dumps(result, indent=2, default=str))
    else:
        import signal
        import threading

        stop_event = threading.Event()

        def _handle_signal(sig: int, _frame: Any) -> None:
            logger.info("Received signal %s -- shutting down ...", sig)
            stop_scheduler()
            stop_event.set()

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        start_scheduler()
        # Run an initial update immediately on startup
        run_update_now()
        stop_event.wait()
