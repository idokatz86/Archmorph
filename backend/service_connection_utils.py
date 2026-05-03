"""Shared helpers for rendering service-level connection edges."""

from __future__ import annotations

import re
from typing import Any


def service_key(value: Any) -> str:
    """Stable fuzzy key for matching connection endpoints to rendered services."""
    text = str(value or "").lower().strip()
    text = re.sub(r"\[[^\]]+\]", "", text)
    text = re.sub(r"\b(?:aws|amazon|azure|gcp|google|microsoft)\b", "", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def connection_endpoint(conn: dict[str, Any], primary: str, secondary: str) -> str:
    return str(conn.get(primary) or conn.get(secondary) or "")


def connection_label(conn: dict[str, Any]) -> str:
    protocol = str(conn.get("protocol") or "").strip()
    conn_type = str(conn.get("type") or "").strip()
    bits = [bit for bit in (protocol, conn_type) if bit]
    return " · ".join(bits)


def mapping_aliases(mappings: list[dict[str, Any]]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        azure = str(mapping.get("azure_service") or mapping.get("target") or "").strip()
        if not azure:
            continue
        for field in (
            "source_service",
            "aws_service",
            "gcp_service",
            "source",
            "azure_service",
            "target",
        ):
            value = mapping.get(field)
            if value:
                aliases[service_key(value)] = azure
        aliases[service_key(azure)] = azure
    return aliases


def resolved_connection_endpoint(endpoint: str, aliases: dict[str, str]) -> str:
    return aliases.get(service_key(endpoint), endpoint)