"""Tests for architecture_diff.py — version comparison and change tracking."""

from architecture_diff import (
    save_version,
    list_versions,
    get_version,
    branch_version,
    compute_diff,
    _diff_services,
    _diff_confidence,
    _diff_cost,
    _service_key,
)


SNAPSHOT_V1 = {
    "mappings": [
        {"source_service": "EC2", "azure_service": "Azure VMs", "confidence": 0.9},
        {"source_service": "S3", "azure_service": "Blob Storage", "confidence": 0.95},
    ],
    "cost_estimate": {"total_monthly": 500},
}

SNAPSHOT_V2 = {
    "mappings": [
        {"source_service": "EC2", "azure_service": "Azure VMs", "confidence": 0.92},
        {"source_service": "S3", "azure_service": "Blob Storage", "confidence": 0.95},
        {"source_service": "RDS", "azure_service": "Azure SQL", "confidence": 0.85},
    ],
    "cost_estimate": {"total_monthly": 750},
}


class TestSaveVersion:
    def test_save_returns_version_info(self):
        result = save_version("diff-diag-1", SNAPSHOT_V1, label="initial")
        assert result["version"] == 1
        assert result["label"] == "initial"

    def test_save_increments_version(self):
        save_version("diff-diag-2", SNAPSHOT_V1)
        result = save_version("diff-diag-2", SNAPSHOT_V2)
        assert result["version"] == 2


class TestListVersions:
    def test_list_returns_all_versions(self):
        save_version("diff-diag-3", SNAPSHOT_V1)
        save_version("diff-diag-3", SNAPSHOT_V2)
        versions = list_versions("diff-diag-3")
        assert len(versions) >= 2

    def test_list_empty_diagram(self):
        versions = list_versions("nonexistent-diagram-xyz")
        assert versions == []


class TestGetVersion:
    def test_get_existing_version(self):
        save_version("diff-diag-4", SNAPSHOT_V1)
        v = get_version("diff-diag-4", 1)
        assert v is not None
        assert v["version"] == 1

    def test_get_nonexistent_version(self):
        v = get_version("diff-diag-4", 999)
        assert v is None


class TestBranchVersion:
    def test_branch_creates_new_version(self):
        save_version("diff-diag-5", SNAPSHOT_V1)
        branched = branch_version("diff-diag-5", 1, label="branched")
        assert branched is not None
        assert branched["label"] == "branched"

    def test_branch_nonexistent_returns_none(self):
        result = branch_version("diff-diag-5", 999)
        assert result is None


class TestServiceKey:
    def test_generates_key(self):
        key = _service_key({"source_service": "EC2", "azure_service": "VMs"})
        assert isinstance(key, str)
        assert len(key) > 0


class TestDiffServices:
    def test_detects_added_services(self):
        diff = _diff_services(SNAPSHOT_V1["mappings"], SNAPSHOT_V2["mappings"])
        assert len(diff.get("added", [])) >= 1

    def test_no_diff_same_services(self):
        diff = _diff_services(SNAPSHOT_V1["mappings"], SNAPSHOT_V1["mappings"])
        assert len(diff.get("added", [])) == 0
        assert len(diff.get("removed", [])) == 0


class TestDiffConfidence:
    def test_detects_confidence_changes(self):
        changes = _diff_confidence(SNAPSHOT_V1["mappings"], SNAPSHOT_V2["mappings"])
        assert isinstance(changes, list)


class TestDiffCost:
    def test_detects_cost_change(self):
        diff = _diff_cost(SNAPSHOT_V1, SNAPSHOT_V2)
        assert isinstance(diff, dict)


class TestComputeDiff:
    def test_compute_diff_between_versions(self):
        save_version("diff-diag-6", SNAPSHOT_V1)
        save_version("diff-diag-6", SNAPSHOT_V2)
        diff = compute_diff("diff-diag-6", 1, 2)
        assert diff is not None
        assert "services" in diff or "cost" in diff or "summary" in diff

    def test_compute_diff_nonexistent_returns_none(self):
        diff = compute_diff("nonexistent-xyz", 1, 2)
        assert diff is None
