"""
Daily Cloud Service Catalog Updater

Periodically fetches service catalogs from AWS, Azure, and GCP pricing APIs,
compares them against the local catalogs, and writes newly discovered services
to a JSON data file (data/discovered_services.json).

The services module merges this discovery file with the static Python catalogs
at import time, so no Python source files are modified at runtime.

Uses APScheduler BackgroundScheduler to run updates every 24 hours at 2:00 AM UTC.
"""

import importlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

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

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------
AWS_INDEX_URL = "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/index.json"
AZURE_PRICES_URL = (
    "https://prices.azure.com/api/retail/prices"
    "?api-version=2023-01-01-preview"
    "&$filter=priceType eq 'Consumption'"
)
GCP_PRICELIST_URL = (
    "https://cloudpricingcalculator.appspot.com/static/data/pricelist.json"
)

# ---------------------------------------------------------------------------
# HTTP settings
# ---------------------------------------------------------------------------
_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)
_MAX_AZURE_PAGES = 20  # safety cap for Azure pagination

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
    try:
        with open(_UPDATES_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "last_check": None,
            "checks": [],
            "new_services_found": {"aws": [], "azure": [], "gcp": []},
            "auto_added": {"aws": [], "azure": [], "gcp": []},
        }


def _write_state(state: dict[str, Any]) -> None:
    """Persist state to service_updates.json."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(_UPDATES_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, default=str)


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
    Load previously discovered services from the JSON data file.

    Returns a dict keyed by provider ("aws", "azure", "gcp"),
    each containing a list of service entry dicts.
    """
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
    """Fetch GCP service names from the pricing calculator pricelist."""
    logger.info("Fetching GCP pricelist ...")
    resp = client.get(GCP_PRICELIST_URL)
    resp.raise_for_status()
    data = resp.json()
    pricelist = data.get("gcp_price_list", data)

    services: set[str] = set()
    for key in pricelist:
        # Keys are typically like "CP-COMPUTEENGINE-VMIMAGE-..."
        # Extract a normalised service prefix
        parts = key.split("-")
        if len(parts) >= 2:
            services.add(parts[1] if parts[0] == "CP" else parts[0])
        else:
            services.add(key)

    logger.info("GCP: fetched %d unique service prefixes", len(services))
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

    fetchers = {
        "aws": _fetch_aws_services,
        "azure": _fetch_azure_services,
        "gcp": _fetch_gcp_services,
    }

    with httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
        for provider, fetch_fn in fetchers.items():
            try:
                remote_services = fetch_fn(client)
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


# ---------------------------------------------------------------------------
# Scheduler management
# ---------------------------------------------------------------------------


def start_scheduler() -> None:
    """Start the background scheduler (daily at 02:00 UTC)."""
    global _scheduler, _running  # noqa: PLW0603

    if _running and _scheduler is not None:
        logger.warning("Scheduler is already running.")
        return

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        run_update_now,
        trigger=CronTrigger(hour=2, minute=0, timezone="UTC"),
        id="cloud_service_update",
        name="Daily cloud service catalog update",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    _running = True
    logger.info("Scheduler started -- next run at 02:00 UTC daily.")


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
