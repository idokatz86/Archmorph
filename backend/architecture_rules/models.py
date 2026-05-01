"""Data models for the architecture limitations engine (Issue #610)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Severity(str, Enum):
    """Severity tiers for architecture issues.

    blocker  — the architecture cannot work as drawn. Generated IaC will be
               wrong or non-functional. IaC generation is gated on this.
    warning  — the architecture works but has a significant gap (cost,
               reliability, security, or migration effort).
    info     — informational. Best-practice nudge, alternative tier, etc.
    """

    BLOCKER = "blocker"
    WARNING = "warning"
    INFO = "info"


_SEVERITY_RANK = {Severity.BLOCKER: 3, Severity.WARNING: 2, Severity.INFO: 1}


def severity_rank(s: Severity) -> int:
    """Numeric rank used for sorting issues highest-first."""
    return _SEVERITY_RANK[s]


@dataclass(frozen=True)
class Rule:
    """A single architecture-limitation rule.

    Loaded from YAML. The ``predicate`` field references a function
    registered in ``predicates.py`` via the ``@register_predicate`` decorator.
    """

    id: str
    title: str
    severity: Severity
    category: str
    message: str
    remediation: str
    docs_url: str
    predicate: str
    predicate_args: Dict[str, Any] = field(default_factory=dict)
    references: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ArchitectureIssue:
    """A single rule-firing on a specific analysis result.

    Returned by ``engine.evaluate()`` — these are the structured findings
    surfaced to API responses, the frontend Architecture Health panel,
    and the IaC generation gate.

    ``source`` records provenance: ``curated`` (hand-written), ``ai``
    (Phase 2 AI-fallback), ``admin_approved`` (Phase 3 review queue).
    """

    rule_id: str
    severity: Severity
    category: str
    title: str
    message: str
    remediation: str
    docs_url: str
    affected_services: List[str] = field(default_factory=list)
    source: str = "curated"
    evidence: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for inclusion in the analysis result JSON."""
        return {
            "rule_id": self.rule_id,
            "severity": self.severity.value,
            "category": self.category,
            "title": self.title,
            "message": self.message,
            "remediation": self.remediation,
            "docs_url": self.docs_url,
            "affected_services": list(self.affected_services),
            "source": self.source,
            "evidence": self.evidence,
        }
