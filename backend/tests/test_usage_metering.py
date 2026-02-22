"""
Archmorph — Usage Metering Unit Tests
Tests for services/usage_metering.py (Issue #106)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.usage_metering import (
    METRICS,
    record_usage,
    get_usage,
    check_quota,
    reset_usage,
    get_all_usage_stats,
)


# ====================================================================
# METRICS data quality
# ====================================================================

class TestMetrics:
    def test_metrics_defined(self):
        assert len(METRICS) >= 5

    def test_known_metrics(self):
        expected = {"analyses", "iac_downloads", "hld_generations"}
        assert expected.issubset(set(METRICS))


# ====================================================================
# record_usage + get_usage
# ====================================================================

class TestRecordUsage:
    def test_record_and_get(self):
        org_id = "test-org-usage-001"
        record_usage(org_id, "analyses")
        result = get_usage(org_id)
        assert isinstance(result, dict)
        usage = result.get("usage", result)
        assert usage.get("analyses", 0) >= 1

    def test_record_multiple(self):
        org_id = "test-org-usage-002"
        record_usage(org_id, "analyses")
        record_usage(org_id, "analyses")
        record_usage(org_id, "iac_downloads")
        result = get_usage(org_id)
        usage = result.get("usage", result)
        assert usage.get("analyses", 0) >= 2
        assert usage.get("iac_downloads", 0) >= 1

    def test_unknown_metric(self):
        # Should not crash on unknown metric
        try:
            record_usage("test-org-unknown", "nonexistent_metric_xyz")
        except (ValueError, KeyError):
            pass  # Acceptable to raise


# ====================================================================
# check_quota
# ====================================================================

class TestCheckQuota:
    def test_within_quota(self):
        org_id = "test-org-quota-001"
        result = check_quota(org_id, "analyses", limit=1000)
        assert isinstance(result, dict)
        assert result.get("allowed") is True

    def test_exceeded_quota(self):
        org_id = "test-org-quota-exceed"
        for _ in range(5):
            record_usage(org_id, "analyses")
        result = check_quota(org_id, "analyses", limit=3)
        assert isinstance(result, dict)
        assert result.get("allowed") is False


# ====================================================================
# reset_usage
# ====================================================================

class TestResetUsage:
    def test_reset_clears(self):
        org_id = "test-org-reset-001"
        record_usage(org_id, "analyses")
        reset_usage(org_id)
        result = get_usage(org_id)
        usage = result.get("usage", result)
        assert usage.get("analyses", 0) == 0


# ====================================================================
# get_all_usage_stats
# ====================================================================

class TestGetAllUsageStats:
    def test_returns_dict_or_list(self):
        stats = get_all_usage_stats()
        assert isinstance(stats, (dict, list))
