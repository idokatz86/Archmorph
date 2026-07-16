"""Tests for migration timeline generation, phasing, and export contracts."""

import csv
import io

from export_capabilities import issue_export_capability
from migration_timeline import (
    generate_timeline,
    render_timeline_markdown,
    render_timeline_csv,
    _classify_complexity,
    _estimate_hours,
    _build_dependency_order,
)
from routers.shared import EXPORT_CAPABILITY_STORE, SESSION_STORE


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
        assert complexity in ("low", "medium", "high", "critical", "complex", "simple")

    def test_database_category(self):
        complexity = _classify_complexity("RDS", "database")
        assert complexity in ("low", "medium", "high", "critical", "complex", "simple")


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


def test_timeline_routes_generate_seven_phases_and_export_real_formats(test_client):
    diagram_id = "timeline-contract-diagram"
    SESSION_STORE[diagram_id] = dict(SAMPLE_ANALYSIS)

    try:
        generated = test_client.post(f"/api/diagrams/{diagram_id}/migration-timeline")
        assert generated.status_code == 200
        assert generated.json()["total_phases"] == 7
        assert len(generated.json()["phases"]) == 7

        expectations = {
            "json": ("application/json", ".json"),
            "md": ("text/markdown", ".md"),
            "csv": ("text/csv", ".csv"),
        }
        for export_format, (media_type, extension) in expectations.items():
            response = test_client.get(
                f"/api/diagrams/{diagram_id}/migration-timeline/export?format={export_format}",
            )
            assert response.status_code == 200
            assert response.headers["content-type"].startswith(media_type)
            assert response.headers["content-disposition"].endswith(f'{extension}"')
            assert len(response.headers["x-artifact-sha256"]) == 64
            assert response.headers["x-export-capability-next"]

            if export_format == "json":
                assert len(response.json()["phases"]) == 7
            elif export_format == "md":
                assert response.text.startswith("# ")
                assert "Migration Timeline" in response.text.splitlines()[0]
            else:
                rows = list(csv.reader(io.StringIO(response.text)))
                assert rows[0]
                assert len(rows) > 1
    finally:
        SESSION_STORE.delete(diagram_id)
        EXPORT_CAPABILITY_STORE.clear()


def test_timeline_export_consumes_one_time_capability(test_client, monkeypatch):
    diagram_id = "timeline-capability-diagram"
    monkeypatch.setenv("ARCHMORPH_EXPORT_CAPABILITY_REQUIRED", "true")
    SESSION_STORE[diagram_id] = {
        **SAMPLE_ANALYSIS,
        "migration_timeline": generate_timeline(SAMPLE_ANALYSIS),
    }
    token = issue_export_capability(diagram_id)

    try:
        first = test_client.get(
            f"/api/diagrams/{diagram_id}/migration-timeline/export?format=json",
            headers={"X-Export-Capability": token},
        )
        assert first.status_code == 200
        assert first.headers["x-export-capability-next"]

        replay = test_client.get(
            f"/api/diagrams/{diagram_id}/migration-timeline/export?format=json",
            headers={"X-Export-Capability": token},
        )
        assert replay.status_code == 401
    finally:
        SESSION_STORE.delete(diagram_id)
        EXPORT_CAPABILITY_STORE.clear()
