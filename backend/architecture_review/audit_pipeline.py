"""Audit-evidence pipeline detector for regulated workloads (#627)."""

from __future__ import annotations

import re
from functools import lru_cache
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from architecture_rules.models import ArchitectureIssue, Severity
from .regulated_classifier import RegulatedWorkloadClassification, collect_text_corpus


@dataclass(frozen=True)
class AuditEvidenceDetection:
    has_worm_store: bool
    has_cross_account_or_region_copy: bool
    has_kms_cmk: bool
    has_retention_period: bool
    retention_years: int | None
    evidence: dict[str, list[str]] = field(default_factory=dict)

    @property
    def missing(self) -> list[str]:
        missing: list[str] = []
        if not self.has_worm_store:
            missing.append("worm_store")
        if not self.has_cross_account_or_region_copy:
            missing.append("independent_copy")
        if not self.has_kms_cmk:
            missing.append("kms_cmk")
        if not self.has_retention_period:
            missing.append("retention_period")
        return missing

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_worm_store": self.has_worm_store,
            "has_cross_account_or_region_copy": self.has_cross_account_or_region_copy,
            "has_kms_cmk": self.has_kms_cmk,
            "has_retention_period": self.has_retention_period,
            "retention_years": self.retention_years,
            "evidence": {key: list(values) for key, values in self.evidence.items()},
            "missing": self.missing,
        }


_CONTROL_PATH = Path(__file__).resolve().parent.parent / "data" / "compliance_controls.yaml"

_WORM_PATTERNS = (
    r"s3 object lock",
    r"object lock\s*\(?compliance",
    r"azure immutable blob",
    r"immutability policy",
    r"locked retention policy",
    r"gcs bucket lock",
    r"\bworm\b",
    r"write once read many",
)
_COPY_PATTERNS = (
    r"cross[- ]account",
    r"cross[- ]region",
    r"separate audit account",
    r"replication to (?:a )?separate",
    r"geo[- ]replication",
)
_KMS_PATTERNS = (
    r"\bcmk\b",
    r"customer[- ]managed key",
    r"kms cmk",
    r"azure key vault key",
    r"cloud kms key",
)
_MONITORING_ONLY_PATTERNS = (
    r"elasticsearch",
    r"opensearch",
    r"log analytics",
    r"cloudwatch",
    r"siem",
)
_NEGATED_EVIDENCE = re.compile(
    r"\b(?:no|not|without|missing|lacks?|absent)\s+(?:\w+\s+){0,4}"
    r"(?:object lock|immutable|immutability|worm|cross[- ]account|cross[- ]region|cmk|customer[- ]managed key|retention)",
    re.IGNORECASE,
)


@lru_cache(maxsize=4)
def _load_compliance_controls_cached(control_path: str) -> dict[str, Any]:
    try:
        with Path(control_path).open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except (FileNotFoundError, OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def load_compliance_controls(path: Path | None = None) -> dict[str, Any]:
    control_path = str(path or _CONTROL_PATH)
    return _load_compliance_controls_cached(control_path)


def _matches(text: str, patterns: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            start = max(0, match.start() - 45)
            end = min(len(text), match.end() + 45)
            context = text[start:end].strip()
            if _NEGATED_EVIDENCE.search(context):
                continue
            hits.append(context)
    return hits[:8]


def _retention_years(text: str) -> int | None:
    years: list[int] = []
    for match in re.finditer(r"(\d{1,2})\s*(?:year|yr)s?\s*(?:retention|archive|audit)?", text, re.IGNORECASE):
        years.append(int(match.group(1)))
    for match in re.finditer(r"retention\s*(?:period|policy)?\D{0,20}(\d{1,2})\s*(?:year|yr)s?", text, re.IGNORECASE):
        years.append(int(match.group(1)))
    return max(years) if years else None


def _required_retention_years(classification: RegulatedWorkloadClassification, controls: dict[str, Any]) -> int:
    domains = controls.get("domains", {}) if isinstance(controls, dict) else {}
    required = 0
    for domain in classification.domains:
        domain_controls = domains.get(domain.value, {}) if isinstance(domains, dict) else {}
        for control in domain_controls.get("audit_controls", []) or []:
            if isinstance(control, dict):
                required = max(required, int(control.get("retention_years") or 0))
    return required or 7


def detect_audit_evidence_pipeline(analysis: dict[str, Any], *, required_retention_years: int = 7) -> AuditEvidenceDetection:
    text = "\n".join(collect_text_corpus(analysis))
    retention_years = _retention_years(text)
    evidence = {
        "worm_store": _matches(text, _WORM_PATTERNS),
        "independent_copy": _matches(text, _COPY_PATTERNS),
        "kms_cmk": _matches(text, _KMS_PATTERNS),
        "monitoring_only": _matches(text, _MONITORING_ONLY_PATTERNS),
    }
    if retention_years is not None:
        evidence["retention_period"] = [f"{retention_years} year retention"]
    return AuditEvidenceDetection(
        has_worm_store=bool(evidence["worm_store"]),
        has_cross_account_or_region_copy=bool(evidence["independent_copy"]),
        has_kms_cmk=bool(evidence["kms_cmk"]),
        has_retention_period=retention_years is not None and retention_years >= required_retention_years,
        retention_years=retention_years,
        evidence={key: value for key, value in evidence.items() if value},
    )


def _required_by(classification: RegulatedWorkloadClassification, controls: dict[str, Any]) -> list[str]:
    domains = controls.get("domains", {}) if isinstance(controls, dict) else {}
    required: list[str] = []
    for domain in classification.domains:
        domain_controls = domains.get(domain.value, {}) if isinstance(domains, dict) else {}
        required.extend(str(item) for item in domain_controls.get("frameworks", []) or [])
    return list(dict.fromkeys(required))


def build_audit_pipeline_issue(
    analysis: dict[str, Any],
    classification: RegulatedWorkloadClassification,
    *,
    controls: dict[str, Any] | None = None,
) -> ArchitectureIssue | None:
    if not classification.domains:
        return None
    controls = controls or load_compliance_controls()
    required_retention = _required_retention_years(classification, controls)
    detection = detect_audit_evidence_pipeline(analysis, required_retention_years=required_retention)
    if not detection.missing:
        return None

    domain_names = [domain.value for domain in classification.domains]
    required_by = _required_by(classification, controls)
    missing_titles = {
        "worm_store": "immutable/WORM evidence store",
        "independent_copy": "cross-account or cross-region audit copy",
        "kms_cmk": "customer-managed key protection",
        "retention_period": f"documented retention period >= {required_retention} years",
    }
    missing_text = ", ".join(missing_titles[key] for key in detection.missing)

    return ArchitectureIssue(
        rule_id="regulated-workload-audit-evidence-pipeline-missing",
        severity=Severity.BLOCKER,
        category="compliance-audit",
        title="Regulated-workload audit-evidence pipeline missing",
        message=(
            "Regulated workload signals were detected, but the architecture does not show "
            f"all required audit-evidence controls: {missing_text}."
        ),
        remediation=(
            "Add an immutable audit pipeline with WORM storage, independent replication, "
            "customer-managed keys, and a documented retention period aligned to the detected regimes."
        ),
        docs_url="https://learn.microsoft.com/azure/storage/blobs/immutable-storage-overview",
        affected_services=[],
        source="curated",
        evidence={
            "display_severity": "critical",
            "domains": domain_names,
            "confidence": classification.confidence,
            "required_by": required_by,
            "required_retention_years": required_retention,
            "pipeline": detection.to_dict(),
        },
    )