"""
Predicate registry for architecture-limitations rules (Issue #610).

A predicate is a function ``(analysis: dict, **kwargs) -> Optional[PredicateMatch]``
that decides whether a rule fires against a given analysis result. Predicates
are registered by name via the ``@register_predicate`` decorator and looked
up at YAML-load time by the engine.

Authoring guidance:
    * Be tolerant of missing/malformed analysis fields. Return None on any
      uncertainty rather than raising.
    * When a rule fires, populate ``PredicateMatch.affected_services`` with
      the human-readable service names that triggered the match — these
      surface in the UI and to the IaC blocker gate.
    * Keep matching loose (substring + normalisation). The vision pipeline
      produces noisy service names ("Azure Front Door (Standard)",
      "front-door-prod", "AFD"…); strict equality misses real architectures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Callable, Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass
class PredicateMatch:
    """A predicate's positive answer.

    affected_services — service names from the analysis that triggered the rule.
    evidence          — small dict surfaced in the issue's ``evidence`` field.
    """

    affected_services: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)


PredicateFn = Callable[..., Optional[PredicateMatch]]
_REGISTRY: Dict[str, PredicateFn] = {}


def register_predicate(name: str) -> Callable[[PredicateFn], PredicateFn]:
    """Decorator: register a predicate function under ``name``."""

    def _decorate(fn: PredicateFn) -> PredicateFn:
        if name in _REGISTRY:
            raise ValueError(f"predicate already registered: {name}")
        _REGISTRY[name] = fn
        return fn

    return _decorate


def get_predicate(name: str) -> Optional[PredicateFn]:
    return _REGISTRY.get(name)


def list_predicate_names() -> List[str]:
    return sorted(_REGISTRY.keys())


# ---------------------------------------------------------------------------
# Helpers — analysis shape adapters
# ---------------------------------------------------------------------------


def _services_in_analysis(analysis: Dict[str, Any]) -> List[str]:
    """Collect every service-name string from common analysis shapes.

    Looks at:
      * identified_services   — list of strings or {"name": ...} dicts
      * service_to_resource_mapping  — list of {"service": ...} dicts
      * mappings              — {"source_service": ..., "azure_service": ...}
    """
    out: List[str] = []
    for s in analysis.get("identified_services") or []:
        if isinstance(s, str):
            out.append(s)
        elif isinstance(s, dict):
            n = s.get("name") or s.get("service") or s.get("title")
            if isinstance(n, str):
                out.append(n)

    for m in analysis.get("service_to_resource_mapping") or []:
        if isinstance(m, dict):
            n = m.get("service")
            if isinstance(n, str):
                out.append(n)

    for m in analysis.get("mappings") or []:
        if isinstance(m, dict):
            source = m.get("source_service")
            target = m.get("azure_service") or m.get("target")
            if isinstance(source, str):
                out.append(source)
            if isinstance(target, str):
                out.append(target)

    return out


def _connections(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = analysis.get("service_connections") or []
    return [c for c in raw if isinstance(c, dict)]


def _mapping_for(analysis: Dict[str, Any], service_name: str) -> Optional[Dict[str, Any]]:
    for m in analysis.get("service_to_resource_mapping") or []:
        if isinstance(m, dict) and _service_matches(m.get("service", ""), service_name):
            return m
    return None


def _category_of(analysis: Dict[str, Any], service_name: str) -> Optional[str]:
    for s in analysis.get("identified_services") or []:
        if isinstance(s, dict) and _service_matches(s.get("name", ""), service_name):
            cat = s.get("category")
            if isinstance(cat, str):
                return cat
    return None


# ---------------------------------------------------------------------------
# Loose service-name matching
# ---------------------------------------------------------------------------


def _normalize(name: str) -> str:
    """Lowercase, strip Azure/AWS/Amazon prefixes, normalise dashes/spaces."""
    if not isinstance(name, str):
        return ""
    n = name.lower().strip()
    for prefix in ("azure ", "aws ", "amazon "):
        if n.startswith(prefix):
            n = n[len(prefix):]
    n = n.replace("-", " ").replace("_", " ")
    while "  " in n:
        n = n.replace("  ", " ")
    return n


def _service_matches(actual: str, expected: str) -> bool:
    """Loose substring match with provider-prefix tolerance.

    "Azure Front Door (Standard)" matches "front door".
    "front-door-prod" matches "Front Door".
    Empty/None on either side returns False.
    """
    if not actual or not expected:
        return False
    a = _normalize(actual)
    e = _normalize(expected)
    if not a or not e:
        return False
    return e in a or a in e


def _has_service(analysis: Dict[str, Any], expected: str) -> List[str]:
    """Return service names from the analysis that match ``expected``."""
    matches: List[str] = []
    for n in _services_in_analysis(analysis):
        if _service_matches(n, expected):
            matches.append(n)
    return matches


# ---------------------------------------------------------------------------
# Registered predicates
# ---------------------------------------------------------------------------


@register_predicate("service_present")
def service_present(analysis: Dict[str, Any], *, name: str) -> Optional[PredicateMatch]:
    """Fire when a service whose name fuzzy-matches ``name`` is present."""
    hits = _has_service(analysis, name)
    if not hits:
        return None
    return PredicateMatch(affected_services=hits, evidence={"matched": hits})


@register_predicate("services_all_present")
def services_all_present(
    analysis: Dict[str, Any], *, names: List[str]
) -> Optional[PredicateMatch]:
    """Fire only when ALL ``names`` are present (in any combination)."""
    if not names:
        return None
    affected: List[str] = []
    for needle in names:
        hits = _has_service(analysis, needle)
        if not hits:
            return None
        affected.extend(hits)
    # de-dupe while preserving order
    seen: set = set()
    deduped = [s for s in affected if not (s in seen or seen.add(s))]
    return PredicateMatch(affected_services=deduped, evidence={"required": names})


@register_predicate("service_pair_connected")
def service_pair_connected(
    analysis: Dict[str, Any], *, a: str, b: str
) -> Optional[PredicateMatch]:
    """Fire when the analysis has a connection that touches both ``a`` and ``b``."""
    for c in _connections(analysis):
        f = str(c.get("from", ""))
        t = str(c.get("to", ""))
        if (
            (_service_matches(f, a) and _service_matches(t, b))
            or (_service_matches(f, b) and _service_matches(t, a))
        ):
            return PredicateMatch(
                affected_services=[f, t],
                evidence={"from": f, "to": t, "type": c.get("type")},
            )
    return None


@register_predicate("connection_uses_protocol")
def connection_uses_protocol(
    analysis: Dict[str, Any], *, protocols: List[str]
) -> Optional[PredicateMatch]:
    """Fire when any connection has a ``type`` matching one of the protocols."""
    if not protocols:
        return None
    wanted = {p.lower() for p in protocols}
    for c in _connections(analysis):
        t = str(c.get("type", "")).lower()
        if any(p in t for p in wanted):
            return PredicateMatch(
                affected_services=[str(c.get("from", "")), str(c.get("to", ""))],
                evidence={"protocol": c.get("type"), "from": c.get("from"), "to": c.get("to")},
            )
    return None


@register_predicate("service_count_at_least")
def service_count_at_least(
    analysis: Dict[str, Any], *, keywords: List[str], threshold: int = 2
) -> Optional[PredicateMatch]:
    """Fire when at least ``threshold`` services match any of ``keywords``."""
    if not keywords or threshold < 1:
        return None
    matched: List[str] = []
    for n in _services_in_analysis(analysis):
        if any(_service_matches(n, k) for k in keywords):
            matched.append(n)
    if len(matched) < threshold:
        return None
    return PredicateMatch(
        affected_services=matched,
        evidence={"keywords": keywords, "count": len(matched), "threshold": threshold},
    )


@register_predicate("service_keywords_without_companion")
def service_keywords_without_companion(
    analysis: Dict[str, Any],
    *,
    keywords: List[str],
    companions: List[str],
    exclude_keywords: List[str] | None = None,
    threshold: int = 1,
    companion_mode: str = "any",
) -> Optional[PredicateMatch]:
    """Fire when services match ``keywords`` but no companion control is present.

    This is useful for additive posture rules such as "stateful services without
    backup" or "internet-facing services without WAF evidence". Set
    ``threshold`` above 1 for broad governance rules that should only fire on
    multi-service architectures. ``companion_mode=coverage`` treats companion
    services as coverage evidence and only suppresses when there is at least one
    companion signal per matched workload.
    """
    if not keywords or threshold < 1:
        return None

    companion_names = companions or []
    exclusions = exclude_keywords or []
    matched: List[str] = []
    seen: set[str] = set()
    for service_name in _services_in_analysis(analysis):
        is_companion_service = any(
            _service_matches(service_name, companion)
            for companion in companion_names
        )
        is_excluded_service = any(
            _service_matches(service_name, excluded)
            for excluded in exclusions
        )
        if is_companion_service or is_excluded_service:
            continue
        if any(_service_matches(service_name, keyword) for keyword in keywords):
            if service_name not in seen:
                matched.append(service_name)
                seen.add(service_name)

    if len(matched) < threshold:
        return None

    companion_hits: List[str] = []
    companion_seen: set[str] = set()
    for companion in companion_names:
        for hit in _has_service(analysis, companion):
            if hit not in companion_seen:
                companion_hits.append(hit)
                companion_seen.add(hit)

    if companion_mode == "coverage":
        if len(companion_hits) >= len(matched):
            return None
    elif companion_hits:
        return None

    return PredicateMatch(
        affected_services=matched,
        evidence={
            "keywords": keywords,
            "missing_companions": companions,
            "exclude_keywords": exclusions,
            "companion_mode": companion_mode,
            "companion_matches": companion_hits,
            "count": len(matched),
            "threshold": threshold,
        },
    )


@register_predicate("category_present_without_companion")
def category_present_without_companion(
    analysis: Dict[str, Any], *, category: str, companions: List[str]
) -> Optional[PredicateMatch]:
    """Fire when a service in ``category`` is present but no service matching
    any of ``companions`` is also present.

    Example: ``category=integration`` (Event Grid) without any
    ``companions=[Storage, Blob]`` (potential dead-letter targets) → fire.
    """
    in_category: List[str] = []
    for s in analysis.get("identified_services") or []:
        if isinstance(s, dict):
            cat = (s.get("category") or "").lower()
            if category and category.lower() in cat:
                n = s.get("name")
                if isinstance(n, str):
                    in_category.append(n)

    if not in_category:
        return None

    for companion in companions or []:
        if _has_service(analysis, companion):
            return None  # companion present — rule does not fire.

    return PredicateMatch(
        affected_services=in_category,
        evidence={"category": category, "missing_companions": companions},
    )


@register_predicate("service_in_category_with_other")
def service_in_category_with_other(
    analysis: Dict[str, Any], *, category: str, other: str
) -> Optional[PredicateMatch]:
    """Fire when a service in ``category`` co-exists with a service matching ``other``."""
    in_category: List[str] = []
    for s in analysis.get("identified_services") or []:
        if isinstance(s, dict):
            cat = (s.get("category") or "").lower()
            if category and category.lower() in cat:
                n = s.get("name")
                if isinstance(n, str):
                    in_category.append(n)
    if not in_category:
        return None
    other_hits = _has_service(analysis, other)
    if not other_hits:
        return None
    return PredicateMatch(
        affected_services=in_category + other_hits,
        evidence={"category": category, "other": other},
    )


@register_predicate("path_uses_service_with_protocol_mismatch")
def path_uses_service_with_protocol_mismatch(
    analysis: Dict[str, Any],
    *,
    via: str,
    allowed_protocols: List[str],
    disallowed_hint: List[str] | None = None,
) -> Optional[PredicateMatch]:
    """Primary predicate for SFTP-via-Front-Door style mismatches.

    Fires when there's a connection touching the in-path service ``via``
    whose protocol is **not** in ``allowed_protocols``. As a fallback (when
    connection-level protocol metadata is missing), also fires if any
    connection in the analysis uses a protocol from ``disallowed_hint``
    AND the in-path service is present in the architecture — this catches
    architectures where the diagram lacks explicit edge-protocol labels.
    """
    if not via:
        return None

    via_hits = _has_service(analysis, via)
    if not via_hits:
        return None

    allowed_lower = {p.lower() for p in (allowed_protocols or [])}
    disallowed_lower = {p.lower() for p in (disallowed_hint or [])}

    # 1) Strong signal: a connection touching `via` with a non-allowed protocol.
    for c in _connections(analysis):
        f = str(c.get("from", ""))
        t = str(c.get("to", ""))
        proto = str(c.get("type", "")).lower().strip()

        touches_via = _service_matches(f, via) or _service_matches(t, via)
        if not touches_via or not proto:
            continue

        # Normalise proto: "SFTP/SSH" -> tokens {"sftp", "ssh"}
        tokens = {tok.strip() for tok in proto.replace("/", " ").replace(",", " ").split() if tok.strip()}

        in_allowed = any(tok in allowed_lower for tok in tokens) or any(
            a in proto for a in allowed_lower
        )
        in_disallowed = any(tok in disallowed_lower for tok in tokens) or any(
            d in proto for d in disallowed_lower
        )

        if in_disallowed and not in_allowed:
            return PredicateMatch(
                affected_services=[f, t],
                evidence={"via": via, "protocol": c.get("type"), "from": f, "to": t},
            )
        # Strict rule: if proto is set, has tokens, and none of the tokens
        # are allowed → still a mismatch even without an explicit disallowed
        # hint. This catches diagrams that say "FTP" without our hint list
        # ever mentioning FTP.
        if tokens and not in_allowed and not disallowed_lower:
            return PredicateMatch(
                affected_services=[f, t],
                evidence={"via": via, "protocol": c.get("type"), "from": f, "to": t},
            )

    # 2) Fallback: disallowed protocol seen anywhere AND `via` is in the architecture.
    if disallowed_lower:
        for c in _connections(analysis):
            proto = str(c.get("type", "")).lower()
            if not proto:
                continue
            if any(d in proto for d in disallowed_lower):
                return PredicateMatch(
                    affected_services=via_hits,
                    evidence={"via": via, "hint_protocol": c.get("type"), "fallback": True},
                )

    return None


@register_predicate("active_active_with_failover_traffic_split")
def active_active_with_failover_traffic_split(
    analysis: Dict[str, Any],
) -> Optional[PredicateMatch]:
    """Detect active-active labels mixed with failover-style 100/0 traffic splits."""
    services = _services_in_analysis(analysis)
    patterns = analysis.get("architecture_patterns") or []
    dr_mode = str(analysis.get("dr_mode", "")).lower()
    active_active_signal = "active-active" in dr_mode or any(
        "active-active" in str(p).lower() for p in patterns
    ) or any("active-active" in _normalize(s) for s in services)
    if not active_active_signal:
        return None

    regions = analysis.get("regions") or []
    percentages: List[float] = []
    region_names: List[str] = []
    if isinstance(regions, list):
        for r in regions:
            if not isinstance(r, dict):
                continue
            name = r.get("name")
            if isinstance(name, str) and name:
                region_names.append(name)
            pct = r.get("traffic_pct")
            if isinstance(pct, (int, float)):
                percentages.append(float(pct))
            elif isinstance(pct, str):
                numeric = re.sub(r"[^0-9.]", "", pct)
                if numeric:
                    try:
                        percentages.append(float(numeric))
                    except ValueError:
                        pass

    if not percentages:
        blob = " ".join(
            [
                str(analysis.get("description", "")),
                str(analysis.get("title", "")),
                " ".join(services),
            ]
        ).lower()
        if "100/0" in blob or "100 0" in blob:
            return PredicateMatch(
                affected_services=region_names,
                evidence={
                    "dr_mode": analysis.get("dr_mode"),
                    "traffic_split": "100/0",
                },
            )
        return None

    has_primary_like = any(p >= 90 for p in percentages)
    has_standby_like = any(p <= 10 for p in percentages)
    if not (has_primary_like and has_standby_like):
        return None

    return PredicateMatch(
        affected_services=region_names,
        evidence={
            "dr_mode": analysis.get("dr_mode"),
            "traffic_percentages": percentages,
        },
    )


@register_predicate("rds_engine_unresolved")
def rds_engine_unresolved(analysis: Dict[str, Any]) -> Optional[PredicateMatch]:
    """Detect RDS mappings where engine is still unresolved."""
    engine_tokens = ("postgres", "mysql", "sql server", "mariadb", "oracle")
    unresolved_markers = ("engine-specific target required", "manual mapping required")

    affected: List[str] = []
    for m in analysis.get("mappings") or []:
        if not isinstance(m, dict):
            continue
        src = str(m.get("source_service", ""))
        tgt = str(m.get("azure_service", ""))
        src_norm = _normalize(src)
        tgt_norm = _normalize(tgt)
        if "rds" not in src_norm:
            continue
        has_engine = any(tok in src_norm for tok in engine_tokens)
        unresolved = any(marker in tgt_norm for marker in unresolved_markers)
        if unresolved or not has_engine:
            affected.extend([s for s in (src, tgt) if s])

    if affected:
        seen: Set[str] = set()
        deduped = [s for s in affected if not (s in seen or seen.add(s))]
        return PredicateMatch(
            affected_services=deduped,
            evidence={"reason": "rds_engine_unresolved"},
        )

    services = _services_in_analysis(analysis)
    has_generic_rds = any(_normalize(s) == "rds" for s in services)
    has_engine_signal = any(
        any(token in _normalize(s) for token in engine_tokens) for s in services
    )
    if has_generic_rds and not has_engine_signal:
        return PredicateMatch(
            affected_services=[s for s in services if _service_matches(s, "RDS")],
            evidence={"reason": "generic_rds_without_engine_signal"},
        )

    return None
