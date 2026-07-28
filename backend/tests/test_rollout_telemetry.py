import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "emit_rollout_telemetry.py"
SPEC = importlib.util.spec_from_file_location("emit_rollout_telemetry", SCRIPT)
assert SPEC and SPEC.loader
telemetry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(telemetry)


def test_migration_telemetry_is_secret_free_and_owned(monkeypatch):
    monkeypatch.setenv(
        "APPLICATIONINSIGHTS_CONNECTION_STRING",
        "InstrumentationKey=placeholder;IngestionEndpoint=https://example.applicationinsights.azure.com",
    )
    envelope = telemetry.build_envelope(
        event="migration_failed",
        run_id="123",
        execution="migration-run",
        image_digest="sha256:" + "a" * 64,
    )

    properties = envelope["data"]["baseData"]["properties"]
    assert properties == {
        "application": "archmorph",
        "owner": "platform-engineering",
        "workflow_run_id": "123",
        "execution": "migration-run",
        "image_digest": "sha256:" + "a" * 64,
    }
    assert "DATABASE" not in str(envelope)


def test_migration_telemetry_rejects_unknown_or_mutable_evidence(monkeypatch):
    monkeypatch.setenv(
        "APPLICATIONINSIGHTS_CONNECTION_STRING",
        "InstrumentationKey=placeholder;IngestionEndpoint=https://example.applicationinsights.azure.com",
    )
    with pytest.raises(ValueError, match="unsupported"):
        telemetry.build_envelope(
            event="other",
            run_id="123",
            execution="run",
            image_digest="sha256:" + "a" * 64,
        )
    with pytest.raises(ValueError, match="immutable"):
        telemetry.build_envelope(
            event="migration_started",
            run_id="123",
            execution="run",
            image_digest="latest",
        )


def test_migration_telemetry_rejects_non_azure_ingestion_endpoint(monkeypatch):
    monkeypatch.setenv(
        "APPLICATIONINSIGHTS_CONNECTION_STRING",
        "InstrumentationKey=placeholder;IngestionEndpoint=https://example.invalid",
    )

    with pytest.raises(ValueError, match="invalid ingestion endpoint"):
        telemetry._ingestion_url()