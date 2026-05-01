"""
Architecture Limitations Engine — Issue #610.

Detects architecturally invalid Azure compositions (protocol mismatches,
SKU prerequisites, network topology constraints, etc.) by evaluating a
curated rule library against an analysis result.

Public API:
    evaluate(analysis) -> List[ArchitectureIssue]
    has_blocker(issues) -> bool
    list_rules() -> List[Rule]
    reload_rules() -> None
"""

from .engine import evaluate, has_blocker, list_rules, reload_rules
from .models import ArchitectureIssue, Rule, Severity

__all__ = [
    "ArchitectureIssue",
    "Rule",
    "Severity",
    "evaluate",
    "has_blocker",
    "list_rules",
    "reload_rules",
]
