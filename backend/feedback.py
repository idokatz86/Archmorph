"""
Archmorph Feedback & NPS — User feedback collection and Net Promoter Score tracking.

Supports:
- NPS surveys (0-10 scale with follow-up)
- Feature feedback (thumbs up/down + comments)
- Bug reports with context capture
- Analytics aggregation
"""

import copy
import json
import os
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from threading import Lock
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
FEEDBACK_FILE = os.path.join(DATA_DIR, "feedback.json")

# Maximum entries kept per feedback list to prevent unbounded memory growth (#163)
_MAX_NPS_RESPONSES = 5000
_MAX_FEATURE_FEEDBACK = 5000
_MAX_BUG_REPORTS = 2000
_MAX_GENERAL_COMMENTS = 2000

_lock = Lock()


class FeedbackType(str, Enum):
    NPS = "nps"
    FEATURE = "feature"
    BUG = "bug"
    GENERAL = "general"


class NPSCategory(str, Enum):
    PROMOTER = "promoter"  # 9-10
    PASSIVE = "passive"    # 7-8
    DETRACTOR = "detractor"  # 0-6


@dataclass
class NPSResponse:
    score: int  # 0-10
    follow_up: Optional[str]
    timestamp: str
    session_id: Optional[str]
    feature_context: Optional[str]  # e.g., "iac_export", "diagram_analysis"
    
    @property
    def category(self) -> NPSCategory:
        if self.score >= 9:
            return NPSCategory.PROMOTER
        elif self.score >= 7:
            return NPSCategory.PASSIVE
        return NPSCategory.DETRACTOR


@dataclass
class FeatureFeedback:
    feature: str
    helpful: bool  # True = thumbs up, False = thumbs down
    comment: Optional[str]
    timestamp: str
    session_id: Optional[str]


@dataclass
class BugReport:
    description: str
    context: Dict[str, Any]  # Browser, URL, analysis state, etc.
    timestamp: str
    session_id: Optional[str]
    severity: str  # "low", "medium", "high", "critical"


# ─────────────────────────────────────────────────────────────
# In-memory store with file persistence
# ─────────────────────────────────────────────────────────────

_DEFAULT_FEEDBACK: Dict[str, Any] = {
    "nps_responses": [],
    "feature_feedback": [],
    "bug_reports": [],
    "general_comments": [],
    "aggregates": {
        "nps_score": None,
        "total_responses": 0,
        "promoters": 0,
        "passives": 0,
        "detractors": 0,
        "feature_ratings": {}
    }
}

_feedback_store: Dict[str, Any] = {}


def _load_feedback_unlocked():
    """Load feedback from disk without acquiring _lock (caller must hold it)."""
    global _feedback_store
    if os.path.exists(FEEDBACK_FILE):
        try:
            with open(FEEDBACK_FILE, "r") as f:
                _feedback_store = json.load(f)
        except Exception as e:
            logger.warning("Failed to load feedback: %s", e)
            _feedback_store = copy.deepcopy(_DEFAULT_FEEDBACK)
    else:
        _feedback_store = copy.deepcopy(_DEFAULT_FEEDBACK)
    return _feedback_store


def _load_feedback():
    global _feedback_store
    with _lock:
        return _load_feedback_unlocked()


def _save_feedback_unlocked():
    """Save feedback to disk without acquiring _lock (caller must hold it)."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(FEEDBACK_FILE, "w") as f:
            json.dump(_feedback_store, f, indent=2)
    except Exception as e:
        logger.error("Failed to save feedback: %s", e)


def _recalculate_nps():
    """Recalculate NPS score from all responses."""
    global _feedback_store
    responses = _feedback_store.get("nps_responses", [])
    if not responses:
        _feedback_store["aggregates"]["nps_score"] = None
        return
    
    promoters = sum(1 for r in responses if r.get("score", 0) >= 9)
    detractors = sum(1 for r in responses if r.get("score", 0) <= 6)
    total = len(responses)
    
    nps = ((promoters - detractors) / total) * 100 if total > 0 else 0
    
    _feedback_store["aggregates"].update({
        "nps_score": round(nps, 1),
        "total_responses": total,
        "promoters": promoters,
        "passives": total - promoters - detractors,
        "detractors": detractors
    })


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def submit_nps(
    score: int,
    follow_up: Optional[str] = None,
    session_id: Optional[str] = None,
    feature_context: Optional[str] = None
) -> Dict[str, Any]:
    """
    Submit an NPS response (0-10 scale).
    
    Args:
        score: NPS score from 0-10
        follow_up: Optional follow-up comment
        session_id: Optional session identifier
        feature_context: Which feature triggered the survey
        
    Returns:
        Confirmation with current NPS score
    """
    if not 0 <= score <= 10:
        raise ValueError("NPS score must be between 0 and 10")
    
    global _feedback_store
    with _lock:
        if not _feedback_store:
            _load_feedback_unlocked()
        
        response = {
            "score": score,
            "follow_up": follow_up,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "feature_context": feature_context,
            "category": "promoter" if score >= 9 else "passive" if score >= 7 else "detractor"
        }
        
        _feedback_store.setdefault("nps_responses", []).append(response)
        # Cap to prevent unbounded growth (#163)
        nps = _feedback_store["nps_responses"]
        if len(nps) > _MAX_NPS_RESPONSES:
            _feedback_store["nps_responses"] = nps[-_MAX_NPS_RESPONSES:]
        _recalculate_nps()
        _save_feedback_unlocked()
    
    return {
        "status": "recorded",
        "category": response["category"],
        "current_nps": _feedback_store["aggregates"]["nps_score"]
    }


def submit_feature_feedback(
    feature: str,
    helpful: bool,
    comment: Optional[str] = None,
    session_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Submit feature-specific feedback (thumbs up/down).
    
    Args:
        feature: Feature identifier (e.g., "iac_chat", "diagram_export")
        helpful: True for positive, False for negative
        comment: Optional comment
        session_id: Optional session identifier
        
    Returns:
        Confirmation with feature rating summary
    """
    global _feedback_store
    with _lock:
        if not _feedback_store:
            _load_feedback_unlocked()
        
        feedback = {
            "feature": feature,
            "helpful": helpful,
            "comment": comment,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id
        }
        
        _feedback_store.setdefault("feature_feedback", []).append(feedback)
        # Cap to prevent unbounded growth (#163)
        ff = _feedback_store["feature_feedback"]
        if len(ff) > _MAX_FEATURE_FEEDBACK:
            _feedback_store["feature_feedback"] = ff[-_MAX_FEATURE_FEEDBACK:]
        
        # Update feature ratings aggregate
        ratings = _feedback_store["aggregates"].setdefault("feature_ratings", {})
        if feature not in ratings:
            ratings[feature] = {"positive": 0, "negative": 0}
        
        if helpful:
            ratings[feature]["positive"] += 1
        else:
            ratings[feature]["negative"] += 1
        
        _save_feedback_unlocked()
        
        total = ratings[feature]["positive"] + ratings[feature]["negative"]
        satisfaction = (ratings[feature]["positive"] / total * 100) if total > 0 else 0
    
    return {
        "status": "recorded",
        "feature": feature,
        "satisfaction_rate": round(satisfaction, 1),
        "total_ratings": total
    }


def submit_bug_report(
    description: str,
    context: Optional[Dict[str, Any]] = None,
    severity: str = "medium",
    session_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Submit a bug report with context.
    
    Args:
        description: Bug description
        context: Browser info, current state, errors, etc.
        severity: "low", "medium", "high", "critical"
        session_id: Optional session identifier
        
    Returns:
        Confirmation with bug report ID
    """
    import uuid
    
    global _feedback_store
    with _lock:
        if not _feedback_store:
            _load_feedback_unlocked()
        
        bug_id = f"BUG-{uuid.uuid4().hex[:8].upper()}"
        
        report = {
            "id": bug_id,
            "description": description,
            "context": context or {},
            "severity": severity,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "status": "new"
        }
        
        _feedback_store.setdefault("bug_reports", []).append(report)
        # Cap to prevent unbounded growth (#163)
        bugs = _feedback_store["bug_reports"]
        if len(bugs) > _MAX_BUG_REPORTS:
            _feedback_store["bug_reports"] = bugs[-_MAX_BUG_REPORTS:]
        _save_feedback_unlocked()
    
    return {
        "status": "recorded",
        "bug_id": bug_id,
        "message": "Thank you for reporting this issue. We'll investigate shortly."
    }


def get_feedback_summary() -> Dict[str, Any]:
    """Get aggregated feedback summary for admin dashboard."""
    global _feedback_store
    if not _feedback_store:
        _load_feedback()
    
    return {
        "nps": {
            "score": _feedback_store["aggregates"].get("nps_score"),
            "total_responses": _feedback_store["aggregates"].get("total_responses", 0),
            "promoters": _feedback_store["aggregates"].get("promoters", 0),
            "passives": _feedback_store["aggregates"].get("passives", 0),
            "detractors": _feedback_store["aggregates"].get("detractors", 0)
        },
        "feature_ratings": _feedback_store["aggregates"].get("feature_ratings", {}),
        "bug_reports": {
            "total": len(_feedback_store.get("bug_reports", [])),
            "by_severity": {
                sev: sum(1 for b in _feedback_store.get("bug_reports", []) if b.get("severity") == sev)
                for sev in ["low", "medium", "high", "critical"]
            }
        },
        "recent_comments": [
            {
                "type": "nps",
                "comment": r.get("follow_up"),
                "score": r.get("score"),
                "timestamp": r.get("timestamp")
            }
            for r in _feedback_store.get("nps_responses", [])[-10:]
            if r.get("follow_up")
        ]
    }


def get_nps_trend(days: int = 30) -> List[Dict[str, Any]]:
    """Get NPS trend over the last N days."""
    from datetime import timedelta
    
    global _feedback_store
    if not _feedback_store:
        _load_feedback()
    
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    responses = _feedback_store.get("nps_responses", [])
    
    # Group by day
    daily = {}
    for r in responses:
        try:
            ts = datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00"))
            if ts >= cutoff:
                day = ts.strftime("%Y-%m-%d")
                if day not in daily:
                    daily[day] = {"promoters": 0, "passives": 0, "detractors": 0, "total": 0}
                daily[day]["total"] += 1
                if r["score"] >= 9:
                    daily[day]["promoters"] += 1
                elif r["score"] >= 7:
                    daily[day]["passives"] += 1
                else:
                    daily[day]["detractors"] += 1
        except Exception:  # nosec B112 - skip malformed NPS entries gracefully
            logger.debug("Skipping malformed NPS entry: %s", r.get("timestamp"))
            continue
    
    trend = []
    for day, counts in sorted(daily.items()):
        nps = ((counts["promoters"] - counts["detractors"]) / counts["total"]) * 100 if counts["total"] > 0 else 0
        trend.append({
            "date": day,
            "nps": round(nps, 1),
            "responses": counts["total"]
        })
    
    return trend


# Initialize on import
_load_feedback()
