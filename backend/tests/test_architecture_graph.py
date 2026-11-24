from __future__ import annotations

import pytest
from pydantic import ValidationError

from architecture_graph import ArchitectureGraph, build_architecture_graph


def test_graph_projects_only_resolvable_explicit_connections():
    graph = build_architecture_graph({
        "source_provider": "GCP",
        "mappings": [
            {
                "source_service": "GKE",
                "azure_service": "AKS",
                "confidence": 0.9,
                "evidence": {"rationale": "catalog match"},
            },
            {"source_service": "Cloud SQL", "azure_service": "Azure SQL"},
        ],
        "service_connections": [
            {"source": "GKE", "target": "Cloud SQL", "type": "database"},
            {"source": "unknown", "target": "AKS", "type": "traffic"},
        ],
    })

    assert graph["schema_version"] == "architecture-graph/v1"
    assert graph["source_provider"] == "gcp"
    assert len(graph["nodes"]) == 2
    assert len(graph["edges"]) == 1
    assert graph["edges"][0]["relationship"] == "database"
    assert graph["nodes"][0]["evidence"]["rationale"] == "catalog match"
    assert graph["warnings"] == ["connection_1_endpoint_unresolved_or_ambiguous"]


def test_graph_does_not_infer_edges_without_explicit_connections():
    graph = build_architecture_graph({
        "source_provider": "aws",
        "mappings": [{"source_service": "EC2", "azure_service": "Virtual Machines"}],
    })

    assert graph["nodes"]
    assert graph["edges"] == []

def test_normalized_analysis_builds_mapping_evidence_before_graph_projection():
    from routers.diagrams import _normalize_analysis

    analysis = _normalize_analysis({
        "source_provider": "gcp",
        "mappings": [{
            "source_service": "GKE",
            "azure_service": "AKS",
            "confidence": 0.92,
            "source": "catalogue",
        }],
    })

    evidence = analysis["mappings"][0]["evidence"]
    assert evidence["rationale"]
    assert evidence["run_id"]
    assert analysis["run_id"] == evidence["run_id"]
    assert analysis["analysis_timestamp"] == evidence["generated_at"]
    assert analysis["architecture_graph"]["nodes"][0]["evidence"] == evidence


def test_missing_provider_remains_unknown():
    graph = build_architecture_graph({
        "mappings": [{"source_service": "Service", "azure_service": "Azure Service"}],
    })

    assert graph["source_provider"] is None
    assert graph["nodes"][0]["source_provider"] is None


def test_graph_rejects_edges_with_unknown_node_ids():
    with pytest.raises(ValidationError, match="must reference existing nodes"):
        ArchitectureGraph(
            nodes=[],
            edges=[{
                "id": "edge-1",
                "source_node_id": "missing-source",
                "target_node_id": "missing-target",
                "relationship": "traffic",
            }],
        )
