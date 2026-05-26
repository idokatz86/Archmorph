"""Mapping Evidence & Rationale Contract (issue #1130).

Provides a reusable evidence envelope for every AI service mapping.
Evidence is customer-safe: no secrets, no environment-specific details.

Evidence fields per mapping
───────────────────────────
- detection_source     : "catalogue" | "ai" | "user" | "sample" | "infra_import"
- detection_confidence : raw float confidence (0–1)
- rationale            : human-readable reason why this Azure service was chosen
- alternatives_considered : list of alternative Azure services weighed
- known_gaps           : no-direct-equivalent notes and feature gaps
- catalog_freshness    : last_reviewed date from the catalog entry (if any)
- user_override        : True if the user changed or confirmed the mapping
- user_confirmed       : True if the user explicitly confirmed the mapping
- needs_review         : True when confidence < NEEDS_REVIEW_THRESHOLD

Run metadata (build_run_metadata)
──────────────────────────────────
- run_id               : stable correlation / support ID for the analysis run
- analysis_timestamp   : ISO-8601 UTC timestamp of the analysis
- source_provider      : "aws" | "gcp"
- target_provider      : "azure"
- catalog_freshness    : freshness info from freshness_registry (age, stale flag)
- model_version        : AI model identifier used for suggestions
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.mappings import CROSS_CLOUD_MAPPINGS

# Confidence below this threshold flags the mapping for human review.
NEEDS_REVIEW_THRESHOLD = 0.70

# Build a lookup from (source_aws_lower or source_gcp_lower) → catalog row
_CATALOG_BY_AWS: Dict[str, Dict[str, Any]] = {}
_CATALOG_BY_GCP: Dict[str, Dict[str, Any]] = {}

for _row in CROSS_CLOUD_MAPPINGS:
    if _row.get("aws"):
        _CATALOG_BY_AWS[_row["aws"].lower()] = _row
    if _row.get("gcp"):
        _CATALOG_BY_GCP[_row["gcp"].lower()] = _row


# ─────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────

def build_mapping_evidence(
    mapping: Dict[str, Any],
    *,
    run_id: Optional[str] = None,
    analysis_timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a standardised evidence block for a single service mapping.

    Parameters
    ----------
    mapping : dict
        The mapping dict (must contain ``source_service``, ``azure_service``,
        ``confidence``, and optionally ``source``, ``alternatives``,
        ``feature_gaps``, ``notes``, ``source_provider``).
    run_id : str | None
        Correlation ID for the analysis run. If omitted a UUID is generated.
    analysis_timestamp : str | None
        ISO-8601 UTC timestamp. If omitted the current time is used.

    Returns
    -------
    dict
        Evidence block suitable for embedding directly in the mapping dict.
    """
    source_service = _coerce_text(mapping.get("source_service"))
    azure_service = _coerce_text(mapping.get("azure_service") or mapping.get("target_service"))
    confidence = _safe_float(mapping.get("confidence"), default=0.0)
    source = _coerce_text(mapping.get("source") or "unknown").lower()
    source_provider = _coerce_text(mapping.get("source_provider") or "aws").lower()

    # --- rationale ---
    rationale = _build_rationale(mapping, source_service, azure_service, source)

    # --- alternatives considered ---
    alternatives = _build_alternatives(mapping)

    # --- known gaps ---
    known_gaps = _build_known_gaps(mapping)

    # --- catalog freshness ---
    catalog_freshness = _lookup_catalog_freshness(source_service, source_provider)

    # --- user override status ---
    user_override = bool(mapping.get("user_override") or mapping.get("user_added"))
    user_confirmed = bool(
        mapping.get("user_confirmed")
        or mapping.get("review_status") in ("approved", "user_confirmed")
        or source == "user"
    )

    # --- needs review ---
    needs_review = confidence < NEEDS_REVIEW_THRESHOLD and not user_confirmed

    return {
        "detection_source": source,
        "detection_confidence": round(confidence, 4),
        "rationale": rationale,
        "alternatives_considered": alternatives,
        "known_gaps": known_gaps,
        "catalog_freshness": catalog_freshness,
        "user_override": user_override,
        "user_confirmed": user_confirmed,
        "needs_review": needs_review,
        "run_id": run_id or "",
        "generated_at": analysis_timestamp or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def build_run_metadata(
    analysis: Dict[str, Any],
    *,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build run-level metadata for an analysis result.

    This is embedded in manifests and exports so downstream consumers (including
    customers) can trace a package back to its originating run, catalog version,
    and model.

    Parameters
    ----------
    analysis : dict
        The full analysis result.
    run_id : str | None
        Stable correlation / support ID for the run.  If omitted a UUID is
        generated (and will differ between calls — pass the same ID for a
        given analysis session).

    Returns
    -------
    dict
        Run metadata block.
    """
    stable_run_id = run_id or str(analysis.get("run_id") or analysis.get("correlation_id") or uuid.uuid4())
    source_provider = str(
        analysis.get("source_provider") or analysis.get("provider") or "aws"
    ).lower()
    target_provider = str(analysis.get("target_provider") or "azure").lower()
    analysis_timestamp = str(
        analysis.get("analysis_timestamp")
        or analysis.get("generated_at")
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )

    # Catalog freshness from freshness_registry (best effort)
    catalog_freshness = _get_catalog_freshness_from_registry()

    # Confidence summary from mappings
    mappings = [m for m in analysis.get("mappings", []) if isinstance(m, dict)]
    low_conf = sum(1 for m in mappings if _safe_float(m.get("confidence"), default=0.0) < NEEDS_REVIEW_THRESHOLD)
    needs_review_count = sum(1 for m in mappings if m.get("evidence", {}).get("needs_review") or
                             (_safe_float(m.get("confidence"), default=0.0) < NEEDS_REVIEW_THRESHOLD and
                              not m.get("evidence", {}).get("user_confirmed")))

    return {
        "schema_version": "run-metadata/v1",
        "run_id": stable_run_id,
        "analysis_timestamp": analysis_timestamp,
        "source_provider": source_provider,
        "target_provider": target_provider,
        "catalog_freshness": catalog_freshness,
        "model_version": "gpt-4o",
        "total_mappings": len(mappings),
        "low_confidence_count": low_conf,
        "needs_review_count": needs_review_count,
        "methodology": _METHODOLOGY_SUMMARY,
        "limitations": _CUSTOMER_SAFE_LIMITATIONS,
    }


def attach_evidence_to_mappings(
    mappings: List[Dict[str, Any]],
    *,
    run_id: Optional[str] = None,
    analysis_timestamp: Optional[str] = None,
) -> None:
    """Attach an ``evidence`` block and ``needs_review`` flag to each mapping in-place.

    Idempotent: mappings that already carry an ``evidence`` block are skipped
    unless the existing block is missing ``needs_review``.
    """
    ts = analysis_timestamp or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for m in mappings:
        if not isinstance(m, dict):
            continue
        existing_evidence = m.get("evidence")
        if isinstance(existing_evidence, dict) and "needs_review" in existing_evidence:
            continue
        evidence = build_mapping_evidence(m, run_id=run_id, analysis_timestamp=ts)
        m["evidence"] = evidence
        # Promote needs_review to the top level for quick filtering
        m.setdefault("needs_review", evidence["needs_review"])


# ─────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────

def _coerce_text(value: Any) -> str:
    """Return a compact customer-safe text representation for arbitrary mapping fields."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        for key in ("name", "source", "source_service", "azure_service", "target_service", "label", "message", "description"):
            text = _coerce_text(value.get(key))
            if text:
                return text
        return ""
    if isinstance(value, list):
        return ", ".join(text for text in (_coerce_text(item) for item in value) if text)
    return str(value).strip()


def _safe_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def _build_rationale(
    mapping: Dict[str, Any],
    source_service: str,
    azure_service: str,
    source: str,
) -> str:
    """Build a human-readable rationale string."""
    # Use existing notes/confidence_explanation if meaningful
    notes = str(mapping.get("notes") or "").strip()
    # Remove zone annotations (e.g. "Zone 1 – Web: some note")
    import re
    notes = re.sub(r"^Zone\s+\d+\s*[–\-]\s*[^:]+:\s*", "", notes).strip()

    if source == "catalogue":
        base = f"{azure_service} is the recommended Azure equivalent for {source_service} per the Archmorph curated service catalog."
        if notes:
            base += f" {notes}."
        return base
    if source == "user":
        return f"{azure_service} was manually specified by the user for {source_service}."
    if source in ("ai", "gpt"):
        base = f"{azure_service} was selected by AI analysis as the best Azure match for {source_service}."
        if notes:
            base += f" {notes}."
        return base
    if source == "sample":
        base = f"{azure_service} is mapped from a pre-verified sample architecture for {source_service}."
        if notes:
            base += f" {notes}."
        return base
    if source == "infra_import":
        return f"{azure_service} was inferred from IaC/infrastructure import for {source_service}."
    # Generic fallback
    base = f"{azure_service} is the suggested Azure equivalent for {source_service}."
    if notes:
        base += f" {notes}."
    return base


def _build_alternatives(mapping: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract alternative Azure services from the mapping."""
    raw = mapping.get("alternatives") or []
    if not isinstance(raw, list):
        return []
    result = []
    for alt in raw:
        if isinstance(alt, dict):
            result.append({
                "azure_service": _coerce_text(alt.get("name") or alt.get("azure_service")),
                "confidence": _safe_float(alt.get("confidence"), default=0.0),
                "rationale": _coerce_text(alt.get("rationale") or alt.get("notes")),
            })
        elif isinstance(alt, str) and alt.strip():
            result.append({"azure_service": alt.strip(), "confidence": 0.0, "rationale": ""})
    return result[:5]  # cap at 5 alternatives


def _build_known_gaps(mapping: Dict[str, Any]) -> List[str]:
    """Collect known gaps, feature gaps, and no-direct-equivalent notes."""
    gaps: List[str] = []
    # Feature gaps from AI suggestion
    for gap in (mapping.get("feature_gaps") or []):
        if isinstance(gap, str) and gap.strip():
            gaps.append(gap.strip())
    # Limitations (structured)
    for lim in (mapping.get("limitations") or []):
        if isinstance(lim, dict):
            detail = str(lim.get("detail") or lim.get("factor") or "").strip()
            if detail and not any(g.lower() == detail.lower() for g in gaps):
                gaps.append(detail)
        elif isinstance(lim, str) and lim.strip():
            text = lim.strip()
            if not any(g.lower() == text.lower() for g in gaps):
                gaps.append(text)
    # Notes that mention no-direct-equivalent
    notes = str(mapping.get("notes") or "").lower()
    if "no direct equivalent" in notes or "no-direct-equivalent" in notes:
        note_text = str(mapping.get("notes") or "").strip()
        if not any(g.lower() == note_text.lower() for g in gaps):
            gaps.append(note_text)
    return gaps[:10]  # cap at 10 gaps


def _lookup_catalog_freshness(source_service: str, source_provider: str) -> Optional[str]:
    """Return the last_reviewed date for a catalog entry, or None."""
    key = source_service.strip().lower()
    if source_provider == "gcp":
        row = _CATALOG_BY_GCP.get(key)
    else:
        row = _CATALOG_BY_AWS.get(key)
    if row:
        return str(row.get("last_reviewed") or "") or None
    return None


def _get_catalog_freshness_from_registry() -> Dict[str, Any]:
    """Get catalog freshness info from the freshness_registry (best effort)."""
    try:
        from freshness_registry import get_all  # type: ignore[import]
        jobs = get_all()
        for job in jobs:
            if job.get("name") == "service_catalog_refresh":
                return {
                    "last_success": job.get("last_success"),
                    "age_hours": job.get("age_hours"),
                    "stale": job.get("stale", False),
                    "budget_hours": job.get("budget_hours"),
                }
    except Exception:
        pass
    # Fallback: derive from catalog last_reviewed dates
    dates = sorted(
        {row.get("last_reviewed") for row in CROSS_CLOUD_MAPPINGS if row.get("last_reviewed")},
        reverse=True,
    )
    return {
        "last_success": dates[0] if dates else None,
        "age_hours": None,
        "stale": False,
        "budget_hours": None,
    }


# ─────────────────────────────────────────────────────────
# Customer-safe methodology and limitations text
# ─────────────────────────────────────────────────────────

_METHODOLOGY_SUMMARY = (
    "Archmorph detects cloud services from the uploaded architecture diagram using "
    "GPT-4o multimodal analysis and a curated cross-cloud mapping catalog. "
    "Each mapping is scored using a blended confidence model: 70% catalog parity "
    "weight plus 30% AI detection confidence. Mappings with confidence below 70% "
    "are flagged for human review. The mapping catalog is reviewed periodically; "
    "the catalog freshness date is included in each package manifest."
)

_CUSTOMER_SAFE_LIMITATIONS = [
    "Archmorph produces directional mapping recommendations, not certified migration plans.",
    "Confidence scores reflect feature-level parity; they do not account for pricing, "
    "support agreements, or regulatory constraints specific to your organisation.",
    "AI-suggested mappings (source='ai') should be reviewed by a qualified cloud architect "
    "before committing to implementation.",
    "Service catalog is updated periodically; newly released cloud services may not yet "
    "be reflected in mapping recommendations.",
    "Alternatives listed are indicative; the optimal choice depends on workload "
    "characteristics not always visible in a static architecture diagram.",
    "Mappings marked needs_review=true have confidence below 70% and must be "
    "confirmed or overridden by the architecture owner before export.",
]
