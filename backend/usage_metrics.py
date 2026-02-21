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
import json
import os
import logging
import signal
import threading
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone
from threading import Lock

logger = logging.getLogger(__name__)

_shutdown_event = threading.Event()

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
METRICS_FILE = os.path.join(DATA_DIR, "usage_metrics.json")

# Azure Blob Storage persistence (survives container restarts/deploys)
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
METRICS_BLOB_CONTAINER = "metrics"
METRICS_BLOB_NAME = "usage_metrics.json"

# Admin secret – MUST be set via env var in production
ADMIN_SECRET = os.getenv("ARCHMORPH_ADMIN_KEY", "")

_lock = Lock()
_dirty = False          # True when in-memory state diverges from persisted copy
_flush_interval = 30    # seconds between background flush cycles

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


def _get_blob_client():
    """Return an Azure BlobClient for metrics persistence, or None."""
    if not AZURE_STORAGE_CONNECTION_STRING:
        return None
    try:
        from azure.storage.blob import BlobServiceClient
        bsc = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
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


def _load_metrics():
    """Load metrics from Azure Blob Storage (primary) or local disk (fallback)."""
    global _metrics

    # 1. Try Azure Blob Storage
    blob = _get_blob_client()
    if blob:
        try:
            data = blob.download_blob().readall()
            _metrics = json.loads(data)
            _ensure_keys(_metrics)
            logger.info("Loaded usage metrics from Azure Blob Storage")
            return
        except Exception as exc:
            logger.info("Blob load skipped (%s) — trying local file", exc)

    # 2. Fallback to local file
    if os.path.exists(METRICS_FILE):
        try:
            with open(METRICS_FILE, "r") as f:
                _metrics = json.load(f)
            _ensure_keys(_metrics)
            logger.info("Loaded usage metrics from local disk")
        except Exception as exc:
            logger.warning("Failed to load metrics from disk: %s", exc)
            _metrics = json.loads(json.dumps(_DEFAULT_METRICS))
    else:
        _metrics = json.loads(json.dumps(_DEFAULT_METRICS))


def _save_metrics():
    """Persist metrics to Azure Blob Storage (primary) and local disk (fallback)."""
    global _dirty
    payload = json.dumps(_metrics, indent=2, default=str)

    saved = False

    # 1. Try Azure Blob Storage
    blob = _get_blob_client()
    if blob:
        try:
            blob.upload_blob(payload, overwrite=True)
            logger.debug("Saved usage metrics to Azure Blob Storage")
            saved = True
        except Exception as exc:
            logger.warning("Blob save failed (%s) — falling back to disk", exc)

    # 2. Always save to local disk as secondary backup
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(METRICS_FILE, "w") as f:
            f.write(payload)
        saved = True
    except Exception as exc:
        logger.warning("Failed to save metrics to disk: %s", exc)

    if saved:
        _dirty = False


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


# Load on import
_load_metrics()

# Start background flush daemon
_flush_thread = threading.Thread(target=_background_flush, daemon=True, name="metrics-flush")
_flush_thread.start()

# Register shutdown handlers
atexit.register(_shutdown_flush)
try:
    signal.signal(signal.SIGTERM, _shutdown_flush)
except (OSError, ValueError):
    # signal.signal fails if not called from main thread (e.g. in tests)
    pass


# ─────────────────────────────────────────────────────────────
# Record events (simple counters)
# ─────────────────────────────────────────────────────────────
def record_event(event_type: str, details: Optional[Dict] = None):
    """
    Record a usage event and increment counters.

    event_type: One of the counter keys (e.g. 'analyses_run', 'chat_messages')
    details: Optional metadata (diagram_id, format, etc.)
    """
    with _lock:
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")

        # Increment counter
        if event_type in _metrics["counters"]:
            _metrics["counters"][event_type] += 1
        else:
            _metrics["counters"][event_type] = 1

        # Increment daily counter
        if today not in _metrics["daily"]:
            _metrics["daily"][today] = {}
        daily = _metrics["daily"][today]
        daily[event_type] = daily.get(event_type, 0) + 1

        # Add to recent events (keep last 200)
        event = {
            "type": event_type,
            "timestamp": now.isoformat(),
            "details": details or {},
        }
        _metrics["recent_events"].append(event)
        if len(_metrics["recent_events"]) > 200:
            _metrics["recent_events"] = _metrics["recent_events"][-200:]

        # Track first event
        if not _metrics["first_event"]:
            _metrics["first_event"] = now.isoformat()

        _mark_dirty()


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

    with _lock:
        now = datetime.now(timezone.utc).isoformat()
        sessions = _metrics["sessions"]

        if diagram_id not in sessions:
            sessions[diagram_id] = {
                "steps": [],
                "started": now,
                "last": now,
            }

        session = sessions[diagram_id]

        # Only record each step once per session
        if step not in session["steps"]:
            session["steps"].append(step)
            session["last"] = now
            _metrics["funnel_totals"][step] = _metrics["funnel_totals"].get(step, 0) + 1
            _mark_dirty()

        # Prune old sessions (keep last 500)
        if len(sessions) > 500:
            sorted_ids = sorted(sessions, key=lambda k: sessions[k]["last"])
            for old_id in sorted_ids[:len(sessions) - 500]:
                del sessions[old_id]


# ─────────────────────────────────────────────────────────────
# Query metrics
# ─────────────────────────────────────────────────────────────
def get_metrics_summary() -> Dict[str, Any]:
    """Return aggregate usage metrics."""
    with _lock:
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
        return list(reversed(_metrics["recent_events"][-limit:]))


def flush_metrics():
    """Force-save metrics to disk."""
    with _lock:
        _save_metrics()
