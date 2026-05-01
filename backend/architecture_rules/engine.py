"""
Architecture-limitations rule engine (Issue #610).

Loads rules from a YAML library (default: ``backend/data/architecture_rules.yaml``,
overridable via ``ARCHMORPH_ARCH_RULES_PATH``) and evaluates them against an
analysis result.

Public API (re-exported from the package ``__init__``):
    * evaluate(analysis) -> List[ArchitectureIssue]
    * has_blocker(issues) -> bool
    * list_rules() -> List[Rule]
    * reload_rules() -> None
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .models import ArchitectureIssue, Rule, Severity, severity_rank
from .predicates import PredicateMatch, get_predicate, list_predicate_names

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = (
    "id",
    "title",
    "severity",
    "category",
    "message",
    "remediation",
    "docs_url",
    "predicate",
)

_VALID_SEVERITIES = {s.value for s in Severity}


def _default_rules_path() -> Path:
    """Default location of the rule library, relative to this file."""
    here = Path(__file__).resolve().parent
    return here.parent / "data" / "architecture_rules.yaml"


def _resolve_rules_path() -> Path:
    override = os.environ.get("ARCHMORPH_ARCH_RULES_PATH")
    if override:
        return Path(override)
    return _default_rules_path()


# ---------------------------------------------------------------------------
# YAML → Rule
# ---------------------------------------------------------------------------


def _coerce_rule(raw: Dict[str, Any], *, source_path: str) -> Rule:
    if not isinstance(raw, dict):
        raise ValueError(f"{source_path}: rule entry is not a mapping: {raw!r}")

    for field in _REQUIRED_FIELDS:
        if field not in raw or raw[field] is None or raw[field] == "":
            raise ValueError(f"{source_path}: rule missing required field {field!r}: {raw!r}")

    severity_str = str(raw["severity"]).strip().lower()
    if severity_str not in _VALID_SEVERITIES:
        raise ValueError(
            f"{source_path}: rule {raw.get('id')!r} has invalid severity {severity_str!r}; "
            f"expected one of {sorted(_VALID_SEVERITIES)}"
        )

    predicate_name = str(raw["predicate"]).strip()
    if get_predicate(predicate_name) is None:
        raise ValueError(
            f"{source_path}: rule {raw.get('id')!r} references unknown predicate "
            f"{predicate_name!r}; available: {list_predicate_names()}"
        )

    return Rule(
        id=str(raw["id"]).strip(),
        title=str(raw["title"]).strip(),
        severity=Severity(severity_str),
        category=str(raw["category"]).strip(),
        message=str(raw["message"]).rstrip(),
        remediation=str(raw["remediation"]).rstrip(),
        docs_url=str(raw["docs_url"]).strip(),
        predicate=predicate_name,
        predicate_args=dict(raw.get("predicate_args") or {}),
        references=list(raw.get("references") or []),
        tags=list(raw.get("tags") or []),
    )


def _load_rules_from_path(path: str) -> List[Rule]:
    p = Path(path)
    if not p.exists():
        logger.warning("architecture_rules: YAML library not found at %s", p)
        return []

    try:
        with p.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ValueError(f"architecture_rules: failed to parse {p}: {exc}") from exc

    if not isinstance(data, dict) or "rules" not in data:
        raise ValueError(f"{p}: top-level YAML must be a mapping with a 'rules' list")

    raw_rules = data.get("rules") or []
    if not isinstance(raw_rules, list):
        raise ValueError(f"{p}: 'rules' must be a list, got {type(raw_rules).__name__}")

    rules: List[Rule] = []
    seen_ids: set = set()
    for raw in raw_rules:
        rule = _coerce_rule(raw, source_path=str(p))
        if rule.id in seen_ids:
            raise ValueError(f"{p}: duplicate rule id {rule.id!r}")
        seen_ids.add(rule.id)
        rules.append(rule)

    return rules


# ---------------------------------------------------------------------------
# Lazy thread-safe singleton store
# ---------------------------------------------------------------------------

_LOCK = threading.RLock()
_RULES_CACHE: Optional[List[Rule]] = None
_LOADED_FROM: Optional[Path] = None


def _ensure_loaded() -> List[Rule]:
    global _RULES_CACHE, _LOADED_FROM
    with _LOCK:
        if _RULES_CACHE is None:
            path = _resolve_rules_path()
            _RULES_CACHE = _load_rules_from_path(str(path))
            _LOADED_FROM = path
            logger.info(
                "architecture_rules: loaded %d rules from %s",
                len(_RULES_CACHE),
                path,
            )
        return _RULES_CACHE


def reload_rules() -> None:
    """Force the next call to ``evaluate`` / ``list_rules`` to re-read the YAML."""
    global _RULES_CACHE, _LOADED_FROM
    with _LOCK:
        _RULES_CACHE = None
        _LOADED_FROM = None


def list_rules() -> List[Rule]:
    return list(_ensure_loaded())


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def _evaluate_one(rule: Rule, analysis: Dict[str, Any]) -> Optional[ArchitectureIssue]:
    fn = get_predicate(rule.predicate)
    if fn is None:
        logger.warning("architecture_rules: rule %s skipped — unknown predicate %s",
                       rule.id, rule.predicate)
        return None

    try:
        result = fn(analysis, **rule.predicate_args)
    except Exception as exc:  # never let one bad rule break the whole evaluation
        logger.warning(
            "architecture_rules: predicate %s failed for rule %s: %s",
            rule.predicate, rule.id, exc,
        )
        return None

    if result is None:
        return None

    if not isinstance(result, PredicateMatch):
        logger.warning(
            "architecture_rules: predicate %s for rule %s returned %r, expected PredicateMatch",
            rule.predicate, rule.id, type(result).__name__,
        )
        return None

    return ArchitectureIssue(
        rule_id=rule.id,
        severity=rule.severity,
        category=rule.category,
        title=rule.title,
        message=rule.message,
        remediation=rule.remediation,
        docs_url=rule.docs_url,
        affected_services=list(result.affected_services),
        source="curated",
        evidence=dict(result.evidence) if result.evidence else None,
    )


def evaluate(analysis: Dict[str, Any]) -> List[ArchitectureIssue]:
    """Run every loaded rule against ``analysis``.

    Returns issues sorted by severity (blocker > warning > info), then by
    category, then by rule id — stable ordering for snapshot tests and UI.
    """
    if not isinstance(analysis, dict):
        return []

    rules = _ensure_loaded()
    issues: List[ArchitectureIssue] = []
    for rule in rules:
        issue = _evaluate_one(rule, analysis)
        if issue is not None:
            issues.append(issue)

    issues.sort(
        key=lambda i: (-severity_rank(i.severity), i.category, i.rule_id),
    )
    return issues


def has_blocker(issues: List[ArchitectureIssue]) -> bool:
    return any(i.severity == Severity.BLOCKER for i in issues)
