"""
Archmorph Architecture Versioning
Track changes to architecture analyses over time with version history
"""

import logging
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from copy import deepcopy

from cachetools import TTLCache

logger = logging.getLogger(__name__)

# Version store (TTL: 7 days, max 500 diagrams)
VERSION_STORE: TTLCache = TTLCache(maxsize=500, ttl=86400 * 7)


class ChangeType(str, Enum):
    SERVICE_ADDED = "service_added"
    SERVICE_REMOVED = "service_removed"
    SERVICE_MODIFIED = "service_modified"
    MAPPING_CHANGED = "mapping_changed"
    CONFIGURATION_CHANGED = "configuration_changed"
    ANSWERS_APPLIED = "answers_applied"
    NATURAL_LANGUAGE_ADDITION = "nl_service_addition"


@dataclass
class ArchitectureChange:
    """Individual change to an architecture."""
    change_type: ChangeType
    description: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "change_type": self.change_type.value,
            "description": self.description,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass  
class ArchitectureVersion:
    """A specific version of an architecture analysis."""
    version_id: str
    version_number: int
    diagram_id: str
    snapshot: Dict[str, Any]
    changes: List[ArchitectureChange] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: Optional[str] = None
    message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "version_id": self.version_id,
            "version_number": self.version_number,
            "diagram_id": self.diagram_id,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "message": self.message,
            "changes": [c.to_dict() for c in self.changes],
            "summary": self.get_summary(),
        }
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of this version."""
        return {
            "services_count": self.snapshot.get("services_detected", 0),
            "mappings_count": len(self.snapshot.get("mappings", [])),
            "changes_count": len(self.changes),
            "content_hash": self._compute_hash(),
        }
    
    def _compute_hash(self) -> str:
        """Compute a hash of the snapshot content."""
        # Sort mappings for consistent hashing
        mappings = sorted(
            self.snapshot.get("mappings", []),
            key=lambda m: m.get("source_service", "")
        )
        content = str(mappings)
        return hashlib.sha256(content.encode()).hexdigest()[:8]


@dataclass
class VersionHistory:
    """Complete version history for a diagram."""
    diagram_id: str
    versions: List[ArchitectureVersion] = field(default_factory=list)
    current_version: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "diagram_id": self.diagram_id,
            "current_version": self.current_version,
            "total_versions": len(self.versions),
            "versions": [v.to_dict() for v in self.versions],
            "timeline": self._get_timeline(),
        }
    
    def _get_timeline(self) -> List[Dict[str, Any]]:
        """Get a timeline of changes across all versions."""
        timeline = []
        for version in self.versions:
            timeline.append({
                "version": version.version_number,
                "timestamp": version.created_at.isoformat(),
                "message": version.message,
                "changes_count": len(version.changes),
            })
        return timeline


# ─────────────────────────────────────────────────────────────
# Version Management Functions
# ─────────────────────────────────────────────────────────────
def get_or_create_history(diagram_id: str) -> VersionHistory:
    """Get or create version history for a diagram."""
    if diagram_id not in VERSION_STORE:
        VERSION_STORE[diagram_id] = VersionHistory(diagram_id=diagram_id)
    return VERSION_STORE[diagram_id]


def _detect_changes(
    old_snapshot: Optional[Dict[str, Any]],
    new_snapshot: Dict[str, Any],
) -> List[ArchitectureChange]:
    """Detect changes between two architecture snapshots."""
    changes = []
    
    if old_snapshot is None:
        changes.append(ArchitectureChange(
            change_type=ChangeType.SERVICE_ADDED,
            description="Initial architecture analysis",
            details={"services_count": new_snapshot.get("services_detected", 0)},
        ))
        return changes
    
    old_mappings = {m["source_service"]: m for m in old_snapshot.get("mappings", [])}
    new_mappings = {m["source_service"]: m for m in new_snapshot.get("mappings", [])}
    
    # Detect added services
    added = set(new_mappings.keys()) - set(old_mappings.keys())
    for service in added:
        changes.append(ArchitectureChange(
            change_type=ChangeType.SERVICE_ADDED,
            description=f"Added service: {service}",
            details={
                "service": service,
                "azure_service": new_mappings[service].get("azure_service"),
            },
        ))
    
    # Detect removed services
    removed = set(old_mappings.keys()) - set(new_mappings.keys())
    for service in removed:
        changes.append(ArchitectureChange(
            change_type=ChangeType.SERVICE_REMOVED,
            description=f"Removed service: {service}",
            details={"service": service},
        ))
    
    # Detect modified services
    for service in set(old_mappings.keys()) & set(new_mappings.keys()):
        old_mapping = old_mappings[service]
        new_mapping = new_mappings[service]
        
        if old_mapping.get("azure_service") != new_mapping.get("azure_service"):
            changes.append(ArchitectureChange(
                change_type=ChangeType.MAPPING_CHANGED,
                description=f"Changed mapping for {service}",
                details={
                    "service": service,
                    "old_azure_service": old_mapping.get("azure_service"),
                    "new_azure_service": new_mapping.get("azure_service"),
                },
            ))
        
        if old_mapping.get("confidence") != new_mapping.get("confidence"):
            changes.append(ArchitectureChange(
                change_type=ChangeType.SERVICE_MODIFIED,
                description=f"Confidence updated for {service}",
                details={
                    "service": service,
                    "old_confidence": old_mapping.get("confidence"),
                    "new_confidence": new_mapping.get("confidence"),
                },
            ))
    
    # Detect configuration/answer changes
    old_config = old_snapshot.get("refined_architecture", {})
    new_config = new_snapshot.get("refined_architecture", {})
    
    if old_config != new_config:
        changes.append(ArchitectureChange(
            change_type=ChangeType.CONFIGURATION_CHANGED,
            description="Architecture configuration refined",
            details={
                "fields_changed": list(set(new_config.keys()) - set(old_config.keys())),
            },
        ))
    
    # Detect natural language additions
    old_nl = old_snapshot.get("user_context", {}).get("natural_language_additions", [])
    new_nl = new_snapshot.get("user_context", {}).get("natural_language_additions", [])
    
    if len(new_nl) > len(old_nl):
        for addition in new_nl[len(old_nl):]:
            changes.append(ArchitectureChange(
                change_type=ChangeType.NATURAL_LANGUAGE_ADDITION,
                description=f"Added services via NL: {addition.get('text', '')[:50]}...",
                details={
                    "text": addition.get("text"),
                    "services_added": addition.get("services_added", []),
                },
            ))
    
    return changes


def create_version(
    diagram_id: str,
    snapshot: Dict[str, Any],
    message: Optional[str] = None,
    created_by: Optional[str] = None,
) -> ArchitectureVersion:
    """Create a new version of an architecture analysis."""
    history = get_or_create_history(diagram_id)
    
    # Get previous snapshot for change detection
    old_snapshot = None
    if history.versions:
        old_snapshot = history.versions[-1].snapshot
    
    # Detect changes
    changes = _detect_changes(old_snapshot, snapshot)
    
    # Create new version
    version_number = len(history.versions) + 1
    version_id = f"{diagram_id}-v{version_number}"
    
    version = ArchitectureVersion(
        version_id=version_id,
        version_number=version_number,
        diagram_id=diagram_id,
        snapshot=deepcopy(snapshot),
        changes=changes,
        message=message or f"Version {version_number}",
        created_by=created_by,
    )
    
    history.versions.append(version)
    history.current_version = version_number
    
    logger.info(
        "Created version %d for diagram %s with %d changes",
        version_number, diagram_id, len(changes)
    )
    
    return version


def get_version(diagram_id: str, version_number: int) -> Optional[ArchitectureVersion]:
    """Get a specific version of an architecture."""
    history = get_or_create_history(diagram_id)
    
    for version in history.versions:
        if version.version_number == version_number:
            return version
    
    return None


def get_latest_version(diagram_id: str) -> Optional[ArchitectureVersion]:
    """Get the latest version of an architecture."""
    history = get_or_create_history(diagram_id)
    
    if history.versions:
        return history.versions[-1]
    
    return None


def restore_version(diagram_id: str, version_number: int) -> Optional[Dict[str, Any]]:
    """Restore a previous version, creating a new version from it."""
    version = get_version(diagram_id, version_number)
    
    if not version:
        return None
    
    # Create a new version from the restored snapshot
    restored = create_version(
        diagram_id=diagram_id,
        snapshot=deepcopy(version.snapshot),
        message=f"Restored from version {version_number}",
    )
    
    return restored.snapshot


def compare_versions(
    diagram_id: str,
    version_a: int,
    version_b: int,
) -> Dict[str, Any]:
    """Compare two versions and return differences."""
    v_a = get_version(diagram_id, version_a)
    v_b = get_version(diagram_id, version_b)
    
    if not v_a or not v_b:
        return {"error": "One or both versions not found"}
    
    changes = _detect_changes(v_a.snapshot, v_b.snapshot)
    
    # Generate service diff
    mappings_a = {m["source_service"]: m for m in v_a.snapshot.get("mappings", [])}
    mappings_b = {m["source_service"]: m for m in v_b.snapshot.get("mappings", [])}
    
    all_services = set(mappings_a.keys()) | set(mappings_b.keys())
    
    service_diff = []
    for service in sorted(all_services):
        in_a = service in mappings_a
        in_b = service in mappings_b
        
        if in_a and in_b:
            if mappings_a[service] == mappings_b[service]:
                status = "unchanged"
            else:
                status = "modified"
        elif in_a:
            status = "removed"
        else:
            status = "added"
        
        service_diff.append({
            "service": service,
            "status": status,
            "version_a": mappings_a.get(service),
            "version_b": mappings_b.get(service),
        })
    
    return {
        "diagram_id": diagram_id,
        "version_a": version_a,
        "version_b": version_b,
        "changes": [c.to_dict() for c in changes],
        "service_diff": service_diff,
        "summary": {
            "added": len([s for s in service_diff if s["status"] == "added"]),
            "removed": len([s for s in service_diff if s["status"] == "removed"]),
            "modified": len([s for s in service_diff if s["status"] == "modified"]),
            "unchanged": len([s for s in service_diff if s["status"] == "unchanged"]),
        },
    }


def get_version_history(diagram_id: str) -> Dict[str, Any]:
    """Get complete version history for a diagram."""
    history = get_or_create_history(diagram_id)
    return history.to_dict()


def get_changes_since(diagram_id: str, since_version: int) -> List[Dict[str, Any]]:
    """Get all changes since a specific version."""
    history = get_or_create_history(diagram_id)
    
    all_changes = []
    for version in history.versions:
        if version.version_number > since_version:
            for change in version.changes:
                change_dict = change.to_dict()
                change_dict["version"] = version.version_number
                all_changes.append(change_dict)
    
    return all_changes
