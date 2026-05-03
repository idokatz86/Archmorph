"""Regulated-workload classifier for architecture review (#627)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class Domain(str, Enum):
    FINANCIAL_CRIME = "financial_crime"
    PCI = "pci"
    HIPAA = "hipaa"
    GDPR = "gdpr"
    FEDRAMP = "fedramp"
    BANKING_MODEL_RISK = "banking_model_risk"


@dataclass(frozen=True)
class RegulatedWorkloadClassification:
    domains: list[Domain]
    confidence: dict[str, float]
    evidence: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_regulated": bool(self.domains),
            "domains": [domain.value for domain in self.domains],
            "confidence": dict(self.confidence),
            "evidence": {key: list(values) for key, values in self.evidence.items()},
        }


_DOMAIN_SIGNALS: dict[Domain, tuple[tuple[str, float], ...]] = {
    Domain.FINANCIAL_CRIME: (
        (r"\baml\b", 0.55),
        (r"\bsar\b", 0.45),
        (r"\bkyc\b", 0.45),
        (r"transaction monitoring", 0.45),
        (r"financial crime|fincrime", 0.45),
        (r"actimize", 0.4),
        (r"case investigation|case management", 0.25),
        (r"fraud", 0.2),
    ),
    Domain.PCI: (
        (r"\bpci(?:[- ]?dss)?\b", 0.55),
        (r"cardholder", 0.5),
        (r"\bpan\b", 0.45),
        (r"card token|tokenized card|payment token", 0.4),
        (r"payment processor|checkout", 0.3),
        (r"payment", 0.15),
    ),
    Domain.HIPAA: (
        (r"\bhipaa\b", 0.6),
        (r"\bphi\b", 0.5),
        (r"\behr\b|\bemr\b", 0.4),
        (r"patient", 0.3),
        (r"healthcare|medical|claims", 0.25),
        (r"\bfhir\b|\bhl7\b", 0.3),
    ),
    Domain.GDPR: (
        (r"\bgdpr\b", 0.6),
        (r"\bdsar\b|subject access", 0.45),
        (r"personal data|personally identifiable|\bpii\b", 0.4),
        (r"data subject", 0.35),
        (r"eu user|european user|consent", 0.2),
    ),
    Domain.FEDRAMP: (
        (r"\bfedramp\b", 0.65),
        (r"\bil[245]\b", 0.45),
        (r"govcloud|azure government", 0.45),
        (r"\bcjis\b|\bfisma\b", 0.4),
        (r"\.gov\b|government agency", 0.25),
    ),
    Domain.BANKING_MODEL_RISK: (
        (r"sr[- ]?11[- ]?7", 0.65),
        (r"model risk", 0.5),
        (r"credit scoring", 0.4),
        (r"regulatory reporting", 0.35),
        (r"model validation|challenger model", 0.35),
    ),
}

_NEGATED_CONTEXT = re.compile(
    r"\b(?:not|non|no|without|excludes?)\s+(?:\w+\s+){0,3}"
    r"(?:pci|hipaa|phi|aml|sar|kyc|gdpr|fedramp|pan|cardholder)\b",
    re.IGNORECASE,
)


def _flatten(value: Any) -> Iterable[str]:
    if value is None:
        return
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            yield stripped
        return
    if isinstance(value, (int, float, bool)):
        yield str(value)
        return
    if isinstance(value, dict):
        for key, inner in value.items():
            if isinstance(key, str):
                yield key
            yield from _flatten(inner)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _flatten(item)


def collect_text_corpus(analysis: dict[str, Any]) -> list[str]:
    if not isinstance(analysis, dict):
        return []

    preferred_keys = (
        "description",
        "summary",
        "diagram_text",
        "ocr_text",
        "raw_text",
        "filename",
        "source_file",
        "identified_services",
        "mappings",
        "service_connections",
        "service_to_resource_mapping",
        "iac",
        "iac_code",
        "metadata",
    )
    corpus: list[str] = []
    for key in preferred_keys:
        if key in analysis:
            corpus.extend(_flatten(analysis.get(key)) or [])
    corpus.extend(_flatten({k: v for k, v in analysis.items() if k not in preferred_keys}) or [])
    return list(dict.fromkeys(corpus))


def _score_domain(text: str, domain: Domain) -> tuple[float, list[str]]:
    evidence: list[str] = []
    score = 0.0
    for pattern, weight in _DOMAIN_SIGNALS[domain]:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        start = max(0, match.start() - 45)
        end = min(len(text), match.end() + 45)
        context = text[start:end].strip()
        if _NEGATED_CONTEXT.search(context):
            continue
        score += weight
        evidence.append(context)

    if domain == Domain.FINANCIAL_CRIME:
        if re.search(r"\bsar\b", text, re.IGNORECASE) and not re.search(
            r"aml|kyc|fraud|transaction|case|regulatory|filing", text, re.IGNORECASE
        ):
            score = min(score, 0.35)
    if domain == Domain.PCI and re.search(r"payment", text, re.IGNORECASE) and not re.search(
        r"pci|pan|cardholder|card token|tokenized card|processor|checkout", text, re.IGNORECASE
    ):
        score = min(score, 0.35)
    if domain == Domain.FEDRAMP and re.search(r"government", text, re.IGNORECASE) and not re.search(
        r"fedramp|govcloud|azure government|\bil[245]\b|cjis|fisma|\.gov", text, re.IGNORECASE
    ):
        score = min(score, 0.35)
    if domain == Domain.BANKING_MODEL_RISK and re.search(r"\bmodel\b", text, re.IGNORECASE) and not re.search(
        r"model risk|credit scoring|regulatory reporting|validation|sr[- ]?11[- ]?7", text, re.IGNORECASE
    ):
        score = min(score, 0.35)

    return min(round(score, 2), 1.0), evidence[:6]


def classify_regulated_workload(analysis: dict[str, Any], *, threshold: float = 0.6) -> RegulatedWorkloadClassification:
    text = "\n".join(collect_text_corpus(analysis))
    domains: list[Domain] = []
    confidence: dict[str, float] = {}
    evidence: dict[str, list[str]] = {}
    for domain in Domain:
        score, domain_evidence = _score_domain(text, domain)
        if score >= threshold:
            domains.append(domain)
            confidence[domain.value] = score
            evidence[domain.value] = domain_evidence
    domains.sort(key=lambda domain: confidence.get(domain.value, 0), reverse=True)
    return RegulatedWorkloadClassification(domains=domains, confidence=confidence, evidence=evidence)