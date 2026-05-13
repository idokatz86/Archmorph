"""
Archmorph — Service Updater Unit Tests
Tests for the rewritten service_updater.py (v2.2.0)
"""

import os
import sys
import json
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
# Service refresh provider retries
# ====================================================================

class TestProviderRefreshRetries:
    def test_run_update_now_recovers_transient_provider_request_error(
        self,
        tmp_path,
    ):
        import httpx
        import service_updater
        from unittest.mock import patch as _patch

        request = httpx.Request("GET", "https://example.test/gcp")
        gcp_calls = {"count": 0}

        def empty_fetch(_client):
            return set()

        def flaky_gcp_fetch(_client):
            gcp_calls["count"] += 1
            if gcp_calls["count"] == 1:
                raise httpx.RequestError("handshake timed out", request=request)
            return {"RecoveredGcpService"}

        with _patch.dict(os.environ, {
            "SERVICE_REFRESH_PROVIDER_ATTEMPTS": "3",
            "SERVICE_REFRESH_PROVIDER_RETRY_DELAY_SECONDS": "0",
        }, clear=False), \
             _patch("service_updater._fetch_aws_services", empty_fetch), \
             _patch("service_updater._fetch_azure_services", empty_fetch), \
             _patch("service_updater._fetch_gcp_services", flaky_gcp_fetch), \
             _patch("service_updater._load_local_catalog", return_value=([], set())), \
             _patch("service_updater._UPDATES_FILE", tmp_path / "state.json"), \
             _patch("service_updater._DATA_DIR", tmp_path), \
             _patch("service_updater._get_state_blob_client", return_value=None):
            result = service_updater.run_update_now(auto_add=False)
            state = service_updater._read_state()

        assert gcp_calls["count"] == 2
        assert result["errors"] is None
        assert result["retry_attempts"] == {"gcp": 1}
        assert result["new_services"]["gcp"] == ["RecoveredGcpService"]
        assert state["checks"][-1]["errors"] is None

    def test_run_update_now_preserves_errors_after_retry_exhaustion(
        self,
        tmp_path,
    ):
        import httpx
        import service_updater
        from unittest.mock import patch as _patch

        request = httpx.Request("GET", "https://example.test/gcp")
        gcp_calls = {"count": 0}

        def empty_fetch(_client):
            return set()

        def failing_gcp_fetch(_client):
            gcp_calls["count"] += 1
            raise httpx.RequestError("handshake timed out", request=request)

        with _patch.dict(os.environ, {
            "SERVICE_REFRESH_PROVIDER_ATTEMPTS": "3",
            "SERVICE_REFRESH_PROVIDER_RETRY_DELAY_SECONDS": "0",
        }, clear=False), \
             _patch("service_updater._fetch_aws_services", empty_fetch), \
             _patch("service_updater._fetch_azure_services", empty_fetch), \
             _patch("service_updater._fetch_gcp_services", failing_gcp_fetch), \
             _patch("service_updater._load_local_catalog", return_value=([], set())), \
             _patch("service_updater._UPDATES_FILE", tmp_path / "state.json"), \
             _patch("service_updater._DATA_DIR", tmp_path), \
             _patch("service_updater._get_state_blob_client", return_value=None):
            result = service_updater.run_update_now(auto_add=False)

        assert gcp_calls["count"] == 3
        assert result["errors"] == {"gcp": "Request error: handshake timed out"}



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

    def test_blob_state_takes_priority_over_disk(self, tmp_path):
        from unittest.mock import MagicMock

        state_file = tmp_path / "state.json"
        disk_state = {
            "last_check": "disk",
            "checks": [],
            "new_services_found": {"aws": [], "azure": [], "gcp": []},
            "auto_added": {"aws": [], "azure": [], "gcp": []},
        }
        blob_state = {**disk_state, "last_check": "blob"}
        state_file.write_text(json.dumps(disk_state), encoding="utf-8")
        blob_payload = json.dumps(blob_state).encode("utf-8")
        mock_blob = MagicMock()
        mock_blob.download_blob.return_value.readall.return_value = blob_payload

        with patch("service_updater._get_state_blob_client", return_value=mock_blob), \
             patch("service_updater._UPDATES_FILE", state_file), \
             patch("service_updater._DATA_DIR", tmp_path):
            state = _read_state()
            assert state["last_check"] == "blob"

    def test_write_state_mirrors_to_blob(self, tmp_path):
        from unittest.mock import MagicMock

        state_file = tmp_path / "state.json"
        mock_blob = MagicMock()
        test_state = {
            "last_check": "2026-05-02T12:00:00Z",
            "checks": [],
            "new_services_found": {"aws": [], "azure": [], "gcp": []},
            "auto_added": {"aws": [], "azure": [], "gcp": []},
        }

        with patch("service_updater._get_state_blob_client", return_value=mock_blob), \
             patch("service_updater._UPDATES_FILE", state_file), \
             patch("service_updater._DATA_DIR", tmp_path):
            _write_state(test_state)

        mock_blob.upload_blob.assert_called_once()
        payload = mock_blob.upload_blob.call_args.args[0]
        assert b'"last_check": "2026-05-02T12:00:00Z"' in payload


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


# ====================================================================
# Issue #571 — GCP fetcher migration to Discovery API
# ====================================================================

class TestGcpFetcher:
    def test_uses_discovery_api_url(self):
        """The retired pricelist.json URL must not be used."""
        from service_updater import GCP_DISCOVERY_URL
        assert "googleapis.com/discovery" in GCP_DISCOVERY_URL
        assert "cloudpricingcalculator" not in GCP_DISCOVERY_URL

    def test_pricelist_constant_removed(self):
        """The dead pricelist endpoint must be removed entirely."""
        import service_updater
        assert not hasattr(service_updater, "GCP_PRICELIST_URL"), (
            "GCP_PRICELIST_URL still present — points to a 404 endpoint and "
            "must be removed (issue #571)."
        )

    def test_filters_workspace_apis(self):
        """Workspace / consumer APIs should be filtered out."""
        from unittest.mock import MagicMock
        from service_updater import _fetch_gcp_services

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "items": [
                {"name": "compute"},
                {"name": "storage"},
                {"name": "bigquery"},
                {"name": "gmail"},          # filtered
                {"name": "calendar"},       # filtered
                {"name": "youtube"},        # filtered
                {"name": "aiplatform"},
                {"name": ""},               # filtered (empty)
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        result = _fetch_gcp_services(mock_client)

        assert "compute" in result
        assert "storage" in result
        assert "bigquery" in result
        assert "aiplatform" in result
        assert "gmail" not in result
        assert "calendar" not in result
        assert "youtube" not in result
        assert "" not in result


# ====================================================================
# Issue #571 — freshness contract
# ====================================================================

class TestFreshness:
    def test_never_run_is_stale(self, tmp_path):
        from service_updater import get_freshness
        with patch("service_updater._UPDATES_FILE", tmp_path / "missing.json"):
            f = get_freshness()
            assert f["last_check"] is None
            assert f["age_hours"] is None
            assert f["stale"] is True

    def test_recent_run_is_fresh(self, tmp_path):
        from datetime import datetime, timezone
        import json as _json
        from service_updater import get_freshness

        state_file = tmp_path / "updates.json"
        state_file.write_text(_json.dumps({
            "last_check": datetime.now(timezone.utc).isoformat(),
            "checks": [{"timestamp": datetime.now(timezone.utc).isoformat(),
                        "new_services": {"aws": [], "azure": [], "gcp": []},
                        "errors": None}],
            "new_services_found": {"aws": [], "azure": [], "gcp": []},
            "auto_added": {"aws": [], "azure": [], "gcp": []},
        }), encoding="utf-8")

        with patch("service_updater._UPDATES_FILE", state_file):
            f = get_freshness()
            assert f["stale"] is False
            assert f["age_hours"] is not None
            assert f["age_hours"] < 1.0

    def test_get_freshness_rehydrates_scheduled_job_registry(self, tmp_path):
        from datetime import datetime, timezone
        import freshness_registry as fr
        import json as _json
        from service_updater import get_freshness

        fr.reset_for_tests()
        now = datetime.now(timezone.utc).isoformat()
        state_file = tmp_path / "updates.json"
        state_file.write_text(_json.dumps({
            "last_check": now,
            "checks": [{"timestamp": now,
                        "new_services": {"aws": [], "azure": [], "gcp": []},
                        "errors": None}],
            "new_services_found": {"aws": [], "azure": [], "gcp": []},
            "auto_added": {"aws": [], "azure": [], "gcp": []},
        }), encoding="utf-8")

        with patch("service_updater._UPDATES_FILE", state_file), \
             patch("service_updater._get_state_blob_client", return_value=None):
            f = get_freshness()
            jobs = fr.get_all()

        assert f["stale"] is False
        assert jobs[0]["name"] == "service_catalog_refresh"
        assert jobs[0]["last_success"] is not None
        assert jobs[0]["stale"] is False

    def test_get_freshness_rehydrates_scheduled_job_registry_from_blob(self, tmp_path):
        from datetime import datetime, timezone
        from unittest.mock import MagicMock
        import freshness_registry as fr
        import json as _json
        from service_updater import get_freshness

        fr.reset_for_tests()
        now = datetime.now(timezone.utc).isoformat()
        blob_state = {
            "last_check": now,
            "checks": [{"timestamp": now,
                        "new_services": {"aws": [], "azure": [], "gcp": []},
                        "errors": None}],
            "new_services_found": {"aws": [], "azure": [], "gcp": []},
            "auto_added": {"aws": [], "azure": [], "gcp": []},
        }
        mock_blob = MagicMock()
        blob_payload = _json.dumps(blob_state).encode("utf-8")
        mock_blob.download_blob.return_value.readall.return_value = blob_payload

        with patch("service_updater._get_state_blob_client", return_value=mock_blob), \
             patch("service_updater._UPDATES_FILE", tmp_path / "missing.json"), \
             patch("service_updater._DATA_DIR", tmp_path):
            f = get_freshness()
            jobs = fr.get_all()

        assert f["last_check"] == now
        assert f["stale"] is False
        assert jobs[0]["name"] == "service_catalog_refresh"
        assert jobs[0]["last_success"] is not None
        assert jobs[0]["stale"] is False

    def test_get_freshness_uses_last_successful_run_not_failed_check(self, tmp_path):
        from datetime import datetime, timezone, timedelta
        import json as _json
        from service_updater import get_freshness

        successful = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        failed = datetime.now(timezone.utc).isoformat()
        state_file = tmp_path / "updates.json"
        state_file.write_text(_json.dumps({
            "last_check": failed,
            "checks": [
                {"timestamp": successful,
                 "new_services": {"aws": [], "azure": [], "gcp": []},
                 "errors": None},
                {"timestamp": failed,
                 "new_services": {"aws": [], "azure": [], "gcp": []},
                 "errors": {"gcp": "HTTP 500"}},
            ],
            "new_services_found": {"aws": [], "azure": [], "gcp": []},
            "auto_added": {"aws": [], "azure": [], "gcp": []},
        }), encoding="utf-8")

        with patch("service_updater._UPDATES_FILE", state_file), \
             patch("service_updater._get_state_blob_client", return_value=None):
            f = get_freshness()

        assert f["last_check"] == successful
        assert f["stale"] is False
        assert f["providers_failed"] == ["gcp"]

    def test_old_run_is_stale(self, tmp_path):
        from datetime import datetime, timezone, timedelta
        import json as _json
        from service_updater import get_freshness

        old = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
        state_file = tmp_path / "updates.json"
        state_file.write_text(_json.dumps({
            "last_check": old,
            "checks": [{"timestamp": old,
                        "new_services": {"aws": [], "azure": [], "gcp": []},
                        "errors": None}],
            "new_services_found": {"aws": [], "azure": [], "gcp": []},
            "auto_added": {"aws": [], "azure": [], "gcp": []},
        }), encoding="utf-8")

        with patch("service_updater._UPDATES_FILE", state_file):
            f = get_freshness()
            assert f["stale"] is True
            assert f["age_hours"] is not None
            assert f["age_hours"] >= 36

    def test_provider_failure_surfaced(self, tmp_path):
        from datetime import datetime, timezone
        import json as _json
        from service_updater import get_freshness

        now = datetime.now(timezone.utc).isoformat()
        state_file = tmp_path / "updates.json"
        state_file.write_text(_json.dumps({
            "last_check": now,
            "checks": [{"timestamp": now,
                        "new_services": {"aws": [], "azure": [], "gcp": []},
                        "errors": {"gcp": "HTTP 404 from GCP"}}],
            "new_services_found": {"aws": [], "azure": [], "gcp": []},
            "auto_added": {"aws": [], "azure": [], "gcp": []},
        }), encoding="utf-8")

        with patch("service_updater._UPDATES_FILE", state_file):
            f = get_freshness()
            assert "gcp" in f["providers_failed"]
            assert f["last_errors"] == {"gcp": "HTTP 404 from GCP"}


# ====================================================================
# Issue #571 — scheduler opt-out for multi-replica deployments
# ====================================================================

class TestSchedulerOptOut:
    def test_disabled_via_env(self):
        import service_updater
        from service_updater import start_scheduler, stop_scheduler

        stop_scheduler()  # ensure clean baseline
        with patch.dict(os.environ, {"SCHEDULER_DISABLED": "1"}):
            start_scheduler()
            assert service_updater._running is False
            assert service_updater._scheduler is None
        stop_scheduler()


# ====================================================================
# Issue #571 — durable blob persistence (best-effort)
# ====================================================================

class TestBlobPersistence:
    def test_no_env_vars_returns_none(self):
        """Without storage env vars, blob client must be None (disk-only mode)."""
        from service_updater import _get_discovered_blob_client
        with patch.dict(os.environ, {
            "AZURE_STORAGE_ACCOUNT_URL": "",
            "AZURE_STORAGE_CONNECTION_STRING": "",
        }, clear=False):
            assert _get_discovered_blob_client() is None

    def test_save_to_blob_no_op_without_client(self, tmp_path):
        """_save_discovered_to_blob must not raise when no client is configured."""
        from service_updater import _save_discovered_to_blob
        with patch.dict(os.environ, {
            "AZURE_STORAGE_ACCOUNT_URL": "",
            "AZURE_STORAGE_CONNECTION_STRING": "",
        }, clear=False):
            # Should silently no-op, not raise
            _save_discovered_to_blob({"aws": [], "azure": [], "gcp": []})

    def test_load_from_blob_returns_none_without_client(self):
        from service_updater import _load_discovered_from_blob
        with patch.dict(os.environ, {
            "AZURE_STORAGE_ACCOUNT_URL": "",
            "AZURE_STORAGE_CONNECTION_STRING": "",
        }, clear=False):
            assert _load_discovered_from_blob() is None

    def test_blob_load_takes_priority_over_disk(self, tmp_path):
        """When blob returns data, disk file is ignored as source of truth."""
        from service_updater import _load_discovered_services
        from unittest.mock import MagicMock

        # Disk file with its own content
        disc_file = tmp_path / "discovered.json"
        disc_file.write_text(
            '{"aws": [{"id": "aws-from-disk"}], "azure": [], "gcp": []}',
            encoding="utf-8",
        )

        blob_payload = (
            b'{"aws": [{"id": "aws-from-blob"}], "azure": [], "gcp": []}'
        )
        mock_blob = MagicMock()
        mock_blob.download_blob.return_value.readall.return_value = blob_payload

        with patch("service_updater._get_discovered_blob_client",
                   return_value=mock_blob), \
             patch("service_updater._DISCOVERED_FILE", disc_file), \
             patch("service_updater._DATA_DIR", tmp_path):
            result = _load_discovered_services()
            assert result["aws"][0]["id"] == "aws-from-blob"

    def test_blob_preflight_requires_account_url(self):
        from service_updater import verify_service_catalog_blob_access
        with patch.dict(os.environ, {
            "AZURE_STORAGE_ACCOUNT_URL": "",
            "AZURE_STORAGE_CONNECTION_STRING": "UseDevelopmentStorage=true",
        }, clear=False):
            result = verify_service_catalog_blob_access()
        assert result["ok"] is False
        assert result["account_url_configured"] is False
        assert result["error"] == "AZURE_STORAGE_ACCOUNT_URL is not configured"

    def test_blob_client_ignores_azure_client_id_for_system_identity(self):
        from service_updater import _get_service_catalog_blob_client
        from unittest.mock import MagicMock

        mock_container = MagicMock()
        mock_blob_service = MagicMock()
        mock_blob_service.get_container_client.return_value = mock_container

        with patch.dict(os.environ, {
            "AZURE_STORAGE_ACCOUNT_URL": "https://example.blob.core.windows.net",
            "AZURE_STORAGE_CONNECTION_STRING": "",
            "AZURE_CLIENT_ID": "github-oidc-client-id",
            "AZURE_STORAGE_MANAGED_IDENTITY_CLIENT_ID": "",
        }, clear=False), patch(
            "azure.identity.DefaultAzureCredential"
        ) as credential_cls, patch(
            "azure.storage.blob.BlobServiceClient", return_value=mock_blob_service
        ):
            _get_service_catalog_blob_client("service_updates.json")

        credential_cls.assert_called_once_with(managed_identity_client_id=None)

    def test_blob_client_uses_storage_managed_identity_client_id(self):
        from service_updater import _get_service_catalog_blob_client
        from unittest.mock import MagicMock

        mock_container = MagicMock()
        mock_blob_service = MagicMock()
        mock_blob_service.get_container_client.return_value = mock_container

        with patch.dict(os.environ, {
            "AZURE_STORAGE_ACCOUNT_URL": "https://example.blob.core.windows.net",
            "AZURE_STORAGE_CONNECTION_STRING": "",
            "AZURE_CLIENT_ID": "github-oidc-client-id",
            "AZURE_STORAGE_MANAGED_IDENTITY_CLIENT_ID": "storage-user-assigned-id",
        }, clear=False), patch(
            "azure.identity.DefaultAzureCredential"
        ) as credential_cls, patch(
            "azure.storage.blob.BlobServiceClient", return_value=mock_blob_service
        ):
            _get_service_catalog_blob_client("service_updates.json")

        credential_cls.assert_called_once_with(
            managed_identity_client_id="storage-user-assigned-id"
        )

    def test_storage_preflight_managed_identity_ignores_azure_client_id(self):
        from service_updater import _get_service_catalog_managed_identity_container_client
        from unittest.mock import MagicMock

        mock_blob_service = MagicMock()
        with patch.dict(os.environ, {
            "AZURE_STORAGE_ACCOUNT_URL": "https://example.blob.core.windows.net",
            "AZURE_CLIENT_ID": "github-oidc-client-id",
            "AZURE_STORAGE_MANAGED_IDENTITY_CLIENT_ID": "",
        }, clear=False), patch(
            "azure.identity.ManagedIdentityCredential"
        ) as credential_cls, patch(
            "azure.storage.blob.BlobServiceClient", return_value=mock_blob_service
        ):
            _get_service_catalog_managed_identity_container_client()

        credential_cls.assert_called_once_with()

    def test_blob_preflight_exercises_managed_identity_operations(self):
        from service_updater import verify_service_catalog_blob_access

        class BlobItem:
            name = ".deployment-preflight/probe.json"

        class Download:
            def readall(self):
                return blob.payload

        class Blob:
            payload = b""
            deleted = False

            def upload_blob(self, payload, overwrite=False, timeout=None):
                self.payload = payload

            def download_blob(self, timeout=None):
                return Download()

            def delete_blob(self, timeout=None):
                self.deleted = True

        blob = Blob()

        class Container:
            def get_container_properties(self, timeout=None):
                return {"name": "service-catalog"}

            def get_blob_client(self, name):
                BlobItem.name = name
                return blob

            def list_blobs(self, name_starts_with=None, timeout=None):
                return [BlobItem()]

        with patch.dict(os.environ, {
            "AZURE_STORAGE_ACCOUNT_URL": "https://example.blob.core.windows.net",
        }, clear=False), patch(
            "service_updater._get_service_catalog_managed_identity_container_client",
            return_value=Container(),
        ):
            result = verify_service_catalog_blob_access()

        assert result["ok"] is True
        assert result["account_url"] == "https://example.blob.core.windows.net"
        assert result["operations"] == ["write", "read", "list", "delete"]
        assert blob.deleted is True

    def test_blob_preflight_cleans_probe_after_list_failure(self):
        from service_updater import verify_service_catalog_blob_access

        class Download:
            def readall(self):
                return blob.payload

        class Blob:
            payload = b""
            deleted = False

            def upload_blob(self, payload, overwrite=False, timeout=None):
                self.payload = payload

            def download_blob(self, timeout=None):
                return Download()

            def delete_blob(self, timeout=None):
                self.deleted = True

        blob = Blob()

        class Container:
            def get_container_properties(self, timeout=None):
                return {"name": "service-catalog"}

            def get_blob_client(self, name):
                return blob

            def list_blobs(self, name_starts_with=None, timeout=None):
                raise RuntimeError("simulated list failure")

        with patch.dict(os.environ, {
            "AZURE_STORAGE_ACCOUNT_URL": "https://example.blob.core.windows.net",
        }, clear=False), patch(
            "service_updater._get_service_catalog_managed_identity_container_client",
            return_value=Container(),
        ):
            result = verify_service_catalog_blob_access()

        assert result["ok"] is False
        assert result["error"] == "simulated list failure"
        assert blob.deleted is True


# ====================================================================
# Issue #647 — services.reload() and refresh-time hot reload
# ====================================================================

class TestServicesReload:
    def test_reload_function_exists(self):
        import services
        assert hasattr(services, "reload"), (
            "services.reload() missing — required by issue #647 so live API "
            "reflects discoveries without container restart."
        )
        assert callable(services.reload)

    def test_reload_returns_counts(self):
        import services
        counts = services.reload()
        assert isinstance(counts, dict)
        assert set(counts.keys()) >= {"aws", "azure", "gcp"}
        assert all(isinstance(v, int) and v > 0 for v in counts.values())

    def test_lists_are_same_object_across_reloads(self):
        """Critical contract: reload() must mutate in place, not rebind.

        Otherwise `from services import AWS_SERVICES` references in routers
        would still point at the old list after a refresh.
        """
        import services
        before = services.AWS_SERVICES
        services.reload()
        after = services.AWS_SERVICES
        assert before is after, (
            "AWS_SERVICES list identity changed across reload(); routers that "
            "imported by name will still see the old list."
        )

    def test_reload_picks_up_new_discovered_entries(self, tmp_path, monkeypatch):
        """After writing a new entry to discovered_services.json, reload() picks it up."""
        import json as _json
        import services

        # Static-only baseline: reload from a fresh empty discovery file first
        empty_disc = tmp_path / "empty.json"
        empty_disc.write_text('{"aws": [], "azure": [], "gcp": []}', encoding="utf-8")
        monkeypatch.setattr(services, "_DISCOVERED_FILE", empty_disc)
        monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_URL", "")
        monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
        services.reload()
        baseline_aws = len(services.AWS_SERVICES)

        # Now point at a discovery file with one synthetic entry
        disc = tmp_path / "discovered.json"
        disc.write_text(_json.dumps({
            "aws": [
                {"id": "aws-647-test-svc", "name": "Reload Test Svc",
                 "fullName": "AWS Reload Test", "category": "Other",
                 "description": "test", "icon": "cloud"},
            ],
            "azure": [],
            "gcp": [],
        }), encoding="utf-8")
        monkeypatch.setattr(services, "_DISCOVERED_FILE", disc)

        services.reload()

        try:
            assert len(services.AWS_SERVICES) == baseline_aws + 1
            assert any(
                s.get("id") == "aws-647-test-svc" for s in services.AWS_SERVICES
            ), "newly-discovered entry not visible after reload()"
        finally:
            # Restore: reload from the real discovery file so other tests see
            # the canonical state.
            monkeypatch.undo()
            services.reload()

    def test_run_update_now_triggers_reload(self, tmp_path, monkeypatch):
        """run_update_now must call services.reload() when discoveries are saved.

        Issue #647 — without this hook, refresh writes data nobody can read
        until container restart.
        """
        import services
        import service_updater
        from unittest.mock import patch as _patch

        # Sentinel function to detect the reload call
        reload_called = {"count": 0}
        original_reload = services.reload

        def tracking_reload():
            reload_called["count"] += 1
            return original_reload()

        # Stub fetchers to return a synthetic new service so auto_added is non-empty
        def fake_fetch(_client):
            return {"NewSyntheticService647"}

        def empty_fetch(_client):
            return set()

        # Use tmp paths for state + discovered file to avoid polluting real data
        with _patch.object(services, "reload", tracking_reload), \
             _patch("service_updater._fetch_aws_services", fake_fetch), \
             _patch("service_updater._fetch_azure_services", empty_fetch), \
             _patch("service_updater._fetch_gcp_services", empty_fetch), \
             _patch("service_updater._UPDATES_FILE", tmp_path / "state.json"), \
             _patch("service_updater._DISCOVERED_FILE", tmp_path / "discovered.json"), \
             _patch("service_updater._DATA_DIR", tmp_path), \
             _patch("service_updater._get_discovered_blob_client", return_value=None):
            service_updater.run_update_now(auto_add=True)

        assert reload_called["count"] == 1, (
            "services.reload() was not called by run_update_now; live catalog "
            "will not reflect new discoveries until container restart."
        )

    def test_run_update_now_skips_reload_when_no_changes(self, tmp_path):
        """No discoveries → no reload (avoid wasted work)."""
        import services
        import service_updater
        from unittest.mock import patch as _patch

        reload_called = {"count": 0}
        original_reload = services.reload

        def tracking_reload():
            reload_called["count"] += 1
            return original_reload()

        # Make every fetcher return the empty set against an empty local
        # catalog — guaranteed zero new services for every provider.
        def empty_fetch(_client):
            return set()

        def empty_local_catalog(_provider):
            # (service_list, normalised name set)
            return [], set()

        with _patch.object(services, "reload", tracking_reload), \
             _patch("service_updater._fetch_aws_services", empty_fetch), \
             _patch("service_updater._fetch_azure_services", empty_fetch), \
             _patch("service_updater._fetch_gcp_services", empty_fetch), \
             _patch("service_updater._load_local_catalog", empty_local_catalog), \
             _patch("service_updater._UPDATES_FILE", tmp_path / "state.json"), \
             _patch("service_updater._DISCOVERED_FILE", tmp_path / "discovered.json"), \
             _patch("service_updater._DATA_DIR", tmp_path), \
             _patch("service_updater._get_discovered_blob_client", return_value=None):
            service_updater.run_update_now(auto_add=True)

        assert reload_called["count"] == 0, (
            "reload() was called even though no new services were discovered; "
            "this is wasted work."
        )


