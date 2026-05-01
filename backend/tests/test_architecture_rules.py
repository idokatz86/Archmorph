"""Tests for the architecture-limitations rule library (Issue #610)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure backend root is on sys.path so `architecture_rules` resolves.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from architecture_rules import (  # noqa: E402
    ArchitectureIssue,
    Severity,
    evaluate,
    has_blocker,
    list_rules,
    reload_rules,
)
from architecture_rules import predicates as preds  # noqa: E402
from architecture_rules import engine as engine_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def empty_analysis():
    return {"identified_services": [], "service_connections": []}


@pytest.fixture
def sftp_frontdoor_analysis():
    """The user's motivating example.

    SFTP client → Azure Front Door → Azure Storage (SFTP) over SFTP/SSH.
    Front Door is HTTP/HTTPS-only, so this composition cannot work.
    """
    return {
        "identified_services": [
            {"name": "SFTP Client", "category": "Client"},
            {"name": "Azure Front Door", "category": "Networking"},
            {"name": "Azure Storage (SFTP)", "category": "Storage"},
        ],
        "service_connections": [
            {"from": "SFTP Client", "to": "Azure Front Door", "type": "SFTP/SSH"},
            {"from": "Azure Front Door", "to": "Azure Storage (SFTP)", "type": "SFTP"},
        ],
        "service_to_resource_mapping": [
            {
                "service": "Azure Front Door",
                "resource_type": "Microsoft.Network/frontDoors",
            },
            {
                "service": "Azure Storage (SFTP)",
                "resource_type": "Microsoft.Storage/storageAccounts",
            },
        ],
    }


@pytest.fixture
def sane_web_analysis():
    return {
        "identified_services": [
            {"name": "Browser", "category": "Client"},
            {"name": "Azure Front Door", "category": "Networking"},
            {"name": "Azure App Service", "category": "Compute"},
        ],
        "service_connections": [
            {"from": "Browser", "to": "Azure Front Door", "type": "HTTPS"},
            {"from": "Azure Front Door", "to": "Azure App Service", "type": "HTTPS"},
        ],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestServiceHelpers:
    def test_service_matches_handles_azure_prefix(self):
        assert preds._service_matches("Azure Front Door", "front door")
        assert preds._service_matches("front door", "Azure Front Door")

    def test_service_matches_case_insensitive(self):
        assert preds._service_matches("AZURE STORAGE", "azure storage")

    def test_service_matches_dash_space(self):
        assert preds._service_matches("front-door", "front door")

    def test_service_matches_negative(self):
        assert not preds._service_matches("Azure Storage", "Cosmos DB")

    def test_services_in_analysis_collects_names(self, sftp_frontdoor_analysis):
        names = preds._services_in_analysis(sftp_frontdoor_analysis)
        assert any("Front Door" in n for n in names)
        assert any("SFTP Client" in n for n in names)


# ---------------------------------------------------------------------------
# Path-protocol-mismatch predicate (the SFTP/Front Door scenario)
# ---------------------------------------------------------------------------


class TestPathProtocolMismatch:
    def test_fires_on_sftp_via_front_door(self, sftp_frontdoor_analysis):
        match = preds.path_uses_service_with_protocol_mismatch(
            sftp_frontdoor_analysis,
            via="Azure Front Door",
            allowed_protocols=["http", "https"],
            disallowed_hint=["sftp", "ssh"],
        )
        assert match is not None
        assert any("Front Door" in s for s in match.affected_services)

    def test_does_not_fire_on_pure_https(self, sane_web_analysis):
        match = preds.path_uses_service_with_protocol_mismatch(
            sane_web_analysis,
            via="Azure Front Door",
            allowed_protocols=["http", "https"],
            disallowed_hint=["sftp", "ssh"],
        )
        assert match is None

    def test_does_not_fire_when_via_absent(self, empty_analysis):
        match = preds.path_uses_service_with_protocol_mismatch(
            empty_analysis,
            via="Azure Front Door",
            allowed_protocols=["http", "https"],
            disallowed_hint=["sftp"],
        )
        assert match is None


# ---------------------------------------------------------------------------
# Simple registered predicates
# ---------------------------------------------------------------------------


class TestSimplePredicates:
    def test_service_present(self, sftp_frontdoor_analysis):
        match = preds.service_present(sftp_frontdoor_analysis, name="Azure Front Door")
        assert match is not None

    def test_service_present_negative(self, empty_analysis):
        match = preds.service_present(empty_analysis, name="Azure Front Door")
        assert match is None

    def test_service_pair_connected(self, sftp_frontdoor_analysis):
        match = preds.service_pair_connected(
            sftp_frontdoor_analysis, a="Azure Front Door", b="Azure Storage"
        )
        assert match is not None

    def test_services_all_present_negative(self, sane_web_analysis):
        match = preds.services_all_present(
            sane_web_analysis, names=["Azure Front Door", "Cosmos DB"]
        )
        assert match is None

    def test_connection_uses_protocol(self, sftp_frontdoor_analysis):
        match = preds.connection_uses_protocol(
            sftp_frontdoor_analysis, protocols=["sftp"]
        )
        assert match is not None

    def test_get_predicate_unknown_returns_none(self):
        assert preds.get_predicate("does-not-exist") is None

    def test_register_predicate_dup_raises(self):
        with pytest.raises(ValueError):

            @preds.register_predicate("service_present")
            def _dupe(*_a, **_kw):
                return None


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------


class TestYAMLLoader:
    def test_parse_minimal_yaml(self, tmp_path):
        rules_yaml = tmp_path / "rules.yaml"
        rules_yaml.write_text(
            """
rules:
  - id: test-rule
    title: Test rule
    severity: warning
    category: testing
    message: Test message
    remediation: Do nothing
    docs_url: https://example.com
    predicate: service_present
    predicate_args:
      name: Azure Front Door
""".strip()
        )
        rules = engine_mod._load_rules_from_path(str(rules_yaml))
        assert len(rules) == 1
        rule = rules[0]
        assert rule.id == "test-rule"
        assert rule.severity == Severity.WARNING
        assert rule.predicate == "service_present"

    def test_invalid_severity_rejected(self, tmp_path):
        rules_yaml = tmp_path / "rules.yaml"
        rules_yaml.write_text(
            """
rules:
  - id: test-rule
    title: Test rule
    severity: critical-meltdown
    category: testing
    message: msg
    remediation: rem
    docs_url: https://example.com
    predicate: service_present
""".strip()
        )
        with pytest.raises(ValueError, match="severity"):
            engine_mod._load_rules_from_path(str(rules_yaml))

    def test_missing_required_field_rejected(self, tmp_path):
        rules_yaml = tmp_path / "rules.yaml"
        rules_yaml.write_text(
            """
rules:
  - severity: warning
    category: testing
    message: msg
    remediation: rem
    docs_url: https://example.com
    predicate: service_present
""".strip()
        )
        with pytest.raises(ValueError, match="id"):
            engine_mod._load_rules_from_path(str(rules_yaml))

    def test_unknown_predicate_rejected(self, tmp_path):
        rules_yaml = tmp_path / "rules.yaml"
        rules_yaml.write_text(
            """
rules:
  - id: test-rule
    title: Test rule
    severity: warning
    category: testing
    message: msg
    remediation: rem
    docs_url: https://example.com
    predicate: nonexistent_predicate
""".strip()
        )
        with pytest.raises(ValueError, match="unknown predicate"):
            engine_mod._load_rules_from_path(str(rules_yaml))

    def test_duplicate_id_rejected(self, tmp_path):
        rules_yaml = tmp_path / "rules.yaml"
        rules_yaml.write_text(
            """
rules:
  - id: dup
    title: A
    severity: info
    category: testing
    message: m
    remediation: r
    docs_url: https://example.com
    predicate: service_present
    predicate_args:
      name: Foo
  - id: dup
    title: B
    severity: info
    category: testing
    message: m
    remediation: r
    docs_url: https://example.com
    predicate: service_present
    predicate_args:
      name: Bar
""".strip()
        )
        with pytest.raises(ValueError, match="duplicate"):
            engine_mod._load_rules_from_path(str(rules_yaml))


class TestYAMLLoaderFromDisk:
    def test_default_rules_load(self):
        rules = list_rules()
        assert len(rules) >= 25

    def test_default_rules_have_unique_ids(self):
        rules = list_rules()
        ids = [r.id for r in rules]
        assert len(ids) == len(set(ids)), "duplicate rule IDs detected"

    def test_default_rules_reference_known_predicates(self):
        rules = list_rules()
        for r in rules:
            assert preds.get_predicate(r.predicate) is not None, (
                f"rule {r.id} references unknown predicate {r.predicate}"
            )

    def test_default_rules_have_docs_url(self):
        rules = list_rules()
        for r in rules:
            assert r.docs_url.startswith("http"), f"{r.id} missing docs_url"


# ---------------------------------------------------------------------------
# Engine end-to-end
# ---------------------------------------------------------------------------


class TestEngineEndToEnd:
    def test_evaluate_returns_list(self, empty_analysis):
        issues = evaluate(empty_analysis)
        assert isinstance(issues, list)

    def test_evaluate_issue_shape(self, sftp_frontdoor_analysis):
        issues = evaluate(sftp_frontdoor_analysis)
        assert len(issues) >= 1
        issue = issues[0]
        assert isinstance(issue, ArchitectureIssue)
        d = issue.to_dict()
        for key in (
            "rule_id",
            "severity",
            "category",
            "title",
            "message",
            "remediation",
            "docs_url",
            "affected_services",
            "source",
        ):
            assert key in d

    def test_has_blocker_helper(self, sftp_frontdoor_analysis):
        issues = evaluate(sftp_frontdoor_analysis)
        assert has_blocker(issues) is True

    def test_no_blockers_on_sane_arch(self, sane_web_analysis):
        issues = evaluate(sane_web_analysis)
        # warnings/info ok, but no BLOCKERs
        blockers = [i for i in issues if i.severity == Severity.BLOCKER]
        assert blockers == []

    def test_evaluate_sorted_by_severity(self, sftp_frontdoor_analysis):
        issues = evaluate(sftp_frontdoor_analysis)
        ranks = [
            {Severity.BLOCKER: 3, Severity.WARNING: 2, Severity.INFO: 1}[i.severity]
            for i in issues
        ]
        assert ranks == sorted(ranks, reverse=True)

    def test_evaluate_handles_non_dict_input(self):
        assert evaluate(None) == []  # type: ignore[arg-type]
        assert evaluate("not a dict") == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Golden scenarios — the user's headline example
# ---------------------------------------------------------------------------


class TestGoldenScenarios:
    def test_sftp_via_front_door_fires_blocker(self, sftp_frontdoor_analysis):
        issues = evaluate(sftp_frontdoor_analysis)
        blocker_ids = {i.rule_id for i in issues if i.severity == Severity.BLOCKER}
        # Either the dedicated SFTP-specific rule or the generic Front Door
        # protocol rule is acceptable; ideally both fire.
        assert blocker_ids & {
            "front-door-sftp-storage-blocker",
            "front-door-protocol-mismatch",
        }, (
            f"Expected SFTP/FrontDoor blocker rule to fire. Got: {blocker_ids}"
        )


# ---------------------------------------------------------------------------
# YAML override path
# ---------------------------------------------------------------------------


class TestYAMLOverride:
    def test_env_override(self, tmp_path, monkeypatch):
        custom = tmp_path / "custom.yaml"
        custom.write_text(
            """
rules:
  - id: custom-only-rule
    title: Custom rule
    severity: info
    category: testing
    message: msg
    remediation: rem
    docs_url: https://example.com
    predicate: service_present
    predicate_args:
      name: Azure Front Door
""".strip()
        )
        monkeypatch.setenv("ARCHMORPH_ARCH_RULES_PATH", str(custom))
        try:
            reload_rules()
            rules = list_rules()
            assert len(rules) == 1
            assert rules[0].id == "custom-only-rule"
        finally:
            monkeypatch.delenv("ARCHMORPH_ARCH_RULES_PATH", raising=False)
            reload_rules()
