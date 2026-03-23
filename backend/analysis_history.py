"""
Archmorph Analysis History — In-memory persistent history tied to user accounts (Issue #245).

Maps authenticated user_id -> list of analysis summaries. Anonymous users
are unaffected and continue using volatile session-based storage.

Thread-safe via RLock to support concurrent requests across workers.
"""

import threading
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_lock = threading.RLock()

# user_id -> list[dict]  (most recent first)
_history: Dict[str, List[Dict[str, Any]]] = {}

# diagram_id -> user_id  (for bookmark/delete lookups)
_diagram_user_map: Dict[str, str] = {}

# Max analyses per user to prevent unbounded growth
MAX_HISTORY_PER_USER = 200


def save_analysis(
    user_id: str,
    diagram_id: str,
    *,
    source_cloud: str = "aws",
    target_cloud: str = "azure",
    service_count: int = 0,
    confidence_avg: Optional[float] = None,
    title: Optional[str] = None,
    status: str = "completed",
) -> Dict[str, Any]:
    """Save an analysis summary for an authenticated user.

    Returns the saved summary dict.
    """
    summary = {
        "id": diagram_id,
        "diagram_id": diagram_id,
        "source_cloud": source_cloud,
        "target_cloud": target_cloud,
        "service_count": service_count,
        "confidence_avg": confidence_avg,
        "title": title or f"{source_cloud.upper()} → {target_cloud.upper()} migration",
        "status": status,
        "bookmarked": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    with _lock:
        user_list = _history.setdefault(user_id, [])
        # Deduplicate by diagram_id — update if exists
        for i, existing in enumerate(user_list):
            if existing["diagram_id"] == diagram_id:
                user_list[i] = summary
                _diagram_user_map[diagram_id] = user_id
                return summary

        user_list.insert(0, summary)
        _diagram_user_map[diagram_id] = user_id

        # Trim oldest if over limit
        if len(user_list) > MAX_HISTORY_PER_USER:
            removed = user_list[MAX_HISTORY_PER_USER:]
            del user_list[MAX_HISTORY_PER_USER:]
            for r in removed:
                _diagram_user_map.pop(r["diagram_id"], None)

    return summary


def list_analyses(
    user_id: str,
    *,
    limit: int = 20,
    offset: int = 0,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Dict[str, Any]:
    """List analyses for a user with pagination and optional date filtering.

    Returns {"analyses": [...], "total": int, "limit": int, "offset": int}.
    """
    with _lock:
        user_list = _history.get(user_id, [])

        filtered = user_list
        if date_from:
            filtered = [a for a in filtered if a["created_at"] >= date_from]
        if date_to:
            filtered = [a for a in filtered if a["created_at"] <= date_to]

        total = len(filtered)
        page = filtered[offset: offset + limit]

    return {
        "analyses": page,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def get_analysis(user_id: str, analysis_id: str) -> Optional[Dict[str, Any]]:
    """Get a single analysis summary by diagram_id for a user."""
    with _lock:
        for a in _history.get(user_id, []):
            if a["diagram_id"] == analysis_id or a["id"] == analysis_id:
                return a
    return None


def delete_analysis(user_id: str, analysis_id: str) -> bool:
    """Delete an analysis from a user's history. Returns True if found and removed."""
    with _lock:
        user_list = _history.get(user_id, [])
        for i, a in enumerate(user_list):
            if a["diagram_id"] == analysis_id or a["id"] == analysis_id:
                user_list.pop(i)
                _diagram_user_map.pop(analysis_id, None)
                return True
    return False


def toggle_bookmark(user_id: str, analysis_id: str) -> Optional[bool]:
    """Toggle bookmark on an analysis. Returns new bookmark state or None if not found."""
    with _lock:
        for a in _history.get(user_id, []):
            if a["diagram_id"] == analysis_id or a["id"] == analysis_id:
                a["bookmarked"] = not a.get("bookmarked", False)
                return a["bookmarked"]
    return None


def maybe_save_from_session(user_id: Optional[str], session: Dict[str, Any], diagram_id: str) -> None:
    """Hook: save analysis to history if user is authenticated.

    Call this after an analysis completes or session is stored.
    """
    if not user_id:
        return

    mappings = session.get("mappings", [])
    service_count = session.get("services_detected", len(mappings))

    confidences = [m.get("confidence", 0) for m in mappings if m.get("confidence")]
    confidence_avg = round(sum(confidences) / len(confidences), 2) if confidences else None

    source_cloud = session.get("source_provider", "aws")
    target_cloud = session.get("target_provider", "azure")

    save_analysis(
        user_id=user_id,
        diagram_id=diagram_id,
        source_cloud=source_cloud,
        target_cloud=target_cloud,
        service_count=service_count,
        confidence_avg=confidence_avg,
        status="completed",
    )
