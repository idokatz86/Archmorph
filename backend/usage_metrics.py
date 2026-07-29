"""
Archmorph Usage Metrics — Admin-only analytics with funnel tracking.

Tracks: user sessions through the conversion funnel (upload → analyze →
questions → answers → IaC → export), drop-off points, completion rates,
daily activity, and recent events.  Designed for the admin dashboard only.

Persistence priority:
  1. Azure Blob Storage (survives container restarts/deploys)
  2. Local disk (fallback for dev / when blob is unavailable)

A background daemon thread flushes dirty metrics every 30 s and an
atexit / SIGTERM handler guarantees a final flush on shutdown.
"""

import atexit
import copy
import errno
import fcntl
import hashlib
import json
import logging
import os
import signal
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_shutdown_event = threading.Event()

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
METRICS_FILE = os.path.join(DATA_DIR, "usage_metrics.json")

# Azure Blob Storage persistence — RBAC preferred, connection string fallback
AZURE_STORAGE_ACCOUNT_URL = os.getenv("AZURE_STORAGE_ACCOUNT_URL", "")
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
AZURE_STORAGE_MANAGED_IDENTITY_CLIENT_ID = os.getenv(
    "AZURE_STORAGE_MANAGED_IDENTITY_CLIENT_ID",
    "",
)
METRICS_BLOB_CONTAINER = "metrics"
METRICS_BLOB_NAME = "usage_metrics.json"

# Admin secret – MUST be set via env var in production
ADMIN_SECRET = os.getenv("ARCHMORPH_ADMIN_KEY", "")

_lock = threading.RLock()
_dirty = False          # True when in-memory state diverges from persisted copy
_flush_interval = 30    # seconds between background flush cycles
_FILE_LOCK_TIMEOUT_SECONDS = max(
    0.1,
    min(30.0, float(os.getenv("USAGE_METRICS_FILE_LOCK_TIMEOUT_SECONDS", "5"))),
)
_FILE_LOCK_POLL_SECONDS = 0.01
_BLOB_WRITE_MAX_ATTEMPTS = 4
_PURGE_SCAN_BATCH_SIZE = 250


class UsageMetricsPersistenceError(RuntimeError):
    """Base class for truthful telemetry persistence failures."""


class UsageMetricsLockTimeout(UsageMetricsPersistenceError):
    """Raised when another live process holds the metrics lock too long."""


class UsageMetricsCorruptionError(UsageMetricsPersistenceError):
    """Raised when a stable persisted payload is not valid JSON."""


def _metrics_lock_file() -> str:
    return f"{METRICS_FILE}.lock"


@contextmanager
def _metrics_file_lock(*, exclusive: bool):
    """Acquire a bounded POSIX advisory lock released automatically on crash."""
    directory = os.path.dirname(METRICS_FILE) or "."
    os.makedirs(directory, exist_ok=True)
    descriptor = os.open(_metrics_lock_file(), os.O_CREAT | os.O_RDWR, 0o600)
    operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    deadline = time.monotonic() + _FILE_LOCK_TIMEOUT_SECONDS
    try:
        while True:
            try:
                fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise UsageMetricsLockTimeout(
                        "Timed out waiting for the usage metrics persistence lock"
                    ) from exc
                time.sleep(_FILE_LOCK_POLL_SECONDS)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _decode_metrics_payload(payload: object, *, source: str) -> Dict[str, Any]:
    try:
        decoded = json.loads(payload)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UsageMetricsCorruptionError(
            f"Stable usage metrics payload from {source} is corrupt"
        ) from exc
    if not isinstance(decoded, dict):
        raise UsageMetricsCorruptionError(
            f"Stable usage metrics payload from {source} is not an object"
        )
    return decoded


def _read_local_metrics_file() -> Optional[Dict[str, Any]]:
    """Read one stable old-or-new file generation under a shared lock."""
    try:
        with _metrics_file_lock(exclusive=False):
            if not os.path.exists(METRICS_FILE):
                return None
            try:
                with open(METRICS_FILE, "rb") as file_handle:
                    payload = file_handle.read()
            except OSError as exc:
                raise UsageMetricsPersistenceError(
                    "Failed to read the usage metrics file"
                ) from exc
    except UsageMetricsPersistenceError:
        raise
    return _decode_metrics_payload(payload, source="local disk")


def _fsync_directory(directory: str) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        try:
            os.fsync(descriptor)
        except OSError as exc:
            if exc.errno not in {errno.EINVAL, errno.ENOTSUP}:
                raise
    finally:
        os.close(descriptor)


def _atomic_replace_local_metrics(payload: str) -> None:
    """Write, fsync, and atomically replace the metrics file in one directory."""
    directory = os.path.dirname(METRICS_FILE) or "."
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary_file = tempfile.mkstemp(
        prefix=".usage_metrics.",
        suffix=".tmp",
        dir=directory,
        text=True,
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file_handle:
            descriptor = -1
            file_handle.write(payload)
            file_handle.flush()
            os.fsync(file_handle.fileno())
        os.replace(temporary_file, METRICS_FILE)
        _fsync_directory(directory)
    except OSError as exc:
        raise UsageMetricsPersistenceError(
            "Atomic usage metrics file replacement failed"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary_file)
        except FileNotFoundError:
            pass

# Ordered funnel steps
FUNNEL_STEPS = ["upload", "analyze", "questions", "answers", "iac_generate", "export"]
FUNNEL_LABELS = {
    "upload": "Upload Diagram",
    "analyze": "Run Analysis",
    "questions": "View Questions",
    "answers": "Apply Answers",
    "iac_generate": "Generate IaC",
    "export": "Export Diagram",
}

# ─────────────────────────────────────────────────────────────
# In-memory metrics store (persisted to disk periodically)
# ─────────────────────────────────────────────────────────────
_DEFAULT_METRICS: Dict[str, Any] = {
    "counters": {
        "diagrams_uploaded": 0,
        "analyses_run": 0,
        "questions_generated": 0,
        "answers_applied": 0,
        "iac_generated_terraform": 0,
        "iac_generated_bicep": 0,
        "exports_excalidraw": 0,
        "exports_drawio": 0,
        "exports_vsdx": 0,
        "chat_messages": 0,
        "github_issues_created": 0,
        "service_searches": 0,
        "cost_estimates": 0,
        "images_rejected": 0,
        "hld_generated": 0,
        "iac_chat_messages": 0,
        "iac_services_added": 0,
    },
    "daily": {},       # { "2026-02-19": { counter_name: count } }
    "recent_events": [],  # last 200 events
    "first_event": None,
    # ── Funnel tracking ──
    "sessions": {},    # { diagram_id: { "steps": [...], "started": iso, "last": iso } }
    "funnel_totals": {s: 0 for s in FUNNEL_STEPS},
}

_metrics: Dict[str, Any] = {}
_metrics_baseline: Dict[str, Any] = {}
_blob_metrics_baseline: Dict[str, Any] = {}


def _ensure_keys(m: Dict):
    """Backfill any missing keys from _DEFAULT_METRICS."""
    for k, v in _DEFAULT_METRICS.items():
        if k not in m:
            m[k] = v if not isinstance(v, dict) else dict(v)
    for k, v in _DEFAULT_METRICS["counters"].items():
        if k not in m["counters"]:
            m["counters"][k] = v
    if "sessions" not in m:
        m["sessions"] = {}
    if "funnel_totals" not in m:
        m["funnel_totals"] = {s: 0 for s in FUNNEL_STEPS}


def _numeric_delta(current: object, baseline: object) -> int:
    try:
        return max(0, int(current or 0) - int(baseline or 0))
    except (TypeError, ValueError):
        return 0


def _merge_metrics_generations(
    durable: Dict[str, Any],
    current: Dict[str, Any],
    baseline: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge this process's increments into the latest locked generation."""
    merged = copy.deepcopy(durable)
    _ensure_keys(merged)
    _ensure_keys(current)
    _ensure_keys(baseline)

    for counter_name, current_value in current["counters"].items():
        increment = _numeric_delta(
            current_value,
            baseline["counters"].get(counter_name, 0),
        )
        merged["counters"][counter_name] = int(
            merged["counters"].get(counter_name, 0) or 0
        ) + increment

    for day, current_values in current["daily"].items():
        if not isinstance(current_values, dict):
            continue
        merged_day = merged["daily"].setdefault(day, {})
        baseline_day = baseline["daily"].get(day, {})
        if not isinstance(baseline_day, dict):
            baseline_day = {}
        for counter_name, current_value in current_values.items():
            increment = _numeric_delta(
                current_value,
                baseline_day.get(counter_name, 0),
            )
            merged_day[counter_name] = int(
                merged_day.get(counter_name, 0) or 0
            ) + increment

    for step, current_value in current["funnel_totals"].items():
        increment = _numeric_delta(
            current_value,
            baseline["funnel_totals"].get(step, 0),
        )
        merged["funnel_totals"][step] = int(
            merged["funnel_totals"].get(step, 0) or 0
        ) + increment

    baseline_events = {
        json.dumps(event, sort_keys=True, default=str)
        for event in baseline.get("recent_events", [])
    }
    durable_events = {
        json.dumps(event, sort_keys=True, default=str)
        for event in merged.get("recent_events", [])
    }
    for event in current.get("recent_events", []):
        fingerprint = json.dumps(event, sort_keys=True, default=str)
        if fingerprint not in baseline_events and fingerprint not in durable_events:
            merged["recent_events"].append(copy.deepcopy(event))
            durable_events.add(fingerprint)
    merged["recent_events"] = sorted(
        merged["recent_events"],
        key=lambda event: str(event.get("timestamp", "")) if isinstance(event, dict) else "",
    )[-200:]

    merged_sessions = merged.get("sessions", {})
    for session_id, current_session in current.get("sessions", {}).items():
        if not isinstance(current_session, dict):
            continue
        baseline_session = baseline.get("sessions", {}).get(session_id)
        if baseline_session == current_session:
            continue
        durable_session = merged_sessions.get(session_id, {})
        durable_steps = (
            list(durable_session.get("steps", []))
            if isinstance(durable_session, dict)
            else []
        )
        for step in current_session.get("steps", []):
            if step not in durable_steps:
                durable_steps.append(step)
        started_values = [
            str(value)
            for value in (
                durable_session.get("started") if isinstance(durable_session, dict) else None,
                current_session.get("started"),
            )
            if value
        ]
        last_values = [
            str(value)
            for value in (
                durable_session.get("last") if isinstance(durable_session, dict) else None,
                current_session.get("last"),
            )
            if value
        ]
        merged_sessions[session_id] = {
            "steps": durable_steps,
            "started": min(started_values) if started_values else None,
            "last": max(last_values) if last_values else None,
        }
    if len(merged_sessions) > 500:
        ordered = sorted(
            merged_sessions,
            key=lambda key: str(merged_sessions[key].get("last", "")),
        )
        for session_id in ordered[: len(merged_sessions) - 500]:
            del merged_sessions[session_id]

    first_events = [
        str(value)
        for value in (merged.get("first_event"), current.get("first_event"))
        if value
    ]
    merged["first_event"] = min(first_events) if first_events else None
    return merged


def _get_blob_client():
    """Return an Azure BlobClient for metrics persistence, or None.

    Auth priority:
      1. RBAC via DefaultAzureCredential (production — managed identity)
      2. Connection string (local dev / legacy)
    """
    if not AZURE_STORAGE_ACCOUNT_URL and not AZURE_STORAGE_CONNECTION_STRING:
        return None
    try:
        from azure.storage.blob import BlobServiceClient

        if AZURE_STORAGE_ACCOUNT_URL:
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential(
                managed_identity_client_id=AZURE_STORAGE_MANAGED_IDENTITY_CLIENT_ID or None
            )
            bsc = BlobServiceClient(AZURE_STORAGE_ACCOUNT_URL, credential=credential)
            logger.debug("Using RBAC auth for blob storage")
        else:
            bsc = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
            logger.debug("Using connection string auth for blob storage")

        container = bsc.get_container_client(METRICS_BLOB_CONTAINER)
        try:
            container.get_container_properties()
        except Exception:
            container.create_container()
            logger.info("Created blob container '%s' for metrics", METRICS_BLOB_CONTAINER)
        return container.get_blob_client(METRICS_BLOB_NAME)
    except Exception as exc:
        logger.warning("Failed to create blob client: %s", exc)
        return None


def _serialize_metrics_locked() -> str:
    scrubber = globals().get("_scrub_durable_purges_locked")
    if scrubber is not None:
        scrubber()
    pruner = globals().get("_prune_daily_metrics")
    if pruner is not None:
        pruner()
    return json.dumps(_metrics, indent=2, default=str)


def _blob_conflict(exc: Exception) -> bool:
    try:
        from azure.core.exceptions import ResourceExistsError, ResourceModifiedError

        if isinstance(exc, (ResourceExistsError, ResourceModifiedError)):
            return True
    except ImportError:
        pass
    return getattr(exc, "status_code", None) in {409, 412}


def _serialize_candidate_locked(
    candidate: Dict[str, Any],
) -> tuple[Dict[str, Any], str]:
    global _metrics
    previous = _metrics
    _metrics = candidate
    try:
        payload = _serialize_metrics_locked()
        return copy.deepcopy(_metrics), payload
    finally:
        _metrics = previous


def _save_blob_optimistically_locked(
    blob,
    *,
    current: Dict[str, Any],
    baseline: Dict[str, Any],
) -> Dict[str, Any]:
    """CAS process deltas into the latest Blob generation."""
    from azure.core import MatchConditions
    from azure.core.exceptions import ResourceNotFoundError
    from circuit_breakers import blob_breaker

    last_conflict: Optional[Exception] = None
    for _attempt in range(_BLOB_WRITE_MAX_ATTEMPTS):
        try:
            downloader = blob_breaker.call(blob.download_blob)
            remote = _decode_metrics_payload(
                downloader.readall(),
                source="Azure Blob Storage",
            )
            etag = downloader.properties.etag
        except ResourceNotFoundError:
            remote = copy.deepcopy(_DEFAULT_METRICS)
            etag = None

        # Re-apply SQL tombstones after selecting the generation. If another
        # replica commits a purge after this point, one of the conditional
        # writes wins and the loser retries through this scrub path.
        candidate, payload = _serialize_candidate_locked(
            _merge_metrics_generations(remote, current, baseline)
        )
        try:
            if etag is None:
                blob_breaker.call(blob.upload_blob, payload, overwrite=False)
            else:
                blob_breaker.call(
                    blob.upload_blob,
                    payload,
                    overwrite=True,
                    etag=etag,
                    match_condition=MatchConditions.IfNotModified,
                )
            return candidate
        except Exception as exc:
            if not _blob_conflict(exc):
                raise
            last_conflict = exc

    raise UsageMetricsPersistenceError(
        "Usage metrics Blob changed during every bounded conditional write attempt"
    ) from last_conflict


def _load_metrics(*, prefer_blob: bool = True):
    """Load metrics from Azure Blob Storage (primary) or local disk (fallback)."""
    global _blob_metrics_baseline, _metrics, _metrics_baseline
    with _lock:
        # 1. Try Azure Blob Storage
        blob = _get_blob_client() if prefer_blob else None
        if blob:
            try:
                from circuit_breakers import blob_breaker

                data = blob_breaker.call(lambda: blob.download_blob().readall())
                _metrics = _decode_metrics_payload(data, source="Azure Blob Storage")
                _ensure_keys(_metrics)
                scrubber = globals().get("_scrub_durable_purges_locked")
                if scrubber is not None:
                    scrubber()
                _metrics_baseline = copy.deepcopy(_metrics)
                _blob_metrics_baseline = copy.deepcopy(_metrics)
                logger.info("Loaded usage metrics from Azure Blob Storage")
                return
            except Exception as exc:
                logger.info(
                    "Blob load skipped error_type=%s — trying local file",
                    type(exc).__name__,
                )

        # 2. Fallback to one stable local generation.
        try:
            local_payload = _read_local_metrics_file()
            if local_payload is not None:
                _metrics = local_payload
                _ensure_keys(_metrics)
                scrubber = globals().get("_scrub_durable_purges_locked")
                if scrubber is not None:
                    scrubber()
                logger.info("Loaded usage metrics from local disk")
            else:
                _metrics = json.loads(json.dumps(_DEFAULT_METRICS))
        except UsageMetricsPersistenceError as exc:
            logger.warning(
                "Failed to load stable metrics from disk error_type=%s",
                type(exc).__name__,
            )
            _metrics = json.loads(json.dumps(_DEFAULT_METRICS))
        scrubber = globals().get("_scrub_durable_purges_locked")
        if scrubber is not None:
            scrubber()
        _metrics_baseline = copy.deepcopy(_metrics)


def _save_metrics(*, require_all: bool = False) -> bool:
    """Persist metrics to Azure Blob Storage (primary) and local disk (fallback)."""
    global _blob_metrics_baseline, _dirty, _metrics, _metrics_baseline
    with _lock:
        process_metrics = copy.deepcopy(_metrics)
        process_baseline = copy.deepcopy(
            _metrics_baseline or _DEFAULT_METRICS
        )
        blob_required = bool(
            AZURE_STORAGE_ACCOUNT_URL or AZURE_STORAGE_CONNECTION_STRING
        )
        blob_saved = not blob_required
        blob_candidate: Optional[Dict[str, Any]] = None
        disk_saved = False

        blob = _get_blob_client()
        # The file lock covers merge + scrub + atomic replacement. With Blob
        # configured, its ETag-merged generation is canonical and is mirrored
        # byte-for-byte to local backup. It also orders Blob/local generations
        # among workers sharing this volume so the mirror cannot move backward.
        try:
            with _metrics_file_lock(exclusive=True):
                if blob:
                    try:
                        blob_candidate = _save_blob_optimistically_locked(
                            blob,
                            current=process_metrics,
                            baseline=(
                                _blob_metrics_baseline
                                or process_baseline
                            ),
                        )
                        _blob_metrics_baseline = copy.deepcopy(blob_candidate)
                        blob_saved = True
                        logger.debug("Saved usage metrics to Azure Blob Storage")
                    except Exception as exc:
                        logger.warning(
                            "Conditional Blob save failed error_type=%s — local fallback retained",
                            type(exc).__name__,
                        )
                if blob_candidate is not None:
                    candidate = copy.deepcopy(blob_candidate)
                else:
                    if os.path.exists(METRICS_FILE):
                        try:
                            with open(METRICS_FILE, "rb") as file_handle:
                                durable_metrics = _decode_metrics_payload(
                                    file_handle.read(),
                                    source="local disk",
                                )
                        except OSError as exc:
                            raise UsageMetricsPersistenceError(
                                "Failed to read the usage metrics file before merge"
                            ) from exc
                    else:
                        durable_metrics = copy.deepcopy(_DEFAULT_METRICS)
                    candidate = _merge_metrics_generations(
                        durable_metrics,
                        process_metrics,
                        process_baseline,
                    )
                _metrics = candidate
                payload = _serialize_metrics_locked()
                _atomic_replace_local_metrics(payload)
                _metrics_baseline = copy.deepcopy(_metrics)
            disk_saved = True
        except UsageMetricsPersistenceError as exc:
            logger.warning(
                "Failed to atomically save metrics to disk error_type=%s",
                type(exc).__name__,
            )

        if require_all and not (blob_saved and disk_saved):
            raise UsageMetricsPersistenceError(
                "Usage telemetry purge persistence could not be confirmed"
            )
        saved = disk_saved or (blob_required and blob_saved)
        if saved:
            _dirty = False
        return saved


def _mark_dirty():
    """Flag that in-memory metrics have changed and need persisting."""
    global _dirty
    _dirty = True


# ─────────────────────────────────────────────────────────────
# Background flush thread + shutdown handler
# ─────────────────────────────────────────────────────────────
def _background_flush():
    """Daemon thread: flush dirty metrics to storage every _flush_interval s."""
    while not _shutdown_event.is_set():
        _shutdown_event.wait(_flush_interval)
        if _dirty:
            with _lock:
                try:
                    _save_metrics()
                except Exception as exc:
                    logger.warning("Background flush failed: %s", exc)


def _shutdown_flush(*_args):
    """Flush metrics on interpreter exit or SIGTERM."""
    _shutdown_event.set()  # Signal background thread to stop
    with _lock:
        if _dirty:
            try:
                _save_metrics()
                logger.info("Flushed metrics on shutdown")
            except Exception as exc:
                logger.warning("Shutdown flush failed: %s", exc)


# Load on import without external storage I/O so API startup remains probeable.
_load_metrics(prefer_blob=False)

# Start background flush daemon
_flush_thread = threading.Thread(target=_background_flush, daemon=True, name="metrics-flush")
_flush_thread.start()

# Register shutdown handlers
atexit.register(_shutdown_flush)
try:
    _prev_sigterm_handler = signal.getsignal(signal.SIGTERM)

    def _chained_sigterm_handler(*args):
        _shutdown_flush(*args)
        if callable(_prev_sigterm_handler) and _prev_sigterm_handler not in (signal.SIG_DFL, signal.SIG_IGN):
            _prev_sigterm_handler(*args)

    signal.signal(signal.SIGTERM, _chained_sigterm_handler)
except (OSError, ValueError):
    # signal.signal fails if not called from main thread (e.g. in tests)
    pass


# ─────────────────────────────────────────────────────────────
# Daily metrics pruning (#103 — S-020)
# ─────────────────────────────────────────────────────────────
_MAX_DAILY_DAYS = 90
_TELEMETRY_ID_SALT = b"archmorph-telemetry-id-v1"


def _retained_identifier(value: object) -> str:
    """Return a stable non-reversible identifier for 90-day usage retention."""
    return hashlib.sha256(
        _TELEMETRY_ID_SALT + b"\0" + str(value).encode("utf-8")
    ).hexdigest()[:24]


def _sanitize_event_details(details: Optional[Dict]) -> Dict:
    sanitized: Dict[str, Any] = {}
    for key, value in (details or {}).items():
        if key in {
            "diagram_id",
            "project_id",
            "session_id",
            "owner_user_id",
            "tenant_id",
        }:
            sanitized[f"{key}_hash"] = _retained_identifier(value)
        elif key in {"filename", "prompt", "message", "content", "reason"}:
            sanitized[f"{key}_sha256"] = _retained_identifier(value)
        else:
            sanitized[key] = value
    return sanitized


def _subject_targets(
    *,
    diagram_id: Optional[str] = None,
    project_id: Optional[str] = None,
    owner_user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Dict[str, set[str]]:
    raw_values = {
        str(value)
        for value in (diagram_id, project_id, owner_user_id, tenant_id)
        if value
    }
    hashed_values = {_retained_identifier(value) for value in raw_values}
    session_values: set[str] = set()
    if diagram_id:
        session_values.update({diagram_id, _retained_identifier(diagram_id)})
    if project_id:
        project_session = f"project-{project_id}"
        session_values.update(
            {
                project_id,
                project_session,
                _retained_identifier(project_id),
                _retained_identifier(project_session),
            }
        )
    return {
        "raw": raw_values,
        "hashed": hashed_values,
        "sessions": session_values,
        "diagram": (
            {diagram_id, _retained_identifier(diagram_id)} if diagram_id else set()
        ),
        "project": (
            {project_id, _retained_identifier(project_id)} if project_id else set()
        ),
        "owner": (
            {owner_user_id, _retained_identifier(owner_user_id)}
            if owner_user_id
            else set()
        ),
        "tenant": (
            {tenant_id, _retained_identifier(tenant_id)} if tenant_id else set()
        ),
    }


def _event_matches_targets(event: object, targets: Dict[str, set[str]]) -> bool:
    if not isinstance(event, dict):
        return False
    details = event.get("details")
    if not isinstance(details, dict):
        return False
    key_targets = {
        "diagram_id": targets["diagram"],
        "diagram_id_hash": targets["diagram"],
        "project_id": targets["project"],
        "project_id_hash": targets["project"],
        "session_id": targets["sessions"],
        "session_id_hash": targets["sessions"],
        "owner_user_id": targets["owner"],
        "owner_user_id_hash": targets["owner"],
        "tenant_id": targets["tenant"],
        "tenant_id_hash": targets["tenant"],
    }
    primary_keys = {
        "diagram_id",
        "diagram_id_hash",
        "project_id",
        "project_id_hash",
        "session_id",
        "session_id_hash",
    }
    primary_match = any(
        str(details.get(key)) in values
        for key, values in key_targets.items()
        if key in primary_keys and values and details.get(key) is not None
    )
    if targets["diagram"] or targets["project"] or targets["sessions"]:
        return primary_match
    return any(
        str(details.get(key)) in values
        for key, values in key_targets.items()
        if key not in primary_keys and values and details.get(key) is not None
    )


def _scrub_subject_locked(
    *,
    diagram_id: Optional[str] = None,
    project_id: Optional[str] = None,
    owner_user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Dict[str, int]:
    """Remove reconstructable subject telemetry while retaining aggregates."""
    targets = _subject_targets(
        diagram_id=diagram_id,
        project_id=project_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    sessions = _metrics.get("sessions", {})
    removed_sessions = 0
    if isinstance(sessions, dict):
        for session_id in list(sessions):
            if str(session_id) in targets["sessions"]:
                del sessions[session_id]
                removed_sessions += 1
    events = _metrics.get("recent_events", [])
    retained_events = [
        event for event in events if not _event_matches_targets(event, targets)
    ]
    removed_events = len(events) - len(retained_events)
    _metrics["recent_events"] = retained_events
    if removed_sessions or removed_events:
        _mark_dirty()
    return {"sessions": removed_sessions, "events": removed_events}


def _operation_purge_scopes(operation) -> List[Dict[str, str]]:
    scope = {
        "owner_user_id": operation.owner_user_id,
        "tenant_id": operation.tenant_id,
    }
    scopes: List[Dict[str, str]] = []
    if operation.scope_type == "diagram":
        scope["diagram_id"] = operation.scope_id
    else:
        scope["project_id"] = operation.scope_id
        try:
            manifest = json.loads(operation.manifest or "{}")
        except (TypeError, ValueError):
            manifest = {}
        for diagram_id in manifest.get("diagram_ids", []):
            scopes.append({**scope, "diagram_id": str(diagram_id)})
    scopes.append(scope)
    return scopes


def _scrub_durable_purges_locked() -> bool:
    """Apply all tombstones through memory-bounded, indexed cursor batches."""
    db = None
    try:
        from database import SessionLocal
        from models.workspace import PurgeOperation

        db = SessionLocal()
        changed = False
        for purge_status in ("in_progress", "failed", "completed"):
            cursor: Optional[str] = None
            while True:
                query = db.query(PurgeOperation).filter(
                    PurgeOperation.status == purge_status
                )
                if cursor is not None:
                    query = query.filter(PurgeOperation.id > cursor)
                operations = (
                    query.order_by(PurgeOperation.id.asc())
                    .limit(_PURGE_SCAN_BATCH_SIZE)
                    .all()
                )
                if not operations:
                    break
                for operation in operations:
                    for scope in _operation_purge_scopes(operation):
                        counts = _scrub_subject_locked(**scope)
                        changed = changed or bool(
                            counts["sessions"] or counts["events"]
                        )
                cursor = str(operations[-1].id)
        return changed
    except Exception:
        try:
            from database import _PRODUCTION_LIKE
        except Exception:
            _PRODUCTION_LIKE = False
        if not _PRODUCTION_LIKE:
            return False
        # In production, loss of the tombstone authority must not republish
        # pseudonymous sessions or event details from stale process memory.
        removed = bool(_metrics.get("sessions") or _metrics.get("recent_events"))
        _metrics["sessions"] = {}
        _metrics["recent_events"] = []
        if removed:
            _mark_dirty()
        return removed
    finally:
        if db is not None:
            db.close()


@contextmanager
def _subject_write_fence(
    *,
    diagram_id: Optional[str] = None,
    project_id: Optional[str] = None,
):
    """Hold SQL lifecycle authority through one in-process telemetry write."""
    if not diagram_id and not project_id:
        yield True
        return
    db = None
    allowed = True
    try:
        from database import SessionLocal, _PRODUCTION_LIKE
        from models.workspace import DiagramLifecycle, PurgeOperation, Workspace

        db = SessionLocal()
        operation_query = db.query(PurgeOperation.id).filter(
            PurgeOperation.status.in_(("in_progress", "failed", "completed"))
        )
        if diagram_id:
            operation_query = operation_query.filter(
                PurgeOperation.scope_type == "diagram",
                PurgeOperation.scope_id == diagram_id,
            )
        elif project_id:
            operation_query = operation_query.filter(
                PurgeOperation.scope_type == "workspace",
                PurgeOperation.scope_id == project_id,
            )
        if db.get_bind().dialect.name == "postgresql":
            operation_query = operation_query.with_for_update(read=True)
        if operation_query.first() is not None:
            allowed = False
        elif project_id:
            workspace_query = db.query(Workspace).filter(Workspace.id == project_id)
            if db.get_bind().dialect.name == "postgresql":
                workspace_query = workspace_query.with_for_update(read=True)
            workspace = workspace_query.one_or_none()
            allowed = workspace is None or workspace.status == "active"
        else:
            lifecycle_identity = (
                db.query(DiagramLifecycle.workspace_id)
                .filter(DiagramLifecycle.diagram_id == diagram_id)
                .first()
            )
            workspace = None
            if lifecycle_identity is not None and lifecycle_identity.workspace_id:
                workspace_query = db.query(Workspace).filter(
                    Workspace.id == lifecycle_identity.workspace_id
                )
                if db.get_bind().dialect.name == "postgresql":
                    workspace_query = workspace_query.with_for_update(read=True)
                workspace = workspace_query.one_or_none()
            lifecycle_query = db.query(DiagramLifecycle).filter(
                DiagramLifecycle.diagram_id == diagram_id
            )
            if db.get_bind().dialect.name == "postgresql":
                lifecycle_query = lifecycle_query.with_for_update(read=True)
            lifecycles = lifecycle_query.all()
            allowed = bool(
                all(lifecycle.state == "active" for lifecycle in lifecycles)
                and (workspace is None or workspace.status == "active")
            )
    except Exception:
        if db is not None:
            db.rollback()
        try:
            production_like = _PRODUCTION_LIKE
        except NameError:
            production_like = False
        allowed = not production_like

    try:
        yield allowed
        if db is not None:
            db.commit()
    except Exception:
        if db is not None:
            db.rollback()
        raise
    finally:
        if db is not None:
            db.close()


def _record_aggregate_locked(event_type: str, now: datetime) -> None:
    today = now.strftime("%Y-%m-%d")
    if event_type in _metrics["counters"]:
        _metrics["counters"][event_type] += 1
    else:
        _metrics["counters"][event_type] = 1
    if today not in _metrics["daily"]:
        _metrics["daily"][today] = {}
    daily = _metrics["daily"][today]
    daily[event_type] = daily.get(event_type, 0) + 1
    _prune_daily_metrics()
    if not _metrics["first_event"]:
        _metrics["first_event"] = now.isoformat()
    _mark_dirty()


def _prune_daily_metrics():
    """Remove daily metric entries older than _MAX_DAILY_DAYS to prevent unbounded growth."""
    if "daily" not in _metrics:
        return
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_MAX_DAILY_DAYS)).strftime("%Y-%m-%d")
    stale = [d for d in _metrics["daily"] if d < cutoff]
    for d in stale:
        del _metrics["daily"][d]
    if stale:
        logger.debug("Pruned %d stale daily metric entries (before %s)", len(stale), cutoff)


# ─────────────────────────────────────────────────────────────
# Record events (simple counters)
# ─────────────────────────────────────────────────────────────
def record_event(event_type: str, details: Optional[Dict] = None):
    """
    Record a usage event and increment counters.

    event_type: One of the counter keys (e.g. 'analyses_run', 'chat_messages')
    details: Optional metadata (diagram_id, format, etc.)
    """
    raw_details = details or {}
    diagram_id = raw_details.get("diagram_id")
    project_id = raw_details.get("project_id")
    with _subject_write_fence(
        diagram_id=str(diagram_id) if diagram_id else None,
        project_id=str(project_id) if project_id else None,
    ) as details_allowed:
        with _lock:
            now = datetime.now(timezone.utc)
            _record_aggregate_locked(event_type, now)
            if not details_allowed:
                return
            event = {
                "type": event_type,
                "timestamp": now.isoformat(),
                "details": _sanitize_event_details(details),
            }
            _metrics["recent_events"].append(event)
            if len(_metrics["recent_events"]) > 200:
                _metrics["recent_events"] = _metrics["recent_events"][-200:]


# ─────────────────────────────────────────────────────────────
# Funnel tracking (session-based)
# ─────────────────────────────────────────────────────────────
def record_funnel_step(diagram_id: str, step: str):
    """
    Record that a user session reached a funnel step.
    Steps: upload → analyze → questions → answers → iac_generate → export
    Each step is recorded at most once per session.
    """
    if step not in FUNNEL_STEPS:
        return

    project_id = (
        diagram_id.removeprefix("project-")
        if diagram_id.startswith("project-")
        else None
    )
    with _subject_write_fence(
        diagram_id=None if project_id else diagram_id,
        project_id=project_id,
    ) as session_allowed:
        if not session_allowed:
            return
        retained_diagram_id = _retained_identifier(diagram_id)
        with _lock:
            now = datetime.now(timezone.utc).isoformat()
            sessions = _metrics["sessions"]

            if retained_diagram_id not in sessions:
                sessions[retained_diagram_id] = {
                    "steps": [],
                    "started": now,
                    "last": now,
                }

            session = sessions[retained_diagram_id]

            # Only record each step once per session
            if step not in session["steps"]:
                session["steps"].append(step)
                session["last"] = now
                _metrics["funnel_totals"][step] = (
                    _metrics["funnel_totals"].get(step, 0) + 1
                )
                _mark_dirty()

            # Prune old sessions (keep last 500)
            if len(sessions) > 500:
                sorted_ids = sorted(sessions, key=lambda k: sessions[k]["last"])
                for old_id in sorted_ids[: len(sessions) - 500]:
                    del sessions[old_id]


def _payload_subject_absent(
    payload: Dict[str, Any],
    *,
    diagram_id: Optional[str] = None,
    project_id: Optional[str] = None,
    owner_user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> bool:
    targets = _subject_targets(
        diagram_id=diagram_id,
        project_id=project_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    subject_values = set().union(
        targets["diagram"],
        targets["project"],
        targets["sessions"],
    )
    if not subject_values:
        subject_values.update(targets["owner"])
        subject_values.update(targets["tenant"])
    serialized = json.dumps(payload, sort_keys=True, default=str)
    return all(value not in serialized for value in subject_values if value)


def purge_usage_telemetry(
    *,
    owner_user_id: str,
    tenant_id: str,
    diagram_id: Optional[str] = None,
    project_id: Optional[str] = None,
) -> Dict[str, int]:
    """Erase subject telemetry and persist only non-identifying aggregates."""
    if not diagram_id and not project_id:
        raise ValueError("A diagram or project scope is required")
    from database import SessionLocal
    from models.usage import FunnelStepRecord, UsageCounterRecord
    from sqlalchemy import and_, or_

    targets = _subject_targets(diagram_id=diagram_id, project_id=project_id)
    scope_ids = targets["sessions"]
    db = SessionLocal()
    try:
        funnel_deleted = (
            db.query(FunnelStepRecord)
            .filter(
                FunnelStepRecord.diagram_id.in_(scope_ids),
                or_(
                    and_(
                        FunnelStepRecord.owner_user_id == owner_user_id,
                        FunnelStepRecord.tenant_id == tenant_id,
                    ),
                    and_(
                        FunnelStepRecord.owner_user_id.is_(None),
                        FunnelStepRecord.tenant_id.is_(None),
                    ),
                ),
            )
            .delete(synchronize_session=False)
        )
        counters_unscoped = (
            db.query(UsageCounterRecord)
            .filter(
                UsageCounterRecord.owner_user_id == owner_user_id,
                UsageCounterRecord.tenant_id == tenant_id,
            )
            .update(
                {
                    UsageCounterRecord.owner_user_id: None,
                    UsageCounterRecord.tenant_id: None,
                },
                synchronize_session=False,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    with _lock:
        removed = _scrub_subject_locked(
            diagram_id=diagram_id,
            project_id=project_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        )
        _save_metrics(require_all=True)
    return {
        "sessions": removed["sessions"],
        "events": removed["events"],
        "funnel_rows": int(funnel_deleted or 0),
        "counter_scopes_removed": int(counters_unscoped or 0),
    }


def usage_telemetry_absent(
    *,
    owner_user_id: str,
    tenant_id: str,
    diagram_id: Optional[str] = None,
    project_id: Optional[str] = None,
) -> bool:
    """Confirm absence in SQL, process memory, and configured persistence."""
    from database import SessionLocal
    from models.usage import FunnelStepRecord, UsageCounterRecord
    from sqlalchemy import and_, or_

    targets = _subject_targets(diagram_id=diagram_id, project_id=project_id)
    db = SessionLocal()
    try:
        scoped_funnel = (
            db.query(FunnelStepRecord.id)
            .filter(
                FunnelStepRecord.diagram_id.in_(targets["sessions"]),
                or_(
                    and_(
                        FunnelStepRecord.owner_user_id == owner_user_id,
                        FunnelStepRecord.tenant_id == tenant_id,
                    ),
                    and_(
                        FunnelStepRecord.owner_user_id.is_(None),
                        FunnelStepRecord.tenant_id.is_(None),
                    ),
                ),
            )
            .first()
        )
        scoped_counter = (
            db.query(UsageCounterRecord.id)
            .filter(
                UsageCounterRecord.owner_user_id == owner_user_id,
                UsageCounterRecord.tenant_id == tenant_id,
            )
            .first()
        )
        if scoped_funnel is not None or scoped_counter is not None:
            return False
    finally:
        db.close()

    with _lock:
        if not _payload_subject_absent(
            _metrics,
            diagram_id=diagram_id,
            project_id=project_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        ):
            return False

    payloads: list[Dict[str, Any]] = []
    local_payload = _read_local_metrics_file()
    if local_payload is not None:
        payloads.append(local_payload)
    if AZURE_STORAGE_ACCOUNT_URL or AZURE_STORAGE_CONNECTION_STRING:
        blob = _get_blob_client()
        if blob is None:
            raise UsageMetricsPersistenceError(
                "Configured usage metrics Blob client is unavailable"
            )
        try:
            from circuit_breakers import blob_breaker

            payloads.append(
                _decode_metrics_payload(
                    blob_breaker.call(lambda: blob.download_blob().readall()),
                    source="Azure Blob Storage",
                )
            )
        except UsageMetricsPersistenceError:
            raise
        except Exception as exc:
            raise UsageMetricsPersistenceError(
                "Failed to verify the configured usage metrics Blob"
            ) from exc
    return all(
        _payload_subject_absent(
            payload,
            diagram_id=diagram_id,
            project_id=project_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        )
        for payload in payloads
    )


def apply_durable_purge_fences() -> bool:
    """Scrub stale loaded process state after database startup/restart."""
    with _lock:
        return _scrub_durable_purges_locked()


# ─────────────────────────────────────────────────────────────
# Query metrics
# ─────────────────────────────────────────────────────────────
def get_metrics_summary() -> Dict[str, Any]:
    """Return aggregate usage metrics."""
    with _lock:
        _scrub_durable_purges_locked()
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        total_events = sum(_metrics["counters"].values())

        days_active = len(_metrics["daily"]) or 1
        daily_avg = round(total_events / days_active, 1)

        today_stats = _metrics["daily"].get(today, {})
        today_total = sum(today_stats.values())

        return {
            "totals": _metrics["counters"],
            "total_events": total_events,
            "days_active": days_active,
            "daily_average": daily_avg,
            "today": {
                "date": today,
                "events": today_total,
                "breakdown": today_stats,
            },
            "first_event": _metrics["first_event"],
            "last_event": _metrics["recent_events"][-1]["timestamp"] if _metrics["recent_events"] else None,
        }


def get_funnel_metrics() -> Dict[str, Any]:
    """
    Return conversion funnel data.
    Shows how many sessions reached each step and drop-off between steps.
    """
    with _lock:
        _scrub_durable_purges_locked()
        sessions = _metrics["sessions"]
        total_sessions = len(sessions)

        # Count sessions at each step
        step_counts = {s: 0 for s in FUNNEL_STEPS}
        for sid, sess in sessions.items():
            for step in sess["steps"]:
                if step in step_counts:
                    step_counts[step] += 1

        # Build funnel with conversion rates (always relative to first step)
        base_count = step_counts[FUNNEL_STEPS[0]] if step_counts[FUNNEL_STEPS[0]] > 0 else max(total_sessions, 1)
        funnel = []
        for i, step in enumerate(FUNNEL_STEPS):
            count = step_counts[step]
            # Conversion rate: percentage of sessions that reached this step
            # relative to sessions that reached the previous step
            prev_count = step_counts[FUNNEL_STEPS[i - 1]] if i > 0 else base_count
            conversion = round((count / max(prev_count, 1) * 100), 1) if i > 0 else 100.0
            # Cap conversion at 100% — if users skip steps, the later step
            # may have more sessions than an intermediate step
            conversion = min(conversion, 100.0)
            drop_off = max(prev_count - count, 0) if i > 0 else 0

            funnel.append({
                "step": step,
                "label": FUNNEL_LABELS[step],
                "count": count,
                "conversion_rate": conversion,
                "drop_off": drop_off,
                "pct_of_total": round((count / base_count * 100), 1) if base_count > 0 else 0.0,
            })

        # Completion rate
        completed = step_counts.get("iac_generate", 0)
        completion_rate = round((completed / total_sessions * 100), 1) if total_sessions > 0 else 0.0

        # Find biggest drop-off
        max_drop = max(funnel, key=lambda f: f["drop_off"]) if funnel else None
        bottleneck = max_drop["label"] if max_drop and max_drop["drop_off"] > 0 else None

        # Recent sessions (last 20)
        sorted_sessions = sorted(
            sessions.items(),
            key=lambda x: x[1]["last"],
            reverse=True,
        )[:20]

        recent_sessions = []
        for sid, sess in sorted_sessions:
            last_step_idx = -1
            for step in sess["steps"]:
                if step in FUNNEL_STEPS:
                    idx = FUNNEL_STEPS.index(step)
                    if idx > last_step_idx:
                        last_step_idx = idx
            farthest = FUNNEL_STEPS[last_step_idx] if last_step_idx >= 0 else "unknown"
            recent_sessions.append({
                "session_id": sid,
                "steps_completed": len(sess["steps"]),
                "farthest_step": FUNNEL_LABELS.get(farthest, farthest),
                "started": sess["started"],
                "last_activity": sess["last"],
                "completed": "iac_generate" in sess["steps"],
            })

        return {
            "total_sessions": total_sessions,
            "completion_rate": completion_rate,
            "bottleneck": bottleneck,
            "funnel": funnel,
            "recent_sessions": recent_sessions,
        }


def get_daily_metrics(days: int = 30) -> List[Dict[str, Any]]:
    """Return daily metrics for the last N days."""
    with _lock:
        _scrub_durable_purges_locked()
        now = datetime.now(timezone.utc)
        result = []
        for i in range(days):
            date = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            day_data = _metrics["daily"].get(date, {})
            result.append({
                "date": date,
                "total": sum(day_data.values()),
                "breakdown": day_data,
            })
        return list(reversed(result))


def get_recent_events(limit: int = 50) -> List[Dict[str, Any]]:
    """Return the most recent events."""
    with _lock:
        _scrub_durable_purges_locked()
        return list(reversed(_metrics["recent_events"][-limit:]))


def flush_metrics():
    """Force-save metrics to disk."""
    with _lock:
        _save_metrics()
