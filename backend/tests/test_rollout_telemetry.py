import importlib.util
import json
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

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


def test_bridge_customer_degraded_page_is_secret_free_and_owned(monkeypatch):
    monkeypatch.setenv(
        "APPLICATIONINSIGHTS_CONNECTION_STRING",
        "InstrumentationKey=placeholder;IngestionEndpoint=https://example.applicationinsights.azure.com",
    )
    envelope = telemetry.build_envelope(
        event="bridge_customer_degraded",
        run_id="123",
        execution="migration-run",
        image_digest="sha256:" + "a" * 64,
    )
    properties = envelope["data"]["baseData"]["properties"]
    assert properties["owner"] == "platform-engineering"
    assert properties["application"] == "archmorph"
    assert "url" not in str(envelope).lower()
    assert "secret" not in str(envelope).lower()


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


def test_unknown_cli_event_is_non_gating_and_rejected_before_side_effects(
    tmp_path, capsys
):
    evidence = tmp_path / "events.ndjson"
    with (
        patch.object(telemetry, "_append_local_evidence") as append,
        patch.object(telemetry, "emit") as emit,
    ):
        result = telemetry.main(
            [
                "--event",
                "unknown_event",
                "--run-id",
                "123",
                "--execution",
                "migration-run",
                "--image-digest",
                "sha256:" + "a" * 64,
                "--evidence-output",
                str(evidence),
            ]
        )

    assert result == 0
    assert json.loads(capsys.readouterr().out) == {
        "delivery_status": "local_evidence_failed",
        "error_class": "ValueError",
        "event": "unknown_event",
    }
    append.assert_not_called()
    emit.assert_not_called()
    assert not evidence.exists()


def test_migration_telemetry_rejects_non_azure_ingestion_endpoint(monkeypatch):
    monkeypatch.setenv(
        "APPLICATIONINSIGHTS_CONNECTION_STRING",
        "InstrumentationKey=placeholder;IngestionEndpoint=https://example.invalid",
    )

    with pytest.raises(ValueError, match="invalid ingestion endpoint"):
        telemetry._ingestion_url()


@pytest.mark.parametrize(
    "failure",
    [
        URLError("dns unavailable"),
        TimeoutError("bounded timeout"),
        OSError("tls failure"),
        HTTPError("https://example.invalid", 429, "rate limited", {}, None),
    ],
)
def test_telemetry_failure_is_bounded_and_preserves_local_evidence(
    tmp_path, monkeypatch, failure
):
    monkeypatch.setenv(
        "APPLICATIONINSIGHTS_CONNECTION_STRING",
        "InstrumentationKey=placeholder;IngestionEndpoint=https://example.applicationinsights.azure.com",
    )
    evidence = tmp_path / "events.ndjson"
    with (
        patch.object(telemetry, "emit", side_effect=failure) as emit,
        patch.object(telemetry.time, "sleep") as sleep,
    ):
        result = telemetry.emit_best_effort(
            event="migration_started",
            run_id="123",
            execution="migration-run",
            image_digest="sha256:" + "a" * 64,
            evidence_output=evidence,
            max_attempts=3,
            request_timeout=0.1,
        )

    assert emit.call_count == 3
    assert sleep.call_count == 2
    assert result["delivery_status"] == "failed"
    records = [json.loads(line) for line in evidence.read_text().splitlines()]
    assert records[0]["delivery_status"] == "pending"
    assert records[-1]["delivery_status"] == "failed"
    assert "DATABASE" not in evidence.read_text()
    assert "InstrumentationKey" not in evidence.read_text()


def test_telemetry_retries_then_returns_control_on_success(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "APPLICATIONINSIGHTS_CONNECTION_STRING",
        "InstrumentationKey=placeholder;IngestionEndpoint=https://example.applicationinsights.azure.com",
    )
    evidence = tmp_path / "events.ndjson"
    with (
        patch.object(
            telemetry,
            "emit",
            side_effect=[TimeoutError("first"), None],
        ) as emit,
        patch.object(telemetry.time, "sleep"),
    ):
        result = telemetry.emit_best_effort(
            event="migration_quiesced",
            run_id="123",
            execution="migration-run",
            image_digest="sha256:" + "a" * 64,
            evidence_output=evidence,
            max_attempts=3,
            request_timeout=0.1,
        )

    assert emit.call_count == 2
    assert result["delivery_status"] == "delivered"
    assert result["attempt"] == 2
