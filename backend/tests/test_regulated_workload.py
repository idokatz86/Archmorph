"""Tests for regulated workload detection and audit-evidence review (#627)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from architecture_review.audit_pipeline import (  # noqa: E402
    build_audit_pipeline_issue,
    detect_audit_evidence_pipeline,
    load_compliance_controls,
)
from architecture_review.regulated_classifier import (  # noqa: E402
    Domain,
    classify_regulated_workload,
)
from routers.diagrams import _normalize_analysis  # noqa: E402


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_actone_xse_detects_financial_crime_and_gdpr():
    result = classify_regulated_workload(_fixture("actone_xse_regulated.json"))

    assert Domain.FINANCIAL_CRIME in result.domains
    assert Domain.GDPR in result.domains
    assert result.confidence[Domain.FINANCIAL_CRIME.value] >= 0.8
    assert result.evidence[Domain.FINANCIAL_CRIME.value]


def test_generic_saas_does_not_overfire_on_payment_word_alone():
    analysis = {
        "description": "SaaS settings page with payment preferences and generic app logs.",
        "identified_services": ["Web App", "PostgreSQL", "Log Analytics"],
    }

    result = classify_regulated_workload(analysis)

    assert result.domains == []
    assert result.to_dict()["is_regulated"] is False


def test_audit_pipeline_missing_controls_emits_blocker_critical_issue():
    analysis = _fixture("actone_xse_regulated.json")
    classification = classify_regulated_workload(analysis)

    issue = build_audit_pipeline_issue(analysis, classification)

    assert issue is not None
    assert issue.rule_id == "regulated-workload-audit-evidence-pipeline-missing"
    assert issue.severity.value == "blocker"
    assert issue.evidence["display_severity"] == "critical"
    assert issue.evidence["pipeline"]["missing"] == [
        "worm_store",
        "independent_copy",
        "kms_cmk",
        "retention_period",
    ]
    assert issue.affected_services == []


def test_compliance_controls_fail_open_when_file_missing(tmp_path):
    missing_path = tmp_path / "missing-controls.yaml"

    assert load_compliance_controls(missing_path) == {}


def test_worm_matching_does_not_match_substrings():
    analysis = {
        "description": (
            "AML audit telemetry mentions a tapeworm incident in an unrelated note, "
            "with 7 year retention, cross-account copy, and KMS CMK."
        )
    }

    detection = detect_audit_evidence_pipeline(analysis, required_retention_years=7)

    assert "worm_store" in detection.missing


def test_complete_aml_pipeline_suppresses_blocker():
    analysis = {
        "description": (
            "AML and SAR transaction monitoring writes audit events to S3 Object Lock "
            "compliance mode with 7 year retention, cross-account replication to a "
            "separate audit account, and KMS CMK customer-managed key protection."
        ),
        "identified_services": ["Kinesis Firehose", "S3 Object Lock", "AWS KMS CMK"],
    }
    classification = classify_regulated_workload(analysis)
    detection = detect_audit_evidence_pipeline(analysis, required_retention_years=7)

    assert Domain.FINANCIAL_CRIME in classification.domains
    assert detection.missing == []
    assert build_audit_pipeline_issue(analysis, classification) is None


def test_hipaa_requires_ten_year_retention():
    analysis = {
        "description": (
            "HIPAA PHI patient audit events go to Azure immutable Blob with cross-region "
            "replication, customer-managed key in Azure Key Vault, and 7 year retention."
        )
    }
    classification = classify_regulated_workload(analysis)

    issue = build_audit_pipeline_issue(analysis, classification)

    assert Domain.HIPAA in classification.domains
    assert issue is not None
    assert issue.evidence["required_retention_years"] == 10
    assert "retention_period" in issue.evidence["pipeline"]["missing"]


def test_diagram_normalization_adds_regulated_contract_and_blocker_summary():
    result = _normalize_analysis(_fixture("actone_xse_regulated.json"))

    assert result["regulated_workload"]["is_regulated"] is True
    assert "financial_crime" in result["regulated_workload"]["domains"]
    issue_ids = {issue["rule_id"] for issue in result["architecture_issues"]}
    assert "regulated-workload-audit-evidence-pipeline-missing" in issue_ids
    assert result["architecture_issues_summary"]["blocker"] >= 1