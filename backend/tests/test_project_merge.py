from copy import deepcopy

from project_merge import merge_project_analyses


def _analysis(diagram_id, mappings, connections=None):
    return {
        "diagram_id": diagram_id,
        "diagram_type": "Layer",
        "source_provider": "aws",
        "target_provider": "azure",
        "services_detected": len(mappings),
        "zones": [
            {
                "id": 1,
                "name": "Shared",
                "services": [
                    {"aws": m["source_service"], "azure": m["azure_service"], "confidence": m["confidence"]}
                    for m in mappings
                ],
            }
        ],
        "mappings": deepcopy(mappings),
        "service_connections": connections or [],
        "warnings": [],
        "confidence_summary": {"high": 0, "medium": 0, "low": 0, "average": 0},
    }


def test_merge_project_analyses_is_deterministic_across_input_order():
    first = _analysis(
        "diag-b",
        [
            {"source_service": "Amazon S3", "source_provider": "aws", "azure_service": "Azure Blob Storage", "confidence": 0.91},
            {"source_service": "Amazon EC2", "source_provider": "aws", "azure_service": "Azure Virtual Machines", "confidence": 0.82},
        ],
    )
    second = _analysis(
        "diag-a",
        [
            {"source_service": "Amazon RDS", "source_provider": "aws", "azure_service": "Azure SQL Database", "confidence": 0.88},
        ],
    )

    merged_a = merge_project_analyses("project-1", [first, second])
    merged_b = merge_project_analyses("project-1", [second, first])

    assert merged_a == merged_b
    assert merged_a["source_diagram_ids"] == ["diag-a", "diag-b"]
    assert [m["source_service"] for m in merged_a["mappings"]] == [
        "Amazon EC2",
        "Amazon RDS",
        "Amazon S3",
    ]


def test_merge_deduplicates_services_and_preserves_source_diagram_ids():
    first = _analysis(
        "diag-1",
        [{"source_service": "Amazon S3", "source_provider": "aws", "azure_service": "Azure Blob Storage", "confidence": 0.81}],
    )
    second = _analysis(
        "diag-2",
        [{"source_service": "Amazon S3", "source_provider": "aws", "azure_service": "Azure Blob Storage", "confidence": 0.94}],
    )

    merged = merge_project_analyses("project-1", [first, second])

    assert merged["services_detected"] == 1
    assert merged["mappings"][0]["confidence"] == 0.94
    assert merged["mappings"][0]["source_diagram_ids"] == ["diag-1", "diag-2"]
    assert merged["cross_diagram_links"] == [
        {"service": "Amazon S3", "diagram_ids": ["diag-1", "diag-2"], "link_type": "shared_service"},
        {"service": "Azure Blob Storage", "diagram_ids": ["diag-1", "diag-2"], "link_type": "shared_service"},
    ]


def test_merge_unions_service_connections_with_provenance():
    first = _analysis(
        "diag-1",
        [{"source_service": "Amazon EC2", "source_provider": "aws", "azure_service": "Azure Virtual Machines", "confidence": 0.9}],
        connections=[{"from": "Amazon EC2", "to": "Amazon RDS", "protocol": "TCP/5432"}],
    )
    second = _analysis(
        "diag-2",
        [{"source_service": "Amazon RDS", "source_provider": "aws", "azure_service": "Azure SQL Database", "confidence": 0.9}],
        connections=[{"from": "Amazon EC2", "to": "Amazon RDS", "protocol": "TCP/5432"}],
    )

    merged = merge_project_analyses("project-1", [first, second])

    assert merged["service_connections"] == [
        {
            "from": "Amazon EC2",
            "to": "Amazon RDS",
            "protocol": "TCP/5432",
            "source_diagram_ids": ["diag-1", "diag-2"],
        }
    ]