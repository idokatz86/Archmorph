"""Tests for `backend/services/mappings.py` — staleness fixes (#590) +
freshness shape contract (anchors #594 quarterly review CI lint).

Each fixed row is asserted by a dedicated test so a future "drive-by"
edit that re-introduces wrong-engine / stale-branding regressions
fails the build with a single line of output naming the row + bug.
"""

from __future__ import annotations

import re
from datetime import date

import pytest

from services.mappings import CROSS_CLOUD_MAPPINGS


def _by_aws(name: str) -> list[dict]:
    return [m for m in CROSS_CLOUD_MAPPINGS if m["aws"] == name]


# ---------------------------------------------------------------------------
# #590 — Wrong-engine class
# ---------------------------------------------------------------------------

class TestAuroraEngineCorrectness:
    """Aurora is PostgreSQL- or MySQL-compatible. Mapping it to Microsoft
    SQL Server (any flavour, including SQL Database Hyperscale) is a
    wrong-engine defect — the customer ends up on a different engine and
    a SQL Server licence cost they didn't expect."""

    def test_aurora_postgresql_mapped_to_postgresql_flex(self):
        rows = _by_aws("Aurora PostgreSQL")
        assert len(rows) == 1, "Expected exactly one Aurora PostgreSQL row"
        row = rows[0]
        assert row["azure"] == "Azure Database for PostgreSQL Flexible Server"
        assert row["confidence"] >= 0.85

    def test_aurora_mysql_mapped_to_mysql_flex(self):
        rows = _by_aws("Aurora MySQL")
        assert len(rows) == 1, "Expected exactly one Aurora MySQL row"
        row = rows[0]
        assert row["azure"] == "Azure Database for MySQL Flexible Server"
        assert row["confidence"] >= 0.85

    def test_no_aurora_to_sql_server_mapping_anywhere(self):
        """No Aurora row may map to anything containing 'SQL Database' or
        'SQL Server' (Microsoft SQL Server variants). #590 wrong-engine
        defect class — guards against future regressions in either
        direction."""
        sql_server_re = re.compile(r"\bSQL\s+(Database|Server|Hyperscale)\b", re.I)
        for row in CROSS_CLOUD_MAPPINGS:
            if "Aurora" in row["aws"]:
                assert not sql_server_re.search(row["azure"]), (
                    f"Aurora row maps to Microsoft SQL Server: "
                    f"{row['aws']!r} → {row['azure']!r}. This is the "
                    f"wrong-engine defect #590 fixed. Aurora is "
                    f"PostgreSQL- or MySQL-compatible."
                )


# ---------------------------------------------------------------------------
# #590 — Stale branding class
# ---------------------------------------------------------------------------

class TestStaleBranding:
    def test_cognito_drops_b2c_parenthetical(self):
        """Microsoft retired the 'B2C' sub-brand for Entra External ID in
        late 2024. The mapping must not say '(B2C)' anymore."""
        rows = _by_aws("Cognito")
        assert len(rows) == 1
        row = rows[0]
        assert "B2C" not in row["azure"], (
            f"Cognito row still references retired 'B2C' brand: {row['azure']!r}"
        )
        assert row["azure"] == "Entra External ID"

    def test_cloudfront_uses_front_door_not_legacy_cdn(self):
        """Azure CDN Standard is retiring. Modern equivalent is Azure
        Front Door (Standard/Premium with built-in CDN)."""
        rows = _by_aws("CloudFront")
        assert len(rows) == 1
        row = rows[0]
        assert row["azure"] == "Front Door", (
            f"CloudFront row should map to 'Front Door' (modern), "
            f"got {row['azure']!r}. Azure CDN Standard is retiring."
        )
        # Must not include retiring product
        assert "CDN" not in row["azure"], (
            f"CloudFront row still references retiring 'Azure CDN': {row['azure']!r}"
        )


# ---------------------------------------------------------------------------
# #590 — Lossy class
# ---------------------------------------------------------------------------

class TestLossyMappingsWidened:
    def test_guardduty_includes_sentinel(self):
        """GuardDuty (detection) needs both Defender for Cloud + Sentinel
        (SIEM). Either alone loses architectural intent."""
        rows = _by_aws("GuardDuty")
        assert len(rows) == 1
        row = rows[0]
        assert "Defender for Cloud" in row["azure"]
        assert "Sentinel" in row["azure"], (
            f"GuardDuty row must include Sentinel for SIEM completeness; "
            f"got {row['azure']!r}. Pre-#590 was Defender-only (lossy)."
        )

    def test_kms_fips_tier_exists(self):
        """The FIPS 140-3 / dedicated-HSM-backed tier must have its own
        row to avoid silent mapping to generic Key Vault (which is
        software-protected only)."""
        rows = [m for m in CROSS_CLOUD_MAPPINGS if "KMS" in m["aws"] and "FIPS" in m["aws"]]
        assert len(rows) >= 1, (
            "No KMS (FIPS 140-3) row found. #590 added this to disambiguate "
            "from generic Key Vault for CloudHSM-backed Custom Key Stores."
        )
        row = rows[0]
        assert row["azure"] == "Managed HSM"
        assert row["confidence"] >= 0.85


# ---------------------------------------------------------------------------
# #590 — Freshness shape contract (sets up #594 quarterly-review CI lint)
# ---------------------------------------------------------------------------

class TestMappingsFreshness:
    """Every mapping touched by #590 must declare a `last_reviewed` ISO
    date. #594 will turn this into a CI lint rule that all rows declare
    `last_reviewed` and that none are older than 6 months."""

    def test_touched_rows_carry_last_reviewed_iso_date(self):
        """The five rows fixed/added by #590 MUST carry `last_reviewed`."""
        touched_aws_keys = {
            "Aurora PostgreSQL",
            "Aurora MySQL",
            "CloudFront",
            "Cognito",
            "GuardDuty",
            "KMS",
            "KMS (FIPS 140-3)",
        }
        for row in CROSS_CLOUD_MAPPINGS:
            if row["aws"] in touched_aws_keys:
                assert "last_reviewed" in row, (
                    f"Row {row['aws']!r} → {row['azure']!r} is in the "
                    f"#590 touched-set but missing `last_reviewed` field. "
                    f"All touched rows must carry the freshness stamp."
                )
                # Must parse as a YYYY-MM-DD ISO date.
                try:
                    parsed = date.fromisoformat(row["last_reviewed"])
                except ValueError as exc:  # noqa: PERF203
                    pytest.fail(
                        f"Row {row['aws']!r}: `last_reviewed` "
                        f"{row['last_reviewed']!r} is not ISO YYYY-MM-DD: {exc}"
                    )
                # Sanity: not in the future, not before the project existed.
                assert parsed <= date.today(), (
                    f"Row {row['aws']!r}: `last_reviewed` is in the future"
                )
                assert parsed >= date(2024, 1, 1), (
                    f"Row {row['aws']!r}: `last_reviewed` predates the project"
                )

    def test_last_reviewed_is_optional_for_untouched_rows(self):
        """Until #594 mandates the field globally, untouched rows may
        omit it. This test documents that staged rollout."""
        rows_with = [m for m in CROSS_CLOUD_MAPPINGS if "last_reviewed" in m]
        rows_without = [m for m in CROSS_CLOUD_MAPPINGS if "last_reviewed" not in m]
        # At least the #590-touched rows have it.
        assert len(rows_with) >= 5
        # Untouched rows are still allowed.
        assert len(rows_without) > 0, (
            "All rows now have last_reviewed — #594 should flip this test "
            "to assert 100% coverage."
        )


# ---------------------------------------------------------------------------
# Smoke regression — total catalog size + required-field invariant
# ---------------------------------------------------------------------------

class TestCatalogInvariants:
    def test_each_row_has_required_fields(self):
        for row in CROSS_CLOUD_MAPPINGS:
            assert "aws" in row
            assert "azure" in row
            assert "category" in row
            assert "confidence" in row
            assert 0 < row["confidence"] <= 1.0
            assert "notes" in row

    def test_no_duplicate_aws_keys(self):
        """Each AWS service should map to exactly one row, with the
        exception of explicitly-tier'd siblings (e.g. KMS / KMS (FIPS)).
        Pre-#590 there was only `Aurora`; post-#590 there are
        `Aurora PostgreSQL` and `Aurora MySQL` — both legitimate, both
        distinct keys."""
        keys = [m["aws"] for m in CROSS_CLOUD_MAPPINGS]
        dupes = [k for k in set(keys) if keys.count(k) > 1]
        assert not dupes, f"Duplicate AWS keys: {dupes}"
