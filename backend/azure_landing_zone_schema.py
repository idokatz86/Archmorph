"""Landing Zone schema inference helpers (#572).

Adds optional structured context (regions, dr_mode, tiers, actors,
replication) to the analysis result so the Landing Zone SVG generator
(#573) can render a region-aware, tiered architecture diagram.

All inference helpers are deterministic, side-effect-free, and
backwards-compatible: an analysis dict that does not contain any of the
new keys is still valid, and the helpers fill in safe defaults.

These helpers are read-only — they never mutate the input analysis.

Sub-issue: https://github.com/idokatz86/Archmorph/issues/572
Parent epic: https://github.com/idokatz86/Archmorph/issues/571
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Tier classification — maps mapping.category → tier bucket
# ---------------------------------------------------------------------------

# Canonical tier order used everywhere downstream.
TIER_ORDER: tuple[str, ...] = (
    "ingress",
    "compute",
    "data",
    "identity",
    "observability",
    "storage",
)

# Heuristic mapping from analysis-result categories to a tier bucket.
# Lower-cased exact match; if a category is unknown it falls into "compute"
# (the safe default for stateless workloads).
#
# #589 (D2 fix): the original mapping omitted 7 categories in active use by
# `services.mappings.CROSS_CLOUD_MAPPINGS` (Management, DevTools, Integration,
# IoT, Data Governance, Hybrid, Zero Trust, Business). They silently fell to
# "compute", emptying the observability tier on workloads with Azure Monitor /
# ARM tools and the data tier on event-driven workloads with Service Bus /
# Event Grid. The CTO E2E review on 2026-05-01 measured 5 of 8 tiers as empty
# on a workload that should have populated all 8. Each new key below is a
# vendor-neutral routing decision; the comment beside it points at the
# Azure-side resource(s) that drove the tier choice.
_CATEGORY_TO_TIER: dict[str, str] = {
    # Ingress / edge
    "networking": "ingress",
    "edge": "ingress",
    "ingress": "ingress",
    "loadbalancer": "ingress",
    "hybrid": "ingress",          # ExpressRoute, Arc — perimeter / on-prem ingress
    # Compute
    "compute": "compute",
    "container": "compute",
    "containers": "compute",
    "serverless": "compute",
    "ai/ml": "compute",
    "ai-ml": "compute",
    "ml": "compute",
    "media": "compute",           # Media Services, transcoders — workload, not data
    "migration": "compute",       # Azure Migrate, Database Migration — workload tools
    "devtools": "compute",        # #589 — DevOps, Pipelines, Artifacts
    "business": "compute",        # M365, Power Platform — productivity workloads
    # Data
    "database": "data",
    "data": "data",
    "analytics": "data",
    "messaging": "data",
    "queue": "data",
    "stream": "data",
    "integration": "data",        # #589 — Service Bus, Event Grid, Logic Apps
    "iot": "data",                # #589 — IoT Hub, Stream Analytics, Digital Twins
    "data governance": "data",    # #589 — Purview, Data Catalog
    # Identity / security
    "identity": "identity",
    "security": "identity",
    "secrets": "identity",
    "zero trust": "identity",     # #589 — Conditional Access, Entra ID Protection
    # Observability
    "observability": "observability",
    "monitoring": "observability",
    "logging": "observability",
    "telemetry": "observability",
    "management": "observability",  # #589 — Azure Monitor, ARM, Resource Graph
    # Storage
    "storage": "storage",
    "files": "storage",
    "blob": "storage",
}

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_PRIMARY_REGION = {"name": "East US", "role": "primary", "traffic_pct": 100}
DEFAULT_STANDBY_REGION = {"name": "West US 3", "role": "standby", "traffic_pct": 0}

DEFAULT_ACTOR = {"name": "End User", "kind": "external"}

# Replication items derived from data-tier services for DR variants.
_DEFAULT_REPLICATION_TEMPLATES = [
    {"name": "Storage Account", "mode": "geo-redundant (RA-GRS) · async"},
    {"name": "Managed DB",      "mode": "geo-replica · async · failover group"},
    {"name": "Key Vault",       "mode": "KV replication · same-name secret IDs"},
    {"name": "Event Hubs",      "mode": "Geo-DR pairing · alias namespace"},
    {"name": "Front Door",      "mode": "Active/Standby routing rules · health probes"},
    {"name": "Identity",        "mode": "Single Entra tenant · global"},
]


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def infer_dr_mode(analysis: dict[str, Any]) -> str:
    """Return the DR mode for the analysis.

    - ``"active-active"``  — multiple regions with traffic_pct > 0
    - ``"active-standby"`` — multiple regions, exactly one carries traffic
    - ``"single-region"``  — only one region (default)

    If the caller has set ``dr_mode`` explicitly we honour it (after
    validating it is one of the three known values); otherwise we infer
    from ``regions``.
    """
    explicit = analysis.get("dr_mode")
    if isinstance(explicit, str) and explicit in ("active-active", "active-standby", "single-region"):
        return explicit

    regions = analysis.get("regions")
    if not isinstance(regions, list):
        return "single-region"

    # Only well-formed region dicts (with a name) count toward the multi-region
    # check; otherwise a single valid region surrounded by junk would be
    # mis-classified as multi-region.
    valid = [r for r in regions if isinstance(r, dict) and r.get("name")]
    if len(valid) < 2:
        return "single-region"

    pct_carrying = 0
    for r in valid:
        try:
            pct = float(r.get("traffic_pct", 0))
        except (TypeError, ValueError):
            pct = 0.0
        if pct > 0:
            pct_carrying += 1

    return "active-active" if pct_carrying >= 2 else "active-standby"


def infer_regions(analysis: dict[str, Any], *, dr_variant: str = "primary") -> list[dict[str, Any]]:
    """Return the list of regions to render.

    - If ``regions`` is present and well-formed, return a deep-ish copy.
    - Otherwise return a single primary region for ``dr_variant="primary"``
      or a primary + standby pair for ``dr_variant="dr"``.

    The renderer always receives at least one region.
    """
    regions = analysis.get("regions")
    if isinstance(regions, list) and regions:
        out: list[dict[str, Any]] = []
        for r in regions:
            if not isinstance(r, dict) or not r.get("name"):
                continue
            out.append({
                "name": str(r["name"]),
                "role": str(r.get("role", "primary")),
                "traffic_pct": _coerce_pct(r.get("traffic_pct"), default=100 if not out else 0),
            })
        if out:
            # Pad to two regions when DR was requested but only one configured.
            if dr_variant == "dr" and len(out) == 1:
                out.append(dict(DEFAULT_STANDBY_REGION))
            return out

    # Nothing usable — fall back to defaults.
    if dr_variant == "dr":
        return [dict(DEFAULT_PRIMARY_REGION), dict(DEFAULT_STANDBY_REGION)]
    return [dict(DEFAULT_PRIMARY_REGION)]


def infer_tiers_from_mappings(analysis: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Return a tier → service-list map.

    Each service in the returned dict is a small struct::

        {"name": "Azure Application Gateway",
         "source": "AWS Application Load Balancer",
         "subtitle": "Replaces AWS Application Load Balancer"}

    Resolution order:
    1. If ``tiers`` is already present in the analysis, normalise and return it.
    2. Otherwise, derive from ``mappings`` using ``mapping.category``.

    Output is guaranteed to contain every key in ``TIER_ORDER`` (possibly
    with an empty list).
    """
    out: dict[str, list[dict[str, Any]]] = {t: [] for t in TIER_ORDER}

    explicit = analysis.get("tiers")
    if isinstance(explicit, dict):
        for tier, items in explicit.items():
            if tier not in TIER_ORDER or not isinstance(items, list):
                continue
            for entry in items:
                normalised = _normalise_tier_entry(entry)
                if normalised:
                    out[tier].append(normalised)
        if any(v for v in out.values()):
            return out

    # Derive from mappings.
    mappings = analysis.get("mappings", [])
    if not isinstance(mappings, list):
        return out

    for m in mappings:
        if not isinstance(m, dict):
            continue
        azure = m.get("azure_service") or m.get("target") or ""
        source = m.get("source_service") or m.get("source") or ""
        category = (m.get("category") or "").strip().lower()
        if not azure:
            continue
        tier = _CATEGORY_TO_TIER.get(category, "compute")
        out[tier].append({
            "name": str(azure),
            "source": str(source) if source else "",
            "subtitle": f"Replaces {source}" if source else "",
        })

    return out


def infer_actors(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """Return external/internal actors hitting the system.

    Honours ``analysis['actors']`` when present and well-formed, otherwise
    returns the default single end-user actor.
    """
    actors = analysis.get("actors")
    if isinstance(actors, list) and actors:
        out: list[dict[str, Any]] = []
        for a in actors:
            if not isinstance(a, dict) or not a.get("name"):
                continue
            out.append({
                "name": str(a["name"]),
                "kind": str(a.get("kind", "external")),
                "subtitle": str(a.get("subtitle", "")),
                "edge_label": str(a.get("edge_label", "HTTPS")),
            })
        if out:
            return out
    return [dict(DEFAULT_ACTOR, subtitle="", edge_label="HTTPS")]


def infer_replication(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """Return cross-region replication metadata for the DR band.

    Honours ``analysis['replication']`` when present, otherwise returns a
    canonical 6-item template covering the most common Azure stamps.
    Returns an empty list when ``dr_mode`` is single-region.
    """
    if infer_dr_mode(analysis) == "single-region":
        # Allow override even on single-region (caller might want to show
        # what *would* replicate); honour explicit list.
        explicit = analysis.get("replication")
        if isinstance(explicit, list) and explicit:
            return [
                {"name": str(r.get("name", "")), "mode": str(r.get("mode", ""))}
                for r in explicit
                if isinstance(r, dict) and r.get("name")
            ]
        return []

    explicit = analysis.get("replication")
    if isinstance(explicit, list) and explicit:
        out: list[dict[str, Any]] = []
        for r in explicit:
            if not isinstance(r, dict) or not r.get("name"):
                continue
            out.append({"name": str(r["name"]), "mode": str(r.get("mode", ""))})
        if out:
            return out

    return [dict(t) for t in _DEFAULT_REPLICATION_TEMPLATES]


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _coerce_pct(value: Any, *, default: int) -> int:
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(0, min(100, n))


def _normalise_tier_entry(entry: Any) -> dict[str, Any] | None:
    """Accept either a string or a dict and return the canonical struct."""
    if isinstance(entry, str) and entry.strip():
        return {"name": entry.strip(), "source": "", "subtitle": ""}
    if isinstance(entry, dict):
        name = str(entry.get("name", "")).strip()
        if not name:
            return None
        source = str(entry.get("source", "")).strip()
        subtitle = str(entry.get("subtitle", "")).strip()
        if not subtitle and source:
            subtitle = f"Replaces {source}"
        return {"name": name, "source": source, "subtitle": subtitle}
    return None
