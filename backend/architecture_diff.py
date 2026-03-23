"""
Archmorph Architecture Diff & Version Comparison engine.

Stores analysis snapshots as versioned history per diagram_id,
and diffs two versions to show what changed (services, confidence,
cost, IaC).

Thread-safe via RLock. In-memory storage.
"""

import copy
import difflib
import threading
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_lock = threading.RLock()

# diagram_id -> list[version_record]  (ordered by version number)
_versions: Dict[str, List[Dict[str, Any]]] = {}

MAX_VERSIONS_PER_DIAGRAM = 50


def save_version(
    diagram_id: str,
    snapshot: Dict[str, Any],
    *,
    label: Optional[str] = None,
) -> Dict[str, Any]:
    """Save current analysis state as a new version.

    Returns version metadata (without the full snapshot).
    """
    now = datetime.now(timezone.utc).isoformat()

    with _lock:
        versions = _versions.setdefault(diagram_id, [])
        version_number = len(versions) + 1

        record = {
            "version": version_number,
            "diagram_id": diagram_id,
            "label": label or f"v{version_number}",
            "created_at": now,
            "snapshot": copy.deepcopy(snapshot),
        }

        versions.append(record)

        # Trim oldest if over limit
        if len(versions) > MAX_VERSIONS_PER_DIAGRAM:
            versions.pop(0)

    return {
        "version": record["version"],
        "diagram_id": diagram_id,
        "label": record["label"],
        "created_at": record["created_at"],
    }


def list_versions(diagram_id: str) -> List[Dict[str, Any]]:
    """List all versions for a diagram (metadata only)."""
    with _lock:
        versions = _versions.get(diagram_id, [])
        return [
            {
                "version": v["version"],
                "label": v["label"],
                "created_at": v["created_at"],
            }
            for v in versions
        ]


def get_version(diagram_id: str, version: int) -> Optional[Dict[str, Any]]:
    """Get a specific version snapshot."""
    with _lock:
        versions = _versions.get(diagram_id, [])
        for v in versions:
            if v["version"] == version:
                return copy.deepcopy(v)
    return None


def branch_version(
    diagram_id: str,
    version: int,
    *,
    label: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Fork a version for what-if analysis. Creates a new version from an existing one."""
    source = get_version(diagram_id, version)
    if source is None:
        return None

    branch_label = label or f"branch-from-v{version}"
    return save_version(
        diagram_id,
        source["snapshot"],
        label=branch_label,
    )


# ─────────────────────────────────────────────────────────────
# Diff Computation
# ─────────────────────────────────────────────────────────────

def _service_key(svc: Dict[str, Any]) -> str:
    """Unique key for a service entry."""
    return svc.get("name") or svc.get("source_service") or svc.get("id") or str(svc)


def _diff_services(
    old_services: List[Dict[str, Any]],
    new_services: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Diff service lists: added, removed, changed."""
    old_map = {_service_key(s): s for s in old_services}
    new_map = {_service_key(s): s for s in new_services}

    old_keys = set(old_map)
    new_keys = set(new_map)

    added = [new_map[k] for k in sorted(new_keys - old_keys)]
    removed = [old_map[k] for k in sorted(old_keys - new_keys)]

    changed = []
    for k in sorted(old_keys & new_keys):
        old_svc = old_map[k]
        new_svc = new_map[k]
        old_target = old_svc.get("azure_service") or old_svc.get("target_service")
        new_target = new_svc.get("azure_service") or new_svc.get("target_service")
        if old_target != new_target:
            changed.append({
                "service": k,
                "old_mapping": old_target,
                "new_mapping": new_target,
            })

    return {
        "added": added,
        "removed": removed,
        "changed_mappings": changed,
        "added_count": len(added),
        "removed_count": len(removed),
        "changed_count": len(changed),
    }


def _diff_confidence(
    old_services: List[Dict[str, Any]],
    new_services: List[Dict[str, Any]],
    threshold: float = 5.0,
) -> List[Dict[str, Any]]:
    """Find services whose confidence changed more than threshold %."""
    old_map = {_service_key(s): s.get("confidence") for s in old_services}
    new_map = {_service_key(s): s.get("confidence") for s in new_services}

    shifts = []
    for k in sorted(set(old_map) & set(new_map)):
        old_c = old_map[k]
        new_c = new_map[k]
        if old_c is None or new_c is None:
            continue
        delta = new_c - old_c
        if abs(delta) > threshold:
            shifts.append({
                "service": k,
                "old_confidence": old_c,
                "new_confidence": new_c,
                "delta": round(delta, 2),
                "direction": "up" if delta > 0 else "down",
            })
    return shifts


def _diff_cost(
    old_snapshot: Dict[str, Any],
    new_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    """Compare cost between two snapshots."""
    old_cost = old_snapshot.get("cost_estimate", old_snapshot.get("cost", {}))
    new_cost = new_snapshot.get("cost_estimate", new_snapshot.get("cost", {}))

    old_total = old_cost.get("total_monthly", old_cost.get("total", 0)) or 0
    new_total = new_cost.get("total_monthly", new_cost.get("total", 0)) or 0

    # Per-service cost changes
    old_services = old_snapshot.get("services", [])
    new_services = new_snapshot.get("services", [])
    old_cost_map = {}
    for s in old_services:
        c = s.get("cost") or s.get("estimated_cost") or 0
        old_cost_map[_service_key(s)] = c if not isinstance(c, dict) else c.get("monthly", 0)

    new_cost_map = {}
    for s in new_services:
        c = s.get("cost") or s.get("estimated_cost") or 0
        new_cost_map[_service_key(s)] = c if not isinstance(c, dict) else c.get("monthly", 0)

    per_service_delta = []
    for k in sorted(set(old_cost_map) | set(new_cost_map)):
        o = old_cost_map.get(k, 0) or 0
        n = new_cost_map.get(k, 0) or 0
        if o != n:
            per_service_delta.append({
                "service": k,
                "old_cost": o,
                "new_cost": n,
                "delta": round(n - o, 2),
            })

    return {
        "old_total": old_total,
        "new_total": new_total,
        "delta": round(new_total - old_total, 2),
        "direction": "increase" if new_total > old_total else "decrease" if new_total < old_total else "unchanged",
        "per_service": per_service_delta,
    }


def _diff_iac(
    old_snapshot: Dict[str, Any],
    new_snapshot: Dict[str, Any],
) -> Optional[List[str]]:
    """Line-by-line diff of IaC code if present."""
    old_iac = old_snapshot.get("iac_code") or old_snapshot.get("iac", {}).get("code")
    new_iac = new_snapshot.get("iac_code") or new_snapshot.get("iac", {}).get("code")

    if not old_iac and not new_iac:
        return None

    old_lines = (old_iac or "").splitlines(keepends=True)
    new_lines = (new_iac or "").splitlines(keepends=True)

    return list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile="v1", tofile="v2",
        lineterm="",
    ))


def compute_diff(
    diagram_id: str,
    v1: int,
    v2: int,
) -> Optional[Dict[str, Any]]:
    """Compare two version snapshots and return a structured diff.

    Returns None if either version is not found.
    """
    snap1 = get_version(diagram_id, v1)
    snap2 = get_version(diagram_id, v2)

    if snap1 is None or snap2 is None:
        return None

    old = snap1["snapshot"]
    new = snap2["snapshot"]

    old_services = old.get("services", [])
    new_services = new.get("services", [])

    services_diff = _diff_services(old_services, new_services)
    confidence_shifts = _diff_confidence(old_services, new_services)
    cost_delta = _diff_cost(old, new)
    iac_diff = _diff_iac(old, new)

    # Build human-readable summary
    parts = []
    if services_diff["added_count"]:
        parts.append(f"added {services_diff['added_count']} services")
    if services_diff["removed_count"]:
        parts.append(f"removed {services_diff['removed_count']} services")
    if services_diff["changed_count"]:
        parts.append(f"changed {services_diff['changed_count']} mappings")
    if cost_delta["delta"] != 0:
        sign = "+" if cost_delta["delta"] > 0 else ""
        parts.append(f"cost {sign}${cost_delta['delta']}/mo")
    summary = f"v{v1} → v{v2}: " + (", ".join(parts) if parts else "no changes detected")

    return {
        "diagram_id": diagram_id,
        "v1": v1,
        "v2": v2,
        "summary": summary,
        "services": services_diff,
        "confidence_shifts": confidence_shifts,
        "cost_delta": cost_delta,
        "iac_diff": iac_diff,
    }
