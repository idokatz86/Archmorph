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


@pytest.fixture
def phase2_missing_posture_analysis():
    return {
        "identified_services": [
            {"name": "Browser", "category": "Client"},
            {"name": "Azure Front Door", "category": "Networking"},
            {"name": "Azure App Service", "category": "Compute"},
            {"name": "Azure SQL Database", "category": "Database"},
            {"name": "Azure Storage Account", "category": "Storage"},
        ],
        "service_connections": [
            {"from": "Browser", "to": "Azure Front Door", "type": "HTTPS"},
            {"from": "Azure Front Door", "to": "Azure App Service", "type": "HTTPS"},
            {"from": "Azure App Service", "to": "Azure SQL Database", "type": "TDS"},
            {"from": "Azure App Service", "to": "Azure Storage Account", "type": "HTTPS"},
        ],
    }


@pytest.fixture
def phase2_complete_posture_analysis():
    return {
        "identified_services": [
            {"name": "Browser", "category": "Client"},
            {"name": "Azure Front Door", "category": "Networking"},
            {"name": "Front Door WAF Policy", "category": "Security"},
            {"name": "Azure DDoS Network Protection", "category": "Security"},
            {"name": "Azure App Service", "category": "Compute"},
            {"name": "Managed Identity", "category": "Identity"},
            {"name": "Microsoft Entra ID", "category": "Identity"},
            {"name": "Azure SQL Database", "category": "Database"},
            {"name": "SQL Failover Group", "category": "Resilience"},
            {"name": "Azure Storage Account", "category": "Storage"},
            {"name": "Geo-redundant Storage", "category": "Resilience"},
            {"name": "Recovery Services Vault", "category": "Backup"},
            {"name": "Azure Backup", "category": "Backup"},
            {"name": "Azure Policy Tagging Initiative", "category": "Governance"},
        ],
        "service_connections": [
            {"from": "Browser", "to": "Azure Front Door", "type": "HTTPS"},
            {"from": "Azure Front Door", "to": "Azure App Service", "type": "HTTPS"},
            {"from": "Azure App Service", "to": "Azure SQL Database", "type": "TDS"},
            {"from": "Azure App Service", "to": "Azure Storage Account", "type": "HTTPS"},
        ],
    }


@pytest.fixture
def phase2_mixed_stateful_posture_analysis():
    return {
        "identified_services": [
            {"name": "Azure App Service", "category": "Compute"},
            {"name": "Managed Identity", "category": "Identity"},
            {"name": "Azure SQL Database", "category": "Database"},
            {"name": "SQL Failover Group", "category": "Resilience"},
            {"name": "Azure Storage Account", "category": "Storage"},
            {"name": "Azure Backup", "category": "Backup"},
        ],
        "service_connections": [
            {"from": "Azure App Service", "to": "Azure SQL Database", "type": "TDS"},
            {"from": "Azure App Service", "to": "Azure Storage Account", "type": "HTTPS"},
        ],
    }


@pytest.fixture
def private_backend_analysis():
    return {
        "identified_services": [
            {"name": "Azure App Service", "category": "Compute"},
            {"name": "Managed Identity", "category": "Identity"},
            {"name": "Azure SQL Database", "category": "Database"},
            {"name": "SQL Failover Group", "category": "Resilience"},
            {"name": "Azure Backup", "category": "Backup"},
            {"name": "Virtual Network", "category": "Networking"},
            {"name": "Private Endpoint", "category": "Networking"},
        ],
        "service_connections": [
            {"from": "Azure App Service", "to": "Azure SQL Database", "type": "TDS"},
        ],
    }


@pytest.fixture
def phase3_missing_controls_analysis():
    return {
        "identified_services": [
            {"name": "Browser", "category": "Client"},
            {"name": "Azure Front Door", "category": "Networking"},
            {"name": "Custom Domain", "category": "Networking"},
            {"name": "DNS Zone", "category": "Networking"},
            {"name": "API Management", "category": "API"},
            {"name": "Azure App Service", "category": "Compute"},
            {"name": "Azure SQL Database", "category": "Database"},
            {"name": "Azure Storage Account", "category": "Storage"},
            {"name": "Service Bus Queue", "category": "Messaging"},
            {"name": "Event Hubs Namespace", "category": "Streaming"},
            {"name": "HIPAA Workload", "category": "Compliance"},
            {"name": "Multi-tenant SaaS Portal", "category": "Application"},
        ],
        "service_connections": [
            {"from": "Browser", "to": "Azure Front Door", "type": "HTTPS"},
            {"from": "Azure Front Door", "to": "API Management", "type": "HTTPS"},
            {"from": "API Management", "to": "Azure App Service", "type": "HTTPS"},
            {"from": "Azure App Service", "to": "Azure SQL Database", "type": "TDS"},
            {"from": "Azure App Service", "to": "Service Bus Queue", "type": "AMQP"},
            {"from": "Azure App Service", "to": "Event Hubs Namespace", "type": "AMQP"},
        ],
    }


@pytest.fixture
def phase3_complete_controls_analysis():
    return {
        "identified_services": [
            {"name": "Browser", "category": "Client"},
            {"name": "Azure Front Door", "category": "Networking"},
            {"name": "Custom Domain", "category": "Networking"},
            {"name": "DNS Zone", "category": "Networking"},
            {"name": "DNS Validation", "category": "Networking"},
            {"name": "Managed Certificate", "category": "Security"},
            {"name": "API Management", "category": "API"},
            {"name": "Rate Limit Policy", "category": "Security"},
            {"name": "Azure App Service", "category": "Compute"},
            {"name": "Managed Identity", "category": "Identity"},
            {"name": "Azure Key Vault", "category": "Security"},
            {"name": "Application Insights", "category": "Operations"},
            {"name": "Azure Policy", "category": "Governance"},
            {"name": "Defender for Cloud", "category": "Governance"},
            {"name": "Private Endpoint", "category": "Networking"},
            {"name": "Availability Zones", "category": "Resilience"},
            {"name": "Azure SQL Database", "category": "Database"},
            {"name": "Azure Storage Account", "category": "Storage"},
            {"name": "Service Bus Queue", "category": "Messaging"},
            {"name": "Service Bus DLQ", "category": "Messaging"},
            {"name": "Event Hubs Namespace", "category": "Streaming"},
            {"name": "Event Hubs Checkpoint Blob", "category": "Storage"},
            {"name": "HIPAA Workload", "category": "Compliance"},
            {"name": "Tenant Isolation", "category": "Architecture"},
            {"name": "Partition Key", "category": "Data"},
            {"name": "Multi-tenant SaaS Portal", "category": "Application"},
        ],
        "service_connections": [
            {"from": "Browser", "to": "Azure Front Door", "type": "HTTPS"},
            {"from": "Azure Front Door", "to": "API Management", "type": "HTTPS"},
            {"from": "API Management", "to": "Azure App Service", "type": "HTTPS"},
            {"from": "Azure App Service", "to": "Azure SQL Database", "type": "TDS"},
            {"from": "Azure App Service", "to": "Service Bus Queue", "type": "AMQP"},
            {"from": "Azure App Service", "to": "Event Hubs Namespace", "type": "AMQP"},
        ],
    }


@pytest.fixture
def observability_overlap_analysis():
    return {
        "identified_services": [
            {"name": "Azure App Service", "category": "Compute"},
            {"name": "Application Insights", "category": "Operations"},
            {"name": "Log Analytics Workspace", "category": "Operations"},
            {"name": "Datadog", "category": "Operations"},
        ],
        "service_connections": [],
    }


@pytest.fixture
def frontdoor_private_origin_analysis():
    return {
        "identified_services": [
            {"name": "Azure Front Door", "category": "Networking"},
            {"name": "Private Endpoint", "category": "Networking"},
            {"name": "Azure App Service", "category": "Compute"},
        ],
        "service_connections": [
            {"from": "Azure Front Door", "to": "Private Endpoint", "type": "HTTPS"},
        ],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rule_ids(analysis):
    return {issue.rule_id for issue in evaluate(analysis)}


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

    def test_service_keywords_without_companion_positive(
        self, phase2_missing_posture_analysis
    ):
        match = preds.service_keywords_without_companion(
            phase2_missing_posture_analysis,
            keywords=["SQL Database"],
            companions=["Backup"],
        )
        assert match is not None
        assert match.affected_services == ["Azure SQL Database"]

    def test_service_keywords_without_companion_negative(
        self, phase2_complete_posture_analysis
    ):
        match = preds.service_keywords_without_companion(
            phase2_complete_posture_analysis,
            keywords=["SQL Database"],
            companions=["Backup"],
        )
        assert match is None

    def test_service_keywords_without_companion_coverage_keeps_mixed_gap(
        self, phase2_mixed_stateful_posture_analysis
    ):
        match = preds.service_keywords_without_companion(
            phase2_mixed_stateful_posture_analysis,
            keywords=["SQL Database", "Storage"],
            companions=["Failover Group"],
            companion_mode="coverage",
        )
        assert match is not None
        assert set(match.affected_services) == {
            "Azure SQL Database",
            "Azure Storage Account",
        }

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
        assert len(rules) >= 40

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


class TestPhase2RulePack:
    def test_phase2_rules_fire_when_posture_missing(self, phase2_missing_posture_analysis):
        ids = _rule_ids(phase2_missing_posture_analysis)
        assert {
            "dr-cross-region-replication-warning",
            "edge-security-waf-ddos-warning",
            "identity-layer-missing-warning",
            "backup-posture-missing-warning",
            "tagging-policy-missing-info",
        }.issubset(ids)

    def test_phase2_rules_do_not_fire_when_posture_present(
        self, phase2_complete_posture_analysis
    ):
        ids = _rule_ids(phase2_complete_posture_analysis)
        assert "dr-cross-region-replication-warning" not in ids
        assert "edge-security-waf-ddos-warning" not in ids
        assert "identity-layer-missing-warning" not in ids
        assert "backup-posture-missing-warning" not in ids
        assert "tagging-policy-missing-info" not in ids

    def test_stateful_rules_still_fire_on_mixed_partial_coverage(
        self, phase2_mixed_stateful_posture_analysis
    ):
        ids = _rule_ids(phase2_mixed_stateful_posture_analysis)
        assert "dr-cross-region-replication-warning" in ids
        assert "backup-posture-missing-warning" in ids

    def test_edge_rule_does_not_fire_on_private_backend(self, private_backend_analysis):
        ids = _rule_ids(private_backend_analysis)
        assert "edge-security-waf-ddos-warning" not in ids


class TestPhase3RulePack:
    def test_phase3_rules_fire_when_controls_missing(
        self, phase3_missing_controls_analysis
    ):
        ids = _rule_ids(phase3_missing_controls_analysis)
        assert {
            "public-data-service-without-private-link-warning",
            "workload-secrets-without-key-vault-warning",
            "observability-anchor-missing-warning",
            "regulated-workload-without-policy-anchor-warning",
            "multi-domain-edge-validation-info",
            "multi-tenant-app-without-tenant-isolation-warning",
            "service-bus-without-dead-letter-operations-warning",
            "event-hubs-without-checkpoint-storage-warning",
            "public-api-without-rate-limiting-warning",
            "zone-redundancy-posture-missing-warning",
        }.issubset(ids)

    def test_phase3_rules_do_not_fire_when_controls_present(
        self, phase3_complete_controls_analysis
    ):
        ids = _rule_ids(phase3_complete_controls_analysis)
        assert "public-data-service-without-private-link-warning" not in ids
        assert "workload-secrets-without-key-vault-warning" not in ids
        assert "observability-anchor-missing-warning" not in ids
        assert "regulated-workload-without-policy-anchor-warning" not in ids
        assert "multi-domain-edge-validation-info" not in ids
        assert "multi-tenant-app-without-tenant-isolation-warning" not in ids
        assert "service-bus-without-dead-letter-operations-warning" not in ids
        assert "event-hubs-without-checkpoint-storage-warning" not in ids
        assert "public-api-without-rate-limiting-warning" not in ids
        assert "zone-redundancy-posture-missing-warning" not in ids

    def test_observability_overlap_rule_fires_on_multiple_stacks(
        self, observability_overlap_analysis, phase3_complete_controls_analysis
    ):
        assert "observability-stack-overlap-info" in _rule_ids(
            observability_overlap_analysis
        )
        assert "observability-stack-overlap-info" not in _rule_ids(
            phase3_complete_controls_analysis
        )

    def test_premium_edge_cost_rule_requires_private_origin(
        self, frontdoor_private_origin_analysis, sane_web_analysis
    ):
        assert "premium-edge-cost-acknowledgement-info" in _rule_ids(
            frontdoor_private_origin_analysis
        )
        assert "premium-edge-cost-acknowledgement-info" not in _rule_ids(
            sane_web_analysis
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
