"""
Archmorph Usage Metrics — Admin-only analytics with funnel tracking.

Tracks: user sessions through the conversion funnel (upload → analyze →
questions → answers → IaC → export), drop-off points, completion rates,
daily activity, and recent events.  Designed for the admin dashboard only.
"""

import json
import os
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from threading import Lock

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
METRICS_FILE = os.path.join(DATA_DIR, "usage_metrics.json")

# Admin secret – MUST be set via env var in production
ADMIN_SECRET = os.getenv("ARCHMORPH_ADMIN_KEY", "")

_lock = Lock()

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


def _load_metrics():
    """Load metrics from disk."""
    global _metrics
    if os.path.exists(METRICS_FILE):
        try:
            with open(METRICS_FILE, "r") as f:
                _metrics = json.load(f)
            _ensure_keys(_metrics)
            logger.info("Loaded usage metrics from disk")
        except Exception as exc:
            logger.warning(f"Failed to load metrics: {exc}")
            _metrics = json.loads(json.dumps(_DEFAULT_METRICS))
    else:
        _metrics = json.loads(json.dumps(_DEFAULT_METRICS))


def _save_metrics():
    """Persist metrics to disk."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(METRICS_FILE, "w") as f:
            json.dump(_metrics, f, indent=2, default=str)
    except Exception as exc:
        logger.warning(f"Failed to save metrics: {exc}")


# Load on import
_load_metrics()


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

        # Save periodically (every 10 events)
        total = sum(_metrics["counters"].values())
        if total % 10 == 0:
            _save_metrics()


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

        # Build funnel with conversion rates
        funnel = []
        for i, step in enumerate(FUNNEL_STEPS):
            count = step_counts[step]
            prev_count = step_counts[FUNNEL_STEPS[i - 1]] if i > 0 else total_sessions
            conversion = round((count / prev_count * 100), 1) if prev_count > 0 else 0.0
            drop_off = prev_count - count if i > 0 else 0

            funnel.append({
                "step": step,
                "label": FUNNEL_LABELS[step],
                "count": count,
                "conversion_rate": conversion,
                "drop_off": drop_off,
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
