"""
Architect Review Queue Builder — Issue #1137.

Inspects an analysis result and produces structured review items that an
architect must disposition (Accept / Edit / Mark as risk / Exclude) before
deliverables are generated.

Buckets
-------
assumptions       — assumed answers auto-generated during guided questions
low_confidence    — service mappings with confidence < 0.8
architecture_gap  — warnings, missing patterns, unknown services
cost_warning      — cost or pricing anomalies detected in the analysis
security_concern  — compliance, security, or trust-boundary issues

Severity
--------
high   — must be accepted or explicitly retained as a risk before deliverables
medium — should be reviewed; deliverables proceed but item is flagged
low    — informational; architect may dismiss at any time
"""

from __future__ import annotations

import hashlib
from typing import Any

# Confidence threshold below which a mapping is flagged for review
_LOW_CONFIDENCE_THRESHOLD = 0.8

# Keywords that indicate a cost/pricing concern in a warning message
_COST_KEYWORDS = frozenset({
    "cost", "price", "pricing", "budget", "expensive", "spend", "billing",
    "estimate", "license", "egress",
})

# Keywords that indicate a security or compliance concern
_SECURITY_KEYWORDS = frozenset({
    "security", "compliance", "firewall", "encryption", "key vault", "tls",
    "ssl", "secret", "identity", "rbac", "iam", "auth", "access", "pci",
    "hipaa", "gdpr", "soc2", "iso27001", "cmk", "worm", "audit",
})


def _stable_item_id(bucket: str, discriminator: str) -> str:
    """Return a stable, short ID for a review item so frontends can track dispositions."""
    raw = f"{bucket}:{discriminator}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _classify_warning(text: str) -> str:
    """Return 'cost_warning', 'security_concern', or 'architecture_gap' for a warning."""
    lower = text.lower()
    if any(k in lower for k in _COST_KEYWORDS):
        return "cost_warning"
    if any(k in lower for k in _SECURITY_KEYWORDS):
        return "security_concern"
    return "architecture_gap"


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        for key in ("message", "text", "name", "label", "value", "description", "question", "assumed_answer"):
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


def build_review_queue(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the architect review queue from an analysis result.

    Parameters
    ----------
    analysis:
        The full analysis dict returned by the vision analyzer / apply-answers
        endpoint.

    Returns
    -------
    list[dict]
        Review items sorted by severity (high → medium → low) then bucket.
        Each item has the shape::

            {
                "id":          str,   # stable 16-char hex ID
                "bucket":      str,   # see module docstring
                "title":       str,   # short human-readable label
                "description": str,   # full detail
                "severity":    str,   # "high" | "medium" | "low"
                "source":      dict,  # optional raw source data
            }
    """
    items: list[dict[str, Any]] = []

    # ── 1. Low-confidence mappings ─────────────────────────────────────────
    for m in analysis.get("mappings", []):
        if not isinstance(m, dict):
            continue
        confidence = _safe_float(m.get("confidence"), default=0.0)
        if confidence >= _LOW_CONFIDENCE_THRESHOLD:
            continue
        source = _coerce_text(m.get("source_service")) or "Unknown"
        target = _coerce_text(m.get("azure_service") or m.get("target")) or "Unknown"
        pct = int(confidence * 100)
        item_id = _stable_item_id("low_confidence", f"{source}:{target}")
        severity = "high" if confidence < 0.5 else "medium"
        items.append({
            "id": item_id,
            "bucket": "low_confidence",
            "title": f"Low-confidence mapping: {source} → {target}",
            "description": (
                f"The mapping from {source} to {target} has a confidence of "
                f"{pct}%. Validate this mapping before generating deliverables."
            ),
            "severity": severity,
            "source": {"source_service": source, "azure_service": target, "confidence": confidence},
        })

    # ── 2. Warnings (architecture gaps, cost, security) ───────────────────
    for warning in analysis.get("warnings", []):
        text = _coerce_text(warning)
        if not text:
            continue
        bucket = _classify_warning(text)
        item_id = _stable_item_id(bucket, text[:80])
        # Cost and security warnings are high severity; generic gaps are medium
        severity = "high" if bucket in ("cost_warning", "security_concern") else "medium"
        bucket_labels = {
            "cost_warning": "Cost / pricing warning",
            "security_concern": "Security / compliance concern",
            "architecture_gap": "Architecture gap",
        }
        items.append({
            "id": item_id,
            "bucket": bucket,
            "title": f"{bucket_labels[bucket]}: {text[:80]}{'…' if len(text) > 80 else ''}",
            "description": text,
            "severity": severity,
            "source": {"raw_warning": text},
        })

    # ── 3. Assumptions (from guided-questions adaptive set) ────────────────
    for assumption in analysis.get("assumptions", []):
        if not isinstance(assumption, dict):
            continue
        question = _coerce_text(assumption.get("question") or assumption.get("text"))
        if not question:
            continue
        assumed_answer = _coerce_text(assumption.get("assumed_answer"))
        item_id = _stable_item_id("assumptions", question[:80])
        items.append({
            "id": item_id,
            "bucket": "assumptions",
            "title": f"Assumption: {question[:80]}{'…' if len(question) > 80 else ''}",
            "description": (
                f"Archmorph assumed: \"{assumed_answer}\". "
                "Confirm this is correct before generating deliverables."
            ),
            "severity": "medium",
            "source": {"question": question, "assumed_answer": assumed_answer},
        })

    # ── 4. Compliance / security profile ──────────────────────────────────
    profile = analysis.get("profile") or analysis.get("customer_profile") or {}
    compliance = _coerce_text(profile.get("compliance")) if isinstance(profile, dict) else ""
    if compliance and compliance.lower() not in ("none", ""):
        item_id = _stable_item_id("security_concern", f"compliance:{compliance}")
        items.append({
            "id": item_id,
            "bucket": "security_concern",
            "title": f"Compliance scope: {compliance}",
            "description": (
                f"The compliance scope is set to \"{compliance}\". "
                "This is advisory until validated against your control set."
            ),
            "severity": "high",
            "source": {"compliance": compliance},
        })

    # ── 5. Unknown / unmatched services ───────────────────────────────────
    for m in analysis.get("mappings", []):
        if not isinstance(m, dict):
            continue
        target = _coerce_text(m.get("azure_service") or m.get("target"))
        if target.lower() in ("unknown", ""):
            source = _coerce_text(m.get("source_service")) or "Unknown"
            item_id = _stable_item_id("architecture_gap", f"unmatched:{source}")
            items.append({
                "id": item_id,
                "bucket": "architecture_gap",
                "title": f"Unmatched service: {source}",
                "description": (
                    f"No Azure equivalent was found for \"{source}\". "
                    "Review and assign an Azure service manually."
                ),
                "severity": "high",
                "source": {"source_service": source},
            })

    # Sort: high → medium → low, then stable by bucket + title
    _ORDER = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda x: (_ORDER.get(x["severity"], 9), x["bucket"], x["title"]))

    # Deduplicate by id (keep first occurrence after sort)
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        if item["id"] not in seen:
            seen.add(item["id"])
            unique.append(item)

    return unique


def apply_risk_annotations(
    analysis: dict[str, Any],
    dispositions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return a copy of *analysis* with risk annotations injected.

    Items marked as ``mark_risk`` in *dispositions* are appended to
    ``analysis["risk_annotations"]`` so they flow into HLD / package exports.

    Parameters
    ----------
    analysis:
        The analysis dict to annotate.
    dispositions:
        Map of ``{item_id: {"action": ..., "edited_text": ...}}``.
    """
    risk_annotations: list[dict[str, Any]] = list(analysis.get("risk_annotations") or [])
    items = build_review_queue(analysis)
    for item in items:
        disp = dispositions.get(item["id"]) or {}
        if disp.get("action") == "mark_risk":
            note = disp.get("edited_text") or item["description"]
            risk_annotations.append({
                "id": item["id"],
                "bucket": item["bucket"],
                "title": item["title"],
                "note": note,
                "severity": item["severity"],
            })
    result = dict(analysis)
    result["risk_annotations"] = risk_annotations
    return result


def queue_summary(
    items: list[dict[str, Any]],
    dispositions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return a summary dict for gate-checking.

    Returns
    -------
    dict with keys:
        total         — total items in queue
        unresolved    — items without a disposition
        blocking      — high-severity items without a disposition
        resolved      — items with any disposition
        risks_accepted — items marked as risks
    """
    total = len(items)
    unresolved = 0
    blocking = 0
    resolved = 0
    risks_accepted = 0
    for item in items:
        disp = dispositions.get(item["id"])
        if disp and disp.get("action"):
            resolved += 1
            if disp["action"] == "mark_risk":
                risks_accepted += 1
        else:
            unresolved += 1
            if item["severity"] == "high":
                blocking += 1
    return {
        "total": total,
        "unresolved": unresolved,
        "blocking": blocking,
        "resolved": resolved,
        "risks_accepted": risks_accepted,
        "gated": blocking > 0,
    }
