"""
Archmorph — Guided Questions Rule Functions Unit Tests
Tests for the individual _apply_* rule functions in guided_questions.py
"""

import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from guided_questions import (
    _normalise_service,
    _merge_defaults,
    _swap_azure_service,
    _boost_confidence,
    _apply_environment,
    _apply_sku_strategy,
    _apply_compliance,
    _apply_network_isolation,
    _apply_deploy_region,
    _apply_encryption,
    generate_questions,
    apply_answers,
    QUESTION_BANK,
)


# ── Helper fixtures ─────────────────────────────────────────

@pytest.fixture
def sample_mappings():
    return [
        {
            "source_service": "Amazon EC2",
            "azure_service": "Azure Virtual Machines Standard",
            "confidence": 0.85,
            "notes": "Zone 1 Compute",
        },
        {
            "source_service": "Amazon S3",
            "azure_service": "Azure Blob Storage",
            "confidence": 0.90,
            "notes": "Zone 2 Storage",
        },
        {
            "source_service": "Amazon EMR",
            "azure_service": "Azure Synapse Analytics",
            "confidence": 0.80,
            "notes": "Zone 3 Analytics",
        },
    ]


@pytest.fixture
def sample_analysis(sample_mappings):
    return {
        "mappings": sample_mappings,
        "warnings": [],
        "iac_parameters": {},
    }


# ====================================================================
# _normalise_service()
# ====================================================================

class TestNormaliseService:
    def test_known_aws_service(self):
        assert _normalise_service("Amazon S3") == "S3"

    def test_known_long_name(self):
        assert _normalise_service("Amazon EC2") == "EC2"

    def test_unknown_passthrough(self):
        assert _normalise_service("Unknown Service XYZ") == "Unknown Service XYZ"

    def test_lambda(self):
        assert _normalise_service("AWS Lambda") == "Lambda"


# ====================================================================
# _merge_defaults()
# ====================================================================

class TestMergeDefaults:
    def test_fills_missing_keys(self):
        result = _merge_defaults({})
        # Should have a default for every question in the bank
        all_ids = {q["id"] for qs in QUESTION_BANK.values() for q in qs}
        for qid in all_ids:
            assert qid in result, f"Missing default for {qid}"

    def test_preserves_user_answers(self):
        result = _merge_defaults({"env_target": "Development"})
        assert result["env_target"] == "Development"

    def test_default_env_is_production(self):
        result = _merge_defaults({})
        assert result["env_target"] == "Production"


# ====================================================================
# _swap_azure_service()
# ====================================================================

class TestSwapAzureService:
    def test_swaps_matching_service(self, sample_mappings):
        _swap_azure_service(
            sample_mappings, "EMR", "Synapse", "Azure Databricks",
            note_suffix="Databricks selected", confidence_delta=0.05,
        )
        emr = [m for m in sample_mappings if "EMR" in m["source_service"]][0]
        assert emr["azure_service"] == "Azure Databricks"
        assert "Databricks selected" in emr["notes"]
        assert abs(emr["confidence"] - 0.85) < 0.01

    def test_no_match_leaves_unchanged(self, sample_mappings):
        original = copy.deepcopy(sample_mappings)
        _swap_azure_service(sample_mappings, "NonExistent", "Foo", "Bar")
        assert sample_mappings == original


# ====================================================================
# _boost_confidence()
# ====================================================================

class TestBoostConfidence:
    def test_boosts_all(self, sample_mappings):
        _boost_confidence(sample_mappings, 0.05)
        assert abs(sample_mappings[0]["confidence"] - 0.90) < 0.01
        assert abs(sample_mappings[1]["confidence"] - 0.95) < 0.01

    def test_capped_at_1(self, sample_mappings):
        _boost_confidence(sample_mappings, 0.5)
        for m in sample_mappings:
            assert m["confidence"] <= 1.0


# ====================================================================
# _apply_environment()
# ====================================================================

class TestApplyEnvironment:
    def test_development_sets_spot_and_autoshutdown(self, sample_mappings):
        answers = {"env_target": "Development"}
        warnings = []
        iac = {}
        _apply_environment(answers, sample_mappings, warnings, iac)
        assert iac["use_spot_instances"] is True
        assert iac["auto_shutdown"] is True
        assert any("Development" in w for w in warnings)

    def test_production_no_spot(self, sample_mappings):
        answers = {"env_target": "Production"}
        warnings = []
        iac = {}
        _apply_environment(answers, sample_mappings, warnings, iac)
        assert "use_spot_instances" not in iac
        assert iac["environment"] == "production"

    def test_multi_environment(self, sample_mappings):
        answers = {"env_target": "Multi-environment"}
        warnings = []
        iac = {}
        _apply_environment(answers, sample_mappings, warnings, iac)
        assert iac["deploy_environments"] == ["dev", "staging", "prod"]


# ====================================================================
# _apply_sku_strategy()
# ====================================================================

class TestApplySkuStrategy:
    def test_enterprise_upgrades_standard_to_premium(self, sample_mappings):
        answers = {"arch_sku_strategy": "Enterprise (maximum SLA and features)"}
        warnings = []
        iac = {}
        _apply_sku_strategy(answers, sample_mappings, warnings, iac)
        vm = sample_mappings[0]
        assert "Premium" in vm["azure_service"]
        assert "Standard" not in vm["azure_service"]
        assert any("Enterprise" in w for w in warnings)

    def test_cost_optimized_downgrades_premium(self):
        mappings = [
            {"source_service": "X", "azure_service": "Azure Premium Redis", "confidence": 0.8}
        ]
        answers = {"arch_sku_strategy": "Cost-optimized (lowest viable tier)"}
        warnings = []
        iac = {}
        _apply_sku_strategy(answers, mappings, warnings, iac)
        assert "Standard" in mappings[0]["azure_service"]
        assert "Premium" not in mappings[0]["azure_service"]

    def test_balanced_no_swap(self, sample_mappings):
        original_services = [m["azure_service"] for m in sample_mappings]
        answers = {"arch_sku_strategy": "Balanced (good performance-to-cost ratio)"}
        warnings = []
        iac = {}
        _apply_sku_strategy(answers, sample_mappings, warnings, iac)
        # Balanced should not swap services
        for m, orig in zip(sample_mappings, original_services):
            assert m["azure_service"] == orig


# ====================================================================
# _apply_compliance()
# ====================================================================

class TestApplyCompliance:
    def test_hipaa_sets_flag(self, sample_mappings):
        answers = {"sec_compliance": "HIPAA"}
        warnings = []
        iac = {}
        _apply_compliance(answers, sample_mappings, warnings, iac)
        assert iac.get("hipaa_enabled") is True
        assert any("HIPAA" in w for w in warnings)

    def test_no_restriction_no_flags(self, sample_mappings):
        answers = {"sec_compliance": "No specific requirements"}
        warnings = []
        iac = {}
        _apply_compliance(answers, sample_mappings, warnings, iac)
        assert "hipaa_enabled" not in iac


# ====================================================================
# _apply_network_isolation()
# ====================================================================

class TestApplyNetworkIsolation:
    def test_full_private_endpoints(self, sample_mappings):
        answers = {"sec_network_isolation": "Full private endpoints"}
        warnings = []
        iac = {}
        _apply_network_isolation(answers, sample_mappings, warnings, iac)
        assert iac.get("private_endpoints") is True
        assert iac.get("public_network_access") is False

    def test_public_only(self, sample_mappings):
        answers = {"sec_network_isolation": "Public only (simplest, lowest cost)"}
        warnings = []
        iac = {}
        _apply_network_isolation(answers, sample_mappings, warnings, iac)
        assert iac.get("private_endpoints") is not True


# ====================================================================
# _apply_deploy_region()
# ====================================================================

class TestApplyDeployRegion:
    def test_sets_arm_region(self):
        answers = {"arch_deploy_region": "North Europe"}
        iac = {}
        _apply_deploy_region(answers, iac)
        assert iac["deploy_region"] == "northeurope"

    def test_default_west_europe(self):
        answers = {}
        iac = {}
        _apply_deploy_region(answers, iac)
        assert iac.get("deploy_region", "westeurope") == "westeurope"


# ====================================================================
# _apply_encryption()
# ====================================================================

class TestApplyEncryption:
    def test_cmk_sets_flag(self, sample_mappings):
        answers = {"sec_encryption": "Customer-managed keys (CMK)"}
        warnings = []
        iac = {}
        _apply_encryption(answers, sample_mappings, warnings, iac)
        assert iac.get("cmk_enabled") is True


# ====================================================================
# generate_questions()
# ====================================================================

class TestGenerateQuestions:
    def test_returns_list(self):
        result = generate_questions(["EC2", "S3", "Lambda"])
        assert isinstance(result, list)
        assert len(result) > 0

    def test_caps_at_18(self):
        # With many services, should not exceed 18
        many_services = ["EC2", "S3", "Lambda", "RDS", "DynamoDB", "EKS",
                         "EMR", "Kinesis", "SageMaker", "IoT Core", "CloudWatch",
                         "ElastiCache", "SNS", "SQS", "VPC", "Route 53",
                         "CloudFront", "API Gateway"]
        result = generate_questions(many_services)
        assert len(result) <= 18

    def test_always_includes_env_question(self):
        result = generate_questions(["EC2"])
        ids = [q["id"] for q in result]
        assert "env_target" in ids

    def test_question_has_required_fields(self):
        result = generate_questions(["S3"])
        for q in result:
            assert "id" in q
            assert "question" in q
            assert "options" in q
            assert "default" in q


# ====================================================================
# apply_answers() — integration
# ====================================================================

class TestApplyAnswersIntegration:
    def test_returns_new_dict(self, sample_analysis):
        result = apply_answers(sample_analysis, {})
        assert result is not sample_analysis

    def test_original_unchanged(self, sample_analysis):
        original = copy.deepcopy(sample_analysis)
        apply_answers(sample_analysis, {"env_target": "Development"})
        assert sample_analysis == original

    def test_dev_environment_adds_warnings(self, sample_analysis):
        result = apply_answers(sample_analysis, {"env_target": "Development"})
        assert any("Development" in w for w in result["warnings"])

    def test_has_iac_parameters(self, sample_analysis):
        result = apply_answers(sample_analysis, {})
        assert "iac_parameters" in result

    def test_enterprise_sku_upgrades(self, sample_analysis):
        result = apply_answers(
            sample_analysis,
            {"arch_sku_strategy": "Enterprise (maximum SLA and features)"},
        )
        # The VM mapping should have been upgraded
        vm = [m for m in result["mappings"] if "EC2" in m["source_service"]][0]
        assert "Premium" in vm["azure_service"] or "premium" in vm.get("notes", "").lower()
