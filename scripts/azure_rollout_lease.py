#!/usr/bin/env python3
"""Coordinate production rollouts with renewable Azure Blob leases.

GitHub concurrency is deliberately not the source of truth.  A normal rollout
owns one renewable Blob lease.  An emergency rollback first publishes its own
renewable intent Blob, then waits for deterministic priority and exclusive
ownership.  Runner loss expires both leases without a privileged break action.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Callable, Protocol


_ACCOUNT_RE = re.compile(r"^[a-z0-9]{3,24}$")
_CONTAINER_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$")
_SCOPE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
_POSITIVE_INTEGER_RE = re.compile(r"^[1-9][0-9]*$")
_INTENT_BASENAME_RE = re.compile(r"^(?P<run>[0-9]{20})-(?P<attempt>[0-9]{6})\.json$")
_DEFAULT_DURATION_SECONDS = 60


class CoordinationError(RuntimeError):
    """Base error for fail-closed rollout coordination."""


class RollbackPriority(CoordinationError):
    """A live emergency rollback intent requires a deploy/Helm run to yield."""


class LeaseBusy(CoordinationError):
    """Another live owner retained the shared rollout lease for the wait bound."""


class LostLease(CoordinationError):
    """The caller can no longer prove ownership of a required lease."""


class AzureCliError(CoordinationError):
    def __init__(self, message: str, *, stderr: str = "", returncode: int = 1) -> None:
        super().__init__(message)
        self.stderr = stderr
        self.returncode = returncode


@dataclass(frozen=True)
class BlobRecord:
    name: str
    lease_status: str
    lease_state: str
    last_modified_epoch: float | None = None


@dataclass(frozen=True, order=True)
class RollbackIntent:
    run_id: int
    run_attempt: int
    blob_name: str


class BlobLeaseStorage(Protocol):
    def ensure_blob(self, name: str, content: bytes) -> None: ...

    def refresh_blob(self, name: str, content: bytes) -> bool: ...

    def list_blobs(self, prefix: str) -> list[BlobRecord]: ...

    def acquire(self, name: str, duration_seconds: int) -> str | None: ...

    def renew(self, name: str, lease_id: str) -> None: ...

    def release(self, name: str, lease_id: str) -> bool: ...

    def delete(self, name: str) -> bool: ...


class AzureCliBlobLeaseStorage:
    """Passwordless Azure CLI adapter; no account keys or SAS tokens are used."""

    def __init__(self, *, account: str, container: str, executable: str = "az") -> None:
        if not _ACCOUNT_RE.fullmatch(account):
            raise ValueError("rollout coordination account name is invalid")
        if not _CONTAINER_RE.fullmatch(container):
            raise ValueError("rollout coordination container name is invalid")
        self.account = account
        self.container = container
        self.executable = executable

    def _run(self, arguments: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                [
                    self.executable,
                    "storage",
                    "blob",
                    *arguments,
                    "--account-name",
                    self.account,
                    "--container-name",
                    self.container,
                    "--auth-mode",
                    "login",
                    "--only-show-errors",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise AzureCliError(
                "Azure Blob coordination command did not complete"
            ) from error
        if result.returncode != 0:
            raise AzureCliError(
                "Azure Blob coordination command failed",
                stderr=result.stderr,
                returncode=result.returncode,
            )
        return result

    @staticmethod
    def _is_conflict(error: AzureCliError) -> bool:
        message = error.stderr.lower()
        return any(
            marker in message
            for marker in (
                "leasealreadypresent",
                "leaseidmissing",
                "leaseidmismatch",
                "conditionnotmet",
                "blobalreadyexists",
                "already exists",
                "conflict",
            )
        )

    @staticmethod
    def _lease_id(stdout: str) -> str:
        value = stdout.strip()
        if value.startswith("{"):
            try:
                payload = json.loads(value)
            except json.JSONDecodeError as error:
                raise AzureCliError("Azure lease response is malformed") from error
            value = str(payload.get("leaseId") or payload.get("lease_id") or "")
        if not re.fullmatch(r"[A-Za-z0-9-]{16,128}", value):
            raise AzureCliError("Azure lease response omitted a valid lease ID")
        return value

    def ensure_blob(self, name: str, content: bytes) -> None:
        exists = self._run(["exists", "--name", name, "--output", "json"])
        try:
            present = json.loads(exists.stdout).get("exists") is True
        except (AttributeError, json.JSONDecodeError) as error:
            raise AzureCliError("Azure Blob existence response is malformed") from error
        if present:
            return
        temporary_name = ""
        try:
            with tempfile.NamedTemporaryFile(delete=False) as temporary:
                temporary.write(content)
                temporary_name = temporary.name
            try:
                self._run(
                    [
                        "upload",
                        "--name",
                        name,
                        "--file",
                        temporary_name,
                        "--overwrite",
                        "false",
                        "--output",
                        "none",
                    ]
                )
            except AzureCliError as error:
                if not self._is_conflict(error):
                    raise
        finally:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)

    def refresh_blob(self, name: str, content: bytes) -> bool:
        temporary_name = ""
        try:
            with tempfile.NamedTemporaryFile(delete=False) as temporary:
                temporary.write(content)
                temporary_name = temporary.name
            try:
                self._run(
                    [
                        "upload",
                        "--name",
                        name,
                        "--file",
                        temporary_name,
                        "--overwrite",
                        "true",
                        "--output",
                        "none",
                    ]
                )
            except AzureCliError as error:
                if self._is_conflict(error):
                    return False
                raise
        finally:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)
        return True

    def list_blobs(self, prefix: str) -> list[BlobRecord]:
        result = self._run(
            [
                "list",
                "--prefix",
                prefix,
                "--include",
                "metadata",
                "--output",
                "json",
            ]
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise AzureCliError("Azure Blob listing response is malformed") from error
        if not isinstance(payload, list):
            raise AzureCliError("Azure Blob listing response is not a list")
        records: list[BlobRecord] = []
        for item in payload:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                raise AzureCliError("Azure Blob listing contains a malformed entry")
            properties = item.get("properties")
            if not isinstance(properties, dict):
                raise AzureCliError("Azure Blob listing omitted lease properties")
            lease = properties.get("lease")
            lease = lease if isinstance(lease, dict) else {}
            status = str(
                properties.get("leaseStatus")
                or properties.get("lease_status")
                or lease.get("status")
                or ""
            ).lower()
            state = str(
                properties.get("leaseState")
                or properties.get("lease_state")
                or lease.get("state")
                or ""
            ).lower()
            modified = properties.get("lastModified") or properties.get("last_modified")
            if not isinstance(modified, str) or not modified:
                raise AzureCliError("Azure Blob listing omitted last-modified evidence")
            try:
                modified_epoch = datetime.fromisoformat(
                    modified.replace("Z", "+00:00")
                ).timestamp()
            except ValueError as error:
                raise AzureCliError(
                    "Azure Blob last-modified evidence is invalid"
                ) from error
            records.append(BlobRecord(item["name"], status, state, modified_epoch))
        return records

    def acquire(self, name: str, duration_seconds: int) -> str | None:
        try:
            result = self._run(
                [
                    "lease",
                    "acquire",
                    "--blob-name",
                    name,
                    "--lease-duration",
                    str(duration_seconds),
                    "--query",
                    "leaseId",
                    "--output",
                    "tsv",
                ]
            )
        except AzureCliError as error:
            if self._is_conflict(error):
                return None
            raise
        return self._lease_id(result.stdout)

    def renew(self, name: str, lease_id: str) -> None:
        try:
            self._run(
                [
                    "lease",
                    "renew",
                    "--blob-name",
                    name,
                    "--lease-id",
                    lease_id,
                    "--output",
                    "none",
                ]
            )
        except AzureCliError as error:
            if self._is_conflict(error):
                raise LostLease("Azure Blob lease ownership was lost") from error
            raise

    def release(self, name: str, lease_id: str) -> bool:
        try:
            self._run(
                [
                    "lease",
                    "release",
                    "--blob-name",
                    name,
                    "--lease-id",
                    lease_id,
                    "--output",
                    "none",
                ]
            )
        except AzureCliError as error:
            if self._is_conflict(error):
                return False
            raise
        return True

    def delete(self, name: str) -> bool:
        try:
            self._run(["delete", "--name", name, "--output", "none"])
        except AzureCliError as error:
            if (
                "blobnotfound" in error.stderr.lower()
                or "not found" in error.stderr.lower()
            ):
                return False
            if self._is_conflict(error):
                return False
            raise
        return True


class RolloutCoordinator:
    def __init__(
        self,
        storage: BlobLeaseStorage,
        *,
        scope: str,
        duration_seconds: int = _DEFAULT_DURATION_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
        wall_time: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not _SCOPE_RE.fullmatch(scope):
            raise ValueError("rollout coordination scope is invalid")
        if not 15 <= duration_seconds <= 60:
            raise ValueError(
                "Azure Blob lease duration must be between 15 and 60 seconds"
            )
        self.storage = storage
        self.scope = scope
        self.duration_seconds = duration_seconds
        self._monotonic = monotonic
        self._wall_time = wall_time
        self._sleep = sleep
        self.root = f".archmorph-rollout/{scope}"
        self.lock_blob = f"{self.root}/exclusive.lock"
        self.intent_prefix = f"{self.root}/rollback-intents/"

    @staticmethod
    def _intent_numbers(run_id: str, run_attempt: int) -> tuple[int, int]:
        if not _POSITIVE_INTEGER_RE.fullmatch(run_id):
            raise ValueError("workflow run ID must be a positive integer")
        if (
            isinstance(run_attempt, bool)
            or not isinstance(run_attempt, int)
            or run_attempt < 1
        ):
            raise ValueError("workflow run attempt must be a positive integer")
        numeric_run = int(run_id)
        if numeric_run >= 10**20 or run_attempt >= 10**6:
            raise ValueError("workflow run identity exceeds the coordination format")
        return numeric_run, run_attempt

    def intent_blob(self, run_id: str, run_attempt: int) -> str:
        numeric_run, numeric_attempt = self._intent_numbers(run_id, run_attempt)
        return f"{self.intent_prefix}{numeric_run:020d}-{numeric_attempt:06d}.json"

    def _intent_payload(self, *, run_id: str, run_attempt: int) -> bytes:
        numeric_run, numeric_attempt = self._intent_numbers(run_id, run_attempt)
        return json.dumps(
            {
                "schema_version": 1,
                "kind": "emergency_rollback",
                "run_id": str(numeric_run),
                "run_attempt": numeric_attempt,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()

    def _lease_state(self, record: BlobRecord) -> str:
        if record.lease_status == "locked" and record.lease_state in {
            "leased",
            "breaking",
        }:
            return "active"
        if record.lease_status == "unlocked" and record.lease_state == "available":
            if record.last_modified_epoch is None:
                raise CoordinationError("rollback intent has no freshness evidence")
            age = self._wall_time() - record.last_modified_epoch
            if age < 0:
                raise CoordinationError(
                    "rollback intent last-modified evidence is in the future"
                )
            if age <= self.duration_seconds * 2:
                return "publishing"
            return "stale"
        if record.lease_status == "unlocked" and record.lease_state in {
            "expired",
            "broken",
        }:
            return "stale"
        raise CoordinationError("rollback intent has an unknown lease state")

    def active_intents(self, *, garbage_collect: bool = True) -> list[RollbackIntent]:
        intents: list[RollbackIntent] = []
        for record in self.storage.list_blobs(self.intent_prefix):
            if not record.name.startswith(self.intent_prefix):
                raise CoordinationError("rollback intent escaped its reserved prefix")
            basename = record.name.removeprefix(self.intent_prefix)
            match = _INTENT_BASENAME_RE.fullmatch(basename)
            if match is None:
                raise CoordinationError("rollback intent name is malformed")
            state = self._lease_state(record)
            if state == "stale":
                if garbage_collect and not self.storage.delete(record.name):
                    raise CoordinationError(
                        "stale rollback intent changed during garbage collection"
                    )
                continue
            intents.append(
                RollbackIntent(
                    int(match.group("run")),
                    int(match.group("attempt")),
                    record.name,
                )
            )
        return sorted(intents)

    def publish_intent(self, *, run_id: str, run_attempt: int) -> tuple[str, str]:
        blob_name = self.intent_blob(run_id, run_attempt)
        payload = self._intent_payload(run_id=run_id, run_attempt=run_attempt)
        self.storage.ensure_blob(blob_name, payload)
        lease_id = self.storage.acquire(blob_name, self.duration_seconds)
        if lease_id is None:
            raise LeaseBusy("this rollback intent is already owned by a live runner")
        return blob_name, lease_id

    def maintain_pending_intent(
        self,
        *,
        run_id: str,
        run_attempt: int,
        max_seconds: float,
        interval_seconds: float,
    ) -> str:
        """Refresh priority until the approved rollback claims its finite lease."""
        if max_seconds <= 0 or interval_seconds <= 0 or interval_seconds >= max_seconds:
            raise ValueError("priority maintenance bounds are invalid")
        blob_name = self.intent_blob(run_id, run_attempt)
        payload = self._intent_payload(run_id=run_id, run_attempt=run_attempt)
        deadline = self._monotonic() + max_seconds
        while True:
            if not self.storage.refresh_blob(blob_name, payload):
                return "claimed"
            if self._monotonic() >= deadline:
                return "bounded_wait_elapsed"
            self._sleep(min(interval_seconds, max(0.0, deadline - self._monotonic())))

    def claim_intent(
        self,
        *,
        run_id: str,
        run_attempt: int,
        wait_seconds: float,
        retry_seconds: float,
    ) -> tuple[str, str]:
        """Claim this run's independently published intent in deterministic order."""
        if wait_seconds < 0 or retry_seconds <= 0:
            raise ValueError("priority claim wait bounds are invalid")
        intent = self.intent_blob(run_id, run_attempt)
        deadline = self._monotonic() + wait_seconds
        while True:
            active = self.active_intents()
            own = next((item for item in active if item.blob_name == intent), None)
            if own is None:
                if self._monotonic() >= deadline:
                    raise LostLease(
                        "independently published rollback intent is not live"
                    )
                self._sleep(min(retry_seconds, max(0.0, deadline - self._monotonic())))
                continue
            if active[0].blob_name == intent:
                lease_id = self.storage.acquire(intent, self.duration_seconds)
                if lease_id is not None:
                    self._assert_rollback_turn(intent)
                    return intent, lease_id
            if self._monotonic() >= deadline:
                raise LeaseBusy("rollback priority claim exceeded its bounded wait")
            self._sleep(min(retry_seconds, max(0.0, deadline - self._monotonic())))

    def _assert_rollback_turn(self, own_intent: str) -> None:
        active = self.active_intents()
        if not active or all(item.blob_name != own_intent for item in active):
            raise LostLease("rollback priority intent is no longer live")
        if active[0].blob_name != own_intent:
            raise LeaseBusy("an earlier emergency rollback intent has priority")

    def acquire_rollout(
        self,
        *,
        mode: str,
        wait_seconds: float,
        retry_seconds: float,
        own_intent: str = "",
    ) -> str:
        if mode not in {"deploy", "rollback"}:
            raise ValueError("rollout lease mode must be deploy or rollback")
        if wait_seconds < 0 or retry_seconds <= 0:
            raise ValueError("rollout lease wait bounds are invalid")
        if mode == "rollback" and not own_intent:
            raise ValueError("rollback ownership requires a live priority intent")
        self.storage.ensure_blob(self.lock_blob, b"archmorph rollout coordination\n")
        deadline = self._monotonic() + wait_seconds
        while True:
            if mode == "deploy":
                if self.active_intents():
                    raise RollbackPriority("emergency rollback intent is active")
            else:
                try:
                    self._assert_rollback_turn(own_intent)
                except LeaseBusy:
                    if self._monotonic() >= deadline:
                        raise
                    self._sleep(
                        min(retry_seconds, max(0.0, deadline - self._monotonic()))
                    )
                    continue
            lease_id = self.storage.acquire(self.lock_blob, self.duration_seconds)
            if lease_id is not None:
                try:
                    if mode == "deploy" and self.active_intents():
                        raise RollbackPriority(
                            "emergency rollback intent won the acquisition race"
                        )
                    if mode == "rollback":
                        self._assert_rollback_turn(own_intent)
                    return lease_id
                except Exception:
                    self.storage.release(self.lock_blob, lease_id)
                    raise
            if self._monotonic() >= deadline:
                raise LeaseBusy(
                    "exclusive rollout ownership remained busy for the bounded wait"
                )
            self._sleep(min(retry_seconds, max(0.0, deadline - self._monotonic())))

    def checkpoint(
        self,
        *,
        mode: str,
        lease_id: str,
        own_intent: str = "",
        intent_lease_id: str = "",
    ) -> None:
        self.storage.renew(self.lock_blob, lease_id)
        if mode == "deploy":
            if self.active_intents():
                raise RollbackPriority(
                    "deploy yielded at a schema-safe rollback checkpoint"
                )
            return
        if mode != "rollback" or not own_intent or not intent_lease_id:
            raise ValueError("rollback checkpoint requires both lease identities")
        self.storage.renew(own_intent, intent_lease_id)
        self._assert_rollback_turn(own_intent)

    def renew_intent(self, *, intent: str, lease_id: str) -> None:
        self.storage.renew(intent, lease_id)

    def finish(
        self,
        *,
        rollout_lease_id: str = "",
        intent: str = "",
        intent_lease_id: str = "",
        clear_intent: bool,
    ) -> None:
        if rollout_lease_id:
            self.storage.release(self.lock_blob, rollout_lease_id)
        if not intent:
            return
        if not intent_lease_id:
            raise ValueError("intent cleanup requires its lease ID")
        if clear_intent:
            if not self.storage.release(intent, intent_lease_id):
                raise LostLease("rollback intent ownership was lost before clearing")
            if not self.storage.delete(intent):
                raise CoordinationError("rollback intent could not be cleared")


def _secure_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            os.fchmod(temporary.fileno(), 0o600)
            temporary.write(value + "\n")
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
        directory_fd = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _secure_read(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        raise LostLease("lease ID file cannot be read") from error
    if not re.fullmatch(r"[A-Za-z0-9-]{16,128}", value):
        raise LostLease("lease ID file is missing or malformed")
    return value


def _coordinator(args: argparse.Namespace) -> RolloutCoordinator:
    storage = AzureCliBlobLeaseStorage(
        account=args.account,
        container=args.container,
        executable=args.az,
    )
    return RolloutCoordinator(
        storage,
        scope=args.scope,
        duration_seconds=args.duration_seconds,
    )


def _heartbeat(args: argparse.Namespace, coordinator: RolloutCoordinator) -> int:
    if args.interval_seconds <= 0 or args.max_failures < 1:
        raise ValueError("heartbeat bounds are invalid")
    if args.mode == "deploy" and (args.intent or args.intent_lease_id_file):
        raise ValueError("deploy heartbeat must not carry rollback intent ownership")
    if args.mode == "rollback" and (
        not args.intent or args.intent_lease_id_file is None
    ):
        raise ValueError("rollback heartbeat requires priority intent ownership")
    failures = 0
    while True:
        time.sleep(args.interval_seconds)
        try:
            if args.rollout_lease_id_file:
                coordinator.storage.renew(
                    coordinator.lock_blob,
                    _secure_read(args.rollout_lease_id_file),
                )
            if args.intent and args.intent_lease_id_file:
                coordinator.renew_intent(
                    intent=args.intent,
                    lease_id=_secure_read(args.intent_lease_id_file),
                )
            failures = 0
        except CoordinationError as error:
            failures += 1
            print(
                f"Rollout lease heartbeat failure {failures}: {type(error).__name__}",
                file=sys.stderr,
            )
            if failures >= args.max_failures:
                return 4


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--scope", default="production")
    parser.add_argument(
        "--duration-seconds", type=int, default=_DEFAULT_DURATION_SECONDS
    )
    parser.add_argument("--az", default=os.environ.get("AZURE_CLI", "az"))
    commands = parser.add_subparsers(dest="command", required=True)

    publish = commands.add_parser("publish-intent")
    publish.add_argument("--run-id", required=True)
    publish.add_argument("--run-attempt", required=True, type=int)
    publish.add_argument("--intent-output", required=True, type=Path)
    publish.add_argument("--lease-id-output", required=True, type=Path)

    maintain = commands.add_parser("maintain-priority")
    maintain.add_argument("--run-id", required=True)
    maintain.add_argument("--run-attempt", required=True, type=int)
    maintain.add_argument("--max-seconds", type=float, default=3300)
    maintain.add_argument("--interval-seconds", type=float, default=15)

    claim = commands.add_parser("claim-intent")
    claim.add_argument("--run-id", required=True)
    claim.add_argument("--run-attempt", required=True, type=int)
    claim.add_argument("--wait-seconds", type=float, default=900)
    claim.add_argument("--retry-seconds", type=float, default=5)
    claim.add_argument("--intent-output", required=True, type=Path)
    claim.add_argument("--lease-id-output", required=True, type=Path)

    acquire = commands.add_parser("acquire")
    acquire.add_argument("--mode", choices=("deploy", "rollback"), required=True)
    acquire.add_argument("--wait-seconds", type=float, default=900)
    acquire.add_argument("--retry-seconds", type=float, default=5)
    acquire.add_argument("--intent", default="")
    acquire.add_argument("--lease-id-output", required=True, type=Path)

    checkpoint = commands.add_parser("checkpoint")
    checkpoint.add_argument("--mode", choices=("deploy", "rollback"), required=True)
    checkpoint.add_argument("--rollout-lease-id-file", required=True, type=Path)
    checkpoint.add_argument("--intent", default="")
    checkpoint.add_argument("--intent-lease-id-file", type=Path)

    renew = commands.add_parser("renew")
    renew.add_argument("--rollout-lease-id-file", required=True, type=Path)

    wait_turn = commands.add_parser("wait-turn")
    wait_turn.add_argument("--intent", required=True)
    wait_turn.add_argument("--wait-seconds", type=float, default=900)
    wait_turn.add_argument("--retry-seconds", type=float, default=5)

    heartbeat = commands.add_parser("heartbeat")
    heartbeat.add_argument("--mode", choices=("deploy", "rollback"), required=True)
    heartbeat.add_argument("--rollout-lease-id-file", type=Path)
    heartbeat.add_argument("--intent", default="")
    heartbeat.add_argument("--intent-lease-id-file", type=Path)
    heartbeat.add_argument("--interval-seconds", type=float, default=15)
    heartbeat.add_argument("--max-failures", type=int, default=3)

    finish = commands.add_parser("finish")
    finish.add_argument("--rollout-lease-id-file", type=Path)
    finish.add_argument("--intent", default="")
    finish.add_argument("--intent-lease-id-file", type=Path)
    finish.add_argument("--clear-intent", action="store_true")

    commands.add_parser("assert-no-priority")
    args = parser.parse_args()
    coordinator = _coordinator(args)

    if args.command == "publish-intent":
        intent, lease_id = coordinator.publish_intent(
            run_id=args.run_id,
            run_attempt=args.run_attempt,
        )
        _secure_write(args.intent_output, intent)
        _secure_write(args.lease_id_output, lease_id)
        print(json.dumps({"status": "priority_published"}, sort_keys=True))
    elif args.command == "maintain-priority":
        status = coordinator.maintain_pending_intent(
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            max_seconds=args.max_seconds,
            interval_seconds=args.interval_seconds,
        )
        print(json.dumps({"status": status}, sort_keys=True))
    elif args.command == "claim-intent":
        intent, lease_id = coordinator.claim_intent(
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            wait_seconds=args.wait_seconds,
            retry_seconds=args.retry_seconds,
        )
        _secure_write(args.intent_output, intent)
        _secure_write(args.lease_id_output, lease_id)
        print(json.dumps({"status": "priority_claimed"}, sort_keys=True))
    elif args.command == "wait-turn":
        deadline = time.monotonic() + args.wait_seconds
        while True:
            try:
                coordinator._assert_rollback_turn(args.intent)
                break
            except LeaseBusy:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(
                    min(args.retry_seconds, max(0.0, deadline - time.monotonic()))
                )
        print(json.dumps({"status": "priority_granted"}, sort_keys=True))
    elif args.command == "acquire":
        lease_id = coordinator.acquire_rollout(
            mode=args.mode,
            wait_seconds=args.wait_seconds,
            retry_seconds=args.retry_seconds,
            own_intent=args.intent,
        )
        _secure_write(args.lease_id_output, lease_id)
        print(
            json.dumps({"status": "exclusive_owner", "mode": args.mode}, sort_keys=True)
        )
    elif args.command == "checkpoint":
        coordinator.checkpoint(
            mode=args.mode,
            lease_id=_secure_read(args.rollout_lease_id_file),
            own_intent=args.intent,
            intent_lease_id=(
                _secure_read(args.intent_lease_id_file)
                if args.intent_lease_id_file
                else ""
            ),
        )
        print(
            json.dumps({"status": "checkpoint_safe", "mode": args.mode}, sort_keys=True)
        )
    elif args.command == "renew":
        coordinator.storage.renew(
            coordinator.lock_blob,
            _secure_read(args.rollout_lease_id_file),
        )
        print(json.dumps({"status": "exclusive_owner_renewed"}, sort_keys=True))
    elif args.command == "heartbeat":
        return _heartbeat(args, coordinator)
    elif args.command == "finish":
        coordinator.finish(
            rollout_lease_id=(
                _secure_read(args.rollout_lease_id_file)
                if args.rollout_lease_id_file and args.rollout_lease_id_file.exists()
                else ""
            ),
            intent=args.intent,
            intent_lease_id=(
                _secure_read(args.intent_lease_id_file)
                if args.intent_lease_id_file and args.intent_lease_id_file.exists()
                else ""
            ),
            clear_intent=args.clear_intent,
        )
        print(
            json.dumps(
                {"status": "released", "intent_cleared": args.clear_intent},
                sort_keys=True,
            )
        )
    else:
        if coordinator.active_intents():
            raise RollbackPriority("emergency rollback intent is active")
        print(json.dumps({"status": "no_rollback_priority"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RollbackPriority as error:
        print(str(error), file=os.sys.stderr)
        raise SystemExit(10) from error
    except LeaseBusy as error:
        print(str(error), file=os.sys.stderr)
        raise SystemExit(3) from error
    except LostLease as error:
        print(str(error), file=os.sys.stderr)
        raise SystemExit(4) from error
