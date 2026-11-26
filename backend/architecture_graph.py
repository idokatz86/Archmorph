"""Versioned, evidence-preserving projection of an analysis into a graph."""

from __future__ import annotations

import hashlib
import math
from typing import Any, Literal

from pydantic import Field, model_validator

from source_provider import normalize_source_provider
from strict_models import StrictBaseModel


class ArchitectureGraphNode(StrictBaseModel):
    id: str
    source_provider: str | None = None
    source_service: str
    target_service: str | None = None
    category: str | None = None
    confidence: float | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    confidence_provenance: dict[str, Any] = Field(default_factory=dict)
    needs_review: bool | None = None


class ArchitectureGraphEdge(StrictBaseModel):
    id: str
    source_node_id: str
    target_node_id: str
    relationship: str
    evidence_source: Literal["analysis.service_connections"] = "analysis.service_connections"


class ArchitectureGraph(StrictBaseModel):
    schema_version: Literal["architecture-graph/v1"] = "architecture-graph/v1"
    source_provider: str | None = None
    target_provider: str = "azure"
    nodes: list[ArchitectureGraphNode] = Field(default_factory=list)
    edges: list[ArchitectureGraphEdge] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph_references(self) -> "ArchitectureGraph":
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Architecture graph node IDs must be unique")

        known_ids = set(node_ids)
        if any(
            edge.source_node_id not in known_ids or edge.target_node_id not in known_ids
            for edge in self.edges
        ):
            raise ValueError("Architecture graph edges must reference existing nodes")
        return self


def build_architecture_graph(analysis: dict[str, Any]) -> dict[str, Any]:
    """Build a strict graph projection without inferring missing topology."""
    if not isinstance(analysis, dict):
        raise ValueError("analysis must be a dict")

    warnings: list[str] = []
    source_provider = _normalize_provider(analysis.get("source_provider"), warnings)
    if source_provider is None:
        warnings.append("analysis_source_provider_missing_or_unsupported")
    target_provider = str(analysis.get("target_provider") or "azure").strip().lower() or "azure"
    raw_mappings = analysis.get("mappings", [])
    mappings = raw_mappings if isinstance(raw_mappings, list) else []
    if raw_mappings is not None and not isinstance(raw_mappings, list):
        warnings.append("mappings_not_a_list")

    nodes: list[ArchitectureGraphNode] = []
    aliases: dict[str, set[str]] = {}
    for index, mapping in enumerate(mappings):
        if not isinstance(mapping, dict):
            warnings.append(f"mapping_{index}_not_an_object")
            continue

        source_service = _service_name(mapping.get("source_service"))
        target_service = _service_name(mapping.get("azure_service") or mapping.get("target_service"))
        if not source_service:
            warnings.append(f"mapping_{index}_missing_source_service")
            continue

        mapping_provider = mapping.get("source_provider")
        if isinstance(mapping_provider, str) and not mapping_provider.strip():
            mapping_provider = None
        if mapping_provider is None:
            node_provider = source_provider
        else:
            node_provider = _normalize_provider(
                mapping_provider,
                warnings,
                index=index,
            )
        node_material = f"{index}\0{node_provider or ''}\0{source_service}\0{target_service}"
        node_id = f"mapping-{index}-{hashlib.sha256(node_material.encode('utf-8')).hexdigest()[:10]}"
        confidence_value = mapping.get("confidence")
        confidence = None
        if isinstance(confidence_value, (int, float)) and not isinstance(confidence_value, bool):
            candidate_confidence = float(confidence_value)
            if math.isfinite(candidate_confidence):
                confidence = candidate_confidence
            else:
                warnings.append(f"mapping_{index}_confidence_not_finite")
        elif confidence_value is not None:
            warnings.append(f"mapping_{index}_confidence_not_numeric")
        evidence = mapping.get("evidence")
        confidence_provenance = mapping.get("confidence_provenance")
        needs_review = mapping.get("needs_review")
        if not isinstance(needs_review, bool) and isinstance(evidence, dict):
            needs_review = evidence.get("needs_review")
        if not isinstance(needs_review, bool):
            needs_review = None

        node = ArchitectureGraphNode(
            id=node_id,
            source_provider=node_provider,
            source_service=source_service,
            target_service=target_service or None,
            category=_service_name(mapping.get("category")) or None,
            confidence=confidence,
            evidence=evidence if isinstance(evidence, dict) else {},
            confidence_provenance=(
                confidence_provenance if isinstance(confidence_provenance, dict) else {}
            ),
            needs_review=needs_review,
        )
        nodes.append(node)
        for alias in (source_service, target_service):
            key = _normalize_alias(alias)
            if key:
                aliases.setdefault(key, set()).add(node_id)

    raw_connections = analysis.get("service_connections", [])
    connections = raw_connections if isinstance(raw_connections, list) else []
    if raw_connections is not None and not isinstance(raw_connections, list):
        warnings.append("service_connections_not_a_list")

    edges: list[ArchitectureGraphEdge] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for index, connection in enumerate(connections):
        if not isinstance(connection, dict):
            warnings.append(f"connection_{index}_not_an_object")
            continue

        source_name = _service_name(connection.get("source") or connection.get("from"))
        target_name = _service_name(connection.get("target") or connection.get("to"))
        source_ids = aliases.get(_normalize_alias(source_name), set())
        target_ids = aliases.get(_normalize_alias(target_name), set())
        if len(source_ids) != 1 or len(target_ids) != 1:
            warnings.append(f"connection_{index}_endpoint_unresolved_or_ambiguous")
            continue

        source_id = next(iter(source_ids))
        target_id = next(iter(target_ids))
        relationship = _service_name(connection.get("type")) or "unspecified"
        edge_key = (source_id, target_id, relationship)
        if source_id == target_id or edge_key in seen_edges:
            warnings.append(f"connection_{index}_duplicate_or_self_referential")
            continue

        seen_edges.add(edge_key)
        edge_material = f"{source_id}\0{target_id}\0{relationship}"
        edges.append(
            ArchitectureGraphEdge(
                id=f"connection-{hashlib.sha256(edge_material.encode('utf-8')).hexdigest()[:12]}",
                source_node_id=source_id,
                target_node_id=target_id,
                relationship=relationship,
            )
        )

    graph = ArchitectureGraph(
        source_provider=source_provider,
        target_provider=target_provider,
        nodes=nodes,
        edges=edges,
        warnings=warnings,
    )
    return graph.model_dump(mode="json")


def _normalize_provider(value: object, warnings: list[str], *, index: int | None = None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() == "user":
        return None
    try:
        return normalize_source_provider(value)
    except ValueError:
        suffix = f"_{index}" if index is not None else ""
        warnings.append(f"unsupported_source_provider{suffix}")
        return None


def _service_name(value: object) -> str:
    if isinstance(value, dict):
        value = value.get("name", value.get("short_name", ""))
    return value.strip() if isinstance(value, str) else ""


def _normalize_alias(value: str) -> str:
    return " ".join(value.casefold().split())
