"""Analysis payload size guardrails for renderer-facing routes.

Issue #613: user-controlled analysis arrays must be bounded before export
renderers iterate over them. The export-diagram route reads analysis from the
session store rather than directly from a request body, so this module provides
the route-layer equivalent of a Pydantic ``max_items`` contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


MAX_ANALYSIS_LIST_ITEMS = 200
MAX_RESTORE_BODY_BYTES = 12 * 1024 * 1024
MAX_RESTORE_STRING_CHARS = 2 * 1024 * 1024
MAX_RESTORE_NESTING_DEPTH = 20
MAX_RESTORE_NODE_COUNT = 10_000

RENDERER_ANALYSIS_LIST_FIELDS: tuple[str, ...] = (
    "zones",
    "actors",
    "regions",
    "mappings",
    "service_connections",
    "replication",
)


class AnalysisPayloadTooLarge(ValueError):
    """Raised when an analysis payload exceeds renderer input budgets."""

    def __init__(self, field: str, count: int, limit: int):
        self.field = field
        self.count = count
        self.limit = limit
        super().__init__(
            f"Analysis payload field '{field}' contains {count} items; "
            f"maximum is {limit}"
        )

    @property
    def details(self) -> dict[str, int | str]:
        return {
            "field": self.field,
            "count": self.count,
            "limit": self.limit,
        }


def validate_restore_payload_shape(value: Any) -> None:
    """Bound aggregate nodes, nesting, and strings before durable restore."""
    seen = 0

    def walk(node: Any, depth: int) -> None:
        nonlocal seen
        seen += 1
        if seen > MAX_RESTORE_NODE_COUNT:
            raise AnalysisPayloadTooLarge("body.nodes", seen, MAX_RESTORE_NODE_COUNT)
        if depth > MAX_RESTORE_NESTING_DEPTH:
            raise AnalysisPayloadTooLarge(
                "body.depth",
                depth,
                MAX_RESTORE_NESTING_DEPTH,
            )
        if isinstance(node, str):
            if len(node) > MAX_RESTORE_STRING_CHARS:
                raise AnalysisPayloadTooLarge(
                    "body.string",
                    len(node),
                    MAX_RESTORE_STRING_CHARS,
                )
            return
        if isinstance(node, Mapping):
            if len(node) > MAX_ANALYSIS_LIST_ITEMS:
                raise AnalysisPayloadTooLarge(
                    "body.object_fields",
                    len(node),
                    MAX_ANALYSIS_LIST_ITEMS,
                )
            for key, child in node.items():
                walk(str(key), depth + 1)
                walk(child, depth + 1)
            return
        if isinstance(node, (list, tuple)):
            if len(node) > MAX_ANALYSIS_LIST_ITEMS:
                raise AnalysisPayloadTooLarge(
                    "body.array_items",
                    len(node),
                    MAX_ANALYSIS_LIST_ITEMS,
                )
            for child in node:
                walk(child, depth + 1)

    walk(value, 0)


def validate_analysis_payload_bounds(
    analysis: Mapping[str, Any],
    *,
    max_items: int = MAX_ANALYSIS_LIST_ITEMS,
) -> None:
    """Reject analysis arrays that can make export rendering unbounded.

    Top-level renderer inputs are checked directly. Zone service buckets and
    explicit ``tiers`` are nested renderer inputs, so each bucket is checked
    independently.
    """
    for field in RENDERER_ANALYSIS_LIST_FIELDS:
        value = analysis.get(field)
        if isinstance(value, list) and len(value) > max_items:
            raise AnalysisPayloadTooLarge(field, len(value), max_items)

    zones = analysis.get("zones")
    if isinstance(zones, list):
        for index, zone in enumerate(zones):
            if not isinstance(zone, Mapping):
                continue
            services = zone.get("services")
            if isinstance(services, list) and len(services) > max_items:
                raise AnalysisPayloadTooLarge(
                    f"zones[{index}].services",
                    len(services),
                    max_items,
                )

    tiers = analysis.get("tiers")
    if isinstance(tiers, Mapping):
        for tier, entries in tiers.items():
            if isinstance(entries, list) and len(entries) > max_items:
                raise AnalysisPayloadTooLarge(
                    f"tiers.{tier}",
                    len(entries),
                    max_items,
                )