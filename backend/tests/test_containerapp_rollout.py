import json
import hashlib
import hmac
import importlib.util
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "containerapp_rollout.py"
SPEC = importlib.util.spec_from_file_location("containerapp_rollout", SCRIPT)
assert SPEC and SPEC.loader
rollout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rollout)

apply_traffic = rollout.apply_traffic
canonical_traffic = rollout.canonical_traffic
explicit_traffic = rollout.explicit_traffic
traffic_command = rollout.traffic_command
verify_manifest = rollout.verify_manifest
write_manifest = rollout.write_manifest


def test_latest_traffic_becomes_explicit_without_changing_multi_revision_weights():
    source = [
        {"latestRevision": True, "weight": 70},
        {"revisionName": "api-canary", "weight": 20},
        {"revisionName": "api-stable", "weight": 10, "label": "stable"},
    ]

    result = explicit_traffic(source, latest_revision="api-blue")

    assert result == canonical_traffic(
        [
            {"revisionName": "api-blue", "weight": 70},
            {"revisionName": "api-canary", "weight": 20},
            {"revisionName": "api-stable", "weight": 10, "label": "stable"},
        ]
    )
    assert "latest=" not in traffic_command(result)
    assert "api-blue=70" in traffic_command(result)
    assert "api-canary=20" in traffic_command(result)
    assert "stable=10" in traffic_command(result)


def test_traffic_validation_rejects_implicit_or_invalid_manifest():
    with pytest.raises(ValueError, match="valid revision"):
        canonical_traffic([{"revisionName": "", "weight": 100}])
    with pytest.raises(ValueError, match="between 0 and 100"):
        canonical_traffic([{"revisionName": "api-blue", "weight": 101}])
    with pytest.raises(ValueError, match="sum to 100"):
        canonical_traffic([{"revisionName": "api-blue", "weight": 99}])


def test_same_revision_can_have_labeled_and_unlabeled_routes():
    manifest = [
        {"revisionName": "api-blue", "weight": 80},
        {"revisionName": "api-blue", "weight": 20, "label": "stable"},
    ]

    assert sum(item["weight"] for item in canonical_traffic(manifest)) == 100


def test_apply_traffic_sets_then_reads_and_requires_exact_restoration(tmp_path):
    manifest = [
        {"revisionName": "api-blue", "weight": 70},
        {"revisionName": "api-canary", "weight": 30},
    ]
    output = tmp_path / "actual.json"
    with patch.object(
        rollout.subprocess,
        "run",
        side_effect=[
            CompletedProcess([], 0),
            CompletedProcess([], 0, stdout=json.dumps(manifest)),
        ],
    ) as run:
        apply_traffic(
            manifest,
            name="api",
            resource_group="example-rg",
            actual_output=output,
        )

    assert run.call_args_list[0].args[0][-3:] == [
        "--revision-weight",
        "api-blue=70",
        "api-canary=30",
    ]
    assert run.call_args_list[1].args[0][1:3] == ["containerapp", "show"]
    assert json.loads(output.read_text()) == manifest


def test_apply_traffic_fails_when_platform_returns_partial_shift():
    expected = [{"revisionName": "api-blue", "weight": 100}]
    actual = [
        {"revisionName": "api-blue", "weight": 50},
        {"revisionName": "api-green", "weight": 50},
    ]
    with (
        patch.object(
            rollout.subprocess,
            "run",
            side_effect=[
                CompletedProcess([], 0),
                CompletedProcess([], 0, stdout=json.dumps(actual)),
            ],
        ),
        pytest.raises(RuntimeError, match="mismatch after apply"),
    ):
        apply_traffic(expected, name="api", resource_group="example-rg")


def test_signed_bridge_manifest_is_immutable_and_role_bound(tmp_path, monkeypatch):
    monkeypatch.setenv("RELEASE_MANIFEST_HMAC_KEY", "x" * 32)
    path = tmp_path / "bridge.json"
    image = "registry.example/archmorph-api@sha256:" + "a" * 64
    write_manifest(
        path,
        role="bridge",
        revision="api-bridge",
        image=image,
        source_sha="b" * 40,
        accepted_revisions=["014", "013"],
    )

    assert verify_manifest(path, required_role="bridge")["accepted_revisions"] == ["013", "014"]
    with pytest.raises(ValueError, match="role"):
        verify_manifest(path, required_role="final")

    payload = json.loads(path.read_text())
    payload["revision"] = "api-arbitrary"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="signature"):
        verify_manifest(path, required_role="bridge")


def test_signed_manifest_rejects_invalid_source_or_schema_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("RELEASE_MANIFEST_HMAC_KEY", "x" * 32)
    path = tmp_path / "bridge.json"
    image = "registry.example/archmorph-api@sha256:" + "a" * 64
    write_manifest(
        path,
        role="bridge",
        revision="api-bridge",
        image=image,
        source_sha="b" * 40,
        accepted_revisions=["013", "014"],
    )
    payload = json.loads(path.read_text())
    payload["source_sha"] = "short"
    unsigned = {key: value for key, value in payload.items() if key != "signature"}
    canonical = json.dumps(unsigned, separators=(",", ":"), sort_keys=True).encode()
    payload["signature"] = "sha256=" + hmac.new(b"x" * 32, canonical, hashlib.sha256).hexdigest()
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="source SHA"):
        verify_manifest(path, required_role="bridge")