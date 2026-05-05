"""Locust soak harness for Landing Zone SVG export (#597)."""

from __future__ import annotations

import json
import os
import resource
import time
from pathlib import Path
from typing import Any

from locust import HttpUser, constant_throughput, events, task
from locust.exception import StopUser

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + (b"\0" * 100)
SUMMARY_PATH = Path(os.getenv("LANDING_ZONE_SOAK_SUMMARY_PATH", "landing-zone-soak-summary.json"))
TARGET_RPS = int(os.getenv("LANDING_ZONE_TARGET_RPS", "100"))
MIN_RPS_RATIO = float(os.getenv("LANDING_ZONE_MIN_RPS_RATIO", "0.85"))
FAILURE_RATE_THRESHOLD = float(os.getenv("LANDING_ZONE_FAILURE_RATE", "0.001"))
MEMORY_CEILING_MB_PER_WORKER = int(os.getenv("LANDING_ZONE_MEMORY_CEILING_MB", "512"))
API_KEY = os.getenv("LANDING_ZONE_API_KEY") or os.getenv("ARCHMORPH_API_KEY")
_FIRST_EXPORT_STARTED_AT: float | None = None

LANDING_ZONE_ENDPOINTS = {
    "landing_zone_primary": {
        "method": "POST",
        "threshold_ms": 1500,
        "route": "/api/diagrams/{diagram_id}/export-diagram?format=landing-zone-svg&dr_variant=primary",
        "description": "Landing-zone SVG primary variant",
    },
    "landing_zone_dr": {
        "method": "POST",
        "threshold_ms": 3000,
        "route": "/api/diagrams/{diagram_id}/export-diagram?format=landing-zone-svg&dr_variant=dr",
        "description": "Landing-zone SVG DR variant",
    },
}


def _expect_success(response, name: str) -> None:
    if 200 <= response.status_code < 300:
        response.success()
        return
    response.failure(f"{name} returned HTTP {response.status_code}: {response.text[:240]}")


def _auth_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers: dict[str, str] = dict(extra or {})
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    return headers


def _remember_first_export_sample() -> None:
    global _FIRST_EXPORT_STARTED_AT
    if _FIRST_EXPORT_STARTED_AT is None:
        _FIRST_EXPORT_STARTED_AT = time.perf_counter()


def _worker_memory_mb() -> float:
    rss = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if os.uname().sysname == "Darwin":
        return rss / (1024 * 1024)
    return rss / 1024


class LandingZoneUser(HttpUser):
    """Exercise primary and DR ALZ exports against a primed diagram session."""

    wait_time = constant_throughput(float(os.getenv("LANDING_ZONE_USER_RPS", "1")))

    def on_start(self) -> None:
        self.export_capability: str | None = None
        self.diagram_id = self._upload_diagram()
        self._prime_analysis()

    def _upload_diagram(self) -> str:
        with self.client.post(
            "/api/projects/landing-zone-soak/diagrams",
            files={"file": ("aws.png", PNG_BYTES, "image/png")},
            headers=_auth_headers(),
            name="setup_upload_diagram",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"setup upload failed: HTTP {response.status_code} {response.text[:240]}")
                raise StopUser()
            payload = response.json()
            self.export_capability = payload.get("export_capability")
            response.success()
            return str(payload["diagram_id"])

    def _prime_analysis(self) -> None:
        with self.client.post(
            f"/api/diagrams/{self.diagram_id}/analyze",
            headers=_auth_headers(),
            name="setup_prime_analyze",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"setup analyze failed: HTTP {response.status_code} {response.text[:240]}")
                raise StopUser()
            self.export_capability = response.json().get("export_capability", self.export_capability)
            response.success()

    def _export_headers(self) -> dict[str, str]:
        if not self.export_capability:
            raise StopUser()
        return _auth_headers({"X-Export-Capability": self.export_capability})

    def _capture_next_capability(self, response) -> None:
        try:
            self.export_capability = response.json().get("export_capability", self.export_capability)
        except ValueError:
            pass

    @task(3)
    def landing_zone_primary(self) -> None:
        _remember_first_export_sample()
        with self.client.post(
            f"/api/diagrams/{self.diagram_id}/export-diagram?format=landing-zone-svg&dr_variant=primary",
            headers=self._export_headers(),
            name="landing_zone_primary",
            catch_response=True,
        ) as response:
            _expect_success(response, "landing_zone_primary")
            if 200 <= response.status_code < 300:
                self._capture_next_capability(response)

    @task(1)
    def landing_zone_dr(self) -> None:
        _remember_first_export_sample()
        with self.client.post(
            f"/api/diagrams/{self.diagram_id}/export-diagram?format=landing-zone-svg&dr_variant=dr",
            headers=self._export_headers(),
            name="landing_zone_dr",
            catch_response=True,
        ) as response:
            _expect_success(response, "landing_zone_dr")
            if 200 <= response.status_code < 300:
                self._capture_next_capability(response)


def _metric_value(stats, endpoint_name: str, value_name: str):
    entry = stats.get(endpoint_name, LANDING_ZONE_ENDPOINTS[endpoint_name]["method"])
    if entry is None or entry.num_requests == 0:
        return None
    if value_name == "p95_ms":
        return entry.get_response_time_percentile(0.95)
    if value_name == "avg_ms":
        return entry.avg_response_time
    if value_name == "max_ms":
        return entry.max_response_time
    if value_name == "failure_rate":
        return entry.num_failures / entry.num_requests
    return None


def _build_endpoint_summary(stats) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for endpoint_name, target in LANDING_ZONE_ENDPOINTS.items():
        entry = stats.get(endpoint_name, target["method"])
        samples = entry.num_requests if entry is not None else 0
        failures = entry.num_failures if entry is not None else 0
        p95_ms = _metric_value(stats, endpoint_name, "p95_ms")
        failure_rate = _metric_value(stats, endpoint_name, "failure_rate")
        passed = (
            samples > 0
            and p95_ms is not None
            and p95_ms < target["threshold_ms"]
            and failure_rate is not None
            and failure_rate < FAILURE_RATE_THRESHOLD
        )
        summary[endpoint_name] = {
            "description": target["description"],
            "route": target["route"],
            "method": target["method"],
            "samples": samples,
            "failures": failures,
            "failure_rate": failure_rate,
            "p95_ms": p95_ms,
            "avg_ms": _metric_value(stats, endpoint_name, "avg_ms"),
            "max_ms": _metric_value(stats, endpoint_name, "max_ms"),
            "threshold_ms": target["threshold_ms"],
            "passed": passed,
        }
    return summary


def _achieved_rps(endpoint_summary: dict[str, dict[str, Any]], elapsed_seconds: float) -> float:
    if elapsed_seconds <= 0:
        return 0.0
    return sum(values["samples"] for values in endpoint_summary.values()) / elapsed_seconds


def _print_summary(summary: dict[str, Any]) -> None:
    print("\nArchmorph Landing Zone soak summary")
    print(
        f"target_rps={summary['target_rps']} achieved_rps={summary['achieved_rps']:.2f} "
        f"min_rps={summary['minimum_rps']:.2f} failed={summary['failed']}"
    )
    for endpoint_name, values in summary["endpoints"].items():
        status = "PASS" if values["passed"] else "FAIL"
        print(
            f"{status} {endpoint_name}: p95={values['p95_ms']}ms "
            f"threshold={values['threshold_ms']}ms samples={values['samples']} failures={values['failures']}"
        )
    print("")


@events.quitting.add_listener
def enforce_landing_zone_slos(environment, **_kwargs) -> None:
    endpoint_summary = _build_endpoint_summary(environment.stats)
    elapsed_seconds = time.perf_counter() - _FIRST_EXPORT_STARTED_AT if _FIRST_EXPORT_STARTED_AT else 0.0
    achieved_rps = _achieved_rps(endpoint_summary, elapsed_seconds)
    minimum_rps = TARGET_RPS * MIN_RPS_RATIO
    memory_mb = _worker_memory_mb()
    failed = [name for name, values in endpoint_summary.items() if not values["passed"]]
    if achieved_rps < minimum_rps:
        failed.append("throughput")
    if memory_mb > MEMORY_CEILING_MB_PER_WORKER:
        failed.append("worker_memory")
    summary = {
        "target_rps": TARGET_RPS,
        "achieved_rps": achieved_rps,
        "minimum_rps": minimum_rps,
        "elapsed_seconds": elapsed_seconds,
        "failure_rate_threshold": FAILURE_RATE_THRESHOLD,
        "memory_ceiling_mb_per_worker": MEMORY_CEILING_MB_PER_WORKER,
        "worker_memory_mb": memory_mb,
        "failed": failed,
        "endpoints": endpoint_summary,
    }
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    _print_summary(summary)
    if failed:
        environment.process_exit_code = 1
