"""Tests for migration_timeline.py — timeline generation and phasing."""

from migration_timeline import (
    generate_timeline,
    render_timeline_markdown,
    render_timeline_csv,
    _classify_complexity,
    _estimate_hours,
    _build_dependency_order,
)


SAMPLE_ANALYSIS = {
    "mappings": [
        {"source_service": "EC2", "azure_service": "Azure VMs", "confidence": 0.9,
         "category": "compute", "notes": "Zone 1"},
        {"source_service": "S3", "azure_service": "Blob Storage", "confidence": 0.95,
         "category": "storage", "notes": "Zone 2"},
        {"source_service": "RDS", "azure_service": "Azure SQL", "confidence": 0.85,
         "category": "database", "notes": "Zone 3"},
        {"source_service": "Lambda", "azure_service": "Azure Functions", "confidence": 0.92,
         "category": "compute", "notes": "Zone 1"},
    ],
    "source_provider": "aws",
    "target_provider": "azure",
}


class TestClassifyComplexity:
    def test_compute_category(self):
        complexity = _classify_complexity("EC2", "compute")
        assert complexity in ("low", "medium", "high", "critical")

    def test_database_category(self):
        complexity = _classify_complexity("RDS", "database")
        assert complexity in ("low", "medium", "high", "critical")


class TestEstimateHours:
    def test_returns_dict(self):
        hours = _estimate_hours("medium")
        assert isinstance(hours, dict)
        assert "min" in hours or "optimistic" in hours or len(hours) > 0


class TestBuildDependencyOrder:
    def test_returns_ordered_list(self):
        services = ["EC2", "S3", "RDS"]
        order = _build_dependency_order(services)
        assert isinstance(order, list)
        assert len(order) == len(services)


class TestGenerateTimeline:
    def test_generates_timeline(self):
        timeline = generate_timeline(SAMPLE_ANALYSIS, project_name="Test Project")
        assert "phases" in timeline or "timeline" in timeline
        assert isinstance(timeline, dict)

    def test_generates_with_defaults(self):
        timeline = generate_timeline(SAMPLE_ANALYSIS)
        assert isinstance(timeline, dict)

    def test_empty_analysis(self):
        timeline = generate_timeline({"mappings": []})
        assert isinstance(timeline, dict)


class TestRenderTimelineMarkdown:
    def test_renders_markdown(self):
        timeline = generate_timeline(SAMPLE_ANALYSIS)
        md = render_timeline_markdown(timeline)
        assert isinstance(md, str)
        assert len(md) > 0
        assert "#" in md  # Should contain markdown headers


class TestRenderTimelineCsv:
    def test_renders_csv(self):
        timeline = generate_timeline(SAMPLE_ANALYSIS)
        csv = render_timeline_csv(timeline)
        assert isinstance(csv, str)
        assert len(csv) > 0
        assert "," in csv  # Should be comma-separated
