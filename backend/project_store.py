"""Session-backed multi-diagram project registry (#241).

The MVP deliberately mirrors the existing diagram session lifetime instead of
introducing durable workspace persistence.  It records project membership and
per-diagram status so the established diagram APIs can remain unchanged.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from routers.shared import DIAGRAM_PROJECT_STORE, PROJECT_STORE


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_project(project_id: str) -> Dict[str, Any]:
    now = _now_iso()
    return {
        "project_id": project_id,
        "status": "created",
        "created_at": now,
        "updated_at": now,
        "diagram_ids": [],
        "diagrams": [],
        "combined_analysis": None,
        "combined_status": "empty",
    }


def get_project(project_id: str) -> Optional[Dict[str, Any]]:
    project = PROJECT_STORE.get(project_id)
    return deepcopy(project) if project else None


def upsert_project(project_id: str) -> Dict[str, Any]:
    project = PROJECT_STORE.get(project_id) or _empty_project(project_id)
    project["updated_at"] = _now_iso()
    PROJECT_STORE[project_id] = project
    return deepcopy(project)


def register_diagram(project_id: str, diagram_id: str, filename: Optional[str], size: int) -> Dict[str, Any]:
    project = PROJECT_STORE.get(project_id) or _empty_project(project_id)
    now = _now_iso()
    diagram = {
        "diagram_id": diagram_id,
        "project_id": project_id,
        "filename": filename,
        "size": size,
        "status": "uploaded",
        "created_at": now,
        "updated_at": now,
        "services_detected": 0,
    }

    existing = {d.get("diagram_id"): d for d in project.get("diagrams", [])}
    existing[diagram_id] = {**existing.get(diagram_id, {}), **diagram}
    project["diagram_ids"] = sorted(existing.keys())
    project["diagrams"] = [existing[did] for did in project["diagram_ids"]]
    project["status"] = "active"
    project["combined_status"] = "stale"
    project["combined_analysis"] = None
    project["updated_at"] = now

    PROJECT_STORE[project_id] = project
    DIAGRAM_PROJECT_STORE[diagram_id] = project_id
    return deepcopy(project)


def get_project_id_for_diagram(diagram_id: str) -> Optional[str]:
    return DIAGRAM_PROJECT_STORE.get(diagram_id)


def mark_diagram_analyzed(diagram_id: str, analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    project_id = get_project_id_for_diagram(diagram_id)
    if not project_id:
        return None

    project = PROJECT_STORE.get(project_id)
    if not project:
        return None

    now = _now_iso()
    for diagram in project.get("diagrams", []):
        if diagram.get("diagram_id") == diagram_id:
            diagram["status"] = "analyzed"
            diagram["updated_at"] = now
            diagram["services_detected"] = int(analysis.get("services_detected") or len(analysis.get("mappings", [])))
            diagram["diagram_type"] = analysis.get("diagram_type")
            diagram["source_provider"] = analysis.get("source_provider")
            diagram["target_provider"] = analysis.get("target_provider")
            break

    project["diagram_ids"] = sorted(d.get("diagram_id") for d in project.get("diagrams", []) if d.get("diagram_id"))
    project["diagrams"] = sorted(project.get("diagrams", []), key=lambda d: d.get("diagram_id", ""))
    project["combined_status"] = "stale"
    project["combined_analysis"] = None
    project["updated_at"] = now
    PROJECT_STORE[project_id] = project
    return deepcopy(project)


def set_combined_analysis(project_id: str, combined_analysis: Dict[str, Any]) -> Dict[str, Any]:
    project = PROJECT_STORE.get(project_id) or _empty_project(project_id)
    project["combined_analysis"] = combined_analysis
    project["combined_status"] = "ready"
    project["updated_at"] = _now_iso()
    PROJECT_STORE[project_id] = project
    return deepcopy(project)


def list_analyzed_diagrams(project: Dict[str, Any]) -> List[str]:
    return [
        diagram["diagram_id"]
        for diagram in project.get("diagrams", [])
        if diagram.get("status") == "analyzed" and diagram.get("diagram_id")
    ]