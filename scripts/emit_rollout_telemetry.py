#!/usr/bin/env python3
"""Emit secret-free rollout evidence to Application Insights via Azure Monitor."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlsplit


_ALLOWED_EVENTS = {
    "migration_started",
    "migration_failed",
    "migration_timed_out",
    "migration_succeeded",
}


def _connection_properties() -> dict[str, str]:
    connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
    return dict(
        item.split("=", 1)
        for item in connection_string.split(";")
        if "=" in item
    )


def _instrumentation_key() -> str:
    properties = _connection_properties()
    key = properties.get("InstrumentationKey", "").strip()
    if not key:
        raise ValueError("Application Insights connection string is missing InstrumentationKey")
    return key


def _ingestion_url() -> str:
    endpoint = _connection_properties().get("IngestionEndpoint", "").strip().rstrip("/")
    parsed = urlsplit(endpoint)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(
        (".applicationinsights.azure.com", ".applicationinsights.azure.cn")
    ):
        raise ValueError("Application Insights connection string has an invalid ingestion endpoint")
    return endpoint + "/v2/track"


def build_envelope(*, event: str, run_id: str, execution: str, image_digest: str) -> dict:
    if event not in _ALLOWED_EVENTS:
        raise ValueError("unsupported rollout telemetry event")
    if (
        not run_id
        or not execution
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest)
    ):
        raise ValueError("run, execution, and immutable digest evidence are required")
    return {
        "name": "Microsoft.ApplicationInsights.Event",
        "time": datetime.now(timezone.utc).isoformat(),
        "iKey": _instrumentation_key(),
        "data": {
            "baseType": "EventData",
            "baseData": {
                "ver": 2,
                "name": event,
                "properties": {
                    "application": "archmorph",
                    "owner": "platform-engineering",
                    "workflow_run_id": run_id,
                    "execution": execution,
                    "image_digest": image_digest,
                },
            },
        },
    }


def emit(envelope: dict) -> None:
    request = Request(
        _ingestion_url(),
        data=json.dumps(envelope).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=15) as response:  # noqa: S310 - fixed Azure endpoint
        if response.status not in {200, 206}:
            raise RuntimeError(f"telemetry ingestion returned HTTP {response.status}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True, choices=sorted(_ALLOWED_EVENTS))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--execution", required=True)
    parser.add_argument("--image-digest", required=True)
    args = parser.parse_args()
    _ingestion_url()
    emit(
        build_envelope(
            event=args.event,
            run_id=args.run_id,
            execution=args.execution,
            image_digest=args.image_digest,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())