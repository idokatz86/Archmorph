from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "lint_mappings_freshness.py"
SPEC = spec_from_file_location("lint_mappings_freshness", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
lint_mappings_freshness = module_from_spec(SPEC)
sys.modules[SPEC.name] = lint_mappings_freshness
SPEC.loader.exec_module(lint_mappings_freshness)


def test_low_confidence_missing_last_reviewed_is_error():
    findings = lint_mappings_freshness.evaluate_rows(
        [{"aws": "AppSync", "azure": "API Apps", "confidence": 0.75}],
        today=date(2026, 5, 3),
    )

    assert [(f.level, f.message) for f in findings] == [("error", "missing last_reviewed")]


def test_high_confidence_stale_row_is_warning():
    findings = lint_mappings_freshness.evaluate_rows(
        [
            {
                "aws": "EC2",
                "azure": "Virtual Machines",
                "confidence": 0.95,
                "last_reviewed": "2025-01-01",
            }
        ],
        today=date(2026, 5, 3),
        max_age_days=180,
    )

    assert len(findings) == 1
    assert findings[0].level == "warning"
    assert "487 days old" in findings[0].message


def test_low_confidence_stale_row_is_error():
    findings = lint_mappings_freshness.evaluate_rows(
        [
            {
                "aws": "QLDB",
                "azure": "Confidential Ledger",
                "confidence": 0.75,
                "last_reviewed": "2025-01-01",
            }
        ],
        today=date(2026, 5, 3),
        max_age_days=180,
    )

    assert len(findings) == 1
    assert findings[0].level == "error"
    assert "487 days old" in findings[0].message


def test_fresh_rows_pass():
    findings = lint_mappings_freshness.evaluate_rows(
        [
            {
                "aws": "CloudFront",
                "azure": "Front Door",
                "confidence": 0.9,
                "last_reviewed": "2026-05-01",
            }
        ],
        today=date(2026, 5, 3),
    )

    assert findings == []
