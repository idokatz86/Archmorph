#!/usr/bin/env python3
"""Emit secret-free rollout evidence to Application Insights via Azure Monitor."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


_ALLOWED_EVENTS = {
    "migration_started",
    "migration_failed",
    "migration_timed_out",
    "migration_succeeded",
    "migration_quiescence_started",
    "migration_quiesced",
    "migration_recovery_required",
    "bridge_customer_degraded",
}
_MAX_ATTEMPTS = 3
_REQUEST_TIMEOUT_SECONDS = 5


@contextmanager
def _attempt_deadline(seconds: float):
    """Bound DNS, TLS, and HTTP work when running in the CLI main thread."""
    if not hasattr(signal, "setitimer") or threading.current_thread() is not threading.main_thread():
        yield
        return

    def timeout_handler(_signum, _frame):
        raise TimeoutError("telemetry attempt exceeded its deadline")

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)


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


def emit(envelope: dict, *, timeout: float = _REQUEST_TIMEOUT_SECONDS) -> None:
    request = Request(
        _ingestion_url(),
        data=json.dumps(envelope).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed Azure endpoint
        if response.status not in {200, 206}:
            raise RuntimeError(f"telemetry ingestion returned HTTP {response.status}")


def _local_event(*, event: str, run_id: str, execution: str, image_digest: str) -> dict:
    if event not in _ALLOWED_EVENTS:
        raise ValueError("unsupported rollout telemetry event")
    if not run_id or not execution or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest):
        raise ValueError("run, execution, and immutable digest evidence are required")
    return {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "application": "archmorph",
        "owner": "platform-engineering",
        "workflow_run_id": run_id,
        "execution": execution,
        "image_digest": image_digest,
    }


def _append_local_evidence(path: Path, record: dict) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        existing + json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def emit_best_effort(
    *,
    event: str,
    run_id: str,
    execution: str,
    image_digest: str,
    evidence_output: Path,
    max_attempts: int = _MAX_ATTEMPTS,
    request_timeout: float = _REQUEST_TIMEOUT_SECONDS,
) -> dict:
    """Always return after bounded delivery attempts; local evidence is authoritative."""
    if max_attempts < 1 or request_timeout <= 0:
        raise ValueError("telemetry delivery bounds are invalid")
    local = _local_event(
        event=event,
        run_id=run_id,
        execution=execution,
        image_digest=image_digest,
    )
    _append_local_evidence(
        evidence_output,
        {**local, "delivery_status": "pending", "attempt": 0},
    )
    last_error_class = ""
    for attempt in range(1, max_attempts + 1):
        try:
            envelope = build_envelope(
                event=event,
                run_id=run_id,
                execution=execution,
                image_digest=image_digest,
            )
            with _attempt_deadline(request_timeout + 1):
                emit(envelope, timeout=request_timeout)
        except Exception as error:  # best-effort telemetry must never gate migration safety
            last_error_class = type(error).__name__
            if attempt < max_attempts:
                time.sleep(2 ** (attempt - 1))
            continue
        result = {**local, "delivery_status": "delivered", "attempt": attempt}
        _append_local_evidence(evidence_output, result)
        return result
    result = {
        **local,
        "delivery_status": "failed",
        "attempt": max_attempts,
        "error_class": last_error_class or "TelemetryDeliveryError",
    }
    _append_local_evidence(evidence_output, result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--execution", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument(
        "--evidence-output",
        type=Path,
        default=Path("rollout-telemetry.ndjson"),
    )
    args = parser.parse_args(argv)
    try:
        result = emit_best_effort(
            event=args.event,
            run_id=args.run_id,
            execution=args.execution,
            image_digest=args.image_digest,
            evidence_output=args.evidence_output,
        )
        print(
            json.dumps(
                {
                    "event": result["event"],
                    "delivery_status": result["delivery_status"],
                    "attempt": result["attempt"],
                    "error_class": result.get("error_class", ""),
                },
                sort_keys=True,
            )
        )
    except Exception as error:
        print(
            json.dumps(
                {
                    "event": args.event,
                    "delivery_status": "local_evidence_failed",
                    "error_class": type(error).__name__,
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
