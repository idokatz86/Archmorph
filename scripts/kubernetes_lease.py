#!/usr/bin/env python3
"""Bounded, renewable Kubernetes Lease ownership using kubectl CAS operations."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
import signal
import subprocess
import sys
import time
from typing import Any, Callable


class LeaseError(RuntimeError):
    """Base Lease coordination failure."""


class LeaseBusy(LeaseError):
    """A live holder owns the Lease for the complete bounded wait."""


class LostOwnership(LeaseError):
    """The caller no longer owns the Lease."""


class KubectlError(LeaseError):
    def __init__(self, message: str, *, stderr: str = "", returncode: int = 1) -> None:
        super().__init__(message)
        self.stderr = stderr
        self.returncode = returncode


class LeaseClient:
    def __init__(
        self,
        *,
        namespace: str,
        name: str,
        holder: str,
        duration_seconds: int,
        clock_skew_seconds: int = 5,
        kubectl: str = "kubectl",
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if not namespace or not name or not holder:
            raise ValueError("Lease namespace, name, and holder identity are required")
        if duration_seconds < 15:
            raise ValueError("leaseDurationSeconds must be at least 15")
        if clock_skew_seconds < 0 or clock_skew_seconds >= duration_seconds:
            raise ValueError("Lease clock skew allowance is invalid")
        self.namespace = namespace
        self.name = name
        self.holder = holder
        self.duration_seconds = duration_seconds
        self.clock_skew_seconds = clock_skew_seconds
        self.kubectl = kubectl
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep or time.sleep

    def _run(
        self,
        arguments: list[str],
        *,
        payload: dict[str, Any] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [self.kubectl, "-n", self.namespace, *arguments],
            input=(json.dumps(payload) if payload is not None else None),
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        if result.returncode != 0:
            raise KubectlError(
                f"kubectl Lease operation failed: {' '.join(arguments[:3])}",
                stderr=result.stderr,
                returncode=result.returncode,
            )
        return result

    @staticmethod
    def _is_not_found(error: KubectlError) -> bool:
        message = error.stderr.lower()
        return "notfound" in message or "not found" in message

    @staticmethod
    def _is_conflict(error: KubectlError) -> bool:
        message = error.stderr.lower()
        return any(
            marker in message
            for marker in (
                "conflict",
                "alreadyexists",
                "already exists",
                "object has been modified",
            )
        )

    def get(self) -> dict[str, Any] | None:
        try:
            result = self._run(["get", "lease", self.name, "-o", "json"])
        except KubectlError as error:
            if self._is_not_found(error):
                return None
            raise
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise LeaseError("Kubernetes Lease response is not valid JSON") from error
        if not isinstance(payload, dict):
            raise LeaseError("Kubernetes Lease response is not an object")
        return payload

    @staticmethod
    def _timestamp(value: object) -> datetime:
        if not isinstance(value, str) or not value:
            raise LeaseError("Kubernetes Lease has no provable renewal timestamp")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise LeaseError("Kubernetes Lease renewal timestamp is invalid") from error
        if parsed.tzinfo is None:
            raise LeaseError("Kubernetes Lease renewal timestamp has no timezone")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _formatted(moment: datetime) -> str:
        return (
            moment.astimezone(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )

    def _expired(self, lease: dict[str, Any], *, now: datetime) -> bool:
        spec = lease.get("spec")
        metadata = lease.get("metadata")
        if not isinstance(spec, dict) or not isinstance(metadata, dict):
            raise LeaseError("Kubernetes Lease metadata/spec is malformed")
        raw_duration = spec.get("leaseDurationSeconds")
        if (
            isinstance(raw_duration, bool)
            or not isinstance(raw_duration, int)
            or raw_duration < 1
        ):
            raise LeaseError("Kubernetes Lease duration is invalid")
        renewed = (
            spec.get("renewTime")
            or spec.get("acquireTime")
            or metadata.get("creationTimestamp")
        )
        expiry = self._timestamp(renewed) + timedelta(
            seconds=raw_duration + self.clock_skew_seconds
        )
        return now >= expiry

    def _document(
        self,
        *,
        resource_version: str | None,
        acquire_time: str,
        renew_time: str,
        transitions: int,
    ) -> dict[str, Any]:
        metadata: dict[str, str] = {"name": self.name, "namespace": self.namespace}
        if resource_version:
            metadata["resourceVersion"] = resource_version
        return {
            "apiVersion": "coordination.k8s.io/v1",
            "kind": "Lease",
            "metadata": metadata,
            "spec": {
                "holderIdentity": self.holder,
                "leaseDurationSeconds": self.duration_seconds,
                "acquireTime": acquire_time,
                "renewTime": renew_time,
                "leaseTransitions": transitions,
            },
        }

    def _create(self, *, now: datetime) -> bool:
        timestamp = self._formatted(now)
        try:
            self._run(
                ["create", "-f", "-"],
                payload=self._document(
                    resource_version=None,
                    acquire_time=timestamp,
                    renew_time=timestamp,
                    transitions=0,
                ),
            )
        except KubectlError as error:
            if self._is_conflict(error):
                return False
            raise
        return True

    def _replace(
        self,
        lease: dict[str, Any],
        *,
        now: datetime,
        takeover: bool,
    ) -> bool:
        metadata = lease.get("metadata")
        spec = lease.get("spec")
        if not isinstance(metadata, dict) or not isinstance(spec, dict):
            raise LeaseError("Kubernetes Lease metadata/spec is malformed")
        resource_version = str(metadata.get("resourceVersion") or "")
        if not resource_version:
            raise LeaseError("Kubernetes Lease has no resourceVersion for CAS")
        previous_acquire = str(spec.get("acquireTime") or "")
        if not takeover:
            self._timestamp(previous_acquire)
        transitions = spec.get("leaseTransitions", 0)
        if (
            isinstance(transitions, bool)
            or not isinstance(transitions, int)
            or transitions < 0
        ):
            raise LeaseError("Kubernetes Lease transition count is invalid")
        timestamp = self._formatted(now)
        document = self._document(
            resource_version=resource_version,
            acquire_time=timestamp if takeover else previous_acquire,
            renew_time=timestamp,
            transitions=transitions + (1 if takeover else 0),
        )
        try:
            self._run(["replace", "-f", "-"], payload=document)
        except KubectlError as error:
            if self._is_conflict(error):
                return False
            raise
        return True

    def acquire(self, *, wait_seconds: float, retry_seconds: float) -> dict[str, Any]:
        if wait_seconds < 0 or retry_seconds <= 0:
            raise ValueError("Lease wait and retry intervals are invalid")
        deadline = self._monotonic() + wait_seconds
        while True:
            now = self._now()
            lease = self.get()
            if lease is None:
                if self._create(now=now):
                    acquired = self.get()
                    if acquired is None:
                        raise LeaseError(
                            "created Lease disappeared before ownership verification"
                        )
                    if acquired.get("spec", {}).get("holderIdentity") != self.holder:
                        raise LostOwnership("created Lease is owned by another holder")
                    return acquired
            else:
                spec = lease.get("spec")
                holder = spec.get("holderIdentity") if isinstance(spec, dict) else None
                if holder == self.holder:
                    if self._replace(lease, now=now, takeover=False):
                        acquired = self.get()
                        if (
                            acquired is None
                            or acquired.get("spec", {}).get("holderIdentity")
                            != self.holder
                        ):
                            raise LostOwnership("Lease disappeared after reacquisition")
                        return acquired
                elif not holder or self._expired(lease, now=now):
                    if self._replace(lease, now=now, takeover=True):
                        acquired = self.get()
                        if (
                            acquired is None
                            or acquired.get("spec", {}).get("holderIdentity")
                            != self.holder
                        ):
                            raise LostOwnership("Lease takeover was not retained")
                        return acquired
            if self._monotonic() >= deadline:
                owner = "unknown"
                if lease and isinstance(lease.get("spec"), dict):
                    owner = str(lease["spec"].get("holderIdentity") or "unknown")
                raise LeaseBusy(f"Lease is owned by live holder {owner}")
            self._sleep(min(retry_seconds, max(0.0, deadline - self._monotonic())))

    def renew(self, *, max_conflicts: int = 3) -> dict[str, Any]:
        if max_conflicts < 1:
            raise ValueError("Lease renewal conflict bound must be positive")
        for _attempt in range(max_conflicts):
            lease = self.get()
            if lease is None:
                raise LostOwnership("Lease disappeared before renewal")
            spec = lease.get("spec")
            if not isinstance(spec, dict) or spec.get("holderIdentity") != self.holder:
                raise LostOwnership("Lease holder identity changed before renewal")
            if self._replace(lease, now=self._now(), takeover=False):
                renewed = self.get()
                if (
                    renewed is None
                    or renewed.get("spec", {}).get("holderIdentity") != self.holder
                ):
                    raise LostOwnership("Lease ownership was lost after renewal")
                return renewed
        raise LeaseError("Lease renewal exceeded the Kubernetes API conflict bound")

    def release(self) -> bool:
        lease = self.get()
        if lease is None:
            return False
        metadata = lease.get("metadata")
        spec = lease.get("spec")
        if not isinstance(metadata, dict) or not isinstance(spec, dict):
            raise LeaseError("Kubernetes Lease metadata/spec is malformed")
        if spec.get("holderIdentity") != self.holder:
            return False
        resource_version = str(metadata.get("resourceVersion") or "")
        if not resource_version:
            raise LeaseError("Kubernetes Lease has no resourceVersion for release CAS")
        transitions = spec.get("leaseTransitions", 0)
        if isinstance(transitions, bool) or not isinstance(transitions, int):
            raise LeaseError("Kubernetes Lease transition count is invalid")
        timestamp = self._formatted(self._now())
        release_record = {
            "apiVersion": "coordination.k8s.io/v1",
            "kind": "Lease",
            "metadata": {
                "name": self.name,
                "namespace": self.namespace,
                "resourceVersion": resource_version,
            },
            "spec": {
                "holderIdentity": "",
                "leaseDurationSeconds": 1,
                "acquireTime": timestamp,
                "renewTime": timestamp,
                "leaseTransitions": transitions,
            },
        }
        try:
            self._run(["replace", "-f", "-"], payload=release_record)
        except KubectlError as error:
            if self._is_conflict(error) or self._is_not_found(error):
                return False
            raise
        return True


def _client(args: argparse.Namespace) -> LeaseClient:
    return LeaseClient(
        namespace=args.namespace,
        name=args.name,
        holder=args.holder,
        duration_seconds=args.duration_seconds,
        clock_skew_seconds=args.clock_skew_seconds,
        kubectl=args.kubectl,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--holder", required=True)
    parser.add_argument("--duration-seconds", type=int, default=60)
    parser.add_argument("--clock-skew-seconds", type=int, default=5)
    parser.add_argument("--kubectl", default=os.environ.get("KUBECTL", "kubectl"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    acquire = subparsers.add_parser("acquire")
    acquire.add_argument("--wait-seconds", type=float, default=120)
    acquire.add_argument("--retry-seconds", type=float, default=2)

    renew = subparsers.add_parser("renew")
    renew.add_argument("--max-conflicts", type=int, default=3)

    heartbeat = subparsers.add_parser("heartbeat")
    heartbeat.add_argument("--interval-seconds", type=float, default=15)
    heartbeat.add_argument("--max-failures", type=int, default=3)
    heartbeat.add_argument("--parent-pid", type=int, required=True)

    subparsers.add_parser("release")
    args = parser.parse_args()
    client = _client(args)
    if args.command == "acquire":
        print(
            json.dumps(
                client.acquire(
                    wait_seconds=args.wait_seconds,
                    retry_seconds=args.retry_seconds,
                ),
                sort_keys=True,
            )
        )
    elif args.command == "renew":
        print(
            json.dumps(client.renew(max_conflicts=args.max_conflicts), sort_keys=True)
        )
    elif args.command == "heartbeat":
        if args.interval_seconds <= 0 or args.max_failures < 1:
            raise ValueError("Lease heartbeat bounds are invalid")
        failures = 0
        while True:
            time.sleep(args.interval_seconds)
            try:
                os.kill(args.parent_pid, 0)
            except ProcessLookupError:
                return 0
            try:
                client.renew()
                failures = 0
            except (LeaseError, KubectlError) as error:
                failures += 1
                print(f"Lease heartbeat failure {failures}: {error}", file=sys.stderr)
                if failures >= args.max_failures:
                    os.kill(args.parent_pid, signal.SIGTERM)
                    return 2
    else:
        print("released" if client.release() else "not-owner")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LeaseBusy as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(3) from error
    except LostOwnership as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(4) from error
