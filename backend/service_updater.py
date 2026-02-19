"""
Daily Cloud Service Catalog Updater

Periodically fetches service catalogs from AWS, Azure, and GCP pricing APIs,
compares them against the local catalogs, and tracks new/changed services.

Uses APScheduler BackgroundScheduler to run updates every 24 hours at 2:00 AM UTC.
"""

import json
import logging
import os
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
_UPDATES_FILE = _DATA_DIR / "service_updates.json"

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
# Scheduler singleton
# ---------------------------------------------------------------------------
_scheduler: Optional[BackgroundScheduler] = None
_running: bool = False

# ---------------------------------------------------------------------------
# Helpers – persistent state
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
        }


def _write_state(state: dict[str, Any]) -> None:
    """Persist state to service_updates.json."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(_UPDATES_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, default=str)


# ---------------------------------------------------------------------------
# Local catalog loaders
# ---------------------------------------------------------------------------

def _load_local_catalog(module_name: str) -> set[str]:
    """
    Dynamically import a services module and return the set of service names
    it currently knows about.  Works for aws_services, azure_services, and
    gcp_services which expose either an ``SERVICES`` dict/list or a
    ``get_services()`` helper.
    """
    import importlib

    try:
        module = importlib.import_module(f"services.{module_name}")
    except ModuleNotFoundError:
        logger.warning("Could not import services.%s – treating catalog as empty", module_name)
        return set()

    # Try common attribute names used in the codebase
    for attr in ("SERVICES", "services", "SERVICE_MAP", "service_map", "CATALOG"):
        obj = getattr(module, attr, None)
        if obj is not None:
            if isinstance(obj, dict):
                return set(obj.keys())
            if isinstance(obj, (list, set, tuple)):
                return {str(s) for s in obj}

    # Fallback: look for a callable that returns services
    for func_name in ("get_services", "list_services"):
        func = getattr(module, func_name, None)
        if callable(func):
            result = func()
            if isinstance(result, dict):
                return set(result.keys())
            if isinstance(result, (list, set, tuple)):
                return {str(s) for s in result}

    logger.warning("No recognisable catalog found in services.%s", module_name)
    return set()


# ---------------------------------------------------------------------------
# Provider fetchers
# ---------------------------------------------------------------------------

def _fetch_aws_services(client: httpx.Client) -> set[str]:
    """Fetch the AWS service catalog from the pricing index."""
    logger.info("Fetching AWS service index …")
    resp = client.get(AWS_INDEX_URL)
    resp.raise_for_status()
    data = resp.json()
    offers = data.get("offers", {})
    services = set(offers.keys())
    logger.info("AWS: fetched %d services", len(services))
    return services


def _fetch_azure_services(client: httpx.Client) -> set[str]:
    """Fetch Azure service names from the retail prices API (paginated)."""
    logger.info("Fetching Azure service names …")
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

    logger.info("Azure: fetched %d unique service names (%d pages)", len(services), page)
    return services


def _fetch_gcp_services(client: httpx.Client) -> set[str]:
    """Fetch GCP service names from the pricing calculator pricelist."""
    logger.info("Fetching GCP pricelist …")
    resp = client.get(GCP_PRICELIST_URL)
    resp.raise_for_status()
    data = resp.json()
    pricelist = data.get("gcp_price_list", data)

    services: set[str] = set()
    for key in pricelist:
        # Keys are typically like "CP-COMPUTEENGINE-VMIMAGE-…"
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

def run_update_now() -> dict[str, Any]:
    """
    Execute an immediate service catalog update for all three providers.

    Returns a summary dict with timestamps and lists of new services found.
    If a single provider fails the remaining providers are still processed.
    """
    logger.info("Starting cloud service catalog update …")
    timestamp = datetime.now(timezone.utc).isoformat()

    provider_results: dict[str, list[str]] = {"aws": [], "azure": [], "gcp": []}
    errors: dict[str, str] = {}

    fetchers = {
        "aws": (_fetch_aws_services, "aws_services"),
        "azure": (_fetch_azure_services, "azure_services"),
        "gcp": (_fetch_gcp_services, "gcp_services"),
    }

    with httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
        for provider, (fetch_fn, module_name) in fetchers.items():
            try:
                remote_services = fetch_fn(client)
                local_services = _load_local_catalog(module_name)
                new_services = sorted(remote_services - local_services)

                if new_services:
                    logger.info(
                        "%s: %d new service(s) detected: %s",
                        provider.upper(),
                        len(new_services),
                        ", ".join(new_services[:10])
                        + (" …" if len(new_services) > 10 else ""),
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
                logger.error("%s fetch failed: %s", provider.upper(), msg, exc_info=True)
                errors[provider] = msg

    # Build check record
    check_record: dict[str, Any] = {
        "timestamp": timestamp,
        "new_services": provider_results,
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
    logger.info("Scheduler started – next run at 02:00 UTC daily.")


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
    args = parser.parse_args()

    if args.run_now:
        result = run_update_now()
        print(json.dumps(result, indent=2, default=str))
    else:
        import signal
        import threading

        stop_event = threading.Event()

        def _handle_signal(sig: int, _frame: Any) -> None:
            logger.info("Received signal %s – shutting down …", sig)
            stop_scheduler()
            stop_event.set()

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        start_scheduler()
        # Run an initial update immediately on startup
        run_update_now()
        stop_event.wait()
