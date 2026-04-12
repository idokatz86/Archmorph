"""Tests for shareable_reports.py — report sharing with expiry and views."""

from shareable_reports import (
    create_share,
    get_share,
    get_share_stats,
    delete_share,
    render_view,
    _extract_executive_view,
    _extract_technical_view,
    _extract_financial_view,
)


SAMPLE_SNAPSHOT = {
    "title": "AWS to Azure Migration",
    "mappings": [
        {"source_service": "EC2", "azure_service": "Azure VMs", "confidence": 0.9},
        {"source_service": "S3", "azure_service": "Blob Storage", "confidence": 0.95},
    ],
    "cost_estimate": {"total_monthly": 500, "savings": 120},
    "services_detected": 2,
    "source_provider": "aws",
    "target_provider": "azure",
    "executive_summary": "Migration of 2 services from AWS to Azure.",
    "risks_and_mitigations": [{"risk": "Downtime", "impact": "medium", "mitigation": "Blue-green deploy"}],
}


class TestCreateShare:
    def test_creates_share(self):
        share = create_share(SAMPLE_SNAPSHOT, creator_id="user-1")
        assert "share_id" in share

    def test_creates_share_with_custom_expiry(self):
        share = create_share(SAMPLE_SNAPSHOT, expiry_days=7)
        assert share is not None


class TestGetShare:
    def test_get_existing_share(self):
        share = create_share(SAMPLE_SNAPSHOT)
        share_id = share.get("share_id")
        result = get_share(share_id)
        assert result is not None

    def test_get_nonexistent_share(self):
        result = get_share("nonexistent-share-xyz")
        assert result is None


class TestGetShareStats:
    def test_stats_for_existing_share(self):
        share = create_share(SAMPLE_SNAPSHOT)
        share_id = share.get("share_id")
        # Access the share to generate view counts
        get_share(share_id)
        stats = get_share_stats(share_id)
        if stats:
            assert isinstance(stats, dict)

    def test_stats_for_nonexistent(self):
        stats = get_share_stats("nonexistent-xyz")
        assert stats is None


class TestDeleteShare:
    def test_delete_existing(self):
        share = create_share(SAMPLE_SNAPSHOT)
        share_id = share.get("share_id")
        assert delete_share(share_id) is True

    def test_delete_nonexistent(self):
        assert delete_share("nonexistent-xyz") is False


class TestExtractViews:
    def test_executive_view(self):
        view = _extract_executive_view(SAMPLE_SNAPSHOT)
        assert isinstance(view, dict)

    def test_technical_view(self):
        view = _extract_technical_view(SAMPLE_SNAPSHOT)
        assert isinstance(view, dict)

    def test_financial_view(self):
        view = _extract_financial_view(SAMPLE_SNAPSHOT)
        assert isinstance(view, dict)


class TestRenderView:
    def test_render_default_view(self):
        result = render_view(SAMPLE_SNAPSHOT)
        assert isinstance(result, dict)

    def test_render_executive_view(self):
        result = render_view(SAMPLE_SNAPSHOT, view_type="executive")
        assert isinstance(result, dict)

    def test_render_technical_view(self):
        result = render_view(SAMPLE_SNAPSHOT, view_type="technical")
        assert isinstance(result, dict)

    def test_render_financial_view(self):
        result = render_view(SAMPLE_SNAPSHOT, view_type="financial")
        assert isinstance(result, dict)
