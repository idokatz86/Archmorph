"""Fake-kubectl chaos contracts for bounded renewable Kubernetes Leases."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "kubernetes_lease.py"
SPEC = importlib.util.spec_from_file_location("kubernetes_lease", SCRIPT)
assert SPEC and SPEC.loader
lease_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lease_module)


class FakeClock:
    def __init__(self) -> None:
        self.wall = datetime(2026, 7, 29, tzinfo=timezone.utc)
        self.monotonic_value = 0.0

    def now(self) -> datetime:
        return self.wall

    def monotonic(self) -> float:
        return self.monotonic_value

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)

    def advance(self, seconds: float) -> None:
        self.wall += timedelta(seconds=seconds)
        self.monotonic_value += seconds


class FakeKubectl:
    """ResourceVersion-aware fake for kubectl get/create/replace/delete."""

    def __init__(self) -> None:
        self.lease: dict | None = None
        self.resource_version = 0
        self.replace_conflicts = 0
        self.calls: list[list[str]] = []

    def _next_resource_version(self) -> str:
        self.resource_version += 1
        return str(self.resource_version)

    def run(self, arguments: list[str], *, payload: dict | None = None):
        self.calls.append(arguments)
        if arguments[:3] == ["get", "lease", "release-lock"]:
            if self.lease is None:
                raise lease_module.KubectlError("not found", stderr="NotFound")
            return CompletedProcess(
                arguments, 0, stdout=json.dumps(self.lease), stderr=""
            )
        if arguments[:3] == ["create", "-f", "-"]:
            if self.lease is not None:
                raise lease_module.KubectlError("exists", stderr="AlreadyExists")
            assert payload is not None
            self.lease = deepcopy(payload)
            self.lease["metadata"]["resourceVersion"] = self._next_resource_version()
            self.lease["metadata"]["creationTimestamp"] = self.lease["spec"][
                "acquireTime"
            ]
            return CompletedProcess(arguments, 0, stdout="created", stderr="")
        if arguments[:3] == ["replace", "-f", "-"]:
            assert payload is not None
            if self.replace_conflicts:
                self.replace_conflicts -= 1
                raise lease_module.KubectlError("conflict", stderr="Conflict")
            if self.lease is None or payload["metadata"].get(
                "resourceVersion"
            ) != self.lease["metadata"].get("resourceVersion"):
                raise lease_module.KubectlError(
                    "conflict", stderr="object has been modified"
                )
            creation = self.lease["metadata"]["creationTimestamp"]
            self.lease = deepcopy(payload)
            self.lease["metadata"]["resourceVersion"] = self._next_resource_version()
            self.lease["metadata"]["creationTimestamp"] = creation
            return CompletedProcess(arguments, 0, stdout="replaced", stderr="")
        raise AssertionError(f"Unexpected fake kubectl call: {arguments}")


def _client(fake: FakeKubectl, clock: FakeClock, holder: str):
    client = lease_module.LeaseClient(
        namespace="archmorph",
        name="release-lock",
        holder=holder,
        duration_seconds=30,
        clock_skew_seconds=5,
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    client._run = fake.run
    return client


def test_acquire_sets_standard_holder_timestamps_duration_and_resource_version():
    fake = FakeKubectl()
    clock = FakeClock()
    acquired = _client(fake, clock, "run-a").acquire(wait_seconds=0, retry_seconds=1)

    assert acquired["apiVersion"] == "coordination.k8s.io/v1"
    assert acquired["spec"]["holderIdentity"] == "run-a"
    assert acquired["spec"]["leaseDurationSeconds"] == 30
    assert acquired["spec"]["acquireTime"] == acquired["spec"]["renewTime"]
    assert acquired["metadata"]["resourceVersion"] == "1"


def test_live_holder_is_not_stolen_during_bounded_contention_or_clock_skew():
    fake = FakeKubectl()
    clock = FakeClock()
    _client(fake, clock, "run-a").acquire(wait_seconds=0, retry_seconds=1)
    clock.advance(30)

    with pytest.raises(lease_module.LeaseBusy, match="run-a"):
        _client(fake, clock, "run-b").acquire(wait_seconds=4, retry_seconds=1)

    assert fake.lease["spec"]["holderIdentity"] == "run-a"


def test_expired_holder_is_taken_over_with_resource_version_cas():
    fake = FakeKubectl()
    clock = FakeClock()
    _client(fake, clock, "run-a").acquire(wait_seconds=0, retry_seconds=1)
    clock.advance(36)

    acquired = _client(fake, clock, "run-b").acquire(wait_seconds=0, retry_seconds=1)

    assert acquired["spec"]["holderIdentity"] == "run-b"
    assert acquired["spec"]["leaseTransitions"] == 1
    assert acquired["spec"]["acquireTime"] == acquired["spec"]["renewTime"]


def test_takeover_retries_kubernetes_api_cas_conflict_within_bound():
    fake = FakeKubectl()
    clock = FakeClock()
    _client(fake, clock, "run-a").acquire(wait_seconds=0, retry_seconds=1)
    clock.advance(36)
    fake.replace_conflicts = 1

    acquired = _client(fake, clock, "run-b").acquire(wait_seconds=2, retry_seconds=1)

    assert acquired["spec"]["holderIdentity"] == "run-b"
    assert fake.replace_conflicts == 0


def test_periodic_renewal_preserves_acquire_time_and_extends_renew_time():
    fake = FakeKubectl()
    clock = FakeClock()
    client = _client(fake, clock, "run-a")
    acquired = client.acquire(wait_seconds=0, retry_seconds=1)
    clock.advance(10)

    renewed = client.renew()

    assert renewed["spec"]["acquireTime"] == acquired["spec"]["acquireTime"]
    assert renewed["spec"]["renewTime"] != acquired["spec"]["renewTime"]
    assert renewed["spec"]["holderIdentity"] == "run-a"


def test_renewal_retries_api_conflicts_only_within_bound():
    fake = FakeKubectl()
    clock = FakeClock()
    client = _client(fake, clock, "run-a")
    client.acquire(wait_seconds=0, retry_seconds=1)
    fake.replace_conflicts = 2

    assert client.renew(max_conflicts=3)["spec"]["holderIdentity"] == "run-a"

    fake.replace_conflicts = 2
    with pytest.raises(lease_module.LeaseError, match="conflict bound"):
        client.renew(max_conflicts=1)


def test_lost_ownership_cannot_be_renewed_or_released():
    fake = FakeKubectl()
    clock = FakeClock()
    client = _client(fake, clock, "run-a")
    client.acquire(wait_seconds=0, retry_seconds=1)
    fake.lease["spec"]["holderIdentity"] = "run-b"

    with pytest.raises(lease_module.LostOwnership, match="changed"):
        client.renew()
    assert client.release() is False
    assert fake.lease is not None


def test_sigkill_equivalent_without_cleanup_expires_and_recovers_stale_lease():
    fake = FakeKubectl()
    clock = FakeClock()
    abandoned = _client(fake, clock, "killed-runner")
    abandoned.acquire(wait_seconds=0, retry_seconds=1)
    # No release/EXIT trap runs: only standards-compliant Lease expiry recovers it.
    clock.advance(36)

    recovered = _client(fake, clock, "recovery-runner").acquire(
        wait_seconds=0,
        retry_seconds=1,
    )

    assert recovered["spec"]["holderIdentity"] == "recovery-runner"


def test_release_uses_owned_resource_version_and_allows_immediate_reacquisition():
    fake = FakeKubectl()
    clock = FakeClock()
    client = _client(fake, clock, "run-a")
    client.acquire(wait_seconds=0, retry_seconds=1)
    owned_resource_version = fake.lease["metadata"]["resourceVersion"]

    assert client.release() is True
    assert fake.lease["spec"]["holderIdentity"] == ""
    assert fake.lease["spec"]["leaseDurationSeconds"] == 1
    assert fake.lease["metadata"]["resourceVersion"] != owned_resource_version

    acquired = _client(fake, clock, "run-b").acquire(wait_seconds=0, retry_seconds=1)
    assert acquired["spec"]["holderIdentity"] == "run-b"


def test_release_cas_conflict_never_clears_a_newer_lease_record():
    fake = FakeKubectl()
    clock = FakeClock()
    client = _client(fake, clock, "run-a")
    client.acquire(wait_seconds=0, retry_seconds=1)
    fake.replace_conflicts = 1

    assert client.release() is False
    assert fake.lease["spec"]["holderIdentity"] == "run-a"
