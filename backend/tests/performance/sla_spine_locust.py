"""Locust SLO gate for the Archmorph full value spine (#659)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from locust import HttpUser, constant_throughput, events, task
from locust.exception import StopUser

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + (b"\0" * 100)
SUMMARY_PATH = Path(os.getenv("SLO_SPINE_SUMMARY_PATH", "sla-spine-summary.json"))
FAILURE_RATE_THRESHOLD = float(os.getenv("SLO_SPINE_FAILURE_RATE", "0.01"))
TARGET_RPS = int(os.getenv("SLO_SPINE_TARGET_RPS", "30"))
MIN_RPS_RATIO = float(os.getenv("SLO_SPINE_MIN_RPS_RATIO", "0.85"))
API_HEADERS = {"X-API-Key": os.getenv("SLO_SPINE_API_KEY", "sla-spine-api-key")}
_RUN_STARTED_AT: float | None = None

SPINE_ENDPOINTS = {
    "analyze": {
        "method": "POST",
        "threshold_ms": 8000,
        "route": "/api/diagrams/{diagram_id}/analyze",
        "description": "Diagram analysis",
    },
    "generate_landing_zone": {
        "method": "POST",
        "threshold_ms": 1500,
        "route": "/api/diagrams/{diagram_id}/export-diagram?format=landing-zone-svg",
        "description": "Landing-zone SVG generation",
    },
    "generate_iac_terraform": {
        "method": "POST",
        "threshold_ms": 12000,
        "route": "/api/diagrams/{diagram_id}/generate?format=terraform&force=true",
        "description": "Terraform generation",
    },
    "generate_iac_bicep": {
        "method": "POST",
        "threshold_ms": 12000,
        "route": "/api/diagrams/{diagram_id}/generate?format=bicep&force=true",
        "description": "Bicep generation",
    },
    "drift_compare": {
        "method": "POST",
        "threshold_ms": 5000,
        "route": "/api/drift/baselines/{baseline_id}/compare",
        "description": "Drift baseline comparison",
    },
}

DESIGNED_STATE = {
    "nodes": [
        {"id": "web", "type": "static_web_app", "sku": "standard"},
        {"id": "api", "type": "container_app", "sku": "consumption"},
        {"id": "store", "type": "storage_account", "sku": "standard_lrs"},
    ]
}

LIVE_STATE = {
    "nodes": [
        {"resource_id": "web", "resource_type": "static_web_app", "sku": "standard"},
        {"resource_id": "api", "resource_type": "container_app", "sku": "dedicated"},
        {"resource_id": "store", "resource_type": "storage_account", "sku": "standard_lrs"},
    ]
}


def _post_json(user: HttpUser, path: str, payload: dict[str, Any], name: str):
    return user.client.post(
        path,
        data=json.dumps(payload),
        headers={"Content-Type": "application/json", **API_HEADERS},
        name=name,
        catch_response=True,
    )


def _expect_success(response, name: str) -> None:
    if 200 <= response.status_code < 300:
        response.success()
        return
    response.failure(f"{name} returned HTTP {response.status_code}: {response.text[:240]}")


class FullSpineUser(HttpUser):
    """Exercise analyze -> IaC -> ALZ -> drift compare at an aggregate 30 RPS in CI."""

    wait_time = constant_throughput(float(os.getenv("SLO_SPINE_USER_RPS", "1")))

    def on_start(self) -> None:
        self.diagram_id = self._upload_diagram()
        self.baseline_id = self._create_drift_baseline()
        self._prime_session()

    def _upload_diagram(self) -> str:
        with self.client.post(
            "/api/projects/sla-spine/diagrams",
            files={"file": ("aws.png", PNG_BYTES, "image/png")},
            headers=API_HEADERS,
            name="setup_upload_diagram",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"setup upload failed: HTTP {response.status_code} {response.text[:240]}")
                raise StopUser()
            payload = response.json()
            response.success()
            return str(payload["diagram_id"])

    def _prime_session(self) -> None:
        with self.client.post(
            f"/api/diagrams/{self.diagram_id}/analyze",
            headers=API_HEADERS,
            name="setup_prime_analyze",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"setup analyze failed: HTTP {response.status_code} {response.text[:240]}")
                raise StopUser()
            response.success()

    def _create_drift_baseline(self) -> str:
        payload = {
            "name": "SLA spine baseline",
            "designed_state": DESIGNED_STATE,
            "live_state": LIVE_STATE,
            "source": "sla-spine",
        }
        with _post_json(self, "/api/drift/baselines", payload, "setup_create_drift_baseline") as response:
            if response.status_code != 200:
                response.failure(f"setup drift baseline failed: HTTP {response.status_code} {response.text[:240]}")
                raise StopUser()
            data = response.json()
            response.success()
            return str(data["baseline_id"])

    @task(4)
    def analyze(self) -> None:
        with self.client.post(
            f"/api/diagrams/{self.diagram_id}/analyze",
            headers=API_HEADERS,
            name="analyze",
            catch_response=True,
        ) as response:
            _expect_success(response, "analyze")

    @task(2)
    def generate_iac_terraform(self) -> None:
        with self.client.post(
            f"/api/diagrams/{self.diagram_id}/generate?format=terraform&force=true",
            headers=API_HEADERS,
            name="generate_iac_terraform",
            catch_response=True,
        ) as response:
            _expect_success(response, "generate_iac_terraform")

    @task(2)
    def generate_iac_bicep(self) -> None:
        with self.client.post(
            f"/api/diagrams/{self.diagram_id}/generate?format=bicep&force=true",
            headers=API_HEADERS,
            name="generate_iac_bicep",
            catch_response=True,
        ) as response:
            _expect_success(response, "generate_iac_bicep")

    @task(1)
    def generate_landing_zone(self) -> None:
        with self.client.post(
            f"/api/diagrams/{self.diagram_id}/export-diagram?format=landing-zone-svg",
            headers=API_HEADERS,
            name="generate_landing_zone",
            catch_response=True,
        ) as response:
            _expect_success(response, "generate_landing_zone")

    @task(1)
    def drift_compare(self) -> None:
        with _post_json(
            self,
            f"/api/drift/baselines/{self.baseline_id}/compare",
            {"live_state": LIVE_STATE},
            "drift_compare",
        ) as response:
            _expect_success(response, "drift_compare")


def _metric_value(stats, endpoint_name: str, value_name: str):
    entry = stats.get(endpoint_name, SPINE_ENDPOINTS[endpoint_name]["method"])
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
    for endpoint_name, target in SPINE_ENDPOINTS.items():
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
    protected_samples = sum(values["samples"] for values in endpoint_summary.values())
    return protected_samples / elapsed_seconds


def _print_summary(summary: dict[str, Any]) -> None:
    print("\nArchmorph full-spine SLO summary")
    print(
        f"target_rps={summary['target_rps']} achieved_rps={summary['achieved_rps']:.2f} "
        f"min_rps={summary['minimum_rps']:.2f} failed={summary['failed']}"
    )
    for endpoint_name, values in summary["endpoints"].items():
        status = "PASS" if values["passed"] else "FAIL"
        print(
            f"{status} {endpoint_name}: "
            f"p95={values['p95_ms']}ms threshold={values['threshold_ms']}ms "
            f"samples={values['samples']} failures={values['failures']}"
        )
    print("")


@events.test_start.add_listener
def record_run_start(**_kwargs) -> None:
    global _RUN_STARTED_AT
    _RUN_STARTED_AT = time.perf_counter()


@events.quitting.add_listener
def enforce_spine_slos(environment, **_kwargs) -> None:
    endpoint_summary = _build_endpoint_summary(environment.stats)
    elapsed_seconds = time.perf_counter() - _RUN_STARTED_AT if _RUN_STARTED_AT else 0.0
    achieved_rps = _achieved_rps(endpoint_summary, elapsed_seconds)
    minimum_rps = TARGET_RPS * MIN_RPS_RATIO
    throughput_passed = achieved_rps >= minimum_rps
    failed = [name for name, values in endpoint_summary.items() if not values["passed"]]
    if not throughput_passed:
        failed.append("throughput")
    summary = {
        "target_rps": TARGET_RPS,
        "achieved_rps": achieved_rps,
        "minimum_rps": minimum_rps,
        "elapsed_seconds": elapsed_seconds,
        "throughput_passed": throughput_passed,
        "failure_rate_threshold": FAILURE_RATE_THRESHOLD,
        "failed": failed,
        "endpoints": endpoint_summary,
    }
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    _print_summary(summary)
    if failed:
        environment.process_exit_code = 1
