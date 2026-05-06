"""Deterministic project analysis merge for multi-diagram MVP (#241)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List, Tuple


def _text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("name", "source", "service", "source_service", "aws", "gcp", "azure_service", "azure", "label"):
            if value.get(key):
                return str(value[key])
        return str(value)
    return "" if value is None else str(value)


def _norm(value: Any) -> str:
    return " ".join(_text(value).strip().lower().split())


def _stable_unique(values: Iterable[Any]) -> List[Any]:
    seen = set()
    output = []
    for value in values:
        key = _norm(value)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def _mapping_key(mapping: Dict[str, Any]) -> Tuple[str, str, str]:
    return (
        _norm(mapping.get("source_provider") or "aws"),
        _norm(mapping.get("source_service")),
        _norm(mapping.get("azure_service") or mapping.get("target_service")),
    )


def _service_names_from_mapping(mapping: Dict[str, Any]) -> List[str]:
    return [
        name for name in (
            _text(mapping.get("source_service")),
            _text(mapping.get("azure_service") or mapping.get("target_service")),
        ) if name
    ]


def _confidence_summary(mappings: List[Dict[str, Any]]) -> Dict[str, Any]:
    high = medium = low = 0
    total = 0.0
    for mapping in mappings:
        confidence = float(mapping.get("confidence") or 0)
        total += confidence
        if confidence >= 0.9:
            high += 1
        elif confidence >= 0.7:
            medium += 1
        else:
            low += 1
    return {
        "high": high,
        "medium": medium,
        "low": low,
        "average": round(total / len(mappings), 4) if mappings else 0,
    }


def _merge_zones(analyses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    zones_by_name: Dict[str, Dict[str, Any]] = {}
    for analysis in analyses:
        diagram_id = analysis.get("diagram_id")
        for zone in analysis.get("zones") or []:
            name = zone.get("name") or f"Zone {zone.get('id', len(zones_by_name) + 1)}"
            key = _norm(name)
            merged = zones_by_name.setdefault(key, {
                "id": len(zones_by_name) + 1,
                "name": name,
                "number": len(zones_by_name) + 1,
                "services": [],
                "source_diagram_ids": [],
            })
            merged["source_diagram_ids"] = sorted(set(merged["source_diagram_ids"] + [diagram_id]))
            merged["services"] = _stable_unique(merged["services"] + list(zone.get("services") or []))
    return [zones_by_name[key] for key in sorted(zones_by_name)]


def _merge_connections(analyses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    connections: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for analysis in analyses:
        diagram_id = analysis.get("diagram_id")
        for conn in analysis.get("service_connections") or analysis.get("connections") or []:
            source = conn.get("from") or conn.get("source") or conn.get("source_service")
            target = conn.get("to") or conn.get("target") or conn.get("target_service")
            protocol = conn.get("protocol") or conn.get("type") or ""
            key = (_norm(source), _norm(target), _norm(protocol))
            if not key[0] or not key[1]:
                continue
            merged = connections.setdefault(key, deepcopy(conn))
            merged.setdefault("from", _text(source))
            merged.setdefault("to", _text(target))
            merged["source_diagram_ids"] = sorted(set(merged.get("source_diagram_ids", []) + [diagram_id]))
    return [connections[key] for key in sorted(connections)]


def merge_project_analyses(project_id: str, analyses: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge analyzed diagrams into one stable project analysis.

    Duplicate services are merged by `(source_provider, source_service,
    azure_service)`.  The highest-confidence mapping becomes canonical while
    `source_diagram_ids` preserves provenance for cross-diagram visibility.
    """
    sorted_analyses = sorted((deepcopy(a) for a in analyses), key=lambda a: a.get("diagram_id", ""))
    mappings_by_key: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    service_occurrences: Dict[str, Dict[str, Any]] = {}
    warnings: List[Any] = []
    source_providers: List[str] = []
    target_providers: List[str] = []

    for analysis in sorted_analyses:
        diagram_id = analysis.get("diagram_id")
        source_providers.append(analysis.get("source_provider") or "aws")
        target_providers.append(analysis.get("target_provider") or "azure")
        warnings.extend(analysis.get("warnings") or [])

        for mapping in analysis.get("mappings") or []:
            mapping = deepcopy(mapping)
            if "azure_service" not in mapping and "target_service" in mapping:
                mapping["azure_service"] = mapping.pop("target_service")
            mapping["source_service"] = _text(mapping.get("source_service"))
            mapping["azure_service"] = _text(mapping.get("azure_service"))
            mapping.setdefault("source_provider", analysis.get("source_provider") or "aws")
            mapping.setdefault("source_diagram_ids", [])
            mapping["source_diagram_ids"] = sorted(set(mapping["source_diagram_ids"] + [diagram_id]))

            key = _mapping_key(mapping)
            existing = mappings_by_key.get(key)
            if existing is None or float(mapping.get("confidence") or 0) > float(existing.get("confidence") or 0):
                previous_ids = existing.get("source_diagram_ids", []) if existing else []
                mapping["source_diagram_ids"] = sorted(set(mapping["source_diagram_ids"] + previous_ids))
                mappings_by_key[key] = mapping
            else:
                existing["source_diagram_ids"] = sorted(set(existing.get("source_diagram_ids", []) + [diagram_id]))

            for service_name in _service_names_from_mapping(mapping):
                service_key = _norm(service_name)
                occurrence = service_occurrences.setdefault(service_key, {"service": service_name, "diagram_ids": set()})
                occurrence["diagram_ids"].add(diagram_id)

    mappings = [mappings_by_key[key] for key in sorted(mappings_by_key)]
    cross_diagram_links = [
        {
            "service": occurrence["service"],
            "diagram_ids": sorted(occurrence["diagram_ids"]),
            "link_type": "shared_service",
        }
        for key, occurrence in sorted(service_occurrences.items())
        if len(occurrence["diagram_ids"]) > 1
    ]

    return {
        "project_id": project_id,
        "diagram_id": f"project-{project_id}",
        "diagram_type": "Multi-diagram Architecture",
        "source_provider": _stable_unique(source_providers)[0] if source_providers else "aws",
        "source_providers": _stable_unique(source_providers),
        "target_provider": _stable_unique(target_providers)[0] if target_providers else "azure",
        "target_providers": _stable_unique(target_providers),
        "architecture_patterns": _stable_unique(
            pattern
            for analysis in sorted_analyses
            for pattern in (analysis.get("architecture_patterns") or [])
        ),
        "services_detected": len(mappings),
        "zones": _merge_zones(sorted_analyses),
        "mappings": mappings,
        "service_connections": _merge_connections(sorted_analyses),
        "cross_diagram_links": cross_diagram_links,
        "warnings": _stable_unique(warnings),
        "confidence_summary": _confidence_summary(mappings),
        "source_diagram_ids": [a.get("diagram_id") for a in sorted_analyses if a.get("diagram_id")],
        "combined": True,
    }