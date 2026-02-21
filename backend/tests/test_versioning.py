"""
Tests for Architecture Versioning
"""

import pytest
from versioning import (
    ArchitectureVersion, ArchitectureChange, VersionHistory, ChangeType,
    create_version, get_version, get_latest_version, restore_version,
    compare_versions, get_version_history, get_changes_since,
    get_or_create_history, _detect_changes,
    VERSION_STORE,
)


class TestArchitectureChange:
    """Tests for ArchitectureChange class."""
    
    def test_change_creation(self):
        change = ArchitectureChange(
            change_type=ChangeType.SERVICE_ADDED,
            description="Added EC2 instance",
            details={"service": "EC2"},
        )
        assert change.change_type == ChangeType.SERVICE_ADDED
        assert change.description == "Added EC2 instance"
    
    def test_change_to_dict(self):
        change = ArchitectureChange(
            change_type=ChangeType.MAPPING_CHANGED,
            description="Updated mapping",
        )
        data = change.to_dict()
        assert data["change_type"] == "mapping_changed"
        assert "timestamp" in data


class TestArchitectureVersion:
    """Tests for ArchitectureVersion class."""
    
    def test_version_creation(self):
        version = ArchitectureVersion(
            version_id="diag-123-v1",
            version_number=1,
            diagram_id="diag-123",
            snapshot={"mappings": []},
        )
        assert version.version_number == 1
        assert version.diagram_id == "diag-123"
    
    def test_version_summary(self):
        version = ArchitectureVersion(
            version_id="diag-123-v1",
            version_number=1,
            diagram_id="diag-123",
            snapshot={
                "services_detected": 5,
                "mappings": [{"source_service": "EC2"}],
            },
        )
        summary = version.get_summary()
        assert summary["services_count"] == 5
        assert summary["mappings_count"] == 1


class TestChangeDetection:
    """Tests for change detection between snapshots."""
    
    def test_detect_initial_change(self):
        changes = _detect_changes(None, {"services_detected": 3})
        assert len(changes) == 1
        assert changes[0].change_type == ChangeType.SERVICE_ADDED
    
    def test_detect_added_service(self):
        old = {"mappings": [{"source_service": "EC2"}]}
        new = {"mappings": [{"source_service": "EC2"}, {"source_service": "S3"}]}
        
        changes = _detect_changes(old, new)
        added = [c for c in changes if c.change_type == ChangeType.SERVICE_ADDED]
        assert len(added) == 1
        assert "S3" in added[0].description
    
    def test_detect_removed_service(self):
        old = {"mappings": [{"source_service": "EC2"}, {"source_service": "S3"}]}
        new = {"mappings": [{"source_service": "EC2"}]}
        
        changes = _detect_changes(old, new)
        removed = [c for c in changes if c.change_type == ChangeType.SERVICE_REMOVED]
        assert len(removed) == 1
        assert "S3" in removed[0].description
    
    def test_detect_mapping_change(self):
        old = {"mappings": [{"source_service": "EC2", "azure_service": "VM"}]}
        new = {"mappings": [{"source_service": "EC2", "azure_service": "Virtual Machine Scale Sets"}]}
        
        changes = _detect_changes(old, new)
        mapping_changes = [c for c in changes if c.change_type == ChangeType.MAPPING_CHANGED]
        assert len(mapping_changes) == 1


class TestVersionManagement:
    """Tests for version management functions."""
    
    def setup_method(self):
        VERSION_STORE.clear()
    
    def test_create_first_version(self):
        snapshot = {
            "diagram_id": "diag-123",
            "mappings": [{"source_service": "EC2"}],
            "services_detected": 1,
        }
        
        version = create_version("diag-123", snapshot, message="Initial version")
        
        assert version.version_number == 1
        assert version.message == "Initial version"
        assert len(version.changes) > 0
    
    def test_create_multiple_versions(self):
        create_version("diag-123", {"mappings": []}, message="v1")
        create_version("diag-123", {"mappings": [{"source_service": "EC2"}]}, message="v2")
        version3 = create_version("diag-123", {"mappings": [{"source_service": "EC2"}, {"source_service": "S3"}]}, message="v3")
        
        assert version3.version_number == 3
    
    def test_get_version(self):
        create_version("diag-123", {"mappings": []}, message="Test")
        
        version = get_version("diag-123", 1)
        assert version is not None
        assert version.version_number == 1
    
    def test_get_nonexistent_version(self):
        version = get_version("diag-123", 999)
        assert version is None
    
    def test_get_latest_version(self):
        create_version("diag-123", {"mappings": []})
        create_version("diag-123", {"mappings": [{"source_service": "EC2"}]})
        
        latest = get_latest_version("diag-123")
        assert latest is not None
        assert latest.version_number == 2
    
    def test_restore_version(self):
        create_version("diag-123", {"mappings": [{"source_service": "EC2"}]})
        create_version("diag-123", {"mappings": [{"source_service": "S3"}]})
        
        restored = restore_version("diag-123", 1)
        
        assert restored is not None
        assert restored["mappings"][0]["source_service"] == "EC2"
        
        # Should have created a new version
        latest = get_latest_version("diag-123")
        assert latest.version_number == 3
    
    def test_compare_versions(self):
        create_version("diag-123", {"mappings": [{"source_service": "EC2"}]})
        create_version("diag-123", {"mappings": [{"source_service": "EC2"}, {"source_service": "S3"}]})
        
        comparison = compare_versions("diag-123", 1, 2)
        
        assert comparison["version_a"] == 1
        assert comparison["version_b"] == 2
        assert comparison["summary"]["added"] == 1
    
    def test_get_version_history(self):
        create_version("diag-123", {"mappings": []})
        create_version("diag-123", {"mappings": [{"source_service": "EC2"}]})
        
        history = get_version_history("diag-123")
        
        assert history["diagram_id"] == "diag-123"
        assert history["total_versions"] == 2
        assert len(history["versions"]) == 2
    
    def test_get_changes_since(self):
        create_version("diag-123", {"mappings": []})
        create_version("diag-123", {"mappings": [{"source_service": "EC2"}]})
        create_version("diag-123", {"mappings": [{"source_service": "EC2"}, {"source_service": "S3"}]})
        
        changes = get_changes_since("diag-123", 1)
        
        assert len(changes) > 0
        assert all(c["version"] > 1 for c in changes)
