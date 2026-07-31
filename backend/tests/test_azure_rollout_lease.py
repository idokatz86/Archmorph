from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from subprocess import CompletedProcess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "azure_rollout_lease.py"
SPEC = importlib.util.spec_from_file_location("azure_rollout_lease", SCRIPT)
assert SPEC and SPEC.loader
coordination = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = coordination
SPEC.loader.exec_module(coordination)
LEASE_ID_PLACEHOLDER = "00000000-0000-0000-0000-000000000000"


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeBlobStorage:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.blobs: dict[str, bytes] = {}
        self.modified: dict[str, float] = {}
        self.leases: dict[str, tuple[str, float]] = {}
        self.sequence = 0
        self.deleted: list[str] = []

    def ensure_blob(self, name: str, content: bytes) -> None:
        if name not in self.blobs:
            self.blobs[name] = content
            self.modified[name] = self.clock.now()

    def refresh_blob(self, name: str, content: bytes) -> bool:
        if self._live(name):
            return False
        self.blobs[name] = content
        self.modified[name] = self.clock.now()
        return True

    def _live(self, name: str) -> bool:
        lease = self.leases.get(name)
        return bool(lease and lease[1] > self.clock.now())

    def list_blobs(self, prefix: str) -> list[object]:
        records = []
        for name in sorted(self.blobs):
            if not name.startswith(prefix):
                continue
            if self._live(name):
                status, state = "locked", "leased"
            elif name not in self.leases:
                status, state = "unlocked", "available"
            else:
                status, state = "unlocked", "expired"
            records.append(
                coordination.BlobRecord(
                    name,
                    status,
                    state,
                    self.modified[name],
                )
            )
        return records

    def acquire(self, name: str, duration_seconds: int) -> str | None:
        if self._live(name):
            return None
        self.sequence += 1
        lease_id = f"00000000-0000-4000-8000-{self.sequence:012d}"
        self.leases[name] = (lease_id, self.clock.now() + duration_seconds)
        return lease_id

    def renew(self, name: str, lease_id: str) -> None:
        if not self._live(name) or self.leases[name][0] != lease_id:
            raise coordination.LostLease("fake lease expired or changed")
        self.leases[name] = (
            lease_id,
            self.clock.now() + 15,
        )

    def release(self, name: str, lease_id: str) -> bool:
        if not self._live(name) or self.leases[name][0] != lease_id:
            return False
        del self.leases[name]
        return True

    def delete(self, name: str) -> bool:
        if self._live(name):
            return False
        if name not in self.blobs:
            return False
        del self.blobs[name]
        self.modified.pop(name, None)
        self.deleted.append(name)
        return True


def _coordinator(duration: int = 15):
    clock = FakeClock()
    storage = FakeBlobStorage(clock)
    owner = coordination.RolloutCoordinator(
        storage,
        scope="production",
        duration_seconds=duration,
        monotonic=clock.now,
        wall_time=clock.now,
        sleep=clock.sleep,
    )
    return owner, storage, clock


def test_active_deploy_yields_to_queued_rollback_and_newer_deploy_cannot_displace_it():
    owner, _storage, _clock = _coordinator()
    deploy_lease = owner.acquire_rollout(
        mode="deploy",
        wait_seconds=0,
        retry_seconds=1,
    )
    intent, intent_lease = owner.publish_intent(run_id="100", run_attempt=1)

    with pytest.raises(coordination.RollbackPriority, match="yielded"):
        owner.checkpoint(mode="deploy", lease_id=deploy_lease)
    with pytest.raises(coordination.RollbackPriority, match="active"):
        owner.acquire_rollout(mode="deploy", wait_seconds=0, retry_seconds=1)
    with pytest.raises(coordination.LeaseBusy, match="remained busy"):
        owner.acquire_rollout(
            mode="rollback",
            wait_seconds=0,
            retry_seconds=1,
            own_intent=intent,
        )

    owner.finish(clear_intent=False, rollout_lease_id=deploy_lease)
    rollback_lease = owner.acquire_rollout(
        mode="rollback",
        wait_seconds=0,
        retry_seconds=1,
        own_intent=intent,
    )
    owner.checkpoint(
        mode="rollback",
        lease_id=rollback_lease,
        own_intent=intent,
        intent_lease_id=intent_lease,
    )


def test_multiple_rollbacks_serialize_by_run_and_attempt_not_arrival_or_pending_slot():
    owner, _storage, _clock = _coordinator()
    later, later_lease = owner.publish_intent(run_id="201", run_attempt=1)
    earlier, earlier_lease = owner.publish_intent(run_id="200", run_attempt=2)

    with pytest.raises(coordination.LeaseBusy, match="earlier"):
        owner.acquire_rollout(
            mode="rollback",
            wait_seconds=0,
            retry_seconds=1,
            own_intent=later,
        )
    first_owner = owner.acquire_rollout(
        mode="rollback",
        wait_seconds=0,
        retry_seconds=1,
        own_intent=earlier,
    )
    owner.finish(
        rollout_lease_id=first_owner,
        intent=earlier,
        intent_lease_id=earlier_lease,
        clear_intent=True,
    )
    second_owner = owner.acquire_rollout(
        mode="rollback",
        wait_seconds=0,
        retry_seconds=1,
        own_intent=later,
    )
    owner.finish(
        rollout_lease_id=second_owner,
        intent=later,
        intent_lease_id=later_lease,
        clear_intent=True,
    )
    assert owner.active_intents() == []


def test_runner_loss_expires_shared_lock_and_stale_priority_without_breaking_live_lease():
    owner, storage, clock = _coordinator()
    owner.acquire_rollout(mode="deploy", wait_seconds=0, retry_seconds=1)
    intent, _intent_lease = owner.publish_intent(run_id="300", run_attempt=1)

    clock.advance(16)
    assert owner.active_intents() == []
    assert intent in storage.deleted

    replacement = owner.acquire_rollout(
        mode="deploy",
        wait_seconds=0,
        retry_seconds=1,
    )
    assert replacement


def test_fresh_unleased_intent_blocks_deploy_during_publish_acquire_race():
    owner, storage, clock = _coordinator()
    intent = owner.intent_blob("350", 1)
    storage.ensure_blob(intent, b"pending")

    with pytest.raises(coordination.RollbackPriority, match="active"):
        owner.acquire_rollout(mode="deploy", wait_seconds=0, retry_seconds=1)
    assert intent in storage.blobs

    clock.advance(31)
    assert owner.active_intents() == []
    assert intent not in storage.blobs


def test_independent_priority_maintenance_hands_off_to_approved_claim():
    owner, storage, _clock = _coordinator()
    intent = owner.intent_blob("375", 1)
    original_refresh = storage.refresh_blob
    refresh_count = 0

    def refresh(name, content):
        nonlocal refresh_count
        refresh_count += 1
        if refresh_count == 2:
            assert storage.acquire(intent, 15)
            return False
        return original_refresh(name, content)

    storage.refresh_blob = refresh
    status = owner.maintain_pending_intent(
        run_id="375",
        run_attempt=1,
        max_seconds=60,
        interval_seconds=5,
    )
    assert status == "claimed"
    assert refresh_count == 2


def test_claim_waits_for_independent_publisher_and_multiple_claims_remain_ordered():
    owner, storage, clock = _coordinator()
    later = owner.intent_blob("381", 1)
    earlier = owner.intent_blob("380", 1)
    sleep_count = 0
    original_sleep = clock.sleep

    def publish_on_wait(seconds):
        nonlocal sleep_count
        sleep_count += 1
        original_sleep(seconds)
        if sleep_count == 1:
            storage.refresh_blob(later, b"later")
            storage.refresh_blob(earlier, b"earlier")

    owner._sleep = publish_on_wait
    with pytest.raises(coordination.LeaseBusy, match="bounded wait"):
        owner.claim_intent(
            run_id="381",
            run_attempt=1,
            wait_seconds=2,
            retry_seconds=1,
        )
    first_intent, first_lease = owner.claim_intent(
        run_id="380",
        run_attempt=1,
        wait_seconds=0,
        retry_seconds=1,
    )
    assert first_intent == earlier
    assert storage.release(first_intent, first_lease)
    assert storage.delete(first_intent)
    second_intent, _second_lease = owner.claim_intent(
        run_id="381",
        run_attempt=1,
        wait_seconds=0,
        retry_seconds=1,
    )
    assert second_intent == later


def test_cancelled_rollback_can_leave_priority_to_expire_but_success_clears_immediately():
    owner, storage, clock = _coordinator()
    cancelled, _cancelled_lease = owner.publish_intent(run_id="400", run_attempt=1)
    clock.advance(16)
    assert owner.active_intents() == []
    assert cancelled not in storage.blobs

    successful, successful_lease = owner.publish_intent(run_id="401", run_attempt=1)
    rollout_lease = owner.acquire_rollout(
        mode="rollback",
        wait_seconds=0,
        retry_seconds=1,
        own_intent=successful,
    )
    owner.finish(
        rollout_lease_id=rollout_lease,
        intent=successful,
        intent_lease_id=successful_lease,
        clear_intent=True,
    )
    assert successful not in storage.blobs
    assert owner.acquire_rollout(mode="deploy", wait_seconds=0, retry_seconds=1)


def test_intent_heartbeat_prevents_runner_loss_expiry_until_renewal_stops():
    owner, _storage, clock = _coordinator()
    intent, intent_lease = owner.publish_intent(run_id="500", run_attempt=1)
    clock.advance(10)
    owner.renew_intent(intent=intent, lease_id=intent_lease)
    clock.advance(10)
    assert [item.blob_name for item in owner.active_intents()] == [intent]
    clock.advance(6)
    assert owner.active_intents() == []


@pytest.mark.parametrize("file_state", ["malformed", "invalid-utf8", "missing"])
def test_heartbeat_counts_malformed_or_missing_lease_id_as_bounded_loss(
    tmp_path, capsys, file_state
):
    owner, storage, _clock = _coordinator()
    lease_file = tmp_path / "rollout-lease-id"
    if file_state == "malformed":
        lease_file.write_text("bad!\n", encoding="utf-8")
    elif file_state == "invalid-utf8":
        lease_file.write_bytes(b"\xff\xfe")
    args = SimpleNamespace(
        interval_seconds=1,
        max_failures=2,
        mode="deploy",
        intent="",
        intent_lease_id_file=None,
        rollout_lease_id_file=lease_file,
        status_file=tmp_path / "heartbeat-status",
    )

    with patch.object(coordination.time, "sleep"):
        assert coordination._heartbeat(args, owner) == 4

    assert storage.leases == {}
    assert args.status_file.read_text(encoding="utf-8") == "lost\n"
    assert capsys.readouterr().err.count("LostLease") == 2


def test_heartbeat_assertion_fails_closed_for_loss_malformed_status_or_dead_pid(
    tmp_path,
):
    status_file = tmp_path / "heartbeat-status"
    with patch.object(coordination.os, "kill") as kill:
        coordination._assert_heartbeat(status_file, 123)
        kill.assert_called_once_with(123, 0)

    status_file.write_text("lost\n", encoding="utf-8")
    with pytest.raises(coordination.LostLease, match="reported lost ownership"):
        coordination._assert_heartbeat(status_file, 123)

    status_file.write_text("unexpected\n", encoding="utf-8")
    with pytest.raises(coordination.LostLease, match="status is malformed"):
        coordination._assert_heartbeat(status_file, 123)

    status_file.unlink()
    with (
        patch.object(coordination.os, "kill", side_effect=ProcessLookupError),
        pytest.raises(coordination.LostLease, match="is not running"),
    ):
        coordination._assert_heartbeat(status_file, 123)


def test_supervised_mutation_is_terminated_when_heartbeat_dies(tmp_path):
    owner, storage, _clock = _coordinator()
    lease_id = owner.acquire_rollout(mode="deploy", wait_seconds=0, retry_seconds=1)
    lease_file = tmp_path / "rollout-lease-id"
    coordination._secure_write(lease_file, lease_id)
    args = SimpleNamespace(
        mutation_command=["mutation", "arg"],
        rollout_lease_id_file=lease_file,
        status_file=tmp_path / "heartbeat-status",
        heartbeat_pid=123,
        poll_seconds=1,
    )
    process = SimpleNamespace(pid=456, returncode=None)
    polls = iter([None, None])
    process.poll = lambda: next(polls)
    process.wait = lambda timeout=None: setattr(process, "returncode", -15) or -15
    heartbeat_checks = [None, None, coordination.LostLease("lost")]

    with (
        patch.object(coordination.subprocess, "Popen", return_value=process) as popen,
        patch.object(coordination, "_assert_heartbeat", side_effect=heartbeat_checks),
        patch.object(coordination.time, "sleep"),
        patch.object(coordination.os, "killpg") as killpg,
        pytest.raises(coordination.LostLease, match="lost"),
    ):
        coordination._supervise_command(args, owner)

    popen.assert_called_once_with(["mutation", "arg"], start_new_session=True)
    assert killpg.call_args_list == [
        ((456, coordination.signal.SIGTERM),),
        ((456, coordination.signal.SIGKILL),),
    ]
    assert storage.leases[owner.lock_blob][0] == lease_id


def test_supervised_mutation_rechecks_ownership_after_success(tmp_path):
    owner, _storage, _clock = _coordinator()
    lease_id = owner.acquire_rollout(mode="deploy", wait_seconds=0, retry_seconds=1)
    lease_file = tmp_path / "rollout-lease-id"
    coordination._secure_write(lease_file, lease_id)
    args = SimpleNamespace(
        mutation_command=["--", "mutation"],
        rollout_lease_id_file=lease_file,
        status_file=tmp_path / "heartbeat-status",
        heartbeat_pid=123,
        poll_seconds=1,
    )
    process = SimpleNamespace(pid=456, returncode=0, poll=lambda: 0)

    with (
        patch.object(coordination.subprocess, "Popen", return_value=process),
        patch.object(coordination, "_assert_heartbeat") as heartbeat,
    ):
        assert coordination._supervise_command(args, owner) == 0

    assert heartbeat.call_count == 2


def test_secure_coordination_write_fsyncs_file_and_directory(tmp_path):
    lease_file = tmp_path / "rollout-lease-id"
    lease_id = "placeholder-lease-id-0001"
    original_fsync = coordination.os.fsync

    with patch.object(coordination.os, "fsync", wraps=original_fsync) as fsync:
        coordination._secure_write(lease_file, lease_id)

    assert fsync.call_count >= 2
    assert coordination._secure_read(lease_file) == lease_id
    assert lease_file.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".rollout-lease-id.*.tmp"))


def test_unknown_or_malformed_priority_state_fails_closed():
    owner, storage, _clock = _coordinator()
    malformed = owner.intent_prefix + "not-an-intent.json"
    storage.ensure_blob(malformed, b"{}")
    with pytest.raises(coordination.CoordinationError, match="name is malformed"):
        owner.active_intents()

    storage.blobs.clear()
    valid = owner.intent_blob("600", 1)
    storage.blobs[valid] = b"{}"
    storage.list_blobs = lambda _prefix: [coordination.BlobRecord(valid, "", "")]
    with pytest.raises(coordination.CoordinationError, match="unknown lease state"):
        owner.active_intents()


def test_stale_intent_garbage_collection_race_fails_closed():
    owner, storage, clock = _coordinator()
    intent, _lease = owner.publish_intent(run_id="650", run_attempt=1)
    clock.advance(16)
    original_delete = storage.delete
    storage.delete = lambda _name: False
    with pytest.raises(coordination.CoordinationError, match="changed"):
        owner.active_intents()
    assert intent in storage.blobs
    storage.delete = original_delete


def test_fake_azure_cli_uses_login_auth_and_never_account_keys_or_sas():
    storage = coordination.AzureCliBlobLeaseStorage(
        account="exampleaccount",
        container="state",
    )
    with patch.object(
        coordination.subprocess,
        "run",
        return_value=CompletedProcess(
            [],
            0,
            stdout="lease-placeholder-0001\n",
        ),
    ) as run:
        assert storage.acquire(".archmorph-rollout/production/exclusive.lock", 60)

    command = run.call_args.args[0]
    assert command[:4] == ["az", "storage", "blob", "lease"]
    assert command[-7:] == [
        "--account-name",
        "exampleaccount",
        "--container-name",
        "state",
        "--auth-mode",
        "login",
        "--only-show-errors",
    ]
    assert "--account-key" not in command
    assert "--sas-token" not in command
    assert "--query" not in command
    assert command[command.index("--output") + 1] == "json"


def test_transaction_state_upload_requires_lease_and_download_is_passwordless(
    tmp_path,
):
    storage = coordination.AzureCliBlobLeaseStorage(
        account="exampleaccount",
        container="state",
    )
    source = tmp_path / "rollout-state.json"
    source.write_text('{"signed":true}\n', encoding="utf-8")
    destination = tmp_path / "downloaded.json"
    with patch.object(
        coordination.subprocess,
        "run",
        return_value=CompletedProcess([], 0, stdout=""),
    ) as run:
        storage.upload_owned(
            ".archmorph-rollout/production/exclusive.lock",
            source,
            LEASE_ID_PLACEHOLDER,
        )
        assert storage.download(
            ".archmorph-rollout/production/exclusive.lock",
            destination,
        )

    upload = run.call_args_list[0].args[0]
    download = run.call_args_list[1].args[0]
    assert "upload" in upload
    assert upload[upload.index("--lease-id") + 1] == LEASE_ID_PLACEHOLDER
    assert upload[upload.index("--overwrite") + 1] == "true"
    assert "download" in download
    for command in (upload, download):
        assert command[command.index("--auth-mode") + 1] == "login"
        assert "--account-key" not in command
        assert "--sas-token" not in command


def test_transaction_upload_commit_then_timeout_is_reconciled_by_exact_readback(
    tmp_path,
):
    storage = coordination.AzureCliBlobLeaseStorage(
        account="exampleaccount",
        container="state",
    )
    source = tmp_path / "rollout-state.json"
    source.write_text('{"signed":true}\n', encoding="utf-8")

    def run(arguments):
        if "upload" in arguments:
            raise coordination.AzureCliError("timeout")
        readback = Path(arguments[arguments.index("--file") + 1])
        readback.write_bytes(source.read_bytes())
        return CompletedProcess([], 0, stdout="")

    with patch.object(storage, "_run", side_effect=run):
        storage.upload_owned(
            ".archmorph-rollout/production/exclusive.lock",
            source,
            LEASE_ID_PLACEHOLDER,
        )

    assert not (tmp_path / ".rollout-state.json.readback").exists()


def test_lock_sentinel_is_not_treated_as_durable_transaction(tmp_path):
    state = tmp_path / "state.json"
    state.write_bytes(coordination._LOCK_SENTINEL)
    assert coordination._transaction_present(state) is False
    assert not state.exists()

    state.write_text('{"schema_version":3,"signature":"signed"}\n', encoding="utf-8")
    assert coordination._transaction_present(state) is True
    assert state.exists()


@pytest.mark.parametrize(
    "stdout",
    [
        f'"{LEASE_ID_PLACEHOLDER}"\n',
        f'{{"leaseId":"{LEASE_ID_PLACEHOLDER}"}}\n',
        f"{LEASE_ID_PLACEHOLDER}\n",
    ],
)
def test_lease_id_accepts_current_and_legacy_azure_cli_response_shapes(stdout):
    assert (
        coordination.AzureCliBlobLeaseStorage._lease_id(stdout) == LEASE_ID_PLACEHOLDER
    )


def test_azure_cli_blob_listing_uses_supported_compact_metadata_selector():
    storage = coordination.AzureCliBlobLeaseStorage(
        account="exampleaccount",
        container="state",
    )
    payload = [
        {
            "name": ".archmorph-rollout/production/exclusive.lock",
            "properties": {
                "lastModified": "2026-07-31T00:00:00Z",
                "leaseState": "available",
                "leaseStatus": "unlocked",
            },
        }
    ]
    with patch.object(
        coordination.subprocess,
        "run",
        return_value=CompletedProcess([], 0, stdout=json.dumps(payload)),
    ) as run:
        records = storage.list_blobs(".archmorph-rollout/production/")

    assert len(records) == 1
    command = run.call_args.args[0]
    assert command[command.index("--include") + 1] == "m"
    assert "metadata" not in command


@pytest.mark.parametrize(
    ("run_id", "attempt"),
    [("0", 1), ("abc", 1), ("1", 0), ("1", -1), ("1", True)],
)
def test_priority_identity_rejects_ambiguous_values(run_id, attempt):
    owner, _storage, _clock = _coordinator()
    with pytest.raises(ValueError):
        owner.intent_blob(run_id, attempt)
