"""
Archmorph — Service Updater Unit Tests
Tests for the rewritten service_updater.py (v2.2.0)
"""

import os
import sys
from unittest.mock import patch


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from service_updater import (
    _normalise,
    _guess_category,
    _make_service_entry,
    _load_local_catalog,
    _read_state,
    _write_state,
    _load_discovered_services,
    _save_discovered_services,
    _PROVIDER_CONFIG,
)


# ====================================================================
# _normalise()
# ====================================================================

class TestNormalise:
    def test_strips_spaces(self):
        assert _normalise("Hello World") == "helloworld"

    def test_strips_special_chars(self):
        assert _normalise("AWS Lambda!") == "awslambda"

    def test_lowercase(self):
        assert _normalise("EC2") == "ec2"

    def test_strips_hyphens_underscores(self):
        assert _normalise("my-service_v2") == "myservicev2"

    def test_empty_string(self):
        assert _normalise("") == ""

    def test_already_normalised(self):
        assert _normalise("s3") == "s3"

    def test_unicode_chars_stripped(self):
        # Non-alnum unicode should be stripped
        assert _normalise("café") == "caf"


# ====================================================================
# _guess_category()
# ====================================================================

class TestGuessCategory:
    def test_compute_ec2(self):
        assert _guess_category("EC2 AutoScaling") == "Compute"

    def test_compute_lambda(self):
        assert _guess_category("AWS Lambda") == "Compute"

    def test_compute_machine(self):
        assert _guess_category("Virtual Machine Scale Sets") == "Compute"

    def test_storage_s3(self):
        assert _guess_category("Amazon S3 Glacier") == "Storage"

    def test_storage_blob(self):
        assert _guess_category("Azure Blob Storage") == "Storage"

    def test_database_sql(self):
        assert _guess_category("Azure SQL Database") == "Database"

    def test_database_redis(self):
        assert _guess_category("Amazon ElastiCache Redis") == "Database"

    def test_networking_vpc(self):
        assert _guess_category("Amazon VPC") == "Networking"

    def test_networking_cdn(self):
        assert _guess_category("Azure CDN") == "Networking"

    def test_security_iam(self):
        assert _guess_category("AWS IAM") == "Security"

    def test_security_key_vault(self):
        assert _guess_category("Azure Key Vault") == "Security"

    def test_monitoring_cloudwatch(self):
        assert _guess_category("Amazon CloudWatch Logs") == "Monitoring"

    def test_ai_ml_sagemaker(self):
        assert _guess_category("Amazon SageMaker") == "AI/ML"

    def test_ai_ml_bedrock(self):
        assert _guess_category("Amazon Bedrock Runtime") == "AI/ML"

    def test_ai_ml_cognitive(self):
        assert _guess_category("Azure Cognitive Services") == "AI/ML"

    def test_devops_pipeline(self):
        assert _guess_category("Azure DevOps Pipeline") == "DevOps"

    def test_analytics_kinesis(self):
        assert _guess_category("Amazon Kinesis Data Streams") == "Analytics"

    def test_integration_sqs(self):
        assert _guess_category("Amazon SQS") == "Integration"

    def test_migration_transfer(self):
        assert _guess_category("AWS Migration Service") == "Migration"

    def test_unknown_returns_other(self):
        assert _guess_category("MyCustomThing") == "Other"

    def test_empty_string(self):
        assert _guess_category("") == "Other"


# ====================================================================
# _make_service_entry()
# ====================================================================

class TestMakeServiceEntry:
    def test_aws_entry_structure(self):
        entry = _make_service_entry("New Compute Service", "aws")
        assert entry["id"] == "aws-new-compute-service"
        assert entry["name"] == "New Compute Service"
        assert entry["fullName"] == "AWS New Compute Service"
        assert entry["category"] == "Compute"
        assert entry["icon"] == "server"
        assert "description" in entry

    def test_azure_entry_structure(self):
        entry = _make_service_entry("Blob Archive", "azure")
        assert entry["id"] == "az-blob-archive"
        assert entry["fullName"] == "Azure Blob Archive"
        assert entry["category"] == "Storage"
        assert entry["icon"] == "storage"

    def test_gcp_entry_structure(self):
        entry = _make_service_entry("BigQuery ML", "gcp")
        assert entry["id"] == "gcp-bigquery-ml"
        assert entry["fullName"] == "Google Cloud BigQuery ML"
        assert entry["category"] == "AI/ML"

    def test_unknown_category_uses_default_icon(self):
        entry = _make_service_entry("Quantum Foo", "aws")
        assert entry["category"] == "Other"
        assert entry["icon"] == "cloud"

    def test_strips_whitespace(self):
        entry = _make_service_entry("  Padded Service  ", "aws")
        assert entry["name"] == "Padded Service"

    def test_slug_handles_special_chars(self):
        entry = _make_service_entry("Service (v2.0)", "azure")
        assert "(" not in entry["id"]
        assert ")" not in entry["id"]
        assert entry["id"].startswith("az-")


# ====================================================================
# _load_local_catalog()
# ====================================================================

class TestLoadLocalCatalog:
    def test_loads_aws_catalog(self):
        services, names = _load_local_catalog("aws")
        assert len(services) > 100
        assert "ec2" in names or _normalise("EC2") in names

    def test_loads_azure_catalog(self):
        services, names = _load_local_catalog("azure")
        assert len(services) > 100

    def test_loads_gcp_catalog(self):
        services, names = _load_local_catalog("gcp")
        assert len(services) > 50

    def test_name_set_contains_normalised_names(self):
        services, names = _load_local_catalog("aws")
        # Should include normalised forms of id, name, and fullName
        # Check a known service
        found = any("lambda" in n for n in names)
        assert found, "Expected 'lambda' in normalised name set"

    def test_name_set_includes_ids(self):
        services, names = _load_local_catalog("aws")
        # AWS services have ids like "aws-ec2"
        found = any("awsec2" in n for n in names)
        assert found, "Expected normalised id in name set"


# ====================================================================
# _read_state / _write_state
# ====================================================================

class TestReadWriteState:
    def test_read_missing_file_returns_default(self, tmp_path):
        with patch("service_updater._UPDATES_FILE", tmp_path / "nonexistent.json"):
            state = _read_state()
            assert state["last_check"] is None
            assert isinstance(state["checks"], list)
            assert "new_services_found" in state
            assert "auto_added" in state

    def test_roundtrip(self, tmp_path):
        state_file = tmp_path / "state.json"
        with patch("service_updater._UPDATES_FILE", state_file), \
             patch("service_updater._DATA_DIR", tmp_path):
            test_state = {
                "last_check": "2024-01-01T00:00:00",
                "checks": [{"ts": "2024-01-01"}],
                "new_services_found": {"aws": ["SvcA"], "azure": [], "gcp": []},
                "auto_added": {"aws": [], "azure": [], "gcp": []},
            }
            _write_state(test_state)
            loaded = _read_state()
            assert loaded["last_check"] == "2024-01-01T00:00:00"
            assert loaded["new_services_found"]["aws"] == ["SvcA"]

    def test_read_corrupt_json_returns_default(self, tmp_path):
        state_file = tmp_path / "state.json"
        state_file.write_text("{invalid json}", encoding="utf-8")
        with patch("service_updater._UPDATES_FILE", state_file):
            state = _read_state()
            assert state["last_check"] is None


# ====================================================================
# _PROVIDER_CONFIG consistency
# ====================================================================

class TestProviderConfig:
    def test_all_three_providers(self):
        assert "aws" in _PROVIDER_CONFIG
        assert "azure" in _PROVIDER_CONFIG
        assert "gcp" in _PROVIDER_CONFIG

    def test_required_keys(self):
        for provider, config in _PROVIDER_CONFIG.items():
            assert "module" in config, f"{provider} missing 'module'"
            assert "variable" in config, f"{provider} missing 'variable'"
            assert "id_prefix" in config, f"{provider} missing 'id_prefix'"

    def test_variable_names_match_actual_exports(self):
        import importlib
        for provider, config in _PROVIDER_CONFIG.items():
            mod = importlib.import_module(config["module"])
            assert hasattr(mod, config["variable"]), (
                f"{config['module']} has no attribute {config['variable']}"
            )

    def test_no_file_key_in_config(self):
        """Ensure _PROVIDER_CONFIG no longer references .py catalog files."""
        for provider, config in _PROVIDER_CONFIG.items():
            assert "file" not in config, (
                f"{provider} config should not have 'file' key (no .py file modification)"
            )


# ====================================================================
# _load_discovered_services / _save_discovered_services
# ====================================================================

class TestDiscoveredServices:
    def test_load_missing_file_returns_empty(self, tmp_path):
        with patch("service_updater._DISCOVERED_FILE", tmp_path / "nonexistent.json"):
            result = _load_discovered_services()
            assert result == {"aws": [], "azure": [], "gcp": []}

    def test_load_corrupt_json_returns_empty(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{not valid", encoding="utf-8")
        with patch("service_updater._DISCOVERED_FILE", bad_file):
            result = _load_discovered_services()
            assert result == {"aws": [], "azure": [], "gcp": []}

    def test_save_and_load_roundtrip(self, tmp_path):
        disc_file = tmp_path / "discovered.json"
        with patch("service_updater._DISCOVERED_FILE", disc_file), \
             patch("service_updater._DATA_DIR", tmp_path):
            entries = [
                {"id": "aws-test-svc", "name": "Test Svc", "fullName": "AWS Test Svc",
                 "category": "Other", "description": "test", "icon": "cloud"},
            ]
            added = _save_discovered_services("aws", entries)
            assert added == 1

            loaded = _load_discovered_services()
            assert len(loaded["aws"]) == 1
            assert loaded["aws"][0]["id"] == "aws-test-svc"

    def test_save_deduplicates_by_id(self, tmp_path):
        disc_file = tmp_path / "discovered.json"
        with patch("service_updater._DISCOVERED_FILE", disc_file), \
             patch("service_updater._DATA_DIR", tmp_path):
            entry = {"id": "aws-dup", "name": "Dup", "fullName": "AWS Dup",
                     "category": "Other", "description": "d", "icon": "cloud"}
            _save_discovered_services("aws", [entry])
            added = _save_discovered_services("aws", [entry])
            assert added == 0  # duplicate, nothing new

            loaded = _load_discovered_services()
            assert len(loaded["aws"]) == 1

    def test_save_empty_returns_zero(self, tmp_path):
        disc_file = tmp_path / "discovered.json"
        with patch("service_updater._DISCOVERED_FILE", disc_file), \
             patch("service_updater._DATA_DIR", tmp_path):
            assert _save_discovered_services("aws", []) == 0

    def test_does_not_modify_py_files(self, tmp_path):
        """Verify that saving discovered services never touches .py files."""
        disc_file = tmp_path / "discovered.json"
        fake_py = tmp_path / "aws_services.py"
        fake_py.write_text("AWS_SERVICES = []\n", encoding="utf-8")
        original_content = fake_py.read_text()

        with patch("service_updater._DISCOVERED_FILE", disc_file), \
             patch("service_updater._DATA_DIR", tmp_path):
            entry = {"id": "aws-new", "name": "New", "fullName": "AWS New",
                     "category": "Other", "description": "n", "icon": "cloud"}
            _save_discovered_services("aws", [entry])

        assert fake_py.read_text() == original_content, \
            ".py file was modified -- service updater must only write to JSON"
